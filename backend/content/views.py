import mimetypes
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, StreamingHttpResponse
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from config.storage import get_storage
from content.models import Document, NoteScope, Question, Reel, ReelView
from content.notes import Note, progress, questions_in_scope, reels_in_scope, scope_for, sync_notes_folder
from quiz import activity
from quiz.services import rebuild_todays_set

QUIZ_FIELDS = {"selected", "page_from", "page_to", "include_quiz"}


def _note_data(note: Note) -> dict:
    document, scope = note.document, note.scope
    questions = Question.objects.filter(chunk__document=document)
    reels = Reel.objects.filter(chunk__document=document)
    return {
        "id": document.pk,
        "filename": document.filename,
        "folder": note.folder,
        "available": note.available,
        "page_count": document.page_count,
        "processed_to": document.last_processed_page,
        "scope": {
            "selected": scope.selected,
            "page_from": scope.page_from,
            "page_to": scope.last_page,
            "include_quiz": scope.include_quiz,
            "include_reels": scope.include_reels,
            "priority": scope.priority,
        },
        "progress": progress(document, scope),
        "questions": {"total": questions.count(), "in_scope": len(questions_in_scope(questions))},
        "reels": {"total": reels.count(), "in_scope": len(reels_in_scope(reels))},
    }


class ListInput(serializers.Serializer):
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=20)
    q = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")
    folder = serializers.CharField(required=False, allow_blank=True, max_length=500, default="")
    selected = serializers.ChoiceField(choices=["all", "yes", "no"], required=False, default="all")


def _notes_list(params: dict | None = None) -> dict:
    """Manage notes, in pipeline order. With `page`, only that page is returned (and only its
    progress is computed), filtered by name, folder and selection; without it, every PDF."""
    params = params or {}
    everything = sync_notes_folder()
    available = [n for n in everything if n.available]
    ready = questions_in_scope(Question.objects.filter(chunk__document__in=[n.document for n in available]))
    summary = {"documents": len(everything), "selected": sum(n.scope.selected for n in available),
               "questions_ready": len(ready)}

    shown = everything
    if q := params.get("q", "").strip().lower():
        shown = [n for n in shown if q in n.document.filename.lower()]
    if folder := params.get("folder"):
        shown = [n for n in shown if n.available and n.folder == folder]
    if (selected := params.get("selected", "all")) != "all":
        shown = [n for n in shown if n.available and n.scope.selected == (selected == "yes")]

    page, size = params.get("page"), params.get("page_size", 20)
    if page is not None:
        pages = max(1, -(-len(shown) // size))
        page = min(page, pages)
        items = shown[(page - 1) * size:page * size]
    else:
        items = shown
    # Where each PDF sits in the pipeline order (only PDFs on disk take part), for reordering.
    position = {n.document.pk: i for i, n in enumerate(available)}
    return {
        "notes_dir": str(settings.KL_NOTES_DIR).replace(str(Path.home()), "~", 1),
        "notes": [{**_note_data(n), "position": position.get(n.document.pk)} for n in items],
        "total": len(shown),
        "page": page or 1,
        "page_size": size if page is not None else len(shown),
        "folders": sorted({n.folder for n in available}),
        "summary": summary,
    }


@api_view(["GET"])
def notes(request: Request) -> Response:
    params = ListInput(data=request.query_params)
    params.is_valid(raise_exception=True)
    return Response(_notes_list(params.validated_data))


class ScopeInput(serializers.Serializer):
    selected = serializers.BooleanField(required=False)
    page_from = serializers.IntegerField(required=False, min_value=1)
    page_to = serializers.IntegerField(required=False, min_value=1)
    include_quiz = serializers.BooleanField(required=False)
    include_reels = serializers.BooleanField(required=False)


@api_view(["PATCH"])
def update_scope(request: Request, document_id: int) -> Response:
    document = get_object_or_404(Document, pk=document_id)
    payload = ScopeInput(data=request.data)
    payload.is_valid(raise_exception=True)
    changes = payload.validated_data

    with transaction.atomic():
        scope = scope_for(document)
        page_from = changes.get("page_from", scope.page_from)
        page_to = changes.get("page_to", scope.last_page)
        if not 1 <= page_from <= page_to <= document.page_count:
            return Response({"detail": f"Pages must satisfy 1 ≤ from ≤ to ≤ {document.page_count}."},
                            status=status.HTTP_400_BAD_REQUEST)
        for field, value in changes.items():
            setattr(scope, field, value)
        # Store "to the end" as None, so the range keeps covering the last page if the PDF grows.
        scope.page_to = None if page_to == document.page_count else page_to
        scope.save()
        quiz = rebuild_todays_set() if QUIZ_FIELDS & changes.keys() else None

    note = next(n for n in sync_notes_folder() if n.document.pk == document.pk)
    return Response({"note": _note_data(note), "todays_quiz": quiz})


class PositionInput(serializers.Serializer):
    position = serializers.IntegerField(min_value=0)


@api_view(["PUT"])
def move(request: Request, document_id: int) -> Response:
    """Drag to reorder: put one PDF at a 0-based position in the pipeline order (PDFs on disk).
    Every PDF's priority is rewritten to its new index, so the order stays dense."""
    payload = PositionInput(data=request.data)
    payload.is_valid(raise_exception=True)
    order = [n.document for n in sync_notes_folder() if n.available]
    document = next((d for d in order if d.pk == document_id), None)
    if document is None:
        return Response({"detail": "Only PDFs in the notes folder can be reordered."},
                        status=status.HTTP_404_NOT_FOUND)
    order.remove(document)
    position = min(payload.validated_data["position"], len(order))
    order.insert(position, document)
    with transaction.atomic():
        for priority, doc in enumerate(order):
            scope, _ = NoteScope.objects.get_or_create(document=doc)
            if scope.priority != priority:
                scope.priority = priority
                scope.save(update_fields=["priority", "updated_at"])
    return Response({"id": document.pk, "position": position})


@api_view(["GET"])
def note_items(request: Request, document_id: int) -> Response:
    """Everything generated from one PDF, with the pages each item comes from."""
    document = get_object_or_404(Document, pk=document_id)
    questions = Question.objects.filter(chunk__document=document).select_related("chunk").prefetch_related(
        "quiz_sets").order_by("chunk__page_start", "id")
    reels = Reel.objects.filter(chunk__document=document).select_related("chunk").order_by("chunk__page_start", "id")
    return Response({
        "questions": [{
            "id": q.pk, "stem": q.stem, "difficulty": q.difficulty, "topic": q.chunk.title,
            "source_pages": q.source_pages, "quiz_date": max((qs.available_on for qs in q.quiz_sets.all()), default=None),
        } for q in questions],
        "reels": [{
            "id": r.pk, "title": r.title, "kind": r.kind, "topic": r.chunk.title,
            "source_pages": r.source_pages, "duration_s": r.duration_s,
        } for r in reels],
    })



@api_view(["GET"])
def reels(request: Request) -> Response:
    """The My Notes reel feed: reels whose pages are in the learner's current scope, newest first."""
    items = reels_in_scope(Reel.objects.select_related("chunk__document").annotate(view_count=Count("views"))
                           .order_by("-created_at", "-id"))
    storage = get_storage()
    return Response({"reels": [{
        "id": r.pk, "title": r.title, "key_point": r.key_point, "kind": r.kind, "duration_s": r.duration_s,
        "document": r.chunk.document.filename, "topic": r.chunk.title, "source_pages": r.source_pages,
        "url": storage.resolve_url(r.storage_key), "poster": _poster(r, storage), "created_at": r.created_at,
        "views": r.view_count,
    } for r in items]})


# Two counts closer together than this are one watch sent twice (a retried request, a double event).
VIEW_DEBOUNCE = timedelta(seconds=10)


@api_view(["POST"])
def reel_view(request: Request, reel_id: int) -> Response:
    """Count one watch. The app sends this when 80% of a play-through has actually been watched."""
    reel = get_object_or_404(Reel, pk=reel_id)
    with transaction.atomic():
        Reel.objects.select_for_update().filter(pk=reel.pk).first()  # serialise counting per reel
        last = reel.views.order_by("-created_at").first()
        counted = last is None or timezone.now() - last.created_at >= VIEW_DEBOUNCE
        if counted:
            view = ReelView.objects.create(reel=reel)
            activity.refresh(activity.local_day(view.created_at))
    return Response({"views": reel.views.count(), "counted": counted},
                    status=status.HTTP_201_CREATED if counted else status.HTTP_200_OK)


def _poster(reel: Reel, storage) -> str | None:
    key = reel.storage_key.removesuffix(".mp4") + ".png"
    return storage.resolve_url(key) if storage.exists(key) else None


_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def media(request: HttpRequest, key: str) -> HttpResponse:
    """Serve a generated file from MEDIA_ROOT, with byte ranges so video players can seek.

    Only reachable when STORAGE_BACKEND=local — LocalDiskStorage.resolve_url() points here.
    In production (STORAGE_BACKEND=r2), resolve_url() returns an R2 URL directly and this
    view is never hit; video bytes flow straight from R2 to the browser."""
    root = Path(settings.MEDIA_ROOT).resolve()
    path = (root / key).resolve()
    if root not in path.parents or not path.is_file():
        raise Http404
    size = path.stat().st_size
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    match = _RANGE.match(request.headers.get("Range", ""))
    if not match or not any(match.groups()):
        response = FileResponse(path.open("rb"), content_type=content_type)
        response["Accept-Ranges"] = "bytes"
        return response
    start, end = match.groups()
    if start:
        first, last = int(start), min(int(end) if end else size - 1, size - 1)
    else:  # "bytes=-N": the last N bytes
        first, last = max(size - int(end), 0), size - 1
    if first > last or first >= size:
        response = HttpResponse(status=416)
        response["Content-Range"] = f"bytes */{size}"
        return response

    def body(f=path.open("rb"), remaining=last - first + 1):
        with f:
            f.seek(first)
            while remaining > 0 and (chunk := f.read(min(1 << 16, remaining))):
                remaining -= len(chunk)
                yield chunk

    response = StreamingHttpResponse(body(), status=206, content_type=content_type)
    response["Content-Range"] = f"bytes {first}-{last}/{size}"
    response["Content-Length"] = str(last - first + 1)
    response["Accept-Ranges"] = "bytes"
    return response
