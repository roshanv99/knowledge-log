"""Prompt files: Markdown in plugin/knowledge-log/prompts/, with optional YAML frontmatter."""

from pathlib import Path


def load_prompt(prompts_dir: Path, name: str) -> str:
    body = (prompts_dir / f"{name}.md").read_text()
    if body.startswith("---"):
        body = body.split("---", 2)[2]
    return body.strip()
