"""What the Django backend can't see for itself once it's deployed away from the notes
folder (deploy/HOSTINGER.md, content/notes.py): a walk of KL_NOTES_DIR, reported to
POST /api/pipeline/notes/sync so `available`/`folder` reflect what's really on disk.

No local caching of hashes — re-hashing every PDF on every sync is cheap at the scale of a
personal notes folder, and simpler than a cache that itself needs invalidating correctly.
"""

import hashlib
from pathlib import Path

import pymupdf


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def scan(notes_dir: Path) -> list[dict]:
    """Every PDF under notes_dir, as a notes-sync report entry each. Empty if the folder
    doesn't exist (a sync with no entries marks every known document unavailable)."""
    if not notes_dir.is_dir():
        return []
    entries = []
    for path in sorted(notes_dir.rglob("*.pdf")):
        stat = path.stat()
        with pymupdf.open(path) as pdf:
            page_count = pdf.page_count
        entries.append({
            "path": str(path), "filename": path.name, "file_hash": _sha256(path),
            "size": stat.st_size, "mtime": stat.st_mtime, "page_count": page_count,
            "folder": str(path.parent.relative_to(notes_dir)),
        })
    return entries
