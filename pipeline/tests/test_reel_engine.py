"""The reel step engine against a fake API and fake media (no manim, no TTS)."""

import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from kl.config import load_settings
from kl.reels.engine import FIX_ROUNDS, SCRIPT_ROUNDS, VISUAL_ROUNDS, ReelEngine
from tests.test_engine import NOTES, FakeApi, make_pdf, write


@dataclass
class Render:
    ok: bool
    video: Path | None
    error: str
    seconds: float
    timings: list
    layout_issues: list


class FakeMedia:
    """Stands in for kl.reels.media. `renders` scripts what each render returns."""

    def __init__(self):
        self.lint_issues: list[str] = []
        self.renders: list[str] = []  # "ok", "crash" or "layout"
        self.synthesized = 0

    def synthesize_beats(self, narrations, out_dir, paces=None):
        self.synthesized += 1
        out_dir.mkdir(parents=True, exist_ok=True)
        beats = [{"text": t, "wav": str(out_dir / f"beat{i}.wav"), "duration": 8.0} for i, t in enumerate(narrations)]
        (out_dir / "beats.json").write_text(json.dumps(beats))
        return beats

    def lint_scene(self, code, n_beats):
        return self.lint_issues

    def render_scene(self, code, beats_json, work):
        outcome = self.renders.pop(0) if self.renders else "ok"
        video = work / "reel.mp4"
        video.write_bytes(b"\x00\x00\x00\x18ftypisom")
        timings = [{"end": 8.0 * (i + 1), "overrun": 0.0} for i in range(5)]
        if outcome == "crash":
            return Render(False, None, "Traceback: boom", 3.0, [], [])
        if outcome == "layout":
            return Render(True, video, "", 9.0, timings, ["beat 2: label off screen"])
        return Render(True, video, "", 9.0, timings, [])

    def extract_frames(self, video, timings, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        frames = [(i, out_dir / f"beat{i}.png") for i in (0, 2, 4)]
        for _, path in frames:
            path.write_bytes(b"\x89PNG\r\n\x1a\n")
        return frames

    def probe_duration(self, video):
        return 41.5


def script(words_per_beat=25, beats=5, title="Bridge networks"):
    narration = " ".join(["word"] * words_per_beat) + "."
    return {"title": title, "key_point": "Containers on one bridge talk by name.",
            "beats": [{"narration": narration, "visual": f"visual {i}", "pace": 1.0} for i in range(beats)]}


@pytest.fixture
def env(tmp_path):
    pdf = make_pdf(tmp_path / "Docker.pdf", 12)
    settings = replace(load_settings(), output_dir=tmp_path / "output", work_dir=tmp_path / ".kl",
                       logs_dir=tmp_path / "logs")

    def make(chunks=((1, 4),), read=None):
        api = FakeApi(pdf, list(chunks), read)
        engine = ReelEngine(settings, api, settings.work_dir)
        engine.media = FakeMedia()
        return engine, api
    return make


def tdir(engine) -> Path:
    return Path(engine.load()["task"]["dir"])


def to_scene(engine):
    engine.submit_notes(write(tdir(engine) / "notes.json", NOTES))
    engine.submit_script(write(tdir(engine) / "draft-script.json", script()))
    r = engine.load()["task"]["script_round"]
    return engine.submit_script_review(write(tdir(engine) / f"script-review-{r}.json",
                                             {"passed": True, "severity": "none", "issues": []}))


def scene(engine, code="class Reel(ReelScene): pass"):
    (tdir(engine) / "scene.py").write_text(code)
    return engine.render()


def visual(engine, passed=True, score=4):
    n = engine.load()["task"]["attempt_no"]
    issues = [] if passed else [{"beat": 2, "problem": "label overlaps", "fix": "move it down"}]
    return engine.submit_visual(write(tdir(engine) / f"visual-{n}.json",
                                      {"passed": passed, "score": score, "issues": issues}))


def test_happy_path_makes_uploads_and_completes_a_reel(env):
    engine, api = env()
    assert "read-brief.md" in engine.start()
    out = to_scene(engine)
    assert "Narration recorded: 40.0s over 5 beats" in out and "scene-brief.md" in out
    brief = (tdir(engine) / "scene-brief.md").read_text()
    assert "beat 0: 8.00s | visual: visual 0" in brief and "reel-scene.md" in brief and "reel_scene.py" in brief
    out = scene(engine)
    assert "RENDER OK" in out and "FRESH general-purpose subagent" in out
    assert "beat 2 | narration:" in (tdir(engine) / "visual-brief-1.md").read_text()
    out = visual(engine)
    assert "reel 'Bridge networks'" in out and "Run 1 finished: range_done" in out
    reel = api.completed[101]["reel"]
    assert reel == {"title": "Bridge networks", "key_point": "Containers on one bridge talk by name.",
                    "storage_key": "reels/task-101.mp4", "duration_s": 41.5}
    assert ("upload_media", 101, "reel.mp4") in api.calls and ("upload_media", 101, "beat0.png") in api.calls
    assert [e["step"] for e in api.completed[101]["review_log"]] == ["script", "script_review", "visual"]
    assert (engine.settings.output_dir / "docker" / "reels" / "p001-004.mp4").exists()
    stages = [c[2] for c in api.calls if c[0] == "heartbeat"]
    assert stages == ["read", "script", "script_review", "tts", "scene", "render", "visual"]


def test_mechanical_script_checks(env):
    engine, _ = env()
    engine.start()
    engine.submit_notes(write(tdir(engine) / "notes.json", NOTES))
    out = engine.submit_script(write(tdir(engine) / "draft-script.json", script(words_per_beat=10)))
    assert "INVALID script" in out and "narration is 50 words" in out
    bad = script()
    bad["beats"][1]["narration"] = "Set KEY=value then run it " + " ".join(["word"] * 20) + "."
    bad["title"] = "A title that is far too long"
    out = engine.submit_script(write(tdir(engine) / "draft-script.json", bad))
    assert "read literally" in out and "longer than 5 words" in out
    assert engine.load()["task"]["stage"] == "script"


def test_script_review_budget_fails_the_task_for_good(env):
    engine, api = env()
    engine.start()
    engine.submit_notes(write(tdir(engine) / "notes.json", NOTES))
    for r in range(1, SCRIPT_ROUNDS + 1):
        engine.submit_script(write(tdir(engine) / "draft-script.json", script()))
        out = engine.submit_script_review(write(tdir(engine) / f"script-review-{r}.json",
                                                {"passed": False, "severity": "high", "issues": [f"beat 2: wrong {r}"]}))
        if r < SCRIPT_ROUNDS:
            assert f"wrong {r}" in (tdir(engine) / f"script-brief-{r + 1}.md").read_text()
    fail = next(c for c in api.calls if c[0] == "fail")
    assert fail[3] is False and "script review still failing after 3 rounds" in fail[2]
    assert engine.media.synthesized == 0 and "range_done" in out


def test_render_fixes_are_budgeted_per_visual_round(env):
    engine, api = env()
    engine.start()
    to_scene(engine)
    engine.media.lint_issues = ["import of ['os'] is not allowed"]
    out = scene(engine)
    assert "LINT FAILED" in out and "Render fix 1 of 3" in out
    assert "import of" in (tdir(engine) / "scene-brief.md").read_text()
    engine.media.lint_issues = []
    engine.media.renders = ["crash", "layout", "crash"]
    assert "RENDER FAILED" in scene(engine)
    assert "LAYOUT AUDIT FAILED" in scene(engine)
    task = engine.load()["task"]
    assert task["stage"] == "scene" and task["fix_round"] == FIX_ROUNDS
    assert "import of" not in (tdir(engine) / "scene-brief.md").read_text()  # the brief shows the latest failure
    scene(engine)  # a 4th failure in this round
    assert "render fixes used up" in next(c for c in api.calls if c[0] == "fail")[2]


def test_visual_revisions_then_failure(env):
    engine, api = env()
    engine.start()
    to_scene(engine)
    scene(engine)
    out = visual(engine, passed=False, score=2)
    assert f"Visual revision 1 of {VISUAL_ROUNDS}" in out and "beat 2: label overlaps → move it down" in out
    task = engine.load()["task"]
    assert task["stage"] == "scene" and task["fix_round"] == 0
    assert "move it down" in (tdir(engine) / "scene-brief.md").read_text()
    for _ in range(VISUAL_ROUNDS):
        scene(engine)
        out = visual(engine, passed=False, score=2)
    assert "visual review still failing" in next(c for c in api.calls if c[0] == "fail")[2]
    assert "upload_media" not in api.names()


def test_read_notes_are_reused_and_untestable_pages_skip(env):
    engine, api = env(chunks=[(1, 4), (5, 8)], read={(1, 4): NOTES})
    assert "script-brief-1.md" in engine.start()  # notes from the quiz run: straight to the script
    engine.fail("not worth a reel", retryable=False)
    cover = {**NOTES, "key_points": [{"point": "cover", "page": 5}], "testable": False}
    out = engine.submit_notes(write(tdir(engine) / "notes.json", cover))
    assert "skipped: nothing to teach" in out


def test_lost_claim_during_upload_moves_on(env):
    engine, api = env(chunks=[(1, 4), (5, 8)])
    engine.start()
    to_scene(engine)
    scene(engine)
    api.lose.add("upload_media")
    out = visual(engine)
    assert "no longer holds that task" in out and engine.load()["task"]["chunk"]["page_start"] == 5


def test_render_crash_leaves_the_scene_step_retryable(env):
    engine, _ = env()
    engine.start()
    to_scene(engine)

    def explode(*a, **k):
        raise RuntimeError("ffmpeg missing")
    engine.media.render_scene = explode
    with pytest.raises(RuntimeError):
        scene(engine)
    assert engine.load()["task"]["stage"] == "scene"
