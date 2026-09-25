"""The run lifecycle behind /api/pipeline/*: start, claim, heartbeat, notes, complete, fail, finish.

Every call from a runner proves it still holds its claim. A claim is lost when the lease
expired and another run re-claimed the task; the late runner then gets LeaseLost (HTTP 409)
and must drop that task.
"""

import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from config.storage import get_storage
from content.models import Chunk, Document, GenerationRun, GenerationTask, Kind, Question, Reel
from pipeline import planner
from pipeline.models import Runner, RunRequest
from quiz.models import Settings

Status = GenerationTask.Status
FINISHED = (Status.DONE, Status.SKIPPED)


class PipelineError(Exception):
    status = 400


class Disabled(PipelineError):
    status = 403


class Conflict(PipelineError):
    status = 409


class LeaseLost(Conflict):
    pass


class RunFinished(Conflict):
    pass


def close_abandoned_runs() -> None:
    """Runs silent for longer than a lease died without finishing; close them and free their tasks."""
    cutoff = timezone.now() - planner.lease()
    for run in GenerationRun.objects.filter(finished_at__isnull=True, last_seen_at__lt=cutoff):
        _close(run, "abandoned", None)


def _close(run: GenerationRun, stop_reason: str, usage: dict | None) -> None:
    # A finished run holds no claims: hand its unfinished tasks straight back instead of waiting for leases.
    run.tasks.filter(status=Status.CLAIMED).update(status=Status.PENDING, lease_expires_at=None, stage=None,
                                                   detail=None)
    run.finished_at, run.stop_reason = timezone.now(), stop_reason
    if usage is not None:
        run.usage = usage
    run.save()


def runs_today(kind: str) -> int:
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    idle = (planner.Reason.NOTHING_SELECTED, planner.Reason.RANGE_DONE, planner.Reason.ALL_FAILED, "disabled",
            "reel_limit")
    # Runs that found nothing to do don't count against the daily cap.
    return (GenerationRun.objects.filter(kind=kind, started_at__gte=start)
            .exclude(tasks_done=0, stop_reason__in=idle).count())


def reel_limit_reached(prefs: Settings) -> bool:
    """Made reels plus reels being made have reached Settings.reel_limit (0 means no limit)."""
    if not prefs.reel_limit:
        return False
    in_progress = GenerationTask.objects.filter(kind=Kind.REEL, status=Status.CLAIMED,
                                                lease_expires_at__gte=timezone.now()).count()
    return Reel.objects.count() + in_progress >= prefs.reel_limit


def open_request(kind: str) -> RunRequest | None:
    return (RunRequest.objects.filter(kind=kind, consumed_by_run__isnull=True, expires_at__gt=timezone.now())
            .order_by("created_at").first())


def start_run(kind: str, runner: str, params: dict) -> GenerationRun:
    prefs = Settings.load()
    if not prefs.pipeline_enabled:
        raise Disabled("The pipeline is switched off in Settings.")
    close_abandoned_runs()
    if runs_today(kind) >= prefs.max_runs_per_day:
        raise Disabled(f"Already ran {prefs.max_runs_per_day} {kind} runs today (the daily cap in Settings).")
    try:
        with transaction.atomic():
            run = GenerationRun.objects.create(kind=kind, runner=runner, params=params)
            if request := open_request(kind):
                request.consumed_by_run = run
                request.save(update_fields=["consumed_by_run"])
    except IntegrityError:
        active = GenerationRun.objects.filter(kind=kind, finished_at__isnull=True).first()
        raise Conflict(f"A {kind} run is already active (run {active.pk if active else '?'}, "
                       f"{active.runner if active else ''}).") from None
    return run


def _live_run(run: GenerationRun) -> GenerationRun:
    if run.finished_at is not None:
        raise RunFinished(f"Run {run.pk} has finished ({run.stop_reason}).")
    GenerationRun.objects.filter(pk=run.pk).update(last_seen_at=timezone.now())
    return run


def claim(run: GenerationRun, document_id: int | None = None) -> GenerationTask | str:
    _live_run(run)
    prefs = Settings.load()
    if not prefs.pipeline_enabled:  # the kill switch also stops a run that is already going
        return "disabled"
    if run.tasks_done + run.tasks.filter(status=Status.CLAIMED).count() >= prefs.max_tasks_per_run:
        return "run_cap"
    if run.kind == Kind.REEL and reel_limit_reached(prefs):
        return "reel_limit"
    return planner.claim(run.kind, run, document_id)


def _held(task_id: int, run: GenerationRun) -> GenerationTask:
    """The task, locked, if `run` still holds its claim."""
    task = GenerationTask.objects.select_for_update().select_related("chunk__document").get(pk=task_id)
    if task.run_id != run.pk or task.status != Status.CLAIMED:
        raise LeaseLost(f"Task {task.pk} is no longer claimed by run {run.pk}.")
    return task


def heartbeat(run: GenerationRun, task_id: int, stage: str, detail: str | None) -> GenerationTask:
    _live_run(run)
    with transaction.atomic():
        task = _held(task_id, run)
        task.stage, task.detail = stage, detail
        task.lease_expires_at = timezone.now() + planner.lease()
        task.save(update_fields=["stage", "detail", "lease_expires_at", "updated_at"])
    return task


def save_notes(run: GenerationRun, task_id: int, notes: dict) -> Chunk:
    """Store what was read from the task's pages. `testable: false` marks the pages unreadable."""
    _live_run(run)
    with transaction.atomic():
        task = _held(task_id, run)
        chunk = task.chunk
        chunk.title = notes.get("title")
        chunk.notes = notes
        chunk.status = Chunk.Status.READ if notes.get("testable", True) else Chunk.Status.UNREADABLE
        chunk.updated_at = timezone.now()
        chunk.save()
        task.lease_expires_at = timezone.now() + planner.lease()
        task.save(update_fields=["lease_expires_at", "updated_at"])
    return chunk


MEDIA_TYPES = {"video": (".mp4", lambda head: head[4:8] == b"ftyp", "That isn't an MP4 file."),
               "poster": (".png", lambda head: head[:8] == b"\x89PNG\r\n\x1a\n", "That isn't a PNG file.")}


def media_key(task: GenerationTask, kind: str = "video") -> str:
    return f"reels/task-{task.pk}{MEDIA_TYPES[kind][0]}"


def save_media(run: GenerationRun, task_id: int, stream, length: int, kind: str = "video") -> str:
    """Store a reel's MP4 (or its poster PNG) for a claimed reel task; returns its storage key."""
    if kind not in MEDIA_TYPES:
        raise PipelineError(f"Unknown media kind {kind!r}.")
    _live_run(run)
    with transaction.atomic():
        task = _held(task_id, run)
        if task.kind != Kind.REEL:
            raise PipelineError("Only reel tasks take media.")
    if not 0 < length <= settings.KL_MAX_MEDIA_BYTES:
        raise PipelineError(f"The video must be between 1 byte and {settings.KL_MAX_MEDIA_BYTES // (1024 * 1024)} MB.")
    key = media_key(task, kind)
    # Staged locally first (for the magic-byte check) regardless of backend, then handed to
    # storage.save() — a same-filesystem rename for LocalDiskStorage, a streamed upload_file
    # for R2Storage. Neither reads the whole video into memory.
    stage_dir = Path(settings.MEDIA_ROOT) / "tmp"
    stage_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=stage_dir, suffix=".part")
    received = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := stream.read(min(1 << 20, length - received)):
                received += len(chunk)
                out.write(chunk)
                if received >= length:
                    break
        with open(tmp, "rb") as f:
            head = f.read(12)
        if received != length:
            raise PipelineError(f"Upload was cut short ({received} of {length} bytes).")
        _, looks_right, wrong = MEDIA_TYPES[kind]
        if not looks_right(head):
            raise PipelineError(wrong)
        get_storage().save(tmp, key)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return key


def complete(run: GenerationRun, task_id: int, questions: list[dict], review_log: list,
             skipped_reason: str | None = None, reel: dict | None = None) -> tuple[GenerationTask, int]:
    """Save the task's output (questions, or one reel). Repeating a completion that already landed is a no-op.

    Returns the task and how many items were created."""
    with transaction.atomic():
        task = GenerationTask.objects.select_for_update().select_related("chunk__document").get(pk=task_id)
        if task.status in FINISHED and task.run_id == run.pk:
            return task, 0  # a retried request after a lost response
        _live_run(run)
        task = _held(task_id, run)
        created = 0
        if task.kind == Kind.REEL:
            if questions:
                raise PipelineError("A reel task completes with a reel, not questions.")
            if reel is not None:
                key = media_key(task)
                if reel["storage_key"] != key or not get_storage().exists(key):
                    raise PipelineError(f"Upload the video first (expected {key}).")
                _, created = Reel.objects.update_or_create(task=task, defaults={
                    "chunk": task.chunk, "kind": task.reel_style or "manim", "title": reel["title"],
                    "key_point": reel.get("key_point"), "storage_key": key, "duration_s": reel.get("duration_s"),
                    "source_pages": task.chunk.pages})
                created = int(created)
            empty = reel is None
        else:
            if reel is not None:
                raise PipelineError("A quiz task completes with questions, not a reel.")
            for q in questions:
                _, was_created = Question.objects.get_or_create(chunk=task.chunk, stem=q["stem"], defaults={
                    "task": task, "run": run, "options": q["options"], "correct_index": q["correct_index"],
                    "explanation": q["explanation"], "source_pages": q["source_pages"],
                    "difficulty": q["difficulty"]})
                created += was_created
            empty = not questions or skipped_reason or task.chunk.status == Chunk.Status.UNREADABLE
        task.status = Status.SKIPPED if empty and not created else Status.DONE
        task.review_log = review_log
        task.error = skipped_reason if task.status == Status.SKIPPED else None
        task.lease_expires_at, task.stage, task.detail = None, None, None
        task.finished_at = timezone.now()
        task.save()
        made = {"reels_made": F("reels_made") + created} if task.kind == Kind.REEL else {
            "questions_made": F("questions_made") + created}
        GenerationRun.objects.filter(pk=run.pk).update(tasks_done=F("tasks_done") + 1, **made)
        if task.kind == Kind.QUIZ:
            advance_document(task.chunk.document)
    return task, created


def fail(run: GenerationRun, task_id: int, error: str, retryable: bool) -> GenerationTask:
    _live_run(run)
    with transaction.atomic():
        task = _held(task_id, run)
        task.attempts += 1
        again = retryable and task.attempts < settings.KL_MAX_TASK_ATTEMPTS
        task.status = Status.PENDING if again else Status.FAILED
        task.error = error
        task.lease_expires_at, task.stage, task.detail = None, None, None
        task.finished_at = None if again else timezone.now()
        task.save()
    return task


def retry(task: GenerationTask) -> GenerationTask:
    """From Manage notes: give a failed task a fresh set of attempts."""
    if task.status not in (Status.FAILED, Status.SKIPPED):
        raise Conflict(f"Only failed or skipped tasks can be retried (this one is {task.status}).")
    task.status, task.attempts, task.error, task.finished_at = Status.PENDING, 0, None, None
    task.save()
    return task


def finish(run: GenerationRun, stop_reason: str, usage: dict | None) -> GenerationRun:
    if run.finished_at is None:
        _close(run, stop_reason, usage)
    return run


def wanted(kind: str, runner: Runner) -> dict | None:
    """What the runner's poll should start, if anything. Nothing costs Claude usage until this
    says so. `runner` decides which auto-run switch applies: a scheduled cloud routine and the
    local Mac runner are gated independently (Settings.pipeline_auto_cloud vs pipeline_auto),
    so turning one on doesn't silently start the other."""
    prefs = Settings.load()
    if not prefs.pipeline_enabled:
        return None
    close_abandoned_runs()
    if GenerationRun.objects.filter(kind=kind, finished_at__isnull=True).exists():
        return None
    if runs_today(kind) >= prefs.max_runs_per_day:
        return None
    request = open_request(kind)
    if kind == Kind.REEL and reel_limit_reached(prefs):
        if request:  # nothing will run: close the request rather than leave it pending
            request.expires_at = timezone.now()
            request.save(update_fields=["expires_at"])
        return None
    auto = prefs.pipeline_auto_cloud if runner.kind == Runner.RunnerKind.CLOUD_ROUTINE else prefs.pipeline_auto
    if request is None and not auto:
        return None
    plan = planner.next_plan(kind)
    if isinstance(plan, str):
        if request:  # nothing to do: close the request rather than leave it pending
            request.expires_at = timezone.now()
            request.save(update_fields=["expires_at"])
        return None
    return {"kind": kind, "reason": "run_request" if request else "schedule",
            "request_id": request.pk if request else None,
            "document": plan.document.filename, "folder": plan.document.folder,
            "pages": list(plan.page_range)}


def request_run(kind: str, requested_by: str = "app") -> RunRequest:
    """ "Run now". At most one open request per kind: asking again returns the pending one."""
    return open_request(kind) or RunRequest.objects.create(kind=kind, requested_by=requested_by)


def advance_document(document: Document) -> None:
    """Move last_processed_page to the end of the contiguous run of handled pages from page 1."""
    handled = sorted({(c.page_start, c.page_end) for c in document.chunks.all()
                      if c.status == Chunk.Status.UNREADABLE
                      or c.tasks.filter(kind=Kind.QUIZ, status__in=FINISHED).exists()})
    last = 0
    for start, end in handled:
        if start > last + 1:
            break
        last = max(last, end)
    if document.last_processed_page != last:
        document.last_processed_page = last
        document.save(update_fields=["last_processed_page"])
