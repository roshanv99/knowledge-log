"""Runtime settings, read from the environment (and the project-root .env)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    output_dir: Path
    work_dir: Path  # the step engine's loop state and briefs (.kl/)
    logs_dir: Path
    prompts_dir: Path
    api_base: str
    runner_token: str | None
    claude_bin: str
    questions_per_chunk: int
    max_revisions: int
    page_dpi: int


def load_settings() -> Settings:
    env = os.environ.get
    return Settings(
        output_dir=Path(env("KL_OUTPUT_DIR", PROJECT_ROOT / "output")),
        work_dir=Path(env("KL_WORK_DIR", PROJECT_ROOT / ".kl")),
        logs_dir=Path(env("KL_LOGS_DIR", PROJECT_ROOT / "logs")),
        prompts_dir=Path(env("KL_PROMPTS_DIR", PROJECT_ROOT / "plugin/knowledge-log/prompts")),
        api_base=env("KL_API_BASE", "http://localhost:8010/api"),
        runner_token=env("KL_RUNNER_TOKEN") or None,
        claude_bin=env("KL_CLAUDE_BIN", "claude"),
        questions_per_chunk=int(env("KL_QUESTIONS_PER_CHUNK", "3")),
        max_revisions=int(env("KL_MAX_REVISIONS", "2")),
        page_dpi=int(env("KL_PAGE_DPI", "130")),
    )
