"""The notes folder and the learner's study scope over it.

Every PDF under KL_NOTES_DIR gets a Document (created here if the pipeline hasn't seen it
yet) and a NoteScope. A question or reel is in scope when its PDF is selected, its type is
ticked, and every page it comes from lies inside the chosen range.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pypdf
from django.conf import settings
from django.db.models import QuerySet
from django.utils import timezone

from content.models import Chunk, Document, GenerationTask, Kind, NoteScope, Question, Reel


@dataclass
class Note:
    document: Document
    scope: NoteScope
    available: bool
    folder: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def scope_for(document: Document) -> NoteScope:
    """The document's scope, or the default (everything on) if none is saved yet."""
    try:
        return document.scope
    except NoteScope.DoesNotExist:
        return NoteScope(document=document)


def sync_notes_folder() -> list[Note]:
    """Register every PDF in the notes folder; list them, then known PDFs no longer on disk."""
    root = Path(settings.KL_NOTES_DIR).expanduser()
    notes, seen = [], set()
    for path in sorted(root.rglob("*.pdf")) if root.is_dir() else []:
        stat = path.stat()
        scope = (NoteScope.objects.select_related("document")
                 .filter(document__path=str(path), file_size=stat.st_size, file_mtime=stat.st_mtime).first())
        if scope is None:  # new or changed file: identify it by content
            file_hash = _sha256(path)
            document = Document.objects.filter(file_hash=file_hash).first()
            if document is None:
                document = Document.objects.create(file_hash=file_hash, path=str(path), filename=path.name,
                                                   page_count=len(pypdf.PdfReader(path).pages))
            elif document.path != str(path) or document.filename != path.name:
                document.path, document.filename = str(path), path.name
                document.save(update_fields=["path", "filename"])
            # A new PDF goes to the top of Manage notes, which is the end of the pipeline's queue.
            first = NoteScope.objects.order_by("priority").values_list("priority", flat=True).first()
            scope, _ = NoteScope.objects.get_or_create(
                document=document, defaults={"priority": 0 if first is None else first - 1})
            scope.file_size, scope.file_mtime = stat.st_size, stat.st_mtime
            scope.save(update_fields=["file_size", "file_mtime", "updated_at"])
        seen.add(scope.document_id)
        notes.append(Note(scope.document, scope, True, str(path.parent.relative_to(root))))

    notes.sort(key=lambda n: list_order(n.document, n.scope))
    for document in Document.objects.exclude(pk__in=seen).order_by("filename"):
        notes.append(Note(document, scope_for(document), False, ""))
    return notes


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
