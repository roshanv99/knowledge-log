"""The shared half of every step engine (`kl mcq`, `kl reel`). No LLM calls in here.

A step engine claims one task at a time from the pipeline API and walks it through steps. The
steps that need judgement (reading pages, writing, reviewing) are done by a driver: the Claude
Code session following a skill, or later an API-key worker. The engine writes a brief for each
of those steps, validates what comes back, enforces the budgets, and reports to the API. Every
command prints a `NEXT:` line, and loop state lives in <work>/<kind>/state.json.

This base class owns what all kinds share: claiming, the read step (notes shared by every kind),
leases, invalid submissions, lost claims, resume, fail, stop and finish. A subclass adds its own
steps after `read` and says how a task completes.
"""

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ValidationError

from kl import output
from kl.api import Api, ApiError, LeaseLost
from kl.config import Settings
from kl.pdf import render_pages
from kl.schemas import ChunkNotes

MAX_INVALID = 3  # invalid submissions of one step before the task is failed (retryable)


class EngineError(Exception):
    """A command that can't run in the current state; the message says what to do instead."""


@dataclass
class StepEngine:
    settings: Settings
    api: Api
    work_dir: Path

    kind: ClassVar[str]
    command: ClassVar[str]  # how the driver runs this engine, e.g. "kl mcq"

    # Hooks for the subclass.

    def _new_task(self, task: dict) -> None:
        """Add kind-specific fields to a freshly claimed task."""

    def _begin(self, st: dict, task: dict) -> str:
        """Notes are available: move to the kind's first step. Returns what to print."""
        raise NotImplementedError

    def _step_line(self, task: dict) -> str:
        """The NEXT: line for a kind-specific step."""
        raise NotImplementedError

    def _detail(self, task: dict) -> str | None:
        """Progress detail sent with heartbeats, e.g. 'round 2 of 3'."""
        return None

    def _totals(self, st: dict) -> str:
        return f"{st['tasks_done']} tasks done"

    def _run_report(self, st: dict) -> Path:
        raise NotImplementedError

    # State.

    @property
    def root(self) -> Path:
        return self.work_dir / self.kind

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    def load(self) -> dict | None:
        return json.loads(self.state_path.read_text()) if self.state_path.exists() else None

    def save(self, st: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=2))
        tmp.replace(self.state_path)

    def _require(self) -> dict:
        st = self.load()
        if st is None:
            raise EngineError(f"No run in progress. Start one with `{self.command} start`.")
        return st

    def _require_stage(self, st: dict, *stages: str) -> dict:
        task = st.get("task")
        if not task or task["stage"] not in stages:
            raise EngineError(f"This command needs the '{'/'.join(stages)}' step, but the current step is "
                              f"'{task['stage'] if task else 'none'}'.\n{self.next_line(st)}")
        return task

    # Commands.

    def start(self, document_id: int | None = None, runner_params: dict | None = None) -> str:
        """Start a run, or resume the one in progress if the server still has it."""
        st = self.load()
        if st is not None and st.get("task"):
            try:
                self._beat(st)  # proves the server still has this run and our claim
                return f"Resuming run {st['run_id']}.\n{self.next_line(st)}"
            except (LeaseLost, ApiError) as e:
                self._archive(st, f"stale: {e}")
        elif st is not None:  # stopped between tasks: close that run and start afresh
            try:
                self.api.finish(st["run_id"], "interrupted")
            except ApiError:
                pass
            self._archive(st, "interrupted between tasks")
        run_id = self.api.start_run(self.kind, {"document_id": document_id, **(runner_params or {})})
        st = {"run_id": run_id, "document_id": document_id, "started_at": time.time(), "task": None,
              "tasks_done": 0, "questions_made": 0, "reels_made": 0, "dropped": 0, "chunks": [], "log": []}
        self.save(st)
        return f"Started run {run_id}.\n" + self._claim_next(st)

    def status(self) -> str:
        st = self._require()
        try:
            self._beat(st)
        except LeaseLost:
            return self._lost(st)
        task = st.get("task")
        head = f"Run {st['run_id']}: {self._totals(st)}."
        if task:
            detail = self._detail(task)
            head += (f"\nCurrent: {task['document']['filename']} pages {task['chunk']['page_start']}-"
                     f"{task['chunk']['page_end']}, step {task['stage']}" + (f" ({detail})" if detail else ""))
        return f"{head}\n{self.next_line(st)}"

    def submit_notes(self, path: Path) -> str:
        st = self._require()
        task = self._require_stage(st, "read")
        notes, errors = self._parse(path, ChunkNotes)
        if notes is not None:
            pages = set(range(task["chunk"]["page_start"], task["chunk"]["page_end"] + 1))
            outside = sorted({k.page for k in notes.key_points} - pages)
            if outside:
                errors = [f"key_points cite pages {outside}, outside this chunk ({min(pages)}-{max(pages)})"]
        if errors:
            return self._invalid(st, "notes", errors)
        try:
            self.api.save_notes(task["id"], st["run_id"], notes.model_dump())
        except LeaseLost:
            return self._lost(st)
        task["notes"] = notes.model_dump()
        task["chunk"]["title"] = notes.title
        (Path(task["dir"]) / "notes.json").write_text(json.dumps(task["notes"], indent=2))
        if not notes.testable:
            return self._skip(st, f"nothing to teach: {notes.title}")
        head = f"Saved notes: {notes.title} ({len(notes.key_points)} key points)."
        return f"{head}\n{self._begin(st, task)}"

    def fail(self, error: str, retryable: bool) -> str:
        """The driver gives up on the current task (e.g. unreadable pages, repeated tool errors)."""
        st = self._require()
        task = st.get("task")
        if not task:
            raise EngineError(f"No task to fail.\n{self.next_line(st)}")
        try:
            result = self.api.fail(task["id"], st["run_id"], error, retryable)
        except LeaseLost:
            return self._lost(st)
        self._log(st, f"task {task['id']} failed ({result['status']}): {error}")
        st["task"] = None
        self.save(st)
        return f"Task {task['id']} marked {result['status']}.\n" + self._claim_next(st)

    def stop(self, reason: str, usage: dict | None = None) -> str:
        return self._finish(self._require(), reason, usage)

    # Shared steps.

    def _claim_next(self, st: dict) -> str:
        try:
            result = self.api.claim(st["run_id"], st.get("document_id"))
        except LeaseLost as e:  # the server closed the run
            return self._finish(st, "closed_by_server", None, notify=False, why=str(e))
        if result["task"] is None:
            return self._finish(st, result["reason"], None)
        payload = result["task"]
        chunk, document = payload["chunk"], payload["document"]
        task_dir = self.root / f"task-{payload['id']}"
        if task_dir.exists():  # a re-claimed task starts over; the server has its notes if it had any
            shutil.rmtree(task_dir)
        task_dir.mkdir(parents=True)
        task = {"id": payload["id"], "attempt": payload["attempt"], "reel_style": payload.get("reel_style"),
                "chunk": chunk, "document": document, "dir": str(task_dir), "stage": "read", "round": 0,
                "notes": None, "review_log": [], "invalid": 0}
        self._new_task(task)
        st["task"] = task

        # The notes folder lives on the API's server, so every runner fetches the PDF from there.
        # Keyed by document id: a PDF whose content changes becomes a new document (and id), so a
        # cached copy is never stale.
        pdf = self.settings.work_dir / "pdfs" / f"{document['id']}.pdf"
        if not pdf.exists():
            try:
                self.api.download_pdf(document["id"], pdf)
            except ApiError as e:
                self.save(st)
                return self.fail(f"Couldn't download the PDF: {e}", retryable=e.status != 404)
        pages = render_pages(pdf, chunk["page_start"], chunk["page_end"],
                             output.pages_dir(self.settings, document["filename"]), self.settings.page_dpi)
        task["pages"] = [str(p.image_path) for p in pages]
        (task_dir / "text-layer.txt").write_text(
            "\n".join(f"--- page {p.number} ---\n{p.text or '(no text layer)'}" for p in pages))

        claimed = (f"Claimed task {task['id']}: {document['filename']} pages {chunk['page_start']}-"
                   f"{chunk['page_end']} (attempt {task['attempt']}).")
        if chunk["status"] == "unreadable":
            self.save(st)
            return f"{claimed}\n" + self._skip(st, "these pages hold nothing to teach")
        if chunk["status"] == "read" and chunk["notes"]:
            task["notes"] = chunk["notes"]
            (task_dir / "notes.json").write_text(json.dumps(chunk["notes"], indent=2))
            return f"{claimed}\n{self._begin(st, task)}"
        self._write_read_brief(task)
        self.save(st)
        self._beat(st)
        return f"{claimed}\n{self.next_line(st)}"

    def _skip(self, st: dict, reason: str) -> str:
        """Nothing worth making from these pages."""
        task = st["task"]
        try:
            result = self.api.complete(task["id"], st["run_id"], [], task["review_log"], reason)
        except LeaseLost:
            return self._lost(st)
        return self._done(st, f"Task {task['id']} {result['status']}: {reason}.",
                          {"status": result["status"], "questions": []})

    def _done(self, st: dict, line: str, record: dict) -> str:
        """Bookkeeping after the API accepted a completion, then the next claim."""
        task = st["task"]
        st["tasks_done"] += 1
        st["chunks"].append({"task_id": task["id"], "title": task["chunk"]["title"],
                             "pages": [task["chunk"]["page_start"], task["chunk"]["page_end"]], **record})
        self._log(st, line)
        st["task"] = None
        self.save(st)
        return line + "\n" + self._claim_next(st)

    def _finish(self, st: dict, reason: str, usage: dict | None, *, notify: bool = True, why: str = "") -> str:
        if notify:
            try:
                self.api.finish(st["run_id"], reason, usage)
            except (LeaseLost, ApiError):
                pass  # already closed on the server
        st["stop_reason"] = reason
        report = self._run_report(st)
        self._archive(st, reason)
        detail = f" ({why})" if why else ""
        return (f"Run {st['run_id']} finished: {reason}{detail}. {self._totals(st)}. Review: {report}\n"
                f"NEXT: nothing — the run is over. Tell the user the stop reason and the review path.")

    def _lost(self, st: dict) -> str:
        """Our claim is gone (lease expired and re-claimed, or the run was closed): drop the task, move on."""
        task = st.get("task")
        self._log(st, f"lost the claim on task {task['id'] if task else '?'}")
        st["task"] = None
        self.save(st)
        return "This run no longer holds that task; dropping it.\n" + self._claim_next(st)

    def _invalid(self, st: dict, what: str, errors: list[str]) -> str:
        task = st["task"]
        task["invalid"] += 1
        self.save(st)
        listing = "\n".join(f"  - {e}" for e in errors)
        if task["invalid"] >= MAX_INVALID:
            return (f"The {what} was invalid {MAX_INVALID} times:\n{listing}\n"
                    + self.fail(f"invalid {what} {MAX_INVALID} times: {errors[0]}", retryable=True))
        return (f"INVALID {what} ({task['invalid']} of {MAX_INVALID}); fix these and submit again:\n{listing}\n"
                f"{self.next_line(st)}")

    def _enter(self, st: dict, task: dict, stage: str) -> None:
        """Move to a step: reset the invalid count, save, and renew the lease with the new stage."""
        task["stage"], task["invalid"] = stage, 0
        self.save(st)
        self._beat(st)

    def _beat(self, st: dict) -> None:
        task = st.get("task")
        if task is None:
            return
        self.api.heartbeat(task["id"], st["run_id"], task["stage"],
                           None if task["stage"] == "read" else self._detail(task))

    def _archive(self, st: dict, why: str) -> None:
        if self.state_path.exists():
            done = self.root / "runs"
            done.mkdir(parents=True, exist_ok=True)
            st["archived_because"] = why
            (done / f"run-{st['run_id']}.json").write_text(json.dumps(st, indent=2))
            self.state_path.unlink()
            for task_dir in self.root.glob("task-*"):
                shutil.rmtree(task_dir, ignore_errors=True)

    def _log(self, st: dict, line: str) -> None:
        st["log"].append(line)

    @staticmethod
    def _parse(path: Path, schema: type[BaseModel]):
        try:
            return schema.model_validate_json(Path(path).read_text()), []
        except FileNotFoundError:
            return None, [f"{path} does not exist"]
        except ValidationError as e:
            return None, [f"{'.'.join(map(str, err['loc'])) or 'root'}: {err['msg']}" for err in e.errors()]

    # Briefs and NEXT lines.

    def _pages_md(self, task: dict) -> str:
        return "\n".join(f"- {p}" for p in task["pages"])

    def _write_read_brief(self, task: dict) -> None:
        d = Path(task["dir"])
        (d / "read-brief.md").write_text(f"""# Read pages {task['chunk']['page_start']}-{task['chunk']['page_end']} of {task['document']['filename']}

Instructions: {self.settings.prompts_dir / 'page-reader.md'}

Page images (the source of truth; read every one):
{self._pages_md(task)}

Extracted text layer (often empty or partial): {d / 'text-layer.txt'}

Write the notes as JSON to {d / 'notes.json'} matching this schema, then run
`{self.command} submit notes {d / 'notes.json'}`:

```json
{json.dumps(ChunkNotes.model_json_schema(), indent=1)}
```
""")

    def next_line(self, st: dict) -> str:
        task = st.get("task")
        if not task:
            return f"NEXT: `{self.command} status` (no task in hand)."
        if task["stage"] == "read":
            d = Path(task["dir"])
            return (f"NEXT: follow {d / 'read-brief.md'} yourself (read the page images), then "
                    f"`{self.command} submit notes {d / 'notes.json'}`.")
        return self._step_line(task)

    def _subagent_line(self, brief: Path, out: Path, submit: str) -> str:
        return (f"NEXT: spawn a FRESH general-purpose subagent as the reviewer. Give it only the path {brief} "
                f"and ask it to follow that brief and write {out}. Then `{self.command} submit {submit} {out}`.")
