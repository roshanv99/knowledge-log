import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from content.models import Document, GenerationTask, NoteScope, Question
from pipeline.models import Runner

pytestmark = pytest.mark.django_db
API = "/api/pipeline"

QUESTION = {"stem": "What does a bridge network do?", "options": ["a", "b", "c", "d"], "correct_index": 2,
            "explanation": "Because.", "source_pages": [2, 3], "difficulty": "medium"}
NOTES = {"title": "Bridges", "summary": "About bridges.", "key_points": [{"point": "p", "page": 2}], "testable": True}


def runner_client(name: str) -> APIClient:
    runner = Runner(name=name, kind="claude-session")
    token = runner.issue_token()
    runner.save()
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.fixture
def document():
    doc = Document.objects.create(file_hash="d", filename="Docker.pdf", page_count=8)
    NoteScope.objects.create(document=doc)
    return doc


@pytest.fixture
def mac():
    return runner_client("kl@mac")


def start(client, kind="quiz") -> int:
    response = client.post(f"{API}/runs", {"kind": kind, "params": {"max_pages": 4}}, format="json")
    assert response.status_code == 201, response.data
    return response.data["run_id"]


def claim(client, run_id) -> dict:
    response = client.post(f"{API}/runs/{run_id}/claim", {}, format="json")
    assert response.status_code == 200, response.data
    return response.data


def test_runner_endpoints_need_a_valid_token(document):
    assert APIClient().post(f"{API}/runs", {"kind": "quiz"}, format="json").status_code in (401, 403)
    bad = APIClient()
    bad.credentials(HTTP_AUTHORIZATION="Bearer klr_nope")
    assert bad.post(f"{API}/runs", {"kind": "quiz"}, format="json").status_code == 401
    call_command("runner_token", "kl@mac", "--disable")  # no such runner yet: harmless


def test_full_run_through_the_api(document, mac):
    run_id = start(mac)
    task = claim(mac, run_id)["task"]
    assert task["chunk"]["status"] == "unread" and (task["chunk"]["page_start"], task["chunk"]["page_end"]) == (1, 4)
    assert task["document"]["filename"] == "Docker.pdf" and task["attempt"] == 1

    tid = task["id"]
    assert mac.post(f"{API}/tasks/{tid}/heartbeat", {"run_id": run_id, "stage": "read"},
                    format="json").status_code == 200
    assert mac.put(f"{API}/tasks/{tid}/notes", {"run_id": run_id, **NOTES}, format="json").data == {
        "chunk_status": "read"}

    done = mac.post(f"{API}/tasks/{tid}/complete", {"run_id": run_id, "questions": [QUESTION],
                                                     "review_log": [{"round": 1}]}, format="json")
    assert done.data == {"status": "done", "questions_created": 1}
    again = mac.post(f"{API}/tasks/{tid}/complete", {"run_id": run_id, "questions": [QUESTION]}, format="json")
    assert again.data == {"status": "done", "questions_created": 0}  # idempotent
    assert Question.objects.count() == 1

    finished = mac.post(f"{API}/runs/{run_id}/finish", {"stop_reason": "page_budget_done"}, format="json")
    assert finished.data["tasks_done"] == 1 and finished.data["questions_made"] == 1
    document.refresh_from_db()
    assert document.last_processed_page == 4


def test_complete_rejects_bad_questions(document, mac):
    run_id = start(mac)
    tid = claim(mac, run_id)["task"]["id"]
    bad = [
        {**QUESTION, "source_pages": [7]},  # outside the chunk
        {**QUESTION, "options": ["a", "a", "b", "c"]},
        {**QUESTION, "options": ["a", "b", "c"]},
        {**QUESTION, "correct_index": 4},
        {**QUESTION, "difficulty": "trivial"},
    ]
    for question in bad:
        response = mac.post(f"{API}/tasks/{tid}/complete", {"run_id": run_id, "questions": [question]},
                            format="json")
        assert response.status_code == 400, question
    twins = mac.post(f"{API}/tasks/{tid}/complete", {"run_id": run_id, "questions": [QUESTION, QUESTION]},
                     format="json")
    assert twins.status_code == 400
    assert GenerationTask.objects.get(pk=tid).status == "claimed" and not Question.objects.exists()


def test_lost_claim_gets_409(document, mac):
    run_id = start(mac)
    tid = claim(mac, run_id)["task"]["id"]
    mac.post(f"{API}/runs/{run_id}/finish", {"stop_reason": "usage_limit"}, format="json")
    late = mac.post(f"{API}/tasks/{tid}/heartbeat", {"run_id": run_id, "stage": "write"}, format="json")
    assert late.status_code == 409

    other = runner_client("kl@other")
    run2 = start(other)
    assert claim(other, run2)["task"]["id"] == tid
    stolen = mac.post(f"{API}/tasks/{tid}/complete", {"run_id": run_id, "questions": [QUESTION]}, format="json")
    assert stolen.status_code == 409 and not Question.objects.exists()


def test_runners_cannot_use_each_others_runs(document, mac):
    run_id = start(mac)
    other = runner_client("kl@other")
    assert other.post(f"{API}/runs/{run_id}/claim", {}, format="json").status_code == 404
    assert other.post(f"{API}/runs/{run_id}/finish", {"stop_reason": "x"}, format="json").status_code == 404


def test_second_active_run_conflicts_and_unknown_task_is_404(document, mac):
    run_id = start(mac)
    assert mac.post(f"{API}/runs", {"kind": "quiz"}, format="json").status_code == 409
    assert mac.post(f"{API}/tasks/999/heartbeat", {"run_id": run_id, "stage": "x"}, format="json").status_code == 404
    assert mac.post(f"{API}/tasks/999/complete", {"run_id": run_id}, format="json").status_code == 404
    assert mac.post(f"{API}/tasks/1/complete", {"run_id": "abc"}, format="json").status_code == 400


def test_claim_reports_why_there_is_nothing(document, mac):
    NoteScope.objects.filter(document=document).update(selected=False)
    assert claim(mac, start(mac)) == {"task": None, "reason": "nothing_selected"}


def test_fail_and_retry_from_the_app(document, mac):
    run_id = start(mac)
    tid = claim(mac, run_id)["task"]["id"]
    failed = mac.post(f"{API}/tasks/{tid}/fail", {"run_id": run_id, "error": "render crashed", "retryable": False},
                      format="json")
    assert failed.data == {"status": "failed", "attempts": 1}

    status = APIClient().get(f"{API}/status").data
    assert [t["id"] for t in status["failed_tasks"]] == [tid]
    assert status["failed_tasks"][0]["error"] == "render crashed"
    assert status["active_runs"][0]["id"] == run_id

    assert APIClient().post(f"{API}/tasks/{tid}/retry").data["status"] == "pending"
    assert APIClient().post(f"{API}/tasks/{tid}/retry").status_code == 409


def test_run_now_and_wanted(document, mac):
    assert mac.get(f"{API}/wanted?kind=quiz").status_code == 204
    assert APIClient().post(f"{API}/requests", {"kind": "quiz"}, format="json").status_code == 201
    want = mac.get(f"{API}/wanted?kind=quiz").data
    assert want["reason"] == "run_request" and want["document"] == "Docker.pdf" and want["pages"] == [1, 4]
    assert APIClient().get(f"{API}/status").data["open_requests"][0]["kind"] == "quiz"
    start(mac)
    assert APIClient().get(f"{API}/status").data["open_requests"] == []


def test_runner_token_command_rotates(capsys):
    call_command("runner_token", "kl@mac")
    first = capsys.readouterr().out.strip()
    call_command("runner_token", "kl@mac")
    second = capsys.readouterr().out.strip()
    assert first != second and first.startswith("klr_")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {first}")
    assert client.get(f"{API}/wanted").status_code == 401  # the old token stopped working
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {second}")
    assert client.get(f"{API}/wanted").status_code == 204
