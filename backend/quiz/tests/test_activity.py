from datetime import UTC, datetime, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from content.models import Chunk, Document, GenerationTask, Question, Reel, ReelView
from quiz import activity
from quiz.models import DailyActivity, QuizAttempt, QuizSet, QuizSetQuestion, Settings

pytestmark = pytest.mark.django_db


@pytest.fixture
def quiz_set():
    document = Document.objects.create(file_hash="d", path="/d.pdf", filename="d.pdf", page_count=10)
    chunk = Chunk.objects.create(document=document, page_start=1, page_end=10, status="read")
    task = GenerationTask.objects.create(chunk=chunk, kind="quiz", status="done")
    quiz_set = QuizSet.objects.create(available_on=timezone.localdate())
    for i in range(4):
        q = Question.objects.create(chunk=chunk, task=task, stem=f"Q{i}", options=["a", "b", "c", "d"],
                                    correct_index=0, explanation="e", source_pages=[1], difficulty="easy")
        QuizSetQuestion.objects.create(quiz_set=quiz_set, question=q, position=i)
    return quiz_set


def answer_all(quiz_set, choice=0):
    answers = [{"question_id": q.pk, "choice": choice} for q in quiz_set.questions.all()]
    return APIClient().post(f"/api/quiz/sets/{quiz_set.pk}/attempts", {"answers": answers}, format="json")


def make_reel():
    chunk = Chunk.objects.first()
    return Reel.objects.create(chunk=chunk, kind="manim", title="R", storage_key="reels/x.mp4", source_pages=[1])


def test_retrying_a_set_counts_each_question_once(quiz_set):
    prefs = Settings.load()
    prefs.daily_questions_goal = 4
    prefs.save()
    assert answer_all(quiz_set, choice=1).status_code == 201
    row = DailyActivity.objects.get(day=timezone.localdate())
    assert (row.questions_attempted, row.questions_met) == (4, True)
    answer_all(quiz_set)  # a retry of the same questions
    assert DailyActivity.objects.get().questions_attempted == 4


def test_reel_watches_count_and_goals_are_kept_per_day(quiz_set):
    reel = make_reel()
    assert APIClient().post(f"/api/reels/{reel.pk}/views").status_code == 201
    row = DailyActivity.objects.get()
    assert (row.reels_watched, row.reels_goal, row.reels_met) == (1, 1, True)

    # Raising the goal changes today, but not a day already past.
    yesterday = timezone.localdate() - timedelta(days=1)
    DailyActivity.objects.create(day=yesterday, reels_watched=1, reels_goal=1, reels_met=True, questions_goal=10)
    assert APIClient().put("/api/settings", {"daily_reels_goal": 3}, format="json").status_code == 200
    today = DailyActivity.objects.get(day=timezone.localdate())
    assert (today.reels_goal, today.reels_met) == (3, False)
    assert DailyActivity.objects.get(day=yesterday).reels_met is True


def test_days_follow_the_learners_time_zone(quiz_set, settings):
    settings.TIME_ZONE = "Asia/Kolkata"
    timezone.activate("Asia/Kolkata")
    attempt_time = datetime(2026, 9, 23, 18, 49, tzinfo=UTC)  # 00:19 on 24 Sep, IST
    QuizAttempt.objects.create(quiz_set=quiz_set, answers=[{"question_id": 1, "choice": 0}], correct=1, total=1,
                               score_pct=100, pass_pct=70, passed=True)
    QuizAttempt.objects.update(created_at=attempt_time)
    assert activity.rebuild() == 1
    assert DailyActivity.objects.get().day.isoformat() == "2026-09-24"
    timezone.deactivate()


def test_summary_with_streaks_and_today(quiz_set):
    today = timezone.localdate()
    for back in (1, 2, 4):  # met on the 2 days before today, then a gap
        DailyActivity.objects.create(day=today - timedelta(days=back), questions_attempted=10, questions_goal=10,
                                     questions_met=True, reels_goal=1)
    data = APIClient().get("/api/activity", {"days": 30}).data
    assert data["streaks"] == {"questions": 2, "reels": 0}  # today not done yet: counts back from yesterday
    assert data["today_progress"] == {"questions": 0, "reels": 0}
    assert data["goals"] == {"questions": 10, "reels": 1}
    assert len(data["days"]) == 3

    answer_all(quiz_set)  # 4 of 10 today: not met, so the streak still ends yesterday
    assert APIClient().get("/api/activity").data["streaks"]["questions"] == 2
    prefs = Settings.load()
    prefs.daily_questions_goal = 4
    prefs.save()
    activity.refresh(today)
    assert APIClient().get("/api/activity").data["streaks"]["questions"] == 3
    assert APIClient().get("/api/activity", {"days": "x"}).status_code == 400


def test_rebuild_recounts_from_events(quiz_set):
    answer_all(quiz_set)
    ReelView.objects.create(reel=make_reel())
    DailyActivity.objects.all().delete()
    assert activity.rebuild() == 1
    row = DailyActivity.objects.get()
    assert (row.questions_attempted, row.reels_watched) == (4, 1)
