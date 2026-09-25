# Pipeline ↔ database integration

Status: **built 2026-09-24**: quiz (steps 1–6) and manim reels (step 7, the spike promoted into the pipeline), plus driver B written but **not yet tested live**.
Architecture: the Obsidian note *Pipeline Runners Architecture* and the diagram
`docs/diagrams/pipeline-runners.html` (Archify source `pipeline-runners.architecture.json`).
Related: [`PLAN.md`](PLAN.md), [`MANIM_PIPELINE.md`](MANIM_PIPELINE.md).

## What it does
1. **Postgres is the only store.** Pipelines never touch the database: they claim work and
   report results through `/api/pipeline/*`. The pipeline's SQLite database, `kl/db.py` and
   `import_pipeline` are gone (a final import ran first; backup in
   `data/backups/pre-pipeline-db-2026-09-24.dump`).
2. **The database decides what to do.** A planner in Django applies the Manage notes settings
   (selected PDFs, page range, Quiz / Reels, and drag-to-reorder priority) and hands out one task at
   a time under a renewable lease.
3. **Manage notes shows progress:** per-kind coverage strips, a live status line per PDF, failed
   parts with Retry, and a pipeline panel showing each pipeline's activity. Runs are started from
   Claude Code (`/mcq-generation`, `/reel-generation`) or by the runner; the app has no run button
   (removed 2026-09-24).
4. **Reels are made the same way** and play in the Reels tab.

## Decisions (2026-09-24)
- **Pull model.** The cloud (or local Django) never pushes work and never holds a Claude
  credential. Runners pull over HTTPS with a scoped runner token.
- **Step engines plus drivers.** `kl mcq` and `kl reel` are deterministic CLIs (sharing
  `kl/steps.py`) that own the loop, budgets and validation, and print `NEXT:` steps. **Driver A
  (live):** a Claude Code session running `/mcq-generation` or `/reel-generation` does the writing,
  and fresh subagents review. **Driver B (written, untested live):** `kl mcq drive --api` answers
  the MCQ steps with the Messages API and an API key (quiz only for now).
  LangGraph and the Agent SDK are removed from the MCQ path. The Agent SDK can't legally use
  other people's claude.ai logins, and with an API key the plain Messages API is lighter.
- **Chunks are shared; tasks are per kind.** A chunk (4 pages, `KL_CHUNK_PAGES`) is read once;
  a `generation_task` is "make `kind` output for this chunk".
- **Leases, not locks.** 10 minutes (`KL_LEASE_SECONDS`), extended by every runner call.
- **One active run per kind** (a partial unique index); **quiz and reel runs go in parallel**, each
  in its own Claude Code session. An unread chunk another kind is reading right now is not offered,
  so two sessions never read the same pages; once read, both kinds share the notes.
- **Reels are capped in total** (`reel_limit`, default 5, 0 = no limit): made reels plus reels in
  progress. At the limit, reel claims return `reel_limit`, `wanted` starts nothing, and "Make a reel
  now" is refused. Every reel is a manim explainer (`reel_style="manim"`) until a router exists.
- **Local review files stay** under `output/`; they are not the source of truth.

## Data model
Django migrations own it (`content` 0003–0004, `pipeline` 0001, `quiz` 0002).

| Table | Notes |
|---|---|
| `chunks` | `status` is reading status only: `unread`, `read`, `unreadable` (cover, index, blank; counts as handled for every kind). `review_log`, `error`, `attempts` moved to tasks. |
| `generation_tasks` (new) | `chunk`, `kind` (`quiz`/`reel`), `reel_style`, `status` (`pending` → `claimed` → `done` / `skipped`, or `failed`), `attempts`, `run`, `lease_expires_at`, `stage`, `detail`, `review_log`, `error`, timestamps. Unique on `(chunk, kind)`. |
| `generation_runs` | Added `kind`, `runner` (the token's runner name), `params`, `last_seen_at`, `tasks_done`. Dropped `document`, `page_budget`, `target_mcqs`, `chunks_done`. |
| `questions` / `reels` | Added `task` (required for questions). `run` is now nullable. Reels also got `key_point`; `storage_key` is `reels/task-<id>.mp4` under `MEDIA_ROOT` (`data/media/`), with a poster at `.png`. |
| `note_scopes` | Added `priority`: position in Manage notes, top first. New PDFs go on top (lowest priority); migration 0007 reset it from the added date, newest first. |
| `runners` (new) | `name`, `kind`, `token_hash` (SHA-256), `enabled`, `last_seen_at`. |
| `run_requests` (new) | A request for a run: `kind`, `created_at`, `expires_at` (+6 h), `consumed_by_run`. At most one open per kind. The app's buttons for it were removed on 2026-09-24; `POST /api/pipeline/requests` remains for scripts. |
| `settings` | Added `pipeline_enabled` (kill switch), `pipeline_auto` (off: runs only on request), `max_tasks_per_run` (10), `max_runs_per_day` (6), `reel_limit` (5). |
| `generation_runs` (reels) | `reels_made` alongside `questions_made`. |

The data migration turned every `done` chunk into a `read` chunk plus a `done` quiz task linked
to its questions (7 tasks, 20/20 questions linked; quiz sets, attempts and scopes untouched).

## The planner (`backend/pipeline/planner.py`)
`claim(kind, run, document_id=None)`, one transaction:
1. **Waiting tasks:** `pending` ones (new, handed back, or failed with retries left) and claims
   whose lease expired, locked with `SELECT … FOR UPDATE SKIP LOCKED`.
2. **Chunks read for another kind** with no task of this kind yet.
3. **The next uncovered page window** of a PDF present on disk, as a new chunk.

PDFs go **from the bottom of Manage notes up** (the list is `priority`, then newest first, then path;
`content/notes.py` `list_order`), so with no dragging the oldest PDF is worked on first. Pages go
ascending, only inside scope
(`scope_for`, selected, kind ticked, chunk within the range). Creating chunks and tasks is
serialised with a per-kind Postgres advisory lock, so parallel claimers never collide (tested
with 6 threads). `failed` is final until Retry. Returns a reason when there is nothing:
`nothing_selected`, `range_done` or `all_failed`.

Run lifecycle (`pipeline/services.py`): runs silent for longer than a lease are closed as
`abandoned` and their tasks go back to `pending`. `finish` hands unfinished claims straight
back. The kill switch stops new runs and makes a running one stop at its next claim
(`disabled`). Idle runs (nothing to do, or disabled with 0 tasks) don't count toward the daily cap.

## Pipeline API (`/api/pipeline/…`)

**Runner endpoints** (`Authorization: Bearer klr_…`; a runner only sees its own runs; 404 for
anything else):

| Method and path | Body | Returns |
|---|---|---|
| `GET /wanted?kind=quiz` | — | `200 {kind, reason: run_request\|schedule, request_id, document, pages}` or `204` |
| `POST /runs` | `{kind, params}` | `201 {run_id}`; `403` kill switch or daily cap; `409` a run of this kind is active |
| `POST /runs/{id}/claim` | `{document_id?}` | `200 {task, reason}`: `task` is the payload below, or null with `reason` (`range_done`, `nothing_selected`, `all_failed`, `run_cap`, `disabled`, `reel_limit`) |
| `POST /tasks/{id}/heartbeat` | `{run_id, stage, detail}` | Extends the lease. `409` if the claim is lost |
| `PUT /tasks/{id}/notes` | `{run_id, title, summary, key_points, testable}` | Chunk becomes `read` or `unreadable` |
| `PUT /tasks/{id}/media?run_id=&kind=video\|poster` | raw MP4 or PNG body | `201 {storage_key}`. Reel tasks only; checked by magic bytes; ≤ 200 MB (`KL_MAX_MEDIA_BYTES`); streamed to disk |
| `POST /tasks/{id}/complete` | `{run_id, questions, review_log, skipped_reason?}` or, for reels, `{run_id, reel: {title, key_point, duration_s, storage_key}, review_log}` (the video must be uploaded first) | Idempotent; questions keyed on (chunk, stem). No questions → `skipped`. Server-side validation: 4 distinct options, `correct_index` 0–3, `source_pages` inside the chunk, unique stems, ≤ 20 questions, 256 KB JSON cap |
| `POST /tasks/{id}/fail` | `{run_id, error, retryable}` | `attempts += 1`; `pending` if retryable with attempts left (3), else `failed` |
| `POST /runs/{id}/finish` | `{stop_reason, usage?}` | Hands unfinished claims back |

**App endpoints** (open locally like the rest of the app; behind the app login once hosted):
`GET /status` (now with `reels: {made, limit}`), `POST /requests {kind}` (409 for reels at the
limit), `POST /tasks/{id}/retry`, plus `PUT /api/notes/{id}/position {position}`, `progress` in
`GET /api/notes`, `GET /api/reels` (in-scope reels, newest first, with `url` and `poster`), and
`GET /api/media/<key>` (serves `MEDIA_ROOT` with byte ranges, so video seeking works).

Task payload: `{id, kind, reel_style, attempt, lease_expires_at, chunk: {id, page_start, page_end,
status, title, notes}, document: {id, filename, path, page_count}}`.

Tokens: `cd backend && uv run manage.py runner_token kl@macbook [--kind claude-session|api-worker]`
prints a new token once (rotating the old one); `--disable` revokes. The Mac's token lives in the
git-ignored `.env` as `KL_RUNNER_TOKEN`.

## The step engine (`pipeline/kl`)

```
kl mcq start [--document NAME]           claim (or resume); prints NEXT:
kl mcq submit notes|draft|critique FILE  validate, record, advance; prints NEXT:
kl mcq status                            where the run is; renews the lease
kl mcq fail "why" [--no-retry]           give up on the task
kl mcq stop [--reason usage_limit]       end the run
kl runner poll [--dry-run]               launchd: start a session only if work is wanted
kl docs / kl status                      Manage notes selection / pipeline activity
```

Loop per task: **read** (the session reads every page image; skipped when the chunk is already
`read`) → **write** round N (exactly `3 − approved` questions) → **critique** round N (a fresh
subagent, brief only) → revise until round 3 (`KL_MAX_REVISIONS=2`), then keep approved and
`revise` verdicts, drop `reject` → answer positions shuffled → `complete` → next claim. A missing
review counts as reject. Three invalid submissions of a step fail the task (retryable). A lost
claim drops the task and moves on. State lives in `.kl/quiz/state.json` (git-ignored) with a
brief file per LLM step; review files in `output/runs/run-<id>/summary.md` and
`output/<document>/chunks/pNNN-NNN.md`.

Code: `kl/api.py` (HTTP client), `kl/steps.py` (shared engine: claim, read, leases, invalid
submissions, lost claims, resume), `kl/engine.py` (MCQ loop), `kl/runner.py` (poll),
`kl/output.py`, `kl/cli.py`. Prompts in `plugin/knowledge-log/prompts/`. Skill:
`.claude/skills/mcq-generation/`.

### Reels: `kl reel` (promoted from spikes/manim)

```
read ─► script ─► script-review (subagent) ─► narration (Kokoro, automatic) ─► scene ─► render
   render ok ─► visual review (subagent, frames) ─► upload video + poster ─► complete ─► next task
```

Budgets as in the spike: 3 script rounds, 3 render fixes per visual round, 2 visual revisions;
running out fails the task for good (it shows under "got stuck" with Retry). The script check
enforces 110–150 words, 4–7 beats, no symbols the voice would read aloud, and a title of five words
at most. The scene lint also refuses file, process and network access, since the model writes the
scene from notes it read. Renders time out at 300 s and the lease is renewed before and after each.
Code: `kl/reels/engine.py`, `kl/reels/media.py` (TTS, lint, render, frames), `kl/reels/reel_scene.py`
(the base class), with the `reels` extra (`uv sync --project pipeline --extra reels`: manim, Kokoro).
Briefs: `plugin/knowledge-log/prompts/reel-*.md`. Skill: `.claude/skills/reel-generation/`. Review
copies: `output/<document>/reels/pNNN-NNN.mp4`. The spike in `spikes/manim/` stays as the R&D
record and regression harness.

### Driver B: `kl mcq drive --api` (written, untested live)

`kl/drivers/api.py`, with the `api` extra (`anthropic`). It runs the same MCQ engine (in `.kl/api/`)
and answers each step with one `messages.parse` call: the step's prompt as the system prompt, the
page images inline, the engine's schema as `output_format`, adaptive thinking, and server-side
refusal fallback (`fallbacks: "default"`). A refusal fails the task without retry. The model is
`claude-opus-5` by default (`KL_API_MODEL`). Use an `api-worker` runner token. Unit tests use a fake
client; test it live before relying on it. Reels via the API aren't written.

## The runner (pull model)
`kl runner poll` (launchd every 5 minutes; install with `infra/launchd/install.sh`, not installed
by default) asks `GET /wanted` for each kind. For each kind that is wanted and has no session
running (a pid lock per kind, `.kl/runner-<kind>.pid`) it starts one, so questions and reels can run
at the same time:

```
caffeinate -i claude -p /mcq-generation --permission-mode dontAsk \
  --allowedTools Read "Edit(./.kl/**)" Agent "Bash(uv run --project pipeline kl mcq *)"
caffeinate -i claude -p /reel-generation --permission-mode dontAsk \
  --allowedTools Read "Edit(./.kl/**)" Agent "Bash(uv run --project pipeline --extra reels kl reel *)"
```

Each session gets only its own engine.

Anything not allowed is denied without a prompt: no web access, no other shell commands, and
writes only under `.kl/`. The skill tells the session to treat page text as content, never as
instructions. Logs: `logs/runner-poll.log`, `logs/runner-<kind>-<time>.log`.

## Progress in Manage notes (UI)
- `GET /api/notes` returns notes in priority order, with `scope.priority` and, per kind,
  `progress: {pages_in_range, pages_done, done_ranges, failed[], active}`.
- **Pipeline panel** (`PipelinePanel.tsx`): a row per kind, e.g. "Making a reel: Docker and Kube:
  Animating pages 1–4, scene fix 1 of 3", or "Reel requested", or "Last run 8 min ago: stopped
  because …", plus "1 of 5 reels made" for reels and when the Mac's runner last checked in (red if it's quiet for 15 min
  while work waits).
- **Reels tab** (`ReelsPage.tsx`): in-scope reels, newest first, one per screen, like Instagram and
  TikTok: swipe (phones, native snapping) or scroll (one wheel/trackpad gesture = one reel, the
  momentum tail ignored) to move on. Phones fill the screen above the tab bar; wider screens show a
  centred 9:16 frame on black with ↑/↓ buttons beside it, and the arrow keys, J/K and Page Up/Down move
  too. Tap to play or pause; one plays at a time, and once you've started one, the next plays when it
  scrolls in (not with reduced motion). Title, key point, PDF and pages overlay the video; ⓘ shows or
  hides them for every reel (remembered on the device).
- **Watch counter** (`WatchCounter.tsx`, top-right of every reel): the times watched inside a ring
  that fills with the share of the current play-through actually played (skipping ahead doesn't
  add, seeking back doesn't double count, replaying from the start begins a new play-through). At
  80% the ring turns green with a pop and a burst (just the colour with reduced motion), the count
  goes up, and `POST /api/reels/{id}/views` stores a `reel_views` row (a repeat within 10 s is
  ignored). `/api/reels` returns each reel's `views`.
- **Inside an open PDF row**, what's in the chosen pages is two collapsible sections, Questions and
  Reels, each with its count; the items load when one is first opened and follow the page slider.
- **Built for hundreds of PDFs (2026-09-24):** the list is paged on the server
  (`GET /api/notes?page=&page_size=20&q=&folder=&selected=all|yes|no`, returning `total`, `folders`
  and a `summary` across every PDF; progress is computed only for the page shown). Search by name,
  a folder filter and a selected/not-selected filter sit above it, and the filters and page live in
  the URL. Each PDF is an accordion row: the header (selection, folder and pages, live status, "N
  parts got stuck") is always visible, and the page range, content types, failures and preview open
  on demand. Reordering moves one PDF at a time (`PUT /api/notes/{id}/position {position}`, which
  rewrites every priority densely), by drag within a page or with the arrow keys on the handle,
  across pages too. It's off while a search or filter is active. The list shows newest PDFs first and a
  new PDF goes on top; the pipeline works from the bottom up.
  Without `page`, `GET /api/notes` still returns every PDF (used by `kl docs`).
- **Cards:** a live status line ("Questions: 32 of 149 pages done", or the active step), coverage
  strips under the page track (stripes for questions, dots for reels; only once something is made),
  a "got stuck" list with the error and **Retry**, and a drag handle (pointer drag, or the arrow keys
  on the focused handle, announced to screen readers).
- **Settings:** "Pipeline on" (kill switch), "Start runs by itself" (`pipeline_auto`), and "Reels to make" (`reel_limit`).
- Polling every 5 s only while a run is active or requested, with one refresh when it ends.

## Verification (2026-09-24)
- `cd backend && uv run pytest`: 51 passed (planner, services, API, concurrency, notes progress
  and order; the 19 earlier tests updated).
- `cd pipeline && uv run pytest`: 14 passed (engine loop, budgets, validation, lost claims,
  resume, runner poll), against a `FakeApi`.
- **Live, full chain:** "Make questions now" → `kl runner poll` → headless `claude -p`. The session
  read p29–32 of *Docker and Kube* from the page images, a subagent reviewed, and 3 questions
  landed in Postgres (answers shuffled), with progress at page 32 and run 3 `run_cap`, runner
  `kl@macbook`. It used only the allowed tools.
- **Live crash test** (a second API on :8011 with a 20 s lease): the session's state was deleted
  mid-task, and the next `start` closed the dead run as `abandoned` and re-claimed the same task
  with no duplicate chunk.
- **Reels, live and in parallel (2026-09-24):** "Make questions now" and "Make a reel now" →
  `kl runner poll` started both sessions side by side. The quiz made 3 questions for p33–36; the
  reel session wrote "VMs vs Containers" from p1–4 (reusing the quiz's notes), its script passed
  review first time, the first render scored 3 with overflowing labels, and the fixed second render
  passed at 4. The video was uploaded and plays in the Reels tab, with byte-range seeking through the
  UI proxy. An earlier attempt hit the weekly usage limit mid-run: both runs were closed as
  `abandoned` and their tasks returned to the queue, as designed.
- **Tests:** backend 57, pipeline 24 (quiz engine, reel engine with fake media, driver B with a
  fake client, runner).
- **UI:** 390 px and 1280 px, light and dark, captured with real device emulation (headless
  Chrome's `--window-size` has a 500 px minimum), with no horizontal overflow. Keyboard and
  pointer reorder were exercised in a real browser.

## Next
- **Test driver B live** with an API key and an `api-worker` token (`kl mcq drive --api`), then
  decide whether reels get an API driver too.
- **A reel router** (Claude picks character, manim or diagram per chunk) once 2a or 2c exists; claims
  would then filter on `reel_style`.
- **Hosting:** app login on the app endpoints (the runner token is already in place), and R2 instead
  of `MEDIA_ROOT` for reels.
- `kl reset` was removed with SQLite. To redo pages after a prompt change, delete the task (and
  its questions or reel) in the Django admin; the planner offers the pages again.

## Environment
- Postgres `docker compose -f infra/docker-compose.yml up -d` (port 5434); API
  `cd backend && uv run manage.py runserver 8010`; UI `cd ui && npm run dev` (5180, proxies `/api`).
- Notes: `~/Documents/Notes/Technical Notes/`: *Docker and Kube* (149 pages, questions to page
  36, 1 reel from p1–4), *NGINX* (27), *Redis* (113). 26 questions, 1 of 5 reels.
- **Don't delete learner data.** Set 2 (2026-09-24) has the learner's real attempt.
