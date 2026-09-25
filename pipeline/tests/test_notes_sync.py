"""kl/notes_sync.py::scan() against a real tmp folder of PDFs."""

import shutil
from pathlib import Path

import pymupdf

from kl.notes_sync import scan


def make_pdf(path: Path, pages: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for n in range(1, pages + 1):
        doc.new_page().insert_text((72, 72), f"Page {n}")
    doc.save(path)
    return path


def test_missing_folder_reports_nothing(tmp_path):
    assert scan(tmp_path / "does-not-exist") == []


def test_walks_subfolders_and_reports_each_pdf(tmp_path):
    make_pdf(tmp_path / "Tech" / "Redis.pdf", 3)
    make_pdf(tmp_path / "Docker.pdf", 2)
    entries = scan(tmp_path)
    by_name = {e["filename"]: e for e in entries}
    assert set(by_name) == {"Redis.pdf", "Docker.pdf"}
    assert by_name["Redis.pdf"]["folder"] == "Tech" and by_name["Redis.pdf"]["page_count"] == 3
    assert by_name["Docker.pdf"]["page_count"] == 2
    for e in entries:
        assert e["size"] > 0 and e["mtime"] > 0 and len(e["file_hash"]) == 64


def test_moved_file_hashes_the_same_as_its_original(tmp_path):
    """PDFs writers (pymupdf included) embed a creation timestamp, so two separately generated
    files never hash identically even with the same visual content — identity only survives an
    exact copy (a real rename/move), which is the case content/notes.py relies on to recognise
    a moved file as the same document rather than a new one."""
    original = make_pdf(tmp_path / "a" / "Notes.pdf", 4)
    moved = tmp_path / "b" / "Notes-renamed.pdf"
    moved.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(original, moved)
    entries = {e["filename"]: e for e in scan(tmp_path)}
    assert entries["Notes.pdf"]["file_hash"] == entries["Notes-renamed.pdf"]["file_hash"]
