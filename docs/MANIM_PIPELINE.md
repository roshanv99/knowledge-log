# 2b manim explainer pipeline (R&D spike)

This is the Phase 6 spike. It turns one chunk of PDF notes into a narrated, vertical (1080x1920) explainer reel in the style of 3Blue1Brown, rendered with Manim. It is **kept separate from the main pipeline** until the spike is signed off.

- **Code:** `spikes/manim/`
- **Skill:** `.claude/skills/manim-reel-spike/`
- **Plan entry:** Phase 6 in [`PLAN.md`](PLAN.md)

> **Promoted 2026-09-24.** The spike now runs in the real pipeline as `kl reel` with the
> `/reel-generation` skill: it claims reel tasks from Manage notes, uploads the MP4 and a poster, and
> reels play in the Reels tab. See [`PIPELINE_DB.md`](PIPELINE_DB.md) ("Reels: `kl reel`"). This
> directory stays as the R&D record and regression harness (`samples.json`, `/manim-reel-spike`).

## Core idea: Claude Code is the intelligence
The spike originally had Python call Claude through the Agent SDK. We dropped that, because the goal is for the **Claude Code client itself** to do the thinking. MCP sampling would have been the natural fit, but it is no longer available. The safer equivalent inverts control:

- **The Claude Code session orchestrates and authors.** A skill drives the loop.
- **Reviewers are fresh subagents**, one per verdict. They never see the author's drafting, so their review is independent rather than self-approval.
- **Python is a deterministic tool CLI with no LLM calls.** It does extraction, TTS, lint, render, layout audit and frame capture. It also **owns the loop state and budgets**, so the model can't lose count or skip a gate.

| Role | Done by | Brief (`spikes/manim/prompts/`) | Output |
|---|---|---|---|
| Orchestrator | session, via `/manim-reel-spike` | follows each command's `NEXT:` line | — |
| Script author | session | `manim-script.md` | `script.json` |
| Script critic | fresh subagent | `script-critic.md` | JSON verdict |
| Scene author and fixer | session | `manim-scene.md` | `scene.py` |
| Visual checker | fresh subagent | `visual-check.md` | JSON verdict |
| Mechanics, state and budgets | `spike/cli.py` | — | files in `out/<run>/<sample>/` |

## Flow
```
init ─► [author] script.json ─► check-script ─► [critic subagent] ─► verdict script     ≤3 rounds
     ─► tts          Kokoro per beat, per-beat pace → exact durations
     ─► [author] scene.py ─► render: lint → manim → layout audit → 3 frames            render_fix ≤3
     ─► [visual subagent] ─► verdict visual                                            ≤2 revisions
     ─► done | failed ─► report
```

1. **`init <sample> --run <dir>`** extracts the chunk's page text and **page images**. The notes are mostly screenshots and diagrams, so both the author and the critic read the images.
2. **Script.** The author writes 4–7 beats, each with `narration`, `visual` and `pace`, totalling 110–150 words (about 60 s or less).
   - `check-script` runs the cheap mechanical checks: the schema, the word count, symbols the TTS would read aloud, and title length.
   - The critic subagent then checks facts against the notes, coverage, format, the visual plan, tone and delivery.
3. **TTS.** Each beat is synthesized separately, so the scene author gets each beat's measured `audio_seconds`.
4. **Scene.** The author writes one `Reel(ReelScene)` module, with a `with self.beat(i) as b:` block per beat and animations timed as fractions of `b.duration`. `render` then runs:
   - **Lint:** AST checks for LaTeX-backed mobjects, external assets, camera or 3D scenes, `config` edits, and beats used out of order.
   - **Manim render** at 1080x1920, 30 fps.
   - **Layout audit,** at the end of each beat: anything outside the phone-safe area, and any Text overlapping other Text.
   - **Frames:** 3 frames, taken at the settled end of the first, middle and last beats.

   A failure at any step feeds the exact error back to the author (render_fix).
5. **Visual check.** A subagent judges the frames for legibility, layout, fidelity to the narration and notes, and clarity, and scores them 1–5. It passes at a score of 3 or more with no legibility or correctness problems.
6. **`report <run>`** writes `report.md`, which includes a *human quality* column for you to fill in.

**Why the script comes before the code** (a change from the original plan): the plan had one writer producing "code + narration". Splitting them lets the critic judge plain prose, and lets animation be timed to real audio.

## Runtime: `ReelScene` (`spike/reel_scene.py`)
Every generated scene subclasses it. It covers:
- **Canvas:** 1080x1920 at 30 fps. The frame is 9×16 units, so 1 unit is 120 px. The background is `#0f1117` and the default font is Helvetica Neue.
- **Safe area:** x from −4.0 to 3.2 and y from −5.6 to 6.4, with a stage band for the main diagram between y 4.8 and −4.2 (`place_stage`), plus a `labeled_box` helper. That keeps content clear of the Reels/Shorts UI at the top, bottom and right-hand rail.
- **`with self.beat(i) as b:`** adds the beat's WAV through manim's `add_sound` and pads the beat to the audio length plus 0.25 s. This does manim-voiceover's job without the dependency, and needs no separate mux step.
- **Audit and timings:** they are written to `timing.json`, which drives the frame sampling and the overrun reporting.
- **No LaTeX:** the toolkit is `Text`/`MarkupText`/`Code`/shapes/arrows. This avoids a 4 GB MacTeX install.

## Voice
- **Engine: Kokoro-82M.** It runs locally on CPU at about 8x real time and is calm and natural. It replaced Piper, which sounded flat and robotic.
  - Configure it with `KOKORO_VOICE` (default `af_heart`) and `KOKORO_SPEED`.
  - `TTS_ENGINE=piper` falls back to SRG's Piper voices.
- **Expressiveness is written into the script,** because Kokoro has no emotion control. The Delivery section of `manim-script.md` covers:
  - **rhythm:** mix short and long sentences;
  - **punctuation as timing:** `?` lifts the pitch, `...` holds a pause (measured at +0.45 s), `—` marks a turn, and short sentences land a point;
  - **contrast openers:** "But…", "Here's the fix";
  - **`pace` per beat:** 0.85–1.1, slower for the reveal and the takeaway.

  The critic reviews delivery too.
- **Upgrade path, if more emotional range is needed:** Chatterbox, with its `exaggeration` 0–1 knob and voice cloning. SRG already uses it on RunPod. `chatterbox-mlx` may now fit on a 16 GB Mac.

## Running it
```bash
# interactive
/manim-reel-spike                                  # all samples in spikes/manim/samples.json
/manim-reel-spike redis-lock-expiry                # one sample
# headless (e.g. launchd later)
claude -p "/manim-reel-spike"
# by hand, from spikes/manim
uv run python -m spike.cli --help
uv run python -m spike.cli status out/<run>/<sample>     # where a sample is, and its NEXT step
```
Each run writes to `spikes/manim/out/<run>/`:
- `report.md` and `report.json`;
- `<sample>.mp4`;
- `<sample>/state.json`, the full event log;
- `<sample>/attemptN/`, holding each scene version, its render and its frames.

**Host setup:** `brew install pkgconf cairo pango ffmpeg espeak-ng`, then `uv sync` in `spikes/manim`.

**Samples:** `docker-build-cache` (Docker p100), `nginx-listener-acceptor-reader` (NGINX p5), and `redis-lock-expiry` (Redis p76–77), all from `~/Documents/Notes/Technical Notes`.

## Results so far (2026-09-23)
| sample | status | script rounds | render fixes | visual score | length | render time | total time |
|---|---|---|---|---|---|---|---|
| redis-lock-expiry | passed | 2 | 0 | 3/5 | 49 s (Piper), 57 s (Kokoro) | 7 s | 3.5 min |

- **Script round 1:** the critic caught an undefined lock value, "bye" sounding like a farewell when spoken, a missing else-branch in the fix, and the script running over length. Each critic call took about 18 s.
- **Visual check:** it passed with valid polish notes (whose lock was deleted isn't shown, a floating DEL label, an off-centre takeaway). Neither reviewer caught the serif fallback font, which was fixed in `ReelScene` afterwards.
- **An earlier Agent SDK version stalled.** Each call took 10–25 min before the request was even sent. That's another reason for the in-session design.

### Usage batch (2026-09-24, `out/reels-20260924-0024`)
Each reel ran in its own headless session (`spike/batch.py` runs `claude -p "/manim-reel-spike <id>"` on the default model, Opus 5.5). Plan usage was read between reels from the CLI's `rate_limit_event`, at 1% resolution.

| reel | result | 5h window | 7d window | minutes |
|---|---|---|---|---|
| docker-build-cache | passed | 6% | <1% | 2.9 |
| k8s-cpu-throttling | passed (1 render fix) | 7% | 1% | 3.7 |
| k8s-probes | passed (1 visual revision) | 9% | <1% | 4.8 |
| k8s-qos-eviction | passed | 7% | 1% | 3.8 |
| k8s-deploy-strategies | passed | 6% | 1% | 3.6 |
| docker-ephemeral-data | passed (1 visual revision) | 10% | <1% | 5.6 |
| docker-network-drivers | passed | 12%* | 2%* | 47* |
| k8s-requests-vs-limits | failed: the critic refused to invent outcomes that aren't on the page (sample bug: it needs p108–109) | 5% | <1% | 2.6 |
| nginx-listener-acceptor-reader | interrupted: the Mac slept mid-session | — | 2%* | — |
| nginx-hub-and-spoke | stopped by the user | — | — | — |

\* Distorted by laptop sleep or by the orchestrating session's own activity.

**Takeaway.** A clean reel costs about **7.5% of the 5-hour window** (6–10%) and about **0.5% of the weekly window**. That's about **$1.20 notional**, 3.5–5.5 minutes, and roughly 17 turns including subagents. So about **12 reels fit in one 5-hour window**. 10 reels a day ≈ 75% of a 5-hour window and ≈ 5% of the week, which is about 35% of the weekly budget if run daily. The 7 passing visual scores: 3, 3, 3, 4, 4, 4, 3.

**Lessons.**
- Run batches with `caffeinate`, which `batch.py` now does. Idle sleep kills the in-flight request.
- Measure with the orchestrating session idle, because it draws from the same windows.
- A sample's pages must actually contain the answer its focus asks for.

## Lessons from the first batch (and where each is now enforced)
Three of the 7 passing reels needed a second attempt (1 render fix and 2 visual revisions), and most visual passes came with a list of polish notes. The recurring causes were fixed at the source, so the model gets them right the first time:

| Problem | Seen in | Fix | Enforced by |
|---|---|---|---|
| Em dashes flagged as a TTS risk | 5 of 7 scripts | The Delivery brief had *recommended* `—`, contradicting the critic | `check-script` rejects `—` and `–`; the brief now says to use a comma or a new sentence |
| Wording stronger than the notes ("only three drivers", "no warning", "restart the Pod") | 5 scripts, 1 visual | Keep the notes' qualifiers and terms, in narration and on-screen labels | `manim-script.md` Facts, `manim-scene.md` rule 7, the critic |
| `ValueTracker` reported as "outside the safe area" | cpu-throttling | Audit bug: a `ValueTracker` is never drawn | `ReelScene._audit` skips it |
| Labels crowding the right edge | 5 of 7 | The safe area was too wide, so `SAFE_RIGHT` went from 3.6 to 3.2 (about 85% of the width) | layout audit, which fails the render |
| Diagram top-heavy, empty bottom half | 6 of 7 | `self.place_stage(group)` centres the diagram between title and caption | `manim-scene.md` rule 1 |
| Text cramped in boxes, or left-aligned multi-line labels | probes, cpu | `labeled_box(...)` sizes the box from the text, with padding and centred lines | `manim-scene.md` rule 3 |
| Lines drawn through labels; floating tags | network, build-cache, ephemeral | Connectors end at box edges and run behind them; labels sit `next_to` their target | rules 4 and 5 |
| The point missing from the settled frame (transient `Indicate`) | build-cache, cpu, ephemeral | Each beat ends on a persistent state that shows its idea | rule 6 |
| Script failed: the focus asked about content on a page it wasn't given | requests-vs-limits | Sample now uses p108–109 | the sample-writing rule below |
| Session killed mid-run by laptop idle sleep | nginx | `batch.py` runs `caffeinate -i` | `batch.py` |

**Writing samples:** a sample's `pages` must contain everything its `focus` asks for. Open the pages and check that the answer is actually there. The critic will (correctly) fail a script rather than let it invent the missing part.

## Open decisions
- **Visual pass mark:** 3 or 4? At 3, reels pass with known polish issues.
- **The remaining samples:** run `/manim-reel-spike docker-build-cache nginx-listener-acceptor-reader` to get the 3-sample pass rate that decides whether 2b routing gets enabled.
- **Architecture:** if the in-session design holds up, it should replace "LangGraph + Agent SDK" across PLAN.md. The CLI state file becomes the checkpoint, and a cut-off run resumes with `status` → `NEXT:`. MCQ generation moved to this design on 2026-09-24 (`kl mcq`, see [`PIPELINE_DB.md`](PIPELINE_DB.md)).

## Integrating later
- ✅ **Database hook, done 2026-09-24 (PIPELINE_DB.md step 7):** `init --from-db` claims a `reel` task from `/api/pipeline` (with `reel_style="manim"` once routing exists), each stage change heartbeats, and `done` uploads the MP4 under `MEDIA_ROOT` and completes the task with the reel. `samples.json` stays for the spike's own regression runs. `kl/engine.py` is the working example of a step engine on the pipeline API.
- `prompts/*` moves into `plugin/knowledge-log/skills/`. `visual-check` is shared with 2c.
- `reel_scene.py` and `media.py` move to `pipeline/kl/render/`.
- The `cli.py` state machine becomes the pattern for the other branches.

## Known issues
- SRG's `content_service/venv/bin/piper` is broken, because its shebang points to `~/Desktop/...`. SRG's `.env` also points `FFMPEG_BIN` to a missing `ffmpeg-full`. The spike works around both without changing SRG.
