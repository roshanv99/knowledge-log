"""The learner's notes (uploaded PDFs, content/uploads.py) and their study scope.

Every PDF has a Document and a NoteScope. A question or reel is in scope when its PDF is
selected, its type is ticked, and every page it comes from lies inside the chosen range.
"""

from dataclasses import dataclass

from django.db.models import QuerySet
from django.utils import timezone

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


def list_notes() -> list[Note]:
    """Every known PDF: stored ones first, in pipeline order, then removed ones by filename."""
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
    first. The pipeline works through this list from the bottom up, oldest first."""
    return scope.priority, -document.created_at.timestamp(), -document.pk


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
