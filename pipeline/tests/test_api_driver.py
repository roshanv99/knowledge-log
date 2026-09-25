"""Driver B against a fake Messages API client: every step answered, refusals handled."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from kl.config import load_settings
from kl.drivers.api import FALLBACK_BETA, ApiDriver
from kl.engine import Engine
from kl.schemas import ChunkNotes, Critique, MCQDraft
from tests.test_engine import NOTES, FakeApi, make_pdf, question


class FakeMessages:
    def __init__(self, refuse_on=None):
        self.calls, self.refuse_on = [], refuse_on

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        schema = kwargs["output_format"]
        if self.refuse_on is schema:
            return SimpleNamespace(stop_reason="refusal", stop_details=SimpleNamespace(category="cyber"),
                                   parsed_output=None)
        if schema is ChunkNotes:
            out = ChunkNotes(**NOTES)
        elif schema is MCQDraft:
            out = MCQDraft(questions=[question(i) for i in range(3)])
        else:
            out = Critique(overall="fine", reviews=[{"index": i, "verdict": "approve", "issues": []} for i in range(3)])
        return SimpleNamespace(stop_reason="end_turn", parsed_output=out)


@pytest.fixture
def env(tmp_path):
    pdf = make_pdf(tmp_path / "Docker.pdf", 12)
    settings = replace(load_settings(), output_dir=tmp_path / "output", work_dir=tmp_path / ".kl")

    def make(refuse_on=None, chunks=((1, 4),)):
        api = FakeApi(pdf, list(chunks))
        client = SimpleNamespace(messages=FakeMessages(refuse_on))
        return ApiDriver(Engine(settings, api, settings.work_dir / "api"), client), api, client
    return make


def test_api_driver_runs_a_task_end_to_end(env):
    driver, api, client = env()
    out = driver.run()
    assert "Run 1 finished: range_done" in out and len(api.completed[101]["questions"]) == 3
    schemas = [c["output_format"] for c in client.messages.calls]
    assert schemas == [ChunkNotes, MCQDraft, Critique]
    first = client.messages.calls[0]
    assert first["model"] == "claude-opus-5" and first["thinking"] == {"type": "adaptive"}
    assert first["extra_headers"] == {"anthropic-beta": FALLBACK_BETA} and first["extra_body"] == {"fallbacks": "default"}
    images = [b for b in first["messages"][0]["content"] if b["type"] == "image"]
    assert len(images) == 4 and images[0]["source"]["media_type"] == "image/jpeg"
    assert "You read pages" in first["system"] and not first["system"].startswith("---")
    critic_text = client.messages.calls[2]["messages"][0]["content"][-1]["text"]
    assert "Draft questions" in critic_text and "Question 0?" in critic_text  # files inlined, not paths


def test_refusal_fails_the_task_and_moves_on(env):
    driver, api, _ = env(refuse_on=MCQDraft, chunks=[(1, 4), (5, 8)])
    driver.run(max_steps=4)
    fails = [c for c in api.calls if c[0] == "fail"]
    assert fails and fails[0][2] == "model declined: cyber" and fails[0][3] is False
