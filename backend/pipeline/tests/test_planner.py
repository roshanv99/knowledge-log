from datetime import timedelta

import pytest
from django.utils import timezone

from content.models import Chunk, Document, GenerationRun, GenerationTask, NoteScope, Question
from pipeline import planner, services
from pipeline.planner import Reason
from quiz.models import Settings

pytestmark = pytest.mark.django_db
Status = GenerationTask.Status


@pytest.fixture
def make_doc(tmp_path):
    def make(name: str, pages: int, *, on_disk: bool = True, **scope) -> Document:
        path = tmp_path / name
        if on_disk:
            path.write_bytes(b"%PDF")
        document = Document.objects.create(file_hash=name, path=str(path), filename=name, page_count=pages)
        NoteScope.objects.create(document=document, **scope)
        return document
    return make


def new_run(kind="quiz") -> GenerationRun:
    return services.start_run(kind, "test", {})


def claimed_pages(task) -> tuple[int, int]:
    return task.chunk.page_start, task.chunk.page_end


def test_uncovered_windows_fill_gaps_in_chunk_sized_steps():
    chunks = [Chunk(page_start=1, page_end=4), Chunk(page_start=9, page_end=10)]
    assert planner.uncovered_windows(chunks, 1, 15, 4) == [(5, 8), (11, 14), (15, 15)]
    assert planner.uncovered_windows(chunks, 3, 9, 4) == [(5, 8)]


def test_claims_from_the_bottom_of_manage_notes_up(make_doc):
    later = make_doc("A.pdf", 10, priority=0)  # top of the list
    first = make_doc("B.pdf", 10, priority=1)  # bottom: worked on first
    run = new_run()
    task = services.claim(run)
    assert task.chunk.document == first and claimed_pages(task) == (1, 4)
    assert task.status == Status.CLAIMED and task.run == run and task.lease_expires_at > timezone.now()
    assert claimed_pages(services.claim(run)) == (5, 8)
    assert claimed_pages(services.claim(run)) == (9, 10)
    assert services.claim(run).chunk.document == later


def test_scope_limits_what_is_offered(make_doc):
    make_doc("Off.pdf", 10, selected=False)
    make_doc("NoQuiz.pdf", 10, include_quiz=False)
    ranged = make_doc("Ranged.pdf", 20, page_from=6, page_to=9)
    run = new_run()
    task = services.claim(run)
    assert task.chunk.document == ranged and claimed_pages(task) == (6, 9)
    assert services.claim(run) == Reason.RANGE_DONE
    # Work outside the range is never offered, and its failures don't count.
    outside = Chunk.objects.create(document=ranged, page_start=15, page_end=18)
    GenerationTask.objects.create(chunk=outside, kind="quiz", status=Status.PENDING)
    GenerationTask.objects.create(chunk=Chunk.objects.create(document=ranged, page_start=1, page_end=4),
                                  kind="quiz", status=Status.FAILED, attempts=3)
    assert services.claim(run) == Reason.RANGE_DONE


def test_nothing_selected(make_doc):
    make_doc("Off.pdf", 10, selected=False)
    assert services.claim(new_run()) == Reason.NOTHING_SELECTED


def test_expired_lease_is_reclaimed_before_new_pages(make_doc):
    make_doc("A.pdf", 12)
    dead = new_run()
    task = services.claim(dead)
    services.finish(dead, "crash-test", None)  # finishing hands the task back at once
    assert GenerationTask.objects.get(pk=task.pk).status == Status.PENDING

    # Without finish, the lease has to expire first.
    crashed = new_run()
    again = services.claim(crashed)
    assert again.pk == task.pk
    crashed.last_seen_at = timezone.now() - timedelta(hours=1)
    crashed.save()
    GenerationTask.objects.filter(pk=task.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    services.close_abandoned_runs()
    fresh = new_run()
    assert services.claim(fresh).pk == task.pk


def test_expired_lease_of_a_live_run_is_reoffered(make_doc):
    make_doc("A.pdf", 4)
    slow = new_run()
    task = services.claim(slow)
    GenerationTask.objects.filter(pk=task.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
    retaken = planner.claim("quiz", slow)
    assert retaken.pk == task.pk and retaken.lease_expires_at > timezone.now()


def test_retries_are_capped(make_doc, settings):
    make_doc("A.pdf", 4)
    run = new_run()
    task = services.claim(run)
    for attempt in range(1, settings.KL_MAX_TASK_ATTEMPTS + 1):
        failed = services.fail(run, task.pk, "boom", retryable=True)
        assert failed.attempts == attempt
        if attempt < settings.KL_MAX_TASK_ATTEMPTS:
            assert failed.status == Status.PENDING and services.claim(run).pk == task.pk
    assert failed.status == Status.FAILED
    assert services.claim(run) == Reason.ALL_FAILED
    services.retry(GenerationTask.objects.get(pk=task.pk))
    assert services.claim(run).pk == task.pk


def test_non_retryable_failure_waits_for_a_manual_retry(make_doc):
    make_doc("A.pdf", 4)
    run = new_run()
    task = services.claim(run)
    failed = services.fail(run, task.pk, "bad pages", retryable=False)
    assert failed.status == Status.FAILED and failed.attempts == 1
    assert services.claim(run) == Reason.ALL_FAILED


def test_chunks_read_for_another_kind_get_a_task(make_doc):
    document = make_doc("A.pdf", 8)
    chunk = Chunk.objects.create(document=document, page_start=1, page_end=4, status=Chunk.Status.READ)
    GenerationTask.objects.create(chunk=chunk, kind="reel", status=Status.DONE)
    task = services.claim(new_run())
    assert task.chunk == chunk and task.kind == "quiz"


def test_unreadable_chunks_and_missing_files_are_skipped(make_doc):
    document = make_doc("A.pdf", 8)
    Chunk.objects.create(document=document, page_start=1, page_end=4, status=Chunk.Status.UNREADABLE)
    make_doc("Gone.pdf", 8, on_disk=False, priority=-1)
    task = services.claim(new_run())
    assert task.chunk.document == document and claimed_pages(task) == (5, 8)


def test_document_filter(make_doc):
    make_doc("A.pdf", 8)
    b = make_doc("B.pdf", 8, priority=5)
    assert services.claim(new_run(), document_id=b.pk).chunk.document == b


def test_complete_is_idempotent_and_advances_the_document(make_doc):
    document = make_doc("A.pdf", 8)
    run = new_run()
    task = services.claim(run)
    question = {"stem": "Q?", "options": ["a", "b", "c", "d"], "correct_index": 1, "explanation": "e",
                "source_pages": [2], "difficulty": "easy"}
    done, created = services.complete(run, task.pk, [question], [{"round": 1}])
    assert (done.status, created) == (Status.DONE, 1)
    assert services.complete(run, task.pk, [question], [])[1] == 0
    assert Question.objects.count() == 1 and Question.objects.get().task == done
    document.refresh_from_db()
    run.refresh_from_db()
    assert document.last_processed_page == 4 and (run.tasks_done, run.questions_made) == (1, 1)


def test_lost_lease_is_rejected(make_doc):
    make_doc("A.pdf", 4)
    first = new_run()
    task = services.claim(first)
    services.finish(first, "stopped", None)
    second = new_run()
    assert services.claim(second).pk == task.pk
    for call in (lambda: services.heartbeat(first, task.pk, "write", None),
                 lambda: services.complete(first, task.pk, [], [])):
        with pytest.raises(services.Conflict):
            call()


def test_heartbeat_extends_the_lease(make_doc):
    make_doc("A.pdf", 4)
    run = new_run()
    task = services.claim(run)
    GenerationTask.objects.filter(pk=task.pk).update(lease_expires_at=timezone.now() + timedelta(seconds=5))
    beat = services.heartbeat(run, task.pk, "critique", "round 2 of 3")
    assert beat.lease_expires_at > timezone.now() + timedelta(minutes=5) and beat.stage == "critique"


def test_untestable_notes_skip_the_task(make_doc):
    make_doc("A.pdf", 4)
    run = new_run()
    task = services.claim(run)
    chunk = services.save_notes(run, task.pk, {"title": "Cover", "testable": False})
    assert chunk.status == Chunk.Status.UNREADABLE
    done, _ = services.complete(run, task.pk, [], [], skipped_reason="cover page")
    assert done.status == Status.SKIPPED


def test_one_active_run_per_kind_and_run_caps(make_doc):
    make_doc("A.pdf", 40)
    run = new_run()
    with pytest.raises(services.Conflict):
        new_run()
    assert new_run("reel").kind == "reel"

    prefs = Settings.load()
    prefs.max_tasks_per_run = 2
    prefs.save()
    services.claim(run)
    services.claim(run)
    assert services.claim(run) == "run_cap"


def test_kill_switch_and_daily_cap(make_doc):
    make_doc("A.pdf", 4)
    prefs = Settings.load()
    running = new_run()
    prefs.pipeline_enabled = False
    prefs.save()
    with pytest.raises(services.Disabled):
        new_run("reel")
    assert services.claim(running) == "disabled"  # a run already going stops at its next claim
    services.finish(running, "disabled", None)
    prefs.pipeline_enabled, prefs.max_runs_per_day = True, 1
    prefs.save()
    run = new_run()
    services.complete(run, services.claim(run).pk, [], [])
    services.finish(run, "done", None)
    with pytest.raises(services.Disabled):
        new_run()


def test_idle_runs_do_not_use_up_the_daily_cap(make_doc):
    make_doc("Off.pdf", 4, selected=False)
    prefs = Settings.load()
    prefs.max_runs_per_day = 1
    prefs.save()
    for _ in range(3):
        run = new_run()
        services.finish(run, services.claim(run), None)


def test_wanted_needs_a_request_unless_auto(make_doc):
    make_doc("A.pdf", 8)
    assert services.wanted("quiz") is None
    request = services.request_run("quiz")
    assert services.request_run("quiz") == request  # one open request per kind
    want = services.wanted("quiz")
    assert want["reason"] == "run_request" and want["pages"] == [1, 4]
    run = new_run()
    request.refresh_from_db()
    assert request.consumed_by_run == run
    assert services.wanted("quiz") is None  # a run is active
    services.finish(run, "done", None)

    prefs = Settings.load()
    prefs.pipeline_auto = True
    prefs.save()
    assert services.wanted("quiz")["reason"] == "schedule"


def test_request_with_nothing_to_do_is_closed(make_doc):
    make_doc("Off.pdf", 4, selected=False)
    services.request_run("quiz")
    assert services.wanted("quiz") is None
    assert services.open_request("quiz") is None


def test_parallel_kinds_never_read_the_same_pages_at_once(make_doc):
    make_doc("A.pdf", 8)
    reel_run, quiz_run = new_run("reel"), new_run("quiz")
    reel = services.claim(reel_run)
    quiz = services.claim(quiz_run)
    assert claimed_pages(reel) == (1, 4) and claimed_pages(quiz) == (5, 8)  # not the pages being read
    services.save_notes(reel_run, reel.pk, {"title": "T", "testable": True})
    services.complete(quiz_run, quiz.pk, [], [], skipped_reason="test")
    assert services.claim(quiz_run).chunk_id == reel.chunk_id  # once read, the quiz reuses its notes


def test_without_a_drag_order_the_oldest_pdf_goes_first(make_doc):
    from datetime import timedelta

    newer = make_doc("A.pdf", 4)
    older = make_doc("B.pdf", 4)
    Document.objects.filter(pk=older.pk).update(created_at=newer.created_at - timedelta(days=1))
    run = new_run()
    assert services.claim(run).chunk.document == older  # the bottom of a newest-first list
    assert services.claim(run).chunk.document == newer
