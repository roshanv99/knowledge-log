---
name: manim-reel-spike
description: R&D spike for 2b. Turns sample note chunks into narrated 1080x1920 manim explainer reels, with this Claude session as author and subagents as reviewers.
disable-model-invocation: true
argument-hint: "[sample_id ...]  (default: every sample in spikes/manim/samples.json)"
---

You run the 2b manim spike. **You are the intelligence.** You write every script and scene yourself, and fresh subagents do the reviewing. The tool CLI does everything mechanical: source extraction, TTS (Kokoro), lint, render, layout audit and frames. It also owns the loop state and round budgets in `<work>/state.json`.

Run every command from `spikes/manim` as `uv run python -m spike.cli ...`. Each command ends with a `NEXT:` line, and that line is your next step. `status <work>` reprints it at any time.

## Steps
1. Use the run directory given as `--run <dir>` in `$ARGUMENTS`. If none is given, create `out/<YYYYMMDD-HHMMSS>`. Then run `init <sample> --run <run>` for each sample id in `$ARGUMENTS`, or for every id in `samples.json` if none are given. If a sample is already initialised, continue it from its `NEXT:` line.
2. Take each sample through its `NEXT:` lines, one sample at a time, until its stage is `done` or `failed`. Before you write for the first time, read the brief for your role:
   - **Author (you):** `prompts/manim-script.md` for `script.json`, and `prompts/manim-scene.md` for `scene.py`. Read the source page images, because most of the content is in them.
   - **Reviewers (always a fresh `general-purpose` subagent, one per verdict):** `prompts/script-critic.md` and `prompts/visual-check.md`. Brief the subagent with the prompt file path and the absolute paths it needs:
     - for the critic, `source/notes.txt`, the page PNGs and `script.json`;
     - for the visual checker, the frame PNGs as they were printed, with each one's narration and intended visual, plus `source/notes.txt`.
     
     Ask it for the JSON verdict only. It judges from those files alone. Keep your drafting reasoning out of the brief: the reviewer's independence is what makes this a reflection loop.
3. Record each verdict with `verdict ...` exactly as the reviewer gave it. Pass the same pass/fail, severity or score, and one `--issue` per issue. For visual issues, use the form `"beat N: problem → fix"`. The CLI decides whether you revise or whether the sample ends.
4. Once every sample is `done` or `failed`, run `report <run>`. Then give the user the pass rate table, the path to each video, and one line per sample on what the loops caught. Leave the "human quality" column for the user.

## Rules
- `state.json` changes only through the CLI. When the CLI says a sample `FAILED`, it stays failed: move on to the next sample.
- On a render or lint failure, fix the cause named in the output by editing `scene.py` in place. Then re-run `render`.
- Only this session and its subagents call Claude. The CLI stays LLM-free.
