from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

from content.models import Chunk, Document, GenerationTask, NoteScope, Question
from quiz.models import QuizAttempt, QuizSet, Settings
from quiz.services import build_set, rebuild_todays_set, todays_set

TODAY = date(2026, 9, 23)
pytestmark = pytest.mark.django_db


def make_questions(n: int, pages=lambda i: [i + 1], filename="Notes.pdf") -> list[Question]:
    document = Document.objects.create(file_hash=filename, filename=filename, page_count=50)
    chunk = Chunk.objects.create(document=document, page_start=1, page_end=50, status="read", title="Topic")
    task = GenerationTask.objects.create(chunk=chunk, kind="quiz", status="done")
    return [Question.objects.create(chunk=chunk, task=task, stem=f"Q{i}?", options=["a", "b", "c", "d"],
                                    correct_index=i % 4, explanation="e", source_pages=pages(i), difficulty="easy")
            for i in range(n)]


def answers(quiz_set: QuizSet, n_correct: int) -> list[dict]:
    out = []
    for i, q in enumerate(quiz_set.questions.order_by("id")):
        choice = q.correct_index if i < n_correct else (q.correct_index + 1) % 4
        out.append({"question_id": q.id, "choice": choice})
    return out


def attempt(quiz_set: QuizSet, passed: bool) -> None:
    QuizAttempt.objects.create(quiz_set=quiz_set, answers=[], correct=10 if passed else 0, total=10,
                               score_pct=100 if passed else 0, pass_pct=70, passed=passed)


def test_todays_set_is_built_on_the_day_from_unused_questions():
    make_questions(25)
    first = todays_set(TODAY)
    assert first.available_on == TODAY and first.questions.count() == 10
    assert todays_set(TODAY) == first  # asking again returns the same set
    attempt(first, passed=True)
    second = todays_set(TODAY + timedelta(days=1))
    assert second.questions.count() == 10
    assert not set(first.questions.values_list("id", flat=True)) & set(second.questions.values_list("id", flat=True))


def test_short_set_when_few_questions_remain():
    make_questions(4)
    assert todays_set(TODAY).questions.count() == 4


def test_unattempted_past_set_returns_its_questions_to_the_pool():
    make_questions(10)
    missed = build_set(TODAY - timedelta(days=1))
    current = todays_set(TODAY)
    assert not QuizSet.objects.filter(pk=missed.pk).exists()
    assert current.questions.count() == 10


def test_unattempted_past_set_is_released_even_when_todays_set_exists():
    make_questions(20)
    missed = build_set(TODAY - timedelta(days=1))
    current = build_set(TODAY)
    assert todays_set(TODAY) == current
    assert not QuizSet.objects.filter(pk=missed.pk).exists()
    assert Question.objects.filter(set_items__isnull=True).count() == 10


def test_when_every_question_is_used_a_new_cycle_starts():
    questions = make_questions(10)
    old = build_set(TODAY - timedelta(days=2))
    attempt(old, passed=False)
    fresh = todays_set(TODAY)  # nothing unused is left: the pool starts again
    assert fresh != old and fresh.cycle == old.cycle + 1 == Settings.load().question_cycle
    assert [q.pk for q in fresh.questions.order_by("set_items__position")] == [q.pk for q in questions]
    assert old.questions.count() == 10  # history keeps its questions


def test_a_short_set_before_the_pool_starts_again():
    make_questions(13)
    first = build_set(TODAY - timedelta(days=1))
    attempt(first, passed=True)
    assert todays_set(TODAY).questions.count() == 3  # the 3 left this cycle
    assert Settings.load().question_cycle == 1


def test_practice_draws_randomly_from_scope_and_records_nothing():
    questions = make_questions(3, pages=lambda i: [i + 1], filename="A.pdf")
    other = make_questions(2, filename="B.pdf")
    NoteScope.objects.update_or_create(document=other[0].chunk.document, defaults={"selected": False})
    NoteScope.objects.update_or_create(document=questions[0].chunk.document, defaults={"page_from": 1, "page_to": 2})
    client = APIClient()
    seen = {client.get("/api/quiz/practice").data["question"]["id"] for _ in range(40)}
    assert seen == {questions[0].pk, questions[1].pk}  # ticked PDF, inside its page range only
    data = client.get("/api/quiz/practice", {"exclude": str(questions[0].pk)}).data
    assert data["question"]["id"] == questions[1].pk and data["pool"] == 2
    # Everything excluded: repeats are allowed rather than nothing.
    assert client.get("/api/quiz/practice", {"exclude": f"{questions[0].pk},{questions[1].pk}"}).data["question"]
    assert client.get("/api/quiz/practice", {"exclude": "x"}).status_code == 400
    assert QuizAttempt.objects.count() == 0 and QuizSet.objects.count() == 0
    NoteScope.objects.update(selected=False)
    assert client.get("/api/quiz/practice").data == {"question": None, "pool": 0}


def test_scope_filters_questions_by_selection_type_and_pages():
    make_questions(10)  # pages 1..10
    scope = NoteScope.objects.create(document=Document.objects.get(), page_from=3, page_to=6)
    assert sorted(q.source_pages[0] for q in todays_set(TODAY).questions.all()) == [3, 4, 5, 6]

    scope.include_quiz = False
    scope.save()
    assert rebuild_todays_set(TODAY) == "empty"


def test_question_spanning_outside_range_is_excluded():
    make_questions(3, pages=lambda i: [i + 1, i + 2])  # [1,2], [2,3], [3,4]
    NoteScope.objects.create(document=Document.objects.get(), page_from=1, page_to=3)
    assert sorted(q.stem for q in todays_set(TODAY).questions.all()) == ["Q0?", "Q1?"]


def test_rebuild_only_before_the_set_is_attempted():
    make_questions(20)
    first = todays_set(TODAY)
    assert rebuild_todays_set(TODAY) == "rebuilt"
    assert not QuizSet.objects.filter(pk=first.pk).exists()
    attempt(todays_set(TODAY), passed=False)
    assert rebuild_todays_set(TODAY) == "started"


def test_attempt_scoring_against_pass_mark():
    make_questions(10)
    Settings.objects.create(pk=1, pass_pct=70)
    quiz_set = build_set(TODAY)
    client = APIClient()

    failed = client.post(f"/api/quiz/sets/{quiz_set.id}/attempts", {"answers": answers(quiz_set, 6)}, format="json")
    assert failed.status_code == 201
    assert (failed.data["correct"], failed.data["passed"], failed.data["score_pct"]) == (6, False, 60)

    passed = client.post(f"/api/quiz/sets/{quiz_set.id}/attempts", {"answers": answers(quiz_set, 7)}, format="json")
    assert passed.data["passed"] is True
    assert sum(r["is_correct"] for r in passed.data["results"]) == 7


def test_attempt_must_answer_every_question_once():
    make_questions(10)
    quiz_set = build_set(TODAY)
    partial = answers(quiz_set, 10)[:9]
    response = APIClient().post(f"/api/quiz/sets/{quiz_set.id}/attempts", {"answers": partial}, format="json")
    assert response.status_code == 400
    assert "unanswered" in response.data["detail"]


def test_today_explains_an_empty_quiz():
    client = APIClient()
    assert client.get("/api/quiz/today").data["empty_reason"] == "no_questions"
    make_questions(3)
    NoteScope.objects.create(document=Document.objects.get(), selected=False)
    assert client.get("/api/quiz/today").data["empty_reason"] == "nothing_in_scope"


def test_settings_update_validates_range():
    client = APIClient()
    assert client.put("/api/settings", {"pass_pct": 80}, format="json").data["pass_pct"] == 80
    assert client.put("/api/settings", {"pass_pct": 150}, format="json").status_code == 400
    assert Settings.load().pass_pct == 80
