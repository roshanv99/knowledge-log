import pytest
from rest_framework.test import APIClient

from content.models import Document, GenerationTask, NoteScope, Reel
from pipeline.tests.test_api import API, runner_client

pytestmark = pytest.mark.django_db

# The smallest byte string that passes the MP4 check: a box size, then "ftyp".
MP4 = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 500


@pytest.fixture(autouse=True)
def media_root(tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path / "media"
    return settings.MEDIA_ROOT


@pytest.fixture
def document():
    doc = Document.objects.create(file_hash="d", filename="Docker.pdf", page_count=8)
    NoteScope.objects.create(document=doc)
    return doc


def reel_task(client) -> tuple[int, dict]:
    run_id = client.post(f"{API}/runs", {"kind": "reel"}, format="json").data["run_id"]
    task = client.post(f"{API}/runs/{run_id}/claim", {}, format="json").data["task"]
    return run_id, task


def upload(client, task_id, run_id, body=MP4):
    return client.generic("PUT", f"{API}/tasks/{task_id}/media?run_id={run_id}", body, content_type="video/mp4")


def test_reel_task_upload_complete_and_feed(document, media_root):
    mac = runner_client("kl@mac")
    run_id, task = reel_task(mac)
    assert task["kind"] == "reel" and task["reel_style"] == "manim"
    tid = task["id"]

    reel = {"title": "Bridge networks", "key_point": "Containers on one bridge talk by name.", "duration_s": 58.2,
            "storage_key": f"reels/task-{tid}.mp4"}
    early = mac.post(f"{API}/tasks/{tid}/complete", {"run_id": run_id, "reel": reel}, format="json")
    assert early.status_code == 400 and "Upload the video first" in early.data["detail"]

    assert upload(mac, tid, run_id, b"not a video" * 10).status_code == 400
    assert upload(mac, tid, run_id).data == {"storage_key": f"reels/task-{tid}.mp4"}
    assert (media_root / "reels" / f"task-{tid}.mp4").read_bytes() == MP4

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    poster = mac.generic("PUT", f"{API}/tasks/{tid}/media?run_id={run_id}&kind=poster", png, content_type="image/png")
    assert poster.data == {"storage_key": f"reels/task-{tid}.png"}
    assert mac.generic("PUT", f"{API}/tasks/{tid}/media?run_id={run_id}&kind=poster", MP4,
                       content_type="image/png").status_code == 400
    done = mac.post(f"{API}/tasks/{tid}/complete", {"run_id": run_id, "reel": reel}, format="json")
    assert done.data == {"status": "done", "reels_created": 1}
    again = mac.post(f"{API}/tasks/{tid}/complete", {"run_id": run_id, "reel": reel}, format="json")
    assert again.data == {"status": "done", "reels_created": 0}
    saved = Reel.objects.get()
    assert (saved.kind, saved.source_pages, saved.task_id) == ("manim", [1, 2, 3, 4], tid)
    finished = mac.post(f"{API}/runs/{run_id}/finish", {"stop_reason": "done"}, format="json").data
    assert finished["reels_made"] == 1

    feed = APIClient().get("/api/reels").data["reels"]
    assert [r["title"] for r in feed] == ["Bridge networks"] and feed[0]["url"] == f"/api/media/reels/task-{tid}.mp4"
    assert feed[0]["poster"] == f"/api/media/reels/task-{tid}.png"
    notes = {n["filename"]: n for n in APIClient().get("/api/notes").data["notes"]}
    assert notes["Docker.pdf"]["progress"]["reel"]["done_ranges"] == [[1, 4]]

    # Out of scope: deselecting the PDF hides the reel.
    NoteScope.objects.filter(document=document).update(include_reels=False)
    assert APIClient().get("/api/reels").data["reels"] == []


def test_media_is_served_with_ranges(media_root):
    (media_root / "reels").mkdir(parents=True)
    (media_root / "reels" / "task-1.mp4").write_bytes(MP4)
    client = APIClient()
    full = client.get("/api/media/reels/task-1.mp4")
    assert full.status_code == 200 and b"".join(full.streaming_content) == MP4
    assert full["Accept-Ranges"] == "bytes" and full["Content-Type"] == "video/mp4"
    part = client.get("/api/media/reels/task-1.mp4", HTTP_RANGE="bytes=4-7")
    assert part.status_code == 206 and b"".join(part.streaming_content) == b"ftyp"
    assert part["Content-Range"] == f"bytes 4-7/{len(MP4)}"
    tail = client.get("/api/media/reels/task-1.mp4", HTTP_RANGE="bytes=-3")
    assert b"".join(tail.streaming_content) == MP4[-3:]
    assert client.get("/api/media/reels/task-1.mp4", HTTP_RANGE=f"bytes={len(MP4) + 5}-").status_code == 416
    assert client.get("/api/media/../settings.py").status_code == 404
    assert client.get("/api/media/reels/nope.mp4").status_code == 404


def test_kinds_cannot_mix_outputs(document):
    mac = runner_client("kl@mac")
    run_id, task = reel_task(mac)
    q = {"stem": "Q?", "options": ["a", "b", "c", "d"], "correct_index": 0, "explanation": "e",
         "source_pages": [1], "difficulty": "easy"}
    assert mac.post(f"{API}/tasks/{task['id']}/complete", {"run_id": run_id, "questions": [q]},
                    format="json").status_code == 400
    quiz_run = mac.post(f"{API}/runs", {"kind": "quiz"}, format="json").data["run_id"]
    quiz_task = mac.post(f"{API}/runs/{quiz_run}/claim", {}, format="json").data["task"]
    assert upload(mac, quiz_task["id"], quiz_run).status_code == 400  # only reel tasks take media
    assert GenerationTask.objects.get(pk=task["id"]).status == "claimed"


def test_quiz_and_reel_runs_can_be_active_together(document):
    mac = runner_client("kl@mac")
    assert mac.post(f"{API}/runs", {"kind": "quiz"}, format="json").status_code == 201
    assert mac.post(f"{API}/runs", {"kind": "reel"}, format="json").status_code == 201


def test_reel_limit_stops_reel_work(document, tmp_path):
    from content.models import Chunk
    from quiz.models import Settings

    prefs = Settings.load()
    prefs.reel_limit = 1
    prefs.save()
    mac = runner_client("kl@mac")
    run_id, task = reel_task(mac)  # one reel in progress fills the limit of 1
    assert APIClient().post(f"{API}/requests", {"kind": "reel"},
                            format="json").status_code == 409
    upload(mac, task["id"], run_id)
    mac.post(f"{API}/tasks/{task['id']}/complete", {"run_id": run_id, "reel": {
        "title": "T", "storage_key": f"reels/task-{task['id']}.mp4"}}, format="json")
    assert mac.post(f"{API}/runs/{run_id}/claim", {}, format="json").data == {"task": None, "reason": "reel_limit"}
    assert mac.get(f"{API}/wanted?kind=reel").status_code == 204
    assert Chunk.objects.count() == 1  # nothing new was planned
    prefs.reel_limit = 0  # 0 means no limit
    prefs.save()
    assert mac.post(f"{API}/runs/{run_id}/claim", {}, format="json").data["task"] is not None
    assert oct((tmp_path / "media" / "reels" / f"task-{task['id']}.mp4").stat().st_mode)[-3:] == "644"


def test_watches_are_counted_once_per_play_through(document):
    from datetime import timedelta

    from django.utils import timezone

    from content.models import ReelView

    mac = runner_client("kl@mac")
    run_id, task = reel_task(mac)
    upload(mac, task["id"], run_id)
    mac.post(f"{API}/tasks/{task['id']}/complete", {"run_id": run_id, "reel": {
        "title": "T", "storage_key": f"reels/task-{task['id']}.mp4"}}, format="json")
    reel_id = APIClient().get("/api/reels").data["reels"][0]["id"]
    assert APIClient().get("/api/reels").data["reels"][0]["views"] == 0

    first = APIClient().post(f"/api/reels/{reel_id}/views")
    assert first.status_code == 201 and first.data == {"views": 1, "counted": True}
    twice = APIClient().post(f"/api/reels/{reel_id}/views")  # the same watch sent again
    assert twice.status_code == 200 and twice.data == {"views": 1, "counted": False}
    ReelView.objects.update(created_at=timezone.now() - timedelta(minutes=2))
    assert APIClient().post(f"/api/reels/{reel_id}/views").data == {"views": 2, "counted": True}
    assert APIClient().get("/api/reels").data["reels"][0]["views"] == 2
    assert APIClient().post("/api/reels/999/views").status_code == 404
