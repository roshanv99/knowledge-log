"""The manim reel step engine (`kl reel`), promoted from spikes/manim. No LLM calls in here.

    read ─► script ─► script_review ─(pass)─► narration (Kokoro, automatic) ─► scene ─► render
            ▲  ≤3 rounds   │                                                   ▲ ≤3 fixes │
            └──── fail ────┘                                                   └── fail ──┘
    render ok ─► visual review ─(pass)─► upload + complete ─► next task
                     └─ fail, ≤2 revisions ─► scene

The driver (the Claude Code session) writes the script and the scene; fresh subagents review
the script and the rendered frames. The engine does the mechanical checks, TTS, lint, render,
layout audit and frames, and owns every budget.
"""

import json
import re
import shutil
from pathlib import Path
from types import ModuleType

from pydantic import BaseModel, Field

from kl.api import ApiError, LeaseLost
from kl.output import document_dir
from kl.steps import EngineError, StepEngine

__all__ = ["EngineError", "ReelEngine"]

SCRIPT_ROUNDS = 3  # a draft plus two revisions
FIX_ROUNDS = 3  # render fixes per visual round
VISUAL_ROUNDS = 2  # revisions after a failed visual review
WORDS = (110, 150)  # must match prompts/reel-script.md
SPOKEN_SYMBOLS = re.compile(r"[`*_#<>{}\[\]()|/\\=@$%^&~—–]")


class Beat(BaseModel):
    narration: str
    visual: str
    pace: float = Field(1.0, ge=0.85, le=1.1, description="speech speed for this beat; <1 slower")


class Script(BaseModel):
    title: str
    key_point: str
    beats: list[Beat] = Field(min_length=3, max_length=8)


class ScriptVerdict(BaseModel):
    passed: bool
    severity: str = Field(pattern="^(none|low|medium|high)$")
    issues: list[str]


class VisualIssue(BaseModel):
    beat: int
    problem: str
    fix: str


class VisualVerdict(BaseModel):
    passed: bool
    score: int = Field(ge=1, le=5)
    issues: list[VisualIssue]


class ReelEngine(StepEngine):
    kind = "reel"
    command = "uv run --project pipeline --extra reels kl reel"
    media: ModuleType | None = None  # kl.reels.media; tests pass a fake

    def _media(self):
        if self.media is None:
            from kl.reels import media  # imports manim and Kokoro lazily: only reel steps need them
            self.media = media
        return self.media

    # Hooks.

    def _new_task(self, task: dict) -> None:
        task.update(script_round=0, fix_round=0, visual_round=0, attempt_no=0, issues=[], renders=[])

    def _begin(self, st: dict, task: dict) -> str:
        task["script_round"] = 1
        self._write_script_brief(task)
        self._enter(st, task, "script")
        return self.next_line(st)

    def _detail(self, task: dict) -> str | None:
        return {
            "script": f"script round {task['script_round']} of {SCRIPT_ROUNDS}",
            "script_review": f"script round {task['script_round']} of {SCRIPT_ROUNDS}",
            "tts": "recording narration",
            "scene": f"scene fix {task['fix_round']} of {FIX_ROUNDS}" if task["fix_round"] else "first scene",
            "render": f"render attempt {task['attempt_no']}",
            "visual": f"visual review, revision {task['visual_round']} of {VISUAL_ROUNDS}",
        }.get(task["stage"])

    def _totals(self, st: dict) -> str:
        return f"{st['tasks_done']} tasks, {st['reels_made']} reels made"

    def _run_report(self, st: dict) -> Path:
        run_dir = self.settings.output_dir / "runs" / f"reel-run-{st['run_id']:03d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        lines = [f"# Reel run {st['run_id']}", "", f"Stop reason: **{st.get('stop_reason')}**",
                 f"Tasks: {st['tasks_done']} · reels made: {st['reels_made']}", ""]
        for c in st["chunks"]:
            lines.append(f"- p{c['pages'][0]}–{c['pages'][1]} {c['title'] or ''}: **{c['status']}**"
                         + (f" · {c['video']}" if c.get("video") else ""))
        if st.get("log"):
            lines += ["", "## Log", ""] + [f"- {line}" for line in st["log"]]
        (run_dir / "summary.md").write_text("\n".join(lines) + "\n")
        return run_dir / "summary.md"

    # Commands.

    def submit_script(self, path: Path) -> str:
        st = self._require()
        task = self._require_stage(st, "script")
        script, errors = self._parse(path, Script)
        if script is not None:
            errors = self._check_script(script)
        if errors:
            return self._invalid(st, "script", errors)
        d = Path(task["dir"])
        shutil.copy(path, d / f"script-{task['script_round']}.json")
        shutil.copy(path, d / "script.json")
        words = sum(len(b.narration.split()) for b in script.beats)
        task["review_log"].append({"step": "script", "round": task["script_round"], "words": words,
                                   "beats": len(script.beats), "title": script.title})
        self._write_script_review_brief(task)
        try:
            self._enter(st, task, "script_review")
        except LeaseLost:
            return self._lost(st)
        return f"Script OK: {len(script.beats)} beats, {words} words.\n{self.next_line(st)}"

    def submit_script_review(self, path: Path) -> str:
        st = self._require()
        task = self._require_stage(st, "script_review")
        verdict, errors = self._parse(path, ScriptVerdict)
        if errors:
            return self._invalid(st, "script review", errors)
        task["review_log"].append({"step": "script_review", "round": task["script_round"], **verdict.model_dump()})
        if not verdict.passed:
            if task["script_round"] >= SCRIPT_ROUNDS:
                return self.fail(f"script review still failing after {SCRIPT_ROUNDS} rounds: "
                                 + "; ".join(verdict.issues)[:1500], retryable=False)
            task["script_round"] += 1
            task["issues"] = verdict.issues
            self._write_script_brief(task)
            try:
                self._enter(st, task, "script")
            except LeaseLost:
                return self._lost(st)
            listing = "\n".join(f"  - {i}" for i in verdict.issues)
            return (f"Script round {task['script_round'] - 1} of {SCRIPT_ROUNDS} failed. Fix every issue:\n"
                    f"{listing}\n{self.next_line(st)}")
        # Narration is mechanical: record it now, so the scene author gets exact beat durations.
        try:
            self._enter(st, task, "tts")
        except LeaseLost:
            return self._lost(st)
        script = Script.model_validate_json((Path(task["dir"]) / "script.json").read_text())
        beats = self._media().synthesize_beats([b.narration for b in script.beats], Path(task["dir"]) / "audio",
                                               [b.pace for b in script.beats])
        task["narration_seconds"] = round(sum(b["duration"] for b in beats), 1)
        task["issues"] = []
        self._write_scene_brief(task, script, beats)
        try:
            self._enter(st, task, "scene")
        except LeaseLost:
            return self._lost(st)
        return (f"Script approved. Narration recorded: {task['narration_seconds']}s over {len(beats)} beats.\n"
                f"{self.next_line(st)}")

    def render(self) -> str:
        st = self._require()
        task = self._require_stage(st, "scene")
        d = Path(task["dir"])
        scene_file = d / "scene.py"
        if not scene_file.exists():
            raise EngineError(f"Write {scene_file} first.\n{self.next_line(st)}")
        code = scene_file.read_text()
        beats = json.loads((d / "audio" / "beats.json").read_text())
        task["attempt_no"] += 1
        attempt = d / f"attempt{task['attempt_no']}"
        attempt.mkdir(parents=True, exist_ok=True)
        (attempt / "scene.py").write_text(code)
        media = self._media()

        issues = media.lint_scene(code, len(beats))
        if issues:
            return self._fixable(st, "LINT FAILED:\n" + "\n".join(f"- {i}" for i in issues))
        try:
            self._enter(st, task, "render")  # renews the lease before a render that can take minutes
        except LeaseLost:
            return self._lost(st)
        try:
            result = media.render_scene(code, d / "audio" / "beats.json", attempt)
        finally:  # whatever happens, the driver can fix the scene and render again
            task["stage"] = "scene"
            self.save(st)
        task["renders"].append({"attempt": task["attempt_no"], "ok": result.ok, "seconds": round(result.seconds, 1)})
        if not result.ok:
            return self._fixable(st, f"RENDER FAILED ({result.seconds:.0f}s). Traceback tail:\n{result.error}")
        if result.layout_issues:
            return self._fixable(st, "RENDERED, BUT THE LAYOUT AUDIT FAILED:\n"
                                 + "\n".join(f"- {i}" for i in result.layout_issues))
        frames = media.extract_frames(result.video, result.timings, attempt / "frames")
        task["video"] = str(result.video)
        task["poster"] = str(frames[0][1]) if frames else None  # the first beat, fully drawn
        task["overrun_seconds"] = round(sum(t["overrun"] for t in result.timings), 2)
        script = Script.model_validate_json((d / "script.json").read_text())
        self._write_visual_brief(task, script, frames)
        try:
            self._enter(st, task, "visual")
        except LeaseLost:
            return self._lost(st)
        note = f" Animations overran the narration by {task['overrun_seconds']}s." if task["overrun_seconds"] else ""
        return f"RENDER OK in {result.seconds:.0f}s: {result.video}.{note}\n{self.next_line(st)}"

    def submit_visual(self, path: Path) -> str:
        st = self._require()
        task = self._require_stage(st, "visual")
        verdict, errors = self._parse(path, VisualVerdict)
        if errors:
            return self._invalid(st, "visual review", errors)
        task["review_log"].append({"step": "visual", "attempt": task["attempt_no"], "round": task["visual_round"],
                                   **verdict.model_dump()})
        task["visual_score"] = verdict.score
        if verdict.passed:
            return self._complete(st)
        issues = [f"beat {i.beat}: {i.problem} → {i.fix}" for i in verdict.issues]
        if task["visual_round"] >= VISUAL_ROUNDS:
            return self.fail(f"visual review still failing after {VISUAL_ROUNDS} revisions: "
                             + "; ".join(issues)[:1500], retryable=False)
        task["visual_round"] += 1
        task["fix_round"] = 0  # a visual revision gets a fresh render-fix budget
        task["issues"] = issues
        self._rewrite_scene_brief(task)
        try:
            self._enter(st, task, "scene")
        except LeaseLost:
            return self._lost(st)
        listing = "\n".join(f"  - {i}" for i in issues)
        return (f"Visual revision {task['visual_round']} of {VISUAL_ROUNDS} (score {verdict.score}). "
                f"Apply every fix in the scene:\n{listing}\n{self.next_line(st)}")

    # Steps.

    def _fixable(self, st: dict, detail: str) -> str:
        task = st["task"]
        task["fix_round"] += 1
        task["review_log"].append({"step": "render_fix", "attempt": task["attempt_no"], "detail": detail[-2000:]})
        if task["fix_round"] > FIX_ROUNDS:
            return self.fail(f"render fixes used up ({FIX_ROUNDS}): {detail[:600]}", retryable=False)
        task["issues"] = [detail]
        self._rewrite_scene_brief(task)
        try:
            self._enter(st, task, "scene")
        except LeaseLost:
            return self._lost(st)
        return f"{detail}\n\nRender fix {task['fix_round']} of {FIX_ROUNDS} used for this round.\n{self.next_line(st)}"

    def _complete(self, st: dict) -> str:
        task = st["task"]
        d = Path(task["dir"])
        script = Script.model_validate_json((d / "script.json").read_text())
        video = Path(task["video"])
        # A copy for human review next to the chunk reports; the app's copy goes through the API.
        review = (document_dir(self.settings, task["document"]["filename"]) / "reels"
                  / f"p{task['chunk']['page_start']:03d}-{task['chunk']['page_end']:03d}.mp4")
        review.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(video, review)
        try:
            key = self.api.upload_media(task["id"], st["run_id"], video)
            if task.get("poster") and Path(task["poster"]).exists():
                try:
                    self.api.upload_media(task["id"], st["run_id"], Path(task["poster"]), kind="poster")
                except ApiError as e:  # a missing poster only costs the feed a preview image
                    self._log(st, f"poster upload failed: {e}")
            result = self.api.complete(task["id"], st["run_id"], [], task["review_log"], reel={
                "title": script.title, "key_point": script.key_point, "storage_key": key,
                "duration_s": self._media().probe_duration(video) or None})
        except LeaseLost:
            return self._lost(st)
        st["reels_made"] += result.get("reels_created", 0)
        line = (f"Task {task['id']} {result['status']}: reel '{script.title}' (visual score {task['visual_score']})."
                f" Review copy: {review}")
        return self._done(st, line, {"status": result["status"], "questions": [], "video": str(review)})

    # Validation.

    @staticmethod
    def _check_script(script: Script) -> list[str]:
        issues = []
        words = sum(len(b.narration.split()) for b in script.beats)
        if not WORDS[0] <= words <= WORDS[1]:
            issues.append(f"narration is {words} words; needs {WORDS[0]}-{WORDS[1]}")
        if not 4 <= len(script.beats) <= 7:
            issues.append(f"{len(script.beats)} beats; needs 4-7")
        for i, b in enumerate(script.beats):
            if bad := SPOKEN_SYMBOLS.findall(b.narration):
                issues.append(f"beat {i}: narration contains symbols the TTS voice will read literally: "
                              f"{sorted(set(bad))}")
        if len(script.title.split()) > 5:
            issues.append("title is longer than 5 words")
        return issues

    # Briefs.

    def _issues_md(self, task: dict, heading: str) -> str:
        if not task["issues"]:
            return ""
        return f"\n## {heading}\n" + "\n".join(f"- {i}" for i in task["issues"]) + "\n"

    def _write_script_brief(self, task: dict) -> None:
        d = Path(task["dir"])
        r = task["script_round"]
        (d / f"script-brief-{r}.md").write_text(f"""# Write the reel script (round {r} of {SCRIPT_ROUNDS})

Instructions: {self.settings.prompts_dir / 'reel-script.md'}

The pages ({task['document']['filename']}, pages {task['chunk']['page_start']}-{task['chunk']['page_end']}) may
cover several ideas. Pick the single most valuable one and teach only that.

Notes read from the pages: {d / 'notes.json'}
Page images (they outrank the notes):
{self._pages_md(task)}
{self._issues_md(task, 'The reviewer failed the last round. Fix every issue')}
Write the script to {d / 'draft-script.json'} (edit it in place on later rounds), then run
`{self.command} submit script {d / 'draft-script.json'}`.

```json
{json.dumps(Script.model_json_schema(), indent=1)}
```
""")

    def _write_script_review_brief(self, task: dict) -> None:
        d = Path(task["dir"])
        r = task["script_round"]
        (d / f"script-review-brief-{r}.md").write_text(f"""# Review a reel script

You are an independent reviewer. Judge only from the files below.

Rubric: {self.settings.prompts_dir / 'reel-script-critic.md'}

Page images (the source of truth):
{self._pages_md(task)}

Notes read from those pages: {d / 'notes.json'}
The script: {d / 'script.json'}

Write your verdict as JSON to {d / f'script-review-{r}.json'} matching this schema:

```json
{json.dumps(ScriptVerdict.model_json_schema(), indent=1)}
```
""")

    def _write_scene_brief(self, task: dict, script: Script, beats: list[dict]) -> None:
        d = Path(task["dir"])
        durations = "\n".join(f"- beat {i}: {b['duration']:.2f}s | visual: {s.visual}"
                              for i, (b, s) in enumerate(zip(beats, script.beats)))
        task["scene_brief_base"] = f"""# Animate the reel

Instructions: {self.settings.prompts_dir / 'reel-scene.md'}
Base class (read it before your first scene): {Path(__file__).parent / 'reel_scene.py'}

Approved script: {d / 'script.json'}
Page images, for what the diagrams should show:
{self._pages_md(task)}

Narration per beat (`b.duration` inside `with self.beat(i) as b`):
{durations}

Write the scene module to {d / 'scene.py'} (edit it in place after a failure), then run
`{self.command} render`.
"""
        self._rewrite_scene_brief(task)

    def _rewrite_scene_brief(self, task: dict) -> None:
        d = Path(task["dir"])
        (d / "scene-brief.md").write_text(task["scene_brief_base"]
                                          + self._issues_md(task, "Fix these in scene.py before rendering again"))

    def _write_visual_brief(self, task: dict, script: Script, frames: list[tuple[int, Path]]) -> None:
        d = Path(task["dir"])
        listing = "\n".join(f"- {path} | beat {i} | narration: {script.beats[i].narration!r} | "
                            f"intended: {script.beats[i].visual!r}" for i, path in frames)
        (d / f"visual-brief-{task['attempt_no']}.md").write_text(f"""# Review the rendered reel's frames

You are an independent reviewer. Judge only from the files below.

Rubric: {self.settings.prompts_dir / 'reel-visual-check.md'}

Frames (the settled end of each listed beat, half resolution):
{listing}

Notes the reel teaches from: {d / 'notes.json'}

Write your verdict as JSON to {d / f'visual-{task["attempt_no"]}.json'} matching this schema:

```json
{json.dumps(VisualVerdict.model_json_schema(), indent=1)}
```
""")

    def _step_line(self, task: dict) -> str:
        d = Path(task["dir"])
        stage = task["stage"]
        if stage == "script":
            brief = d / f"script-brief-{task['script_round']}.md"
            return f"NEXT: follow {brief} yourself, then `{self.command} submit script {d / 'draft-script.json'}`."
        if stage == "script_review":
            r = task["script_round"]
            return self._subagent_line(d / f"script-review-brief-{r}.md", d / f"script-review-{r}.json",
                                       "script-review")
        if stage in ("scene", "render", "tts"):
            return f"NEXT: follow {d / 'scene-brief.md'} yourself, then `{self.command} render`."
        n = task["attempt_no"]
        return self._subagent_line(d / f"visual-brief-{n}.md", d / f"visual-{n}.json", "visual")

