# 2b manim spike (R&D)

The full pipeline doc is [`docs/MANIM_PIPELINE.md`](../../docs/MANIM_PIPELINE.md), mirrored in Obsidian as `Projects/knowledge-log/Manim Pipeline`. This README covers only running the spike.

This is a standalone spike for PLAN.md Phase 6. It covers the `manim_scene` reflective branch plus the `render_fix` and `visual_check` loops, on 3 sample chunks from `~/Documents/Notes`, rendered at 1080x1920. It is separate from the main pipeline and doesn't change SRG.

## Who does what
**The Claude Code session is the intelligence.** It plays the role MCP sampling would have played, without a server calling back into the client. Python never calls an LLM.

| Role | Done by | Brief |
|---|---|---|
| Orchestrator | the session, via the `/manim-reel-spike` skill (`.claude/skills/manim-reel-spike`) | follows each command's `NEXT:` line |
| Script author | the session | `prompts/manim-script.md` → `script.json` |
| Script critic | a fresh subagent per verdict | `prompts/script-critic.md` |
| Scene author and fixer | the session | `prompts/manim-scene.md` → `scene.py` |
| Visual checker | a fresh subagent per verdict | `prompts/visual-check.md` |
| Everything mechanical, loop state and budgets | `spike/cli.py` (deterministic) | — |

The reviewers are subagents so that each verdict comes from a context that never saw the drafting. That independence is what makes it a reflection loop rather than self-approval. The loop budgets live in `<work>/state.json` and are enforced by the CLI, so the model can't lose count or skip a gate:
- 3 script rounds;
- 3 render_fix attempts per visual round;
- 2 visual revisions.

```
init ─► [author] script.json ─► check-script ─► [critic subagent] ─► verdict script   (≤3 rounds)
     ─► tts (Piper per beat → exact durations)
     ─► [author] scene.py ─► render: lint → manim → layout audit → 3 frames          (render_fix ≤3)
     ─► [visual subagent] ─► verdict visual                                          (≤2 revisions)
     ─► done | failed ─► report
```

## Run
Interactively: `/manim-reel-spike` (all samples) or `/manim-reel-spike redis-lock-expiry`.
Headless, for example from launchd later: `claude -p "/manim-reel-spike"`.

The CLI can also be driven by hand from `spikes/manim`. Run `uv run python -m spike.cli --help`, and `status <work>` to see where a sample is.

A run writes these files to `out/<run>/`:
- `report.md` and `report.json`;
- `<sample>.mp4`;
- `<sample>/state.json`, the full event log;
- `<sample>/attemptN/`, holding each scene version, its render and its frames.

Host setup, already done on this Mac: `brew install pkgconf cairo pango ffmpeg`, then `uv sync`. LaTeX is not needed, because the lint forbids LaTeX-backed mobjects.

## Design notes
- **Script before code.** PLAN.md had one writer producing "code + narration". Here narration is written and critiqued first, then synthesized, so the scene author knows each beat's exact duration. The critic also judges plain prose instead of prose embedded in Python.
- **Voiceover.** `spike/reel_scene.py` (`ReelScene`) handles it. `with self.beat(i) as b:` plays the beat's Piper WAV through manim's `add_sound` and pads the beat to the audio length. This is manim-voiceover's idea without the dependency, and it needs no separate mux step.
- **Layout audit.** `ReelScene` also runs this at the end of every beat. It flags anything outside the phone-safe area and any Text overlapping other Text, and those count as render failures. It is a cheap, deterministic check that runs before the visual subagent.
- **Voice.** The narrator is Kokoro-82M, running locally on CPU at about 8x real time. It is calm and natural where Piper is flat. Pick the voice and speed with `KOKORO_VOICE` (default `af_heart`) and `KOKORO_SPEED` (default 1.0). For the old engine, set `TTS_ENGINE=piper`, which uses SRG's voice models read-only. The listening samples are in `out/voices/`. Kokoro has no emotion setting, so its expressiveness is directed through the script. The Delivery section of `prompts/manim-script.md` covers rhythm, punctuation as timing, and contrast words, and each beat gets a `pace` from 0.85 to 1.1, which the critic reviews. The A/B pair is `out/voices/redis_reel_kokoro_{af_heart,expressive}.mp4`.

## Integrating later (if the spike passes)
- **Orchestration.** The spike implies an architecture change for PLAN.md: Claude Code, running the skill, orchestrates the work, instead of LangGraph calling Claude through the Agent SDK. `spike/cli.py`'s state file is the checkpoint. A cut-off run resumes with `status` → `NEXT:`.
- **Prompts.** `prompts/*` moves to `plugin/knowledge-log/skills/` or their references. `visual-check` is shared with 2c.
- **Code.** `spike/reel_scene.py` and `spike/media.py` move to `pipeline/kl/render/`.

## Status (2026-09-23)
**1 of 3 samples run end to end: `redis-lock-expiry` passed** (`out/20260923-212845/`).
- **Script loop: 2 rounds.** Round 1's critic caught real problems: the lock value "hi" was never introduced, "bye" sounds like a farewell when spoken, the fix's else-branch was missing, and the script was over the word limit. Each critic call took about 18 s.
- **Render: 1 attempt, 0 render_fix rounds, about 7 s,** for 49 s of video.
- **visual_check: passed at 3/5.** Its fixes are all valid but weren't needed to pass: an empty value box that doesn't show whose lock was deleted, a floating DEL label, an off-centre takeaway, and an unbalanced panel.
- **Afterwards:** the default font changed from Pango's serif fallback to Helvetica Neue. Neither reviewer flagged the font.

**Open questions:**
- Should the visual gate be ≥4 rather than ≥3? At 3, reels pass with known polish issues.
- Pass rate on `docker-build-cache` and `nginx-listener-acceptor-reader`: run `/manim-reel-spike docker-build-cache nginx-listener-acceptor-reader`.
