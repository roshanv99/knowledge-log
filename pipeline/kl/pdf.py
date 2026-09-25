"""PDF helpers: hashing, page counts, and rendering pages to images for Claude to read.

The notes are mostly screenshots (tables, diagrams, terminal output), so the text layer is
only a hint; the page image is the source of truth.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf


@dataclass(frozen=True)
class Page:
    number: int
    text: str
    image_path: Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def page_count(path: Path) -> int:
    with pymupdf.open(path) as doc:
        return doc.page_count


def render_pages(pdf_path: Path, start: int, end: int, out_dir: Path, dpi: int) -> list[Page]:
    """Render pages start..end (1-based, inclusive) to JPEGs in out_dir, reusing existing files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    with pymupdf.open(pdf_path) as doc:
        for number in range(start, end + 1):
            page = doc[number - 1]
            image_path = out_dir / f"p{number:03d}.jpg"
            if not image_path.exists():
                page.get_pixmap(dpi=dpi).save(image_path, jpg_quality=85)
            pages.append(Page(number, page.get_text().strip(), image_path))
    return pages
