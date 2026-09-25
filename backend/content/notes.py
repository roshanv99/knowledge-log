"""The notes folder and the learner's study scope over it.

Every PDF under KL_NOTES_DIR gets a Document (created here if the pipeline hasn't seen it
yet) and a NoteScope. A question or reel is in scope when its PDF is selected, its type is
ticked, and every page it comes from lies inside the chosen range.

Which PDFs exist is decided by `scan()` + `apply_sync_report()`, run by `manage.py sync_notes`
on a schedule (deploy/notes-sync.sh mirrors the Google Drive folder onto the server first), not
on every request: a deleted or changed PDF shows up in the app after the next sync.
`list_notes()` here just reads what the last sync recorded.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from django.db.models import QuerySet
from django.utils import timezone
from pypdf import PdfReader

from content.models import Chunk, Document, GenerationTask, Kind, NoteScope, Question, Reel


@dataclass
class Note:
    document: Document
    scope: NoteScope
    available: bool
    folder: str


def scope_for(document: Document) -> NoteScope:
    """The document's scope, or the default (everything on) if none is saved yet."""
    try:
        return document.scope
    except NoteScope.DoesNotExist:
        return NoteScope(document=document)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def scan(notes_dir: Path) -> list[dict]:
    """Every PDF under notes_dir, as an `apply_sync_report()` entry each."""
    entries = []
    for path in sorted(notes_dir.rglob("*.pdf")):
        stat = path.stat()
        folder = path.parent.relative_to(notes_dir)
        entries.append({
            "path": str(path), "filename": path.name, "file_hash": _sha256(path),
            "size": stat.st_size, "mtime": stat.st_mtime, "page_count": len(PdfReader(path).pages),
            "folder": "" if folder == Path(".") else str(folder),
        })
    return entries


def apply_sync_report(entries: list[dict]) -> dict:
    """Register/update every PDF in `entries` (see `scan()`), then mark anything not in it as no
    longer available. `entries`: [{path, filename, file_hash, size, mtime, page_count, folder}].

    Same identification rule as before: a PDF's identity is its content hash, not its path, so
    a renamed/moved file is recognised as the same document rather than duplicated."""
    seen = set()
    registered = 0
    for entry in entries:
        scope = (NoteScope.objects.select_related("document")
                 .filter(document__path=entry["path"], file_size=entry["size"], file_mtime=entry["mtime"]).first())
        if scope is None:  # new or changed file: identify it by content
            document = Document.objects.filter(file_hash=entry["file_hash"]).first()
            if document is None:
                document = Document.objects.create(file_hash=entry["file_hash"], path=entry["path"],
                                                   filename=entry["filename"], page_count=entry["page_count"])
                registered += 1
            elif document.path != entry["path"] or document.filename != entry["filename"]:
                document.path, document.filename = entry["path"], entry["filename"]
                document.save(update_fields=["path", "filename"])
            # A new PDF goes to the top of Manage notes, which is the end of the pipeline's queue.
            first = NoteScope.objects.order_by("priority").values_list("priority", flat=True).first()
            scope, _ = NoteScope.objects.get_or_create(
                document=document, defaults={"priority": 0 if first is None else first - 1})
            scope.file_size, scope.file_mtime = entry["size"], entry["mtime"]
            scope.save(update_fields=["file_size", "file_mtime", "updated_at"])
        document = scope.document
        if not document.available or document.folder != entry["folder"]:
            document.available, document.folder = True, entry["folder"]
            document.save(update_fields=["available", "folder"])
        seen.add(document.pk)

    unavailable = Document.objects.exclude(pk__in=seen).filter(available=True)
    went_unavailable = unavailable.count()
    unavailable.update(available=False)
    return {"registered": registered, "available": len(seen), "went_unavailable": went_unavailable}


def list_notes() -> list[Note]:
    """Every known PDF, in pipeline order, from the last sync report — not a live scan.
    Available PDFs first (pipeline order), then ones no longer reported, by filename."""
    documents = list(Document.objects.select_related("scope"))
    notes = [Note(d, scope_for(d), d.available, d.folder) for d in documents]
    available = sorted((n for n in notes if n.available), key=lambda n: list_order(n.document, n.scope))
    gone = sorted((n for n in notes if not n.available), key=lambda n: n.document.filename)
    return available + gone


def _ranges(pages: set[int]) -> list[list[int]]:
    """{1,2,3,7,8} -> [[1,3],[7,8]]"""
    ranges: list[list[int]] = []
    for page in sorted(pages):
        if ranges and page == ranges[-1][1] + 1:
            ranges[-1][1] = page
        else:
            ranges.append([page, page])
    return ranges


def progress(document: Document, scope: NoteScope) -> dict[str, dict]:
    """Per content kind: which pages are handled, what failed, and what is being worked on now."""
    chunks = list(document.chunks.prefetch_related("tasks"))
    now = timezone.now()
    in_range = set(range(scope.page_from, scope.last_page + 1))
    out = {}
    for kind in Kind.values:
        done, failed, active = set(), [], None
        for chunk in chunks:
            task = next((t for t in chunk.tasks.all() if t.kind == kind), None)
            if chunk.status == Chunk.Status.UNREADABLE or (
                    task and task.status in (GenerationTask.Status.DONE, GenerationTask.Status.SKIPPED)):
                done.update(chunk.pages)
            elif task and task.status == GenerationTask.Status.FAILED:
                failed.append({"task_id": task.pk, "pages": [chunk.page_start, chunk.page_end], "error": task.error})
            elif task and task.status == GenerationTask.Status.CLAIMED and task.lease_expires_at > now:
                active = {"task_id": task.pk, "pages": [chunk.page_start, chunk.page_end], "stage": task.stage,
                          "detail": task.detail, "since": task.started_at}
        out[kind] = {"pages_in_range": len(in_range), "pages_done": len(done & in_range),
                     "done_ranges": _ranges(done), "failed": failed, "active": active}
    return out


def list_order(document: Document, scope: NoteScope) -> tuple:
    """Where a PDF sits in Manage notes, top first: its priority (drag to reorder), then newest
    first, then path. The pipeline works through this list from the bottom up, oldest first."""
    return scope.priority, -document.created_at.timestamp(), document.path


def _scopes(document_ids) -> dict[int, NoteScope]:
    documents = Document.objects.filter(pk__in=set(document_ids)).select_related("scope")
    return {d.pk: scope_for(d) for d in documents}


def questions_in_scope(questions: QuerySet[Question]) -> list[Question]:
    questions = list(questions.select_related("chunk"))
    scopes = _scopes(q.chunk.document_id for q in questions)
    return [q for q in questions
            if (s := scopes[q.chunk.document_id]).selected and s.include_quiz and s.covers(q.source_pages)]


def reels_in_scope(reels: QuerySet[Reel]) -> list[Reel]:
    reels = list(reels.select_related("chunk"))
    scopes = _scopes(r.chunk.document_id for r in reels)
    return [r for r in reels
            if (s := scopes[r.chunk.document_id]).selected and s.include_reels and s.covers(r.source_pages)]
