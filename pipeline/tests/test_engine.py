"""The step engine against a fake pipeline API: loop budgets, validation, lost claims, resume."""

import json
from dataclasses import replace
from pathlib import Path

import pymupdf
import pytest

from kl import runner
from kl.api import LeaseLost
from kl.config import load_settings
from kl.engine import MAX_INVALID, Engine, EngineError


def make_pdf(path: Path, pages: int) -> Path:
    doc = pymupdf.open()
    for n in range(1, pages + 1):
        doc.new_page().insert_text((72, 72), f"Page {n}: fact number {n}")
    doc.save(path)
    return path


class FakeApi:
    """Hands out queued chunks as tasks and records every call."""

    def __init__(self, pdf: Path, chunks: list[tuple[int, int]], read: dict | None = None,
                 doc_path: str | None = None, folder: str = ""):
        self.pdf, self.queue, self.read = pdf, list(chunks), read or {}
        # The recorded path can differ from where the real file actually is — e.g. stale, or
        # (see test_resolves_pdf_relative_to_notes_dir_when_present) simulating a machine that
        # only has the file under its own notes_dir, not at the originally-recorded path.
        # None (not resolved here) so tests that reassign api.pdf after construction (e.g.
        # test_missing_pdf_fails_without_retry) still take effect — claim() reads self.pdf live.
        self.doc_path, self.folder = doc_path, folder
        self.calls: list[tuple] = []
        self.completed: dict[int, dict] = {}
        self.lose: set[str] = set()  # method names that raise LeaseLost once
        self.next_id, self.runs = 100, 0

    def _maybe_lose(self, name):
        if name in self.lose:
            self.lose.discard(name)
            raise LeaseLost(409, "claim lost")

    def start_run(self, kind, params):
        self.runs += 1
        self.calls.append(("start_run", kind, params))
        return self.runs

    def claim(self, run_id, document_id=None):
        self.calls.append(("claim", run_id))
        if not self.queue:
            return {"task": None, "reason": "range_done"}
        start, end = self.queue.pop(0)
        self.next_id += 1
        notes = self.read.get((start, end))
        return {"task": {
            "id": self.next_id, "kind": "quiz", "attempt": 1, "lease_expires_at": None,
            "chunk": {"id": self.next_id, "page_start": start, "page_end": end,
                      "status": "read" if notes else "unread", "title": notes and notes["title"], "notes": notes},
            "document": {"id": 1, "filename": self.pdf.name, "path": self.doc_path or str(self.pdf),
                        "folder": self.folder, "page_count": 12}}, "reason": None}

    def heartbeat(self, task_id, run_id, stage, detail=None):
        self._maybe_lose("heartbeat")
        self.calls.append(("heartbeat", task_id, stage, detail))

    def save_notes(self, task_id, run_id, notes):
        self.calls.append(("save_notes", task_id, notes["testable"]))
        return "read" if notes["testable"] else "unreadable"

    def complete(self, task_id, run_id, questions, review_log, skipped_reason=None, reel=None):
        self._maybe_lose("complete")
        status = "done" if questions or reel else "skipped"
        self.completed[task_id] = {"questions": questions, "review_log": review_log, "skipped": skipped_reason,
                                   **({"reel": reel} if reel else {})}
        self.calls.append(("complete", task_id, len(questions)))
        return {"status": status, "questions_created": len(questions), "reels_created": int(bool(reel))}

    def upload_media(self, task_id, run_id, path, kind="video"):
        self._maybe_lose("upload_media")
        self.calls.append(("upload_media", task_id, Path(path).name))
        return f"reels/task-{task_id}.{'png' if kind == 'poster' else 'mp4'}"

    def fail(self, task_id, run_id, error, retryable):
        self.calls.append(("fail", task_id, error, retryable))
        return {"status": "pending" if retryable else "failed", "attempts": 1}

    def finish(self, run_id, stop_reason, usage=None):
        self.calls.append(("finish", run_id, stop_reason))
        return {}

    def wanted(self, kind):
        return None

    def names(self):
        return [c[0] for c in self.calls]


NOTES = {"title": "Bridges", "summary": "s", "key_points": [{"point": "p", "page": 1}], "testable": True}


def question(n: int, pages=(1,)) -> dict:
    return {"stem": f"Question {n}?", "options": [f"right {n}", "w1", "w2", "w3"], "correct_index": 0,
            "explanation": "because", "source_pages": list(pages), "difficulty": "easy"}


@pytest.fixture
def env(tmp_path):
    pdf = make_pdf(tmp_path / "Docker.pdf", 12)
    # notes_dir is isolated too (not left at whatever KL_NOTES_DIR/.env resolves to on the
    # machine running the tests) — claim() tries it first, and every other test here relies on
    # it being empty so they exercise the literal-path fallback deliberately, not by luck.
    settings = replace(load_settings(), output_dir=tmp_path / "output", work_dir=tmp_path / ".kl",
                       logs_dir=tmp_path / "logs", notes_dir=tmp_path / "notes")

    def make(chunks=((1, 4),), read=None, doc_path=None, folder=""):
        api = FakeApi(pdf, list(chunks), read, doc_path=doc_path, folder=folder)
        return Engine(settings, api, settings.work_dir), api
    return make


def write(path: Path, data) -> Path:
    path.write_text(json.dumps(data))
    return path


def task_dir(engine: Engine) -> Path:
    return Path(engine.load()["task"]["dir"])


def draft(engine: Engine, questions: list[dict]) -> str:
    st = engine.load()
    path = write(task_dir(engine) / f"draft-{st['task']['round']}.json", {"questions": questions})
    return engine.submit_draft(path)


def critique(engine: Engine, verdicts: list[str]) -> str:
    st = engine.load()
    reviews = [{"index": i, "verdict": v, "issues": [] if v == "approve" else ["weak"]} for i, v in enumerate(verdicts)]
    path = write(task_dir(engine) / f"critique-{st['task']['round']}.json", {"reviews": reviews, "overall": "ok"})
    return engine.submit_critique(path)


def test_happy_path_reads_writes_reviews_and_completes(env):
    engine, api = env()
    out = engine.start()
    assert "read-brief.md" in out and engine.load()["task"]["stage"] == "read"
    brief = (task_dir(engine) / "read-brief.md").read_text()
    assert "page-reader.md" in brief and "p001.jpg" in brief and "p004.jpg" in brief

    out = engine.submit_notes(write(task_dir(engine) / "notes.json", NOTES))
    assert "write-brief-1.md" in out
    assert "Write exactly 3 questions" in (task_dir(engine) / "write-brief-1.md").read_text()

    out = draft(engine, [question(i) for i in range(3)])
    assert "FRESH general-purpose subagent" in out and "critique-brief-1.md" in out
    assert "mcq-critic.md" in (task_dir(engine) / "critique-brief-1.md").read_text()

    out = critique(engine, ["approve"] * 3)
    assert "Run 1 finished: range_done" in out
    saved = api.completed[101]["questions"]
    assert len(saved) == 3
    for q in saved:  # shuffled, but the marked answer is still the right one
        assert q["options"][q["correct_index"]].startswith("right")
    assert [r["step"] for r in api.completed[101]["review_log"]] == ["draft", "critique"]
    assert api.names()[-1] == "finish" and engine.load() is None
    summary = (engine.settings.output_dir / "runs" / "run-001" / "summary.md").read_text()
    assert "range_done" in summary and "Question 0?" in summary
    assert list((engine.settings.output_dir / "docker" / "chunks").glob("p001-004.md"))


def test_revision_budget_keeps_revise_and_drops_reject(env):
    engine, api = env()
    engine.start()
    engine.submit_notes(write(task_dir(engine) / "notes.json", NOTES))
    draft(engine, [question(i) for i in range(3)])
    assert "Revising 2" in critique(engine, ["approve", "revise", "reject"])
    assert engine.load()["task"]["round"] == 2
    assert "Write exactly 2 questions" in (task_dir(engine) / "write-brief-2.md").read_text()
    draft(engine, [question(10), question(11)])
    critique(engine, ["approve", "revise"])
    assert "Write exactly 1 questions" in (task_dir(engine) / "write-brief-3.md").read_text()
    draft(engine, [question(20)])
    out = critique(engine, ["reject"])  # round 3 of 3: out of rounds
    assert "saved 2 questions (1 dropped after review)" in out
    assert len(api.completed[101]["review_log"]) == 6


def test_last_round_keeps_questions_that_only_need_polish(env):
    engine, api = env()
    engine.settings = replace(engine.settings, max_revisions=0)
    engine.start()
    engine.submit_notes(write(task_dir(engine) / "notes.json", NOTES))
    draft(engine, [question(i) for i in range(3)])
    assert "saved 2 questions (1 dropped" in critique(engine, ["approve", "revise", "reject"])


def test_invalid_drafts_are_bounced_then_the_task_fails(env):
    engine, api = env(chunks=[(1, 4), (5, 8)])
    engine.start()
    engine.submit_notes(write(task_dir(engine) / "notes.json", NOTES))
    out = draft(engine, [question(0), question(1)])
    assert "INVALID draft (1 of 3)" in out and "expected exactly 3 questions" in out
    assert engine.load()["task"]["stage"] == "write"
    out = draft(engine, [question(0, pages=(9,)), question(1), question(2)])
    assert "outside this chunk" in out
    out = draft(engine, [question(0), question(0), question(2)])
    assert "repeats the stem" in out and f"invalid {MAX_INVALID} times" in out.lower()
    assert ("fail", 101, "invalid draft 3 times: question 1: repeats the stem of another question", True) in api.calls
    assert engine.load()["task"]["chunk"]["page_start"] == 5  # moved on to the next task


def test_critique_must_cover_each_draft_once_and_missing_reviews_reject(env):
    engine, api = env()
    engine.start()
    engine.submit_notes(write(task_dir(engine) / "notes.json", NOTES))
    draft(engine, [question(i) for i in range(3)])
    bad = write(task_dir(engine) / "critique-1.json", {"overall": "x", "reviews": [
        {"index": 0, "verdict": "approve", "issues": []}, {"index": 0, "verdict": "approve", "issues": []}]})
    assert "INVALID critique" in engine.submit_critique(bad)
    partial = write(task_dir(engine) / "critique-1.json", {"overall": "x", "reviews": [
        {"index": 0, "verdict": "approve", "issues": []}]})
    out = engine.submit_critique(partial)
    assert "approved 1/3" in out and "Revising 2" in out  # unreviewed drafts count as rejected


def test_untestable_pages_are_skipped(env):
    engine, api = env()
    engine.start()
    out = engine.submit_notes(write(task_dir(engine) / "notes.json", {**NOTES, "testable": False}))
    assert "Task 101 skipped" in out
    assert api.completed[101] == {"questions": [], "review_log": [], "skipped": "nothing to teach: Bridges"}


def test_notes_outside_the_chunk_are_rejected(env):
    engine, api = env()
    engine.start()
    out = engine.submit_notes(write(task_dir(engine) / "notes.json",
                                    {**NOTES, "key_points": [{"point": "p", "page": 7}]}))
    assert "INVALID notes" in out and "save_notes" not in api.names()


def test_already_read_chunk_starts_at_writing(env):
    engine, api = env(read={(1, 4): NOTES})
    assert "write-brief-1.md" in engine.start()
    assert json.loads((task_dir(engine) / "notes.json").read_text()) == NOTES


def test_steps_must_come_in_order(env):
    engine, _ = env()
    engine.start()
    with pytest.raises(EngineError, match="needs the 'write' step"):
        draft(engine, [question(0)])


def test_lost_claim_moves_on(env):
    engine, api = env(chunks=[(1, 4), (5, 8)])
    engine.start()
    engine.submit_notes(write(task_dir(engine) / "notes.json", NOTES))
    draft(engine, [question(i) for i in range(3)])
    api.lose.add("complete")
    out = critique(engine, ["approve"] * 3)
    assert "no longer holds that task" in out and engine.load()["task"]["chunk"]["page_start"] == 5


def test_resume_or_restart(env):
    engine, api = env(chunks=[(1, 4), (5, 8)])
    engine.start()
    assert "Resuming run 1" in engine.start()
    api.lose.add("heartbeat")  # the server closed the run while we were away
    out = engine.start()
    assert "Started run 2" in out and api.runs == 2


def test_resolves_pdf_relative_to_notes_dir_when_present(env):
    """A cloud routine's sandbox has no copy of the file at the recorded path (that path only
    ever made sense on the machine that first discovered it) — it places the PDF under its own
    notes_dir instead, and claim() must prefer that over the stale recorded path."""
    engine, api = env(doc_path="/no/such/machine/has/this/path.pdf", folder="Tech")
    notes_folder = engine.settings.notes_dir / "Tech"
    notes_folder.mkdir(parents=True)
    make_pdf(notes_folder / api.pdf.name, 12)  # same filename, real content, under notes_dir/folder
    out = engine.start()
    assert "PDF not found" not in out
    assert not any(c[0] == "fail" for c in api.calls)
    assert engine.load()["task"]["chunk"]["page_start"] == 1  # claimed and proceeded normally


def test_missing_pdf_fails_without_retry(env, tmp_path):
    engine, api = env()
    api.pdf = tmp_path / "gone.pdf"
    out = engine.start()
    fail_call = next(c for c in api.calls if c[0] == "fail")
    assert fail_call[1] == 101 and str(tmp_path / "gone.pdf") in fail_call[2] and fail_call[3] is False
    assert "range_done" in out


def test_stop_finishes_the_run(env):
    engine, api = env()
    engine.start()
    assert "usage_limit" in engine.stop("usage_limit")
    assert ("finish", 1, "usage_limit") in api.calls and engine.load() is None


def test_runner_poll_starts_one_restricted_session(env, tmp_path):
    engine, api = env()
    s = engine.settings
    assert runner.poll(s, api) == "quiz: nothing wanted."

    api.wanted = lambda kind: {"kind": "quiz", "reason": "run_request", "document": "Docker.pdf", "pages": [1, 4]}
    spawned = []

    class Proc:
        pid = 4242

    def spawn(cmd, **kwargs):
        spawned.append(cmd)
        return Proc()

    assert "Would start" in runner.poll(s, api, dry_run=True) and not spawned
    out = runner.poll(s, api, spawn=spawn)
    assert "Started a session" in out and len(spawned) == 1
    cmd = spawned[0]
    assert cmd[:4] == ["caffeinate", "-i", s.claude_bin, "-p"] and "/mcq-generation" in cmd
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert "Bash(uv run --project pipeline kl mcq *)" in cmd and "WebFetch" not in cmd
    assert not any("kl reel" in c for c in cmd)  # each kind's session only gets its own engine

    import os
    runner.lock_path(s, "quiz").write_text(str(os.getpid()))  # a live quiz session holds the quiz lock
    assert "already running" in runner.poll(s, api, "quiz", spawn=spawn) and len(spawned) == 1
    # ...but a reel session can start alongside it.
    assert "Started a session" in runner.poll(s, api, "reel", spawn=spawn)
    assert "/reel-generation" in spawned[-1] and "Bash(uv run --project pipeline --extra reels kl reel *)" in spawned[-1]
