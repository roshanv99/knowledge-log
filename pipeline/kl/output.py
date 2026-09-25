"""Human-review files under output/. The database (through the API) is the source of truth.

    output/<document>/pages/p001.jpg        rendered pages (what Claude saw)
    output/<document>/chunks/p001-004.md    per-chunk notes, final questions, dropped ones, review log
    output/runs/run-<id>/summary.md         everything a run produced, answers included
    output/runs/run-<id>/questions.json     the same questions as data
"""

import json
import re
from datetime import datetime
from pathlib import Path

from kl.config import Settings

LETTERS = "ABCD"


def document_dir(s: Settings, filename: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", Path(filename).stem.lower()).strip("-")
    return s.output_dir / slug


def pages_dir(s: Settings, filename: str) -> Path:
    return document_dir(s, filename) / "pages"


def chunk_path(s: Settings, filename: str, page_start: int, page_end: int) -> Path:
    return document_dir(s, filename) / "chunks" / f"p{page_start:03d}-{page_end:03d}.md"


def _question_md(n: int, q: dict) -> list[str]:
    lines = [f"**Q{n}.** {q['stem']}  ",
             f"*{q['difficulty']} · pages {', '.join(map(str, q['source_pages']))}*", ""]
    lines += [f"- {'✅' if i == q['correct_index'] else '⬜'} {LETTERS[i]}. {opt}" for i, opt in enumerate(q["options"])]
    return lines + ["", f"> {q['explanation']}", ""]


def write_chunk_report(s: Settings, task: dict, questions: list[dict], dropped: list[dict], status: str) -> Path:
    chunk, document = task["chunk"], task["document"]
    path = chunk_path(s, document["filename"], chunk["page_start"], chunk["page_end"])
    path.parent.mkdir(parents=True, exist_ok=True)
    notes = task["notes"] or {}
    lines = [f"# {chunk['title'] or 'Untitled'} — pages {chunk['page_start']}–{chunk['page_end']}", "",
             f"Document: `{document['filename']}` · task {task['id']} · status **{status}**", "",
             " ".join(f"[p{p}](../pages/p{p:03d}.jpg)" for p in range(chunk["page_start"], chunk["page_end"] + 1)),
             "", "## Summary", "", notes.get("summary", "—"), "", "## Key points", ""]
    lines += [f"- (p{k['page']}) {k['point']}" for k in notes.get("key_points", [])]
    lines += ["", f"## Questions ({len(questions)})", ""]
    for n, q in enumerate(questions, 1):
        lines += _question_md(n, q)
    if dropped:
        lines += [f"## Dropped after review ({len(dropped)})", ""]
        for n, f in enumerate(dropped, 1):
            lines += _question_md(n, f["question"]) + [f"Rejected: {'; '.join(f['issues'])}", ""]
    lines += ["## Review log", ""]
    for entry in task["review_log"]:
        if entry["step"] == "draft":
            lines.append(f"- **Round {entry['round']}** — drafted {len(entry['questions'])} questions")
        else:
            lines.append(f"- **Round {entry['round']} critique** — {entry['overall']}")
            for r in entry["reviews"]:
                issues = f": {'; '.join(r['issues'])}" if r["issues"] else ""
                lines.append(f"  - draft Q{r['index'] + 1}: **{r['verdict']}**{issues}")
    path.write_text("\n".join(lines) + "\n")
    return path


def write_run_report(s: Settings, st: dict) -> Path:
    run_dir = s.output_dir / "runs" / f"run-{st['run_id']:03d}"
    run_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.fromtimestamp(st["started_at"])
    lines = [f"# Run {st['run_id']} — quiz", "", "| | |", "|---|---|",
             f"| Stop reason | **{st.get('stop_reason')}** |",
             f"| Tasks completed | {st['tasks_done']} |",
             f"| Questions saved | {st['questions_made']} |",
             f"| Dropped after review | {st['dropped']} |",
             f"| Started / finished | {started:%Y-%m-%d %H:%M} / {datetime.now():%H:%M} local |", ""]
    n, questions = 0, []
    for c in st["chunks"]:
        rel = Path(c["report"]).resolve().relative_to(s.output_dir.resolve()) if c.get("report") else None
        link = f" · [chunk review](../../{rel})" if rel else ""
        lines += [f"## {c['title']} (p{c['pages'][0]}–{c['pages'][1]}) · {c['status']}{link}", ""]
        for q in c["questions"]:
            n += 1
            lines += _question_md(n, q)
            questions.append({"task_id": c["task_id"], "topic": c["title"], **q})
    if st.get("log"):
        lines += ["## Log", ""] + [f"- {line}" for line in st["log"]]
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n")
    (run_dir / "questions.json").write_text(json.dumps(questions, indent=2))
    return run_dir / "summary.md"
