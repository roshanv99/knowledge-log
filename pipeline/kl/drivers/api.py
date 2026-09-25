"""Driver B: answer the MCQ engine's LLM steps with the Claude Messages API and an API key.

Not yet tested against the real API (2026-09-24): unit tests use a fake client. It exists so the
same step engine can run where no Claude Code session does (a hosted worker, or someone who
brings an API key instead of Claude Code). See docs/PIPELINE_DB.md, "Driver B".

    ANTHROPIC_API_KEY=… KL_RUNNER_TOKEN=<an api-worker token> kl mcq drive --api

Each step is one `messages.parse` call with the step's instructions as the system prompt, the
page images inline, and the engine's JSON schema as the output format. The critic is a separate
call, so it never sees the writer's reasoning, which matches the fresh-subagent rule of driver A.
The engine still validates, budgets and saves everything; this module only fills in the steps.
"""

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from kl.engine import Engine
from kl.llm_prompts import load_prompt
from kl.schemas import ChunkNotes, Critique, MCQDraft

DEFAULT_MODEL = "claude-opus-5"
# Server-side refusal fallback: a declined request is re-run on Anthropic's recommended model.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class StepRefused(Exception):
    """The model (and its fallback) declined the step."""


@dataclass
class ApiDriver:
    engine: Engine
    client: Any  # anthropic.Anthropic, or a fake in tests
    model: str = DEFAULT_MODEL
    max_tokens: int = 16000
    log: list[str] = field(default_factory=list)

    def run(self, document_id: int | None = None, max_steps: int = 200) -> str:
        """Start (or resume) a run and answer steps until the engine says the run is over."""
        out = self.engine.start(document_id, {"driver": "api", "model": self.model})
        self.log.append(out)
        for _ in range(max_steps):
            st = self.engine.load()
            if st is None or not st.get("task"):
                return out
            try:
                out = self.step(st["task"])
            except StepRefused as e:
                out = self.engine.fail(f"model declined: {e}", retryable=False)
            self.log.append(out)
        return self.engine.stop("max_steps")

    def step(self, task: dict) -> str:
        d = Path(task["dir"])
        stage = task["stage"]
        if stage == "read":
            notes = self._ask("page-reader", task, self._read_text(task), ChunkNotes)
            return self.engine.submit_notes(self._write(d / "notes.json", notes))
        if stage == "write":
            r = task["round"]
            draft = self._ask("mcq-writer", task, self._brief(d / f"write-brief-{r}.md", task), MCQDraft)
            return self.engine.submit_draft(self._write(d / f"draft-{r}.json", draft))
        if stage == "critique":
            r = task["round"]
            text = self._brief(d / f"critique-brief-{r}.md", task,
                               extra={"Draft questions": d / f"draft-{r}-for-review.json"})
            verdict = self._ask("mcq-critic", task, text, Critique)
            return self.engine.submit_critique(self._write(d / f"critique-{r}.json", verdict))
        raise ValueError(f"unknown step {stage!r}")

    # One call per step.

    def _ask(self, prompt: str, task: dict, text: str, schema: type[BaseModel]) -> BaseModel:
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                "data": base64.standard_b64encode(Path(p).read_bytes()).decode()}}
                   for p in task["pages"]]
        content.append({"type": "text", "text": text})
        response = self.client.messages.parse(
            model=self.model,
            max_tokens=self.max_tokens,
            system=load_prompt(self.engine.settings.prompts_dir, prompt),
            messages=[{"role": "user", "content": content}],
            output_format=schema,
            thinking={"type": "adaptive"},
            extra_headers={"anthropic-beta": FALLBACK_BETA},
            extra_body={"fallbacks": "default"},
        )
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise StepRefused(getattr(details, "category", None) or "refused")
        if response.parsed_output is None:
            raise StepRefused(f"no structured output (stop_reason={response.stop_reason})")
        return response.parsed_output

    # Inputs: the engine's brief, with the files it points to inlined (the API can't open paths).

    def _read_text(self, task: dict) -> str:
        c = task["chunk"]
        layer = (Path(task["dir"]) / "text-layer.txt").read_text()
        return (f"Document: {task['document']['filename']}\nPages {c['page_start']}-{c['page_end']}. The page "
                f"images above are the source of truth.\n\nExtracted text layer (may be incomplete):\n{layer}")

    def _brief(self, brief: Path, task: dict, extra: dict[str, Path] | None = None) -> str:
        parts = [brief.read_text(), "The page images are attached above.",
                 f"## Notes (notes.json)\n```json\n{json.dumps(task['notes'], indent=1)}\n```"]
        for title, path in (extra or {}).items():
            parts.append(f"## {title}\n```json\n{path.read_text()}\n```")
        parts.append("Return only the JSON object in the requested schema; don't write files or run commands.")
        return "\n\n".join(parts)

    @staticmethod
    def _write(path: Path, value: BaseModel) -> Path:
        path.write_text(value.model_dump_json(indent=2))
        return path
