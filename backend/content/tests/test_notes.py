import hashlib

import pytest
from rest_framework.test import APIClient

from content.models import Chunk, Document, GenerationTask, NoteScope, Question
from pipeline.tests.test_api import API, runner_client
from quiz.models import QuizAttempt, QuizSet

pytestmark = pytest.mark.django_db


def entry(path: str, pages: int, folder: str = "") -> dict:
    """A pipeline notes-sync report entry. `path` only needs to be a stable, unique string here
    (no real file is read server-side any more) — its hash is derived from it directly."""
    return {"path": path, "filename": path.rsplit("/", 1)[-1],
            "file_hash": hashlib.sha256(path.encode()).hexdigest(),
            "size": pages * 137, "mtime": 1.0, "page_count": pages, "folder": folder}


def sync(client: APIClient, entries: list[dict], notes_dir: str = "~/Documents/Notes"):
    """A full-state sync report, as the pipeline sends it — every call reports every PDF
    currently on disk; anything omitted is marked unavailable."""
    response = client.post(f"{API}/notes/sync", {"notes_dir": notes_dir, "documents": entries}, format="json")
    assert response.status_code == 200, response.data
    return response.data


@pytest.fixture
def notes_dir():
    """Registers Redis.pdf and NGINX.pdf. NGINX is sent first so Redis — processed last, same
    as the real pipeline's sorted-path walk where "Redis.pdf" sorts after "NGINX.pdf" — ends up
    on top ("each new PDF goes on top" — content/notes.py::apply_sync_report)."""
    client = runner_client("kl@test")
    sync(client, [entry("/notes/Tech/NGINX.pdf", 5, "Tech"), entry("/notes/Tech/Redis.pdf", 12, "Tech")])
    return client


def add_questions(document: Document, pages: list[list[int]]) -> None:
    chunk = Chunk.objects.create(document=document, page_start=1, page_end=document.page_count, status="read")
    task = GenerationTask.objects.create(chunk=chunk, kind="quiz", status="done")
    for i, source in enumerate(pages):
        Question.objects.create(chunk=chunk, task=task, stem=f"Q{i}", options=["a", "b", "c", "d"], correct_index=0,
                                explanation="e", source_pages=source, difficulty="easy")


def test_lists_every_pdf_in_the_folder_with_defaults(notes_dir):
    data = APIClient().get("/api/notes").data["notes"]
    assert [(n["filename"], n["folder"], n["page_count"]) for n in data] == [("Redis.pdf", "Tech", 12),
                                                                              ("NGINX.pdf", "Tech", 5)]
    assert data[0]["scope"] == {"selected": True, "page_from": 1, "page_to": 12,
                                "include_quiz": True, "include_reels": True, "priority": -1}
    # Re-syncing the same report creates nothing new.
    sync(notes_dir, [entry("/notes/Tech/NGINX.pdf", 5, "Tech"), entry("/notes/Tech/Redis.pdf", 12, "Tech")])
    assert Document.objects.count() == 2 and NoteScope.objects.count() == 2


def test_missing_pdf_is_listed_as_unavailable(notes_dir):
    sync(notes_dir, [entry("/notes/Tech/Redis.pdf", 12, "Tech")])  # NGINX no longer reported
    data = APIClient().get("/api/notes").data["notes"]
    assert [(n["filename"], n["available"]) for n in data] == [("Redis.pdf", True), ("NGINX.pdf", False)]


def test_sync_needs_a_valid_runner_token():
    assert APIClient().post(f"{API}/notes/sync", {"notes_dir": "~", "documents": []},
                            format="json").status_code in (401, 403)


def test_renamed_file_is_recognised_by_content_not_path(notes_dir):
    """Same file_hash, different path/filename: the existing Document is updated in place,
    not duplicated — a moved or renamed PDF stays the same document."""
    redis = Document.objects.get(filename="Redis.pdf")
    moved = entry("/notes/Archive/Redis-2024.pdf", 12, "Archive")
    moved["file_hash"] = redis.file_hash
    sync(notes_dir, [entry("/notes/Tech/NGINX.pdf", 5, "Tech"), moved])
    redis.refresh_from_db()
    assert redis.filename == "Redis-2024.pdf" and redis.folder == "Archive" and redis.available
    assert Document.objects.count() == 2  # still just Redis + NGINX, nothing duplicated


def test_scope_update_counts_items_in_range(notes_dir):
    client = APIClient()
    redis = Document.objects.get(filename="Redis.pdf")
    add_questions(redis, [[1], [2, 3], [8], [11, 12]])

    response = client.patch(f"/api/notes/{redis.pk}", {"page_from": 2, "page_to": 8}, format="json")
    assert response.status_code == 200
    assert response.data["note"]["questions"] == {"total": 4, "in_scope": 2}
    assert response.data["todays_quiz"] == "rebuilt"
    assert NoteScope.objects.get(document=redis).page_to == 8

    whole = client.patch(f"/api/notes/{redis.pk}", {"page_from": 1, "page_to": 12}, format="json")
    assert whole.data["note"]["questions"]["in_scope"] == 4
    assert NoteScope.objects.get(document=redis).page_to is None  # stored as "to the end"


def test_scope_rejects_bad_ranges(notes_dir):
    client = APIClient()
    redis = Document.objects.get(filename="Redis.pdf")
    assert client.patch(f"/api/notes/{redis.pk}", {"page_from": 9, "page_to": 3}, format="json").status_code == 400
    assert client.patch(f"/api/notes/{redis.pk}", {"page_to": 13}, format="json").status_code == 400


def test_reels_toggle_leaves_todays_quiz_alone(notes_dir):
    client = APIClient()
    redis = Document.objects.get(filename="Redis.pdf")
    response = client.patch(f"/api/notes/{redis.pk}", {"include_reels": False}, format="json")
    assert response.data["todays_quiz"] is None


def test_started_quiz_is_not_rebuilt(notes_dir):
    client = APIClient()
    redis = Document.objects.get(filename="Redis.pdf")
    add_questions(redis, [[1], [2]])
    quiz_set = client.get("/api/quiz/today").data["quiz_set"]
    QuizAttempt.objects.create(quiz_set=QuizSet.objects.get(pk=quiz_set["id"]), answers=[], correct=0, total=2,
                               score_pct=0, pass_pct=70, passed=False)
    response = client.patch(f"/api/notes/{redis.pk}", {"selected": False}, format="json")
    assert response.data["todays_quiz"] == "started"


def test_items_report_their_pages(notes_dir):
    client = APIClient()
    redis = Document.objects.get(filename="Redis.pdf")
    add_questions(redis, [[4, 5]])
    items = client.get(f"/api/notes/{redis.pk}/items").data
    assert items["questions"][0]["source_pages"] == [4, 5]
    assert items["reels"] == []


def test_progress_per_kind_and_manage_notes_order(notes_dir):
    from datetime import timedelta

    from django.utils import timezone

    from content.models import GenerationRun

    client = APIClient()
    redis = Document.objects.get(filename="Redis.pdf")
    NoteScope.objects.filter(document=redis).update(page_from=3, page_to=10)
    run = GenerationRun.objects.create(kind="quiz", runner="test")
    chunk = lambda a, b, **kw: Chunk.objects.create(document=redis, page_start=a, page_end=b, **kw)  # noqa: E731
    GenerationTask.objects.create(chunk=chunk(1, 4, status="read"), kind="quiz", status="done")
    chunk(5, 6, status="unreadable")
    GenerationTask.objects.create(chunk=chunk(7, 8), kind="quiz", status="failed", error="boom")
    GenerationTask.objects.create(chunk=chunk(9, 12), kind="quiz", status="claimed", run=run, stage="write",
                                  detail="round 2 of 3", started_at=timezone.now(),
                                  lease_expires_at=timezone.now() + timedelta(minutes=5))

    data = {n["filename"]: n for n in client.get("/api/notes").data["notes"]}
    quiz = data["Redis.pdf"]["progress"]["quiz"]
    assert quiz["done_ranges"] == [[1, 6]] and quiz["pages_in_range"] == 8 and quiz["pages_done"] == 4
    assert quiz["failed"] == [{"task_id": quiz["failed"][0]["task_id"], "pages": [7, 8], "error": "boom"}]
    assert quiz["active"]["pages"] == [9, 12] and quiz["active"]["detail"] == "round 2 of 3"
    reel = data["Redis.pdf"]["progress"]["reel"]
    assert reel["done_ranges"] == [[5, 6]] and reel["active"] is None  # unreadable pages count for every kind

    # Drag to reorder: moving one PDF rewrites every priority densely.
    nginx = Document.objects.get(filename="NGINX.pdf")
    assert client.put(f"/api/notes/{redis.pk}/position", {"position": 0}, format="json").data == {
        "id": redis.pk, "position": 0}
    listed = client.get("/api/notes").data["notes"]
    assert [(n["filename"], n["position"], n["scope"]["priority"]) for n in listed] == [
        ("Redis.pdf", 0, 0), ("NGINX.pdf", 1, 1)]
    assert client.put(f"/api/notes/{nginx.pk}/position", {"position": 99}, format="json").data["position"] == 1
    assert client.put("/api/notes/999/position", {"position": 0}, format="json").status_code == 404
    assert client.put(f"/api/notes/{redis.pk}/position", {"position": -1}, format="json").status_code == 400


def test_paginated_filtered_list():
    client = runner_client("kl@test")
    # In the pipeline's real sorted-path processing order — each new PDF goes on top, so the
    # last one synced (Redis) ends up first.
    entries = [entry("/notes/Maths/Algebra.pdf", 2, "Maths"), entry("/notes/Maths/Graphs.pdf", 3, "Maths"),
               entry("/notes/Tech/Docker.pdf", 4, "Tech"), entry("/notes/Tech/Kafka.pdf", 5, "Tech"),
               entry("/notes/Tech/NGINX.pdf", 6, "Tech"), entry("/notes/Tech/Redis.pdf", 7, "Tech")]
    sync(client, entries)
    app = APIClient()
    assert [n["filename"] for n in app.get("/api/notes").data["notes"]] == [
        "Redis.pdf", "NGINX.pdf", "Kafka.pdf", "Docker.pdf", "Graphs.pdf", "Algebra.pdf"]
    NoteScope.objects.filter(document__filename__in=["Kafka.pdf", "Graphs.pdf"]).update(selected=False)

    page = app.get("/api/notes", {"page": 2, "page_size": 4}).data
    assert [n["filename"] for n in page["notes"]] == ["Graphs.pdf", "Algebra.pdf"]
    assert (page["total"], page["page"], page["page_size"]) == (6, 2, 4)
    assert page["folders"] == ["Maths", "Tech"]
    assert page["summary"] == {"documents": 6, "selected": 4, "questions_ready": 0}
    assert page["notes"][0]["position"] == 4
    assert app.get("/api/notes", {"page": 9, "page_size": 4}).data["page"] == 2  # clamped to the last page

    def names(**params):
        return [n["filename"] for n in app.get("/api/notes", {"page": 1, **params}).data["notes"]]
    assert names(q="gr") == ["Graphs.pdf"]
    assert names(folder="Tech") == ["Redis.pdf", "NGINX.pdf", "Kafka.pdf", "Docker.pdf"]
    assert names(selected="no") == ["Kafka.pdf", "Graphs.pdf"]
    assert names(folder="Tech", selected="yes", q="r") == ["Redis.pdf", "Docker.pdf"]
    assert app.get("/api/notes", {"page": 1, "selected": "maybe"}).status_code == 400
    assert app.get("/api/notes", {"page": 1, "page_size": 500}).status_code == 400

    # A PDF added after reordering still goes on top.
    app.put(f"/api/notes/{Document.objects.get(filename='Algebra.pdf').pk}/position", {"position": 0},
             format="json")
    sync(client, entries + [entry("/notes/Maths/Calculus.pdf", 8, "Maths")])
    assert names(page_size=100)[:2] == ["Calculus.pdf", "Algebra.pdf"]
