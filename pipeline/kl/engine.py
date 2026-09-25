"""The MCQ step engine (`kl mcq`). No LLM calls in here; see kl/steps.py for the shared half.

    read ──► write r1 ──► critique r1 ──► (write rN ──► critique rN)* ──► complete ──► next task

The driver writes each draft and a fresh reviewer critiques it. The engine checks every draft,
enforces the revision budget, keeps "revise" verdicts and drops "reject" ones when rounds run
out, shuffles answer positions, and completes the task.
"""

import json
import random
from pathlib import Path

from kl import output
from kl.api import LeaseLost
from kl.schemas import Critique, MCQDraft
from kl.steps import MAX_INVALID, EngineError, StepEngine

__all__ = ["Engine", "EngineError", "MAX_INVALID"]


class Engine(StepEngine):
    kind = "quiz"
    command = "uv run --project pipeline kl mcq"

    # Hooks.

    def _new_task(self, task: dict) -> None:
        task.update(draft=[], accepted=[], flagged=[])

    def _begin(self, st: dict, task: dict) -> str:
        self._to_write(st, task, 1)
        return self.next_line(st)

    def _detail(self, task: dict) -> str | None:
        return f"round {task['round']} of {self.max_rounds}"

    def _totals(self, st: dict) -> str:
        return f"{st['tasks_done']} tasks, {st['questions_made']} questions saved, {st['dropped']} dropped"

    def _run_report(self, st: dict) -> Path:
        return output.write_run_report(self.settings, st)

    @property
    def max_rounds(self) -> int:
        return 1 + self.settings.max_revisions

    # Commands.

    def submit_draft(self, path: Path) -> str:
        st = self._require()
        task = self._require_stage(st, "write")
        draft, errors = self._parse(path, MCQDraft)
        if draft is not None:
            errors = self._check_draft(task, [q.model_dump() for q in draft.questions])
        if errors:
            return self._invalid(st, "draft", errors)
        questions = [q.model_dump() for q in draft.questions]
        task["draft"] = questions
        task["review_log"].append({"round": task["round"], "step": "draft", "questions": questions})
        self._write_critique_brief(task)
        try:
            self._enter(st, task, "critique")
        except LeaseLost:
            return self._lost(st)
        return f"Draft of {len(questions)} questions recorded (round {task['round']}).\n{self.next_line(st)}"

    def submit_critique(self, path: Path) -> str:
        st = self._require()
        task = self._require_stage(st, "critique")
        critique, errors = self._parse(path, Critique)
        if critique is not None:
            indexes = [r.index for r in critique.reviews]
            if len(set(indexes)) != len(indexes) or not set(indexes) <= set(range(len(task["draft"]))):
                errors = [f"reviews must cover draft indexes 0..{len(task['draft']) - 1}, each once; got {indexes}"]
        if errors:
            return self._invalid(st, "critique", errors)
        result = critique.model_dump()
        task["review_log"].append({"round": task["round"], "step": "critique", **result})
        reviews = {r["index"]: r for r in result["reviews"]}
        flagged = []
        for i, q in enumerate(task["draft"]):
            # A question the critic skipped counts as rejected: nothing unreviewed is published.
            review = reviews.get(i, {"verdict": "reject", "issues": ["not reviewed"]})
            if review["verdict"] == "approve":
                task["accepted"].append(q)
            else:
                flagged.append({"question": q, "verdict": review["verdict"], "issues": review["issues"]})
        reviewed = len(task["draft"])
        task["flagged"], task["draft"] = flagged, []
        summary = f"Round {task['round']}: critic approved {reviewed - len(flagged)}/{reviewed}."
        if flagged and task["round"] < self.max_rounds:
            self._to_write(st, task, task["round"] + 1)
            return f"{summary} Revising {len(flagged)}.\n{self.next_line(st)}"
        # Out of rounds: questions needing only polish are kept, wrong or ungrounded ones dropped.
        keep = task["accepted"] + [f["question"] for f in flagged if f["verdict"] == "revise"]
        dropped = [f for f in flagged if f["verdict"] == "reject"]
        return summary + "\n" + self._complete(st, keep, dropped)

    # Steps.

    def _to_write(self, st: dict, task: dict, round_: int) -> None:
        task["round"] = round_
        self._write_writer_brief(task)
        self._enter(st, task, "write")

    def _complete(self, st: dict, keep: list[dict], dropped: list[dict]) -> str:
        task = st["task"]
        # Writers favour certain answer positions; shuffle so the answer letter carries no signal.
        rng = random.Random(task["id"])
        questions = []
        for q in keep:
            order = rng.sample(range(4), 4)
            questions.append({**q, "options": [q["options"][j] for j in order],
                              "correct_index": order.index(q["correct_index"])})
        try:
            result = self.api.complete(task["id"], st["run_id"], questions, task["review_log"])
        except LeaseLost:
            return self._lost(st)
        report = output.write_chunk_report(self.settings, task, questions, dropped, result["status"])
        st["questions_made"] += result["questions_created"]
        st["dropped"] += len(dropped)
        line = (f"Task {task['id']} {result['status']}: saved {len(questions)} questions"
                f" ({len(dropped)} dropped after review). Review: {report}")
        return self._done(st, line, {"status": result["status"], "questions": questions, "report": str(report)})

    # Validation.

    def _check_draft(self, task: dict, questions: list[dict]) -> list[str]:
        errors = []
        needed = self._needed(task)
        if len(questions) != needed:
            errors.append(f"expected exactly {needed} questions, got {len(questions)}")
        pages = set(range(task["chunk"]["page_start"], task["chunk"]["page_end"] + 1))
        taken = {q["stem"].strip().lower() for q in task["accepted"]}
        for i, q in enumerate(questions):
            if outside := sorted(set(q["source_pages"]) - pages):
                errors.append(f"question {i}: source_pages {outside} are outside this chunk "
                              f"({min(pages)}-{max(pages)})")
            if not q["source_pages"]:
                errors.append(f"question {i}: source_pages is empty")
            if len({o.strip().lower() for o in q["options"]}) != 4:
                errors.append(f"question {i}: the 4 options must be distinct")
            stem = q["stem"].strip().lower()
            if stem in taken:
                errors.append(f"question {i}: repeats the stem of another question")
            taken.add(stem)
        return errors

    def _needed(self, task: dict) -> int:
        return self.settings.questions_per_chunk - len(task["accepted"])

    # Briefs.

    def _write_writer_brief(self, task: dict) -> None:
        d = Path(task["dir"])
        out = d / f"draft-{task['round']}.json"
        revision = ""
        if task["flagged"]:
            revision = f"""
This is revision round {task['round']}. The reviewer flagged these questions; return each one fixed so
every issue is resolved, or replaced with a better question:

```json
{json.dumps(task['flagged'], indent=1)}
```

Already approved (do not repeat their topics):

```json
{json.dumps(task['accepted'], indent=1)}
```
"""
        (d / f"write-brief-{task['round']}.md").write_text(f"""# Write {self._needed(task)} quiz questions (round {task['round']} of {self.max_rounds})

Instructions: {self.settings.prompts_dir / 'mcq-writer.md'}

Notes for pages {task['chunk']['page_start']}-{task['chunk']['page_end']}: {d / 'notes.json'}

Page images (they outrank the notes):
{self._pages_md(task)}
{revision}
Write exactly {self._needed(task)} questions as JSON to {out} matching this schema, then run
`{self.command} submit draft {out}`. `source_pages` must lie within {task['chunk']['page_start']}-{task['chunk']['page_end']}.

```json
{json.dumps(MCQDraft.model_json_schema(), indent=1)}
```
""")

    def _write_critique_brief(self, task: dict) -> None:
        d = Path(task["dir"])
        draft = d / f"draft-{task['round']}-for-review.json"
        draft.write_text(json.dumps(task["draft"], indent=2))
        context = ""
        if task["accepted"]:
            context = f"""
Already approved in this set (context only, do not review them; flag drafts that duplicate them):

```json
{json.dumps(task['accepted'], indent=1)}
```
"""
        out = d / f"critique-{task['round']}.json"
        (d / f"critique-brief-{task['round']}.md").write_text(f"""# Review {len(task['draft'])} draft quiz questions

You are an independent reviewer. Judge only from the files below.

Rubric: {self.settings.prompts_dir / 'mcq-critic.md'}

Page images (the source of truth):
{self._pages_md(task)}

Notes extracted from those pages: {d / 'notes.json'}

Draft questions to review, 0-based indexes in list order: {draft}
{context}
Write your verdict as JSON to {out}, one review per draft index, matching this schema:

```json
{json.dumps(Critique.model_json_schema(), indent=1)}
```
""")

    def _step_line(self, task: dict) -> str:
        d, r = Path(task["dir"]), task["round"]
        if task["stage"] == "write":
            return (f"NEXT: follow {d / f'write-brief-{r}.md'} yourself, then "
                    f"`{self.command} submit draft {d / f'draft-{r}.json'}`.")
        return self._subagent_line(d / f"critique-brief-{r}.md", d / f"critique-{r}.json", "critique")
