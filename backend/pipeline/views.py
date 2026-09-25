"""/api/pipeline/*: runners claim and report work here; Manage notes reads progress and asks for runs.

Runner endpoints need a runner token (pipeline/auth.py) and act only on the runner's own runs.
The app endpoints (status, requests, retry) follow the rest of the app: open while local,
behind the app login once hosted.
"""

from functools import wraps

from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.request import Request
from rest_framework.response import Response

from content.models import GenerationRun, GenerationTask, Reel
from pipeline import serializers as s
from pipeline import services
from pipeline.auth import IsRunner, RunnerTokenAuthentication
from pipeline.models import Runner, RunRequest
from quiz.models import Settings


def runner_endpoint(methods):
    """A view for runners: token auth, pipeline errors mapped to their HTTP status."""
    def decorate(view):
        @api_view(methods)
        @authentication_classes([RunnerTokenAuthentication])
        @permission_classes([IsRunner])
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            try:
                return view(request, *args, **kwargs)
            except services.PipelineError as e:
                return Response({"detail": str(e)}, status=e.status)
            except ObjectDoesNotExist:
                return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return wrapped
    return decorate


def _valid(serializer_class, request: Request, **context) -> dict:
    serializer = serializer_class(data=request.data, context=context)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _own_run(request: Request, run_id: int) -> GenerationRun:
    """The run, if it belongs to the calling runner (404 otherwise, so ids don't leak)."""
    return get_object_or_404(GenerationRun, pk=run_id, runner=request.user.name)


def _task(task_id: int) -> GenerationTask:
    """Whether the caller's run still holds the claim is checked by services (409 when lost)."""
    return get_object_or_404(GenerationTask.objects.select_related("chunk__document"), pk=task_id)


def task_payload(task: GenerationTask) -> dict:
    chunk, document = task.chunk, task.chunk.document
    return {
        "id": task.pk, "kind": task.kind, "reel_style": task.reel_style, "attempt": task.attempts + 1,
        "lease_expires_at": task.lease_expires_at,
        "chunk": {"id": chunk.pk, "page_start": chunk.page_start, "page_end": chunk.page_end,
                  "status": chunk.status, "title": chunk.title, "notes": chunk.notes},
        "document": {"id": document.pk, "filename": document.filename, "path": document.path,
                     "page_count": document.page_count},
    }


# Runner endpoints.

@runner_endpoint(["GET"])
def wanted(request: Request) -> Response:
    kind = request.query_params.get("kind", "quiz")
    want = services.wanted(kind)
    return Response(want) if want else Response(status=status.HTTP_204_NO_CONTENT)


@runner_endpoint(["POST"])
def start_run(request: Request) -> Response:
    data = _valid(s.StartRunInput, request)
    run = services.start_run(data["kind"], request.user.name, data["params"])
    return Response({"run_id": run.pk, "kind": run.kind}, status=status.HTTP_201_CREATED)


@runner_endpoint(["POST"])
def claim(request: Request, run_id: int) -> Response:
    run = _own_run(request, run_id)
    data = _valid(s.ClaimInput, request)
    result = services.claim(run, data.get("document_id"))
    if isinstance(result, str):
        return Response({"task": None, "reason": result})
    return Response({"task": task_payload(result), "reason": None})


@runner_endpoint(["POST"])
def heartbeat(request: Request, task_id: int) -> Response:
    data = _valid(s.HeartbeatInput, request)
    run = _own_run(request, data["run_id"])
    task = services.heartbeat(run, task_id, data["stage"], data.get("detail"))
    return Response({"lease_expires_at": task.lease_expires_at})


@runner_endpoint(["PUT"])
def notes(request: Request, task_id: int) -> Response:
    data = _valid(s.NotesInput, request)
    run = _own_run(request, data.pop("run_id"))
    chunk = services.save_notes(run, task_id, data)
    return Response({"chunk_status": chunk.status})


@runner_endpoint(["POST"])
def complete(request: Request, task_id: int) -> Response:
    run = _own_run(request, _valid(s.RunCallInput, request)["run_id"])
    task = _task(task_id)
    data = _valid(s.CompleteInput, request, pages=set(task.chunk.pages))
    task, created = services.complete(run, task.pk, data["questions"], data["review_log"],
                                      data.get("skipped_reason"), data.get("reel"))
    return Response({"status": task.status,
                     ("reels_created" if task.kind == "reel" else "questions_created"): created})


@runner_endpoint(["PUT"])
def media(request: Request, task_id: int) -> Response:
    """The reel's MP4 (or `?kind=poster` PNG) as the raw request body, with `?run_id=`."""
    try:
        run_id = int(request.query_params.get("run_id", ""))
        length = int(request.headers.get("Content-Length", "0"))
    except ValueError:
        return Response({"detail": "run_id and Content-Length are required."}, status=status.HTTP_400_BAD_REQUEST)
    run = _own_run(request, run_id)
    # Read the underlying stream directly: request.body would buffer it and hit Django's size limit.
    key = services.save_media(run, _task(task_id).pk, request._request, length,
                              request.query_params.get("kind", "video"))
    return Response({"storage_key": key}, status=status.HTTP_201_CREATED)


@runner_endpoint(["POST"])
def fail(request: Request, task_id: int) -> Response:
    data = _valid(s.FailInput, request)
    run = _own_run(request, data["run_id"])
    task = services.fail(run, task_id, data["error"], data["retryable"])
    return Response({"status": task.status, "attempts": task.attempts})


@runner_endpoint(["POST"])
def finish(request: Request, run_id: int) -> Response:
    run = _own_run(request, run_id)
    data = _valid(s.FinishInput, request)
    run = services.finish(run, data["stop_reason"], data["usage"])
    return Response({"run_id": run.pk, "stop_reason": run.stop_reason, "tasks_done": run.tasks_done,
                     "questions_made": run.questions_made, "reels_made": run.reels_made})


# App endpoints (Manage notes).

def _task_row(task: GenerationTask) -> dict:
    return {"id": task.pk, "kind": task.kind, "document_id": task.chunk.document_id,
            "document": task.chunk.document.filename, "pages": [task.chunk.page_start, task.chunk.page_end],
            "status": task.status, "stage": task.stage, "detail": task.detail, "attempts": task.attempts,
            "error": task.error, "since": task.started_at, "finished_at": task.finished_at}


def _run_row(run: GenerationRun) -> dict:
    return {"id": run.pk, "kind": run.kind, "runner": run.runner, "started_at": run.started_at,
            "last_seen_at": run.last_seen_at, "finished_at": run.finished_at, "stop_reason": run.stop_reason,
            "tasks_done": run.tasks_done, "questions_made": run.questions_made, "reels_made": run.reels_made}


@api_view(["GET"])
def pipeline_status(request: Request) -> Response:
    services.close_abandoned_runs()
    tasks = GenerationTask.objects.select_related("chunk__document")
    active_runs = GenerationRun.objects.filter(finished_at__isnull=True).order_by("started_at")
    now = timezone.now()
    return Response({
        "active_runs": [{**_run_row(run), "tasks": [
            _task_row(t) for t in tasks.filter(run=run, status=GenerationTask.Status.CLAIMED)]}
            for run in active_runs],
        "recent_runs": [_run_row(r) for r in GenerationRun.objects.filter(finished_at__isnull=False)
                        .order_by("-finished_at")[:10]],
        "failed_tasks": [_task_row(t) for t in tasks.filter(status=GenerationTask.Status.FAILED)
                         .order_by("chunk__document__path", "chunk__page_start")],
        "open_requests": [{"id": r.pk, "kind": r.kind, "created_at": r.created_at}
                          for r in RunRequest.objects.filter(consumed_by_run__isnull=True, expires_at__gt=now)],
        "runners": [{"name": r.name, "kind": r.kind, "last_seen_at": r.last_seen_at}
                    for r in Runner.objects.filter(enabled=True).order_by("name")],
        "reels": {"made": Reel.objects.count(), "limit": Settings.load().reel_limit},
    })


@api_view(["POST"])
def request_run(request: Request) -> Response:
    data = _valid(s.RequestInput, request)
    if data["kind"] == "reel" and services.reel_limit_reached(Settings.load()):
        return Response({"detail": "The reel limit in Settings is reached. Raise it to make more."},
                        status=status.HTTP_409_CONFLICT)
    run_request = services.request_run(data["kind"])
    return Response({"id": run_request.pk, "kind": run_request.kind, "expires_at": run_request.expires_at},
                    status=status.HTTP_201_CREATED)


@api_view(["POST"])
def retry(request: Request, task_id: int) -> Response:
    task = get_object_or_404(GenerationTask.objects.select_related("chunk__document"), pk=task_id)
    try:
        task = services.retry(task)
    except services.PipelineError as e:
        return Response({"detail": str(e)}, status=e.status)
    return Response(_task_row(task))

