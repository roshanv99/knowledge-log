"""What a pipeline run should work on next. The only place that decides it.

Runners never choose their own work: they ask `claim(kind, run)` and get one task, or a
reason there is nothing to do. The order is:

1. Pending tasks (new, handed back, or failed with retries left) and claims whose lease expired.
   A `failed` task is final until the learner presses Retry in Manage notes.
2. Chunks already read for another kind that have no task of this kind yet.
3. The next unread page window of a PDF, as a new chunk.

Within each step PDFs go from the bottom of Manage notes up (the list shows newest first, so the
pipeline starts with the oldest; dragging changes that), pages ascending. Only
work inside the learner's scope is offered: the PDF is selected, the kind is ticked, and the
chunk lies inside the page range (content/notes.py).
"""

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.utils import timezone

from content.models import Chunk, Document, GenerationRun, GenerationTask, Kind, NoteScope
from content.notes import list_order, scope_for

Status = GenerationTask.Status


# Until a router picks a style per chunk (PLAN.md 2a/2b/2c), every reel is a manim explainer.
DEFAULT_REEL_STYLE = "manim"
CREATE_LOCK = 7_210_001  # pg advisory lock namespace for chunk and task creation


class Reason:
    NOTHING_SELECTED = "nothing_selected"  # no PDF is selected with this kind ticked
    RANGE_DONE = "range_done"  # every page in every selected range has been handled
    ALL_FAILED = "all_failed"  # what's left has failed; retry it from Manage notes


@dataclass
class Plan:
    """The next unit of work, before it is claimed: an existing task, a chunk, or a new window."""

    document: Document
    task: GenerationTask | None = None
    chunk: Chunk | None = None
    pages: tuple[int, int] | None = None

    @property
    def page_range(self) -> tuple[int, int]:
        if self.pages:
            return self.pages
        chunk = self.task.chunk if self.task else self.chunk
        return chunk.page_start, chunk.page_end


def lease() -> timedelta:
    return timedelta(seconds=settings.KL_LEASE_SECONDS)


def uncovered_windows(chunks, first: int, last: int, size: int) -> list[tuple[int, int]]:
    """Page windows of up to `size` pages over pages in first..last that no chunk covers yet."""
    covered = {p for c in chunks for p in range(c.page_start, c.page_end + 1)}
    windows, start = [], None
    for page in range(first, last + 2):
        free = page <= last and page not in covered
        if free and start is None:
            start = page
        if start is not None and (not free or page - start + 1 > size):
            windows.append((start, page - 1))
            start = page if free else None
    return windows


def _includes(scope: NoteScope, kind: str) -> bool:
    return scope.selected and (scope.include_quiz if kind == Kind.QUIZ else scope.include_reels)


def _in_range(scope: NoteScope, chunk: Chunk) -> bool:
    return scope.page_from <= chunk.page_start and chunk.page_end <= scope.last_page


def eligible_documents(kind: str, document_id: int | None = None) -> list[tuple[Document, NoteScope]]:
    """Stored PDFs whose scope asks for this kind, in pipeline order: Manage notes from the bottom
    up. A removed PDF is skipped entirely, including tasks already queued for it."""
    documents = Document.objects.filter(available=True).select_related("scope")
    if document_id is not None:
        documents = documents.filter(pk=document_id)
    pairs = [(d, scope_for(d)) for d in documents]
    pairs = [(d, s) for d, s in pairs if _includes(s, kind)]
    return sorted(pairs, key=lambda p: list_order(*p), reverse=True)


def _waiting() -> Q:
    return Q(status=Status.PENDING) | Q(status=Status.CLAIMED, lease_expires_at__lt=timezone.now())


def next_plan(kind: str, document_id: int | None = None, *, lock: bool = False) -> Plan | str:
    """The next unit of work for `kind`, or a Reason. With `lock`, step 1 rows are locked for update."""
    documents = eligible_documents(kind, document_id)
    if not documents:
        return Reason.NOTHING_SELECTED
    order = {d.pk: i for i, (d, _) in enumerate(documents)}
    scopes = {d.pk: s for d, s in documents}

    # 1. Tasks waiting for a (re)run.
    tasks = GenerationTask.objects.filter(_waiting(), kind=kind, chunk__document_id__in=order)
    if lock:
        tasks = tasks.select_for_update(skip_locked=True, of=("self",))
    tasks = [t for t in tasks.select_related("chunk__document")
             if _in_range(scopes[t.chunk.document_id], t.chunk)]
    if tasks:
        task = min(tasks, key=lambda t: (order[t.chunk.document_id], t.chunk.page_start))
        return Plan(task.chunk.document, task=task)

    # 2. Chunks made for another kind, with no task of this kind yet. An unread one that another
    #    kind is reading right now waits for its notes, so two sessions never read the same pages.
    being_read = GenerationTask.objects.filter(status=Status.CLAIMED, lease_expires_at__gte=timezone.now(),
                                               chunk__status=Chunk.Status.UNREAD).values("chunk_id")
    chunks = (Chunk.objects.filter(document_id__in=order).exclude(status=Chunk.Status.UNREADABLE)
              .exclude(tasks__kind=kind).exclude(pk__in=being_read).select_related("document"))
    chunks = [c for c in chunks if _in_range(scopes[c.document_id], c)]
    if chunks:
        chunk = min(chunks, key=lambda c: (order[c.document_id], c.page_start))
        return Plan(chunk.document, chunk=chunk)

    # 3. The next page window no chunk covers yet.
    for document, scope in documents:
        windows = uncovered_windows(document.chunks.all(), scope.page_from, scope.last_page,
                                    settings.KL_CHUNK_PAGES)
        if windows:
            return Plan(document, pages=windows[0])

    failed = GenerationTask.objects.filter(kind=kind, status=Status.FAILED, chunk__document_id__in=order)
    if any(_in_range(scopes[t.chunk.document_id], t.chunk) for t in failed.select_related("chunk")):
        return Reason.ALL_FAILED
    return Reason.RANGE_DONE


def _serialize_creation(kind: str) -> None:
    """Held until the transaction ends, so only one runner at a time creates chunks and tasks."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [CREATE_LOCK, kind])


def claim(kind: str, run: GenerationRun, document_id: int | None = None) -> GenerationTask | str:
    """Claim the next task for `run`, creating the chunk and task if needed. Returns a Reason if none."""
    for _ in range(5):  # a unique-constraint race should be impossible under the lock; retry to be safe
        try:
            with transaction.atomic():
                plan = next_plan(kind, document_id, lock=True)
                if not isinstance(plan, str) and plan.task is None:
                    # Everyone racing for new work would plan the same window: queue up, then plan again,
                    # now seeing what the runners ahead of us created.
                    _serialize_creation(kind)
                    plan = next_plan(kind, document_id, lock=True)
                if isinstance(plan, str):
                    return plan
                task = plan.task
                if task is None:
                    chunk = plan.chunk or Chunk.objects.create(
                        document=plan.document, page_start=plan.pages[0], page_end=plan.pages[1])
                    task = GenerationTask.objects.create(
                        chunk=chunk, kind=kind, reel_style=DEFAULT_REEL_STYLE if kind == Kind.REEL else None)
                now = timezone.now()
                task.status, task.run = Status.CLAIMED, run
                task.lease_expires_at, task.started_at = now + lease(), now
                task.stage, task.detail, task.finished_at = None, None, None
                task.save()
                return task
        except IntegrityError:
            continue
    raise RuntimeError("could not claim a task: repeated conflicts with other runners")
