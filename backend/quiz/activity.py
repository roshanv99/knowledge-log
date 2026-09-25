"""Daily activity against the daily goals: the data behind the Quiz page tracker.

Days are dates in the learner's time zone (settings.TIME_ZONE). The daily_activity row for a day
is refreshed in the same transaction as the event that changes it (a quiz attempt, a counted reel
watch), so the tracker reads one small row per day however long the history gets.
"""

from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.utils import timezone

from content.models import ReelView
from quiz.models import DailyActivity, QuizAttempt, Settings


def local_day(moment) -> date:
    return timezone.localdate(moment)


def _bounds(day: date):
    """The day's start and end instants in the learner's time zone."""
    start = timezone.make_aware(datetime.combine(day, time.min))
    return start, timezone.make_aware(datetime.combine(day + timedelta(days=1), time.min))


def _counts(day: date) -> tuple[int, int]:
    start, end = _bounds(day)
    answered = {a["question_id"]
                for answers in QuizAttempt.objects.filter(created_at__gte=start, created_at__lt=end)
                .values_list("answers", flat=True) for a in answers}
    watched = ReelView.objects.filter(created_at__gte=start, created_at__lt=end).count()
    return len(answered), watched


def refresh(day: date, goals: Settings | None = None) -> DailyActivity:
    """Recount one day from its events. New rows (and today's) take the current goals; a past
    day keeps the goals it was recorded with."""
    with transaction.atomic():
        row = DailyActivity.objects.select_for_update().filter(day=day).first()
        if row is None or day == timezone.localdate():
            prefs = goals or Settings.load()
            row = row or DailyActivity(day=day)
            row.questions_goal, row.reels_goal = prefs.daily_questions_goal, prefs.daily_reels_goal
        row.questions_attempted, row.reels_watched = _counts(day)
        row.questions_met = row.questions_attempted >= row.questions_goal
        row.reels_met = row.reels_watched >= row.reels_goal
        row.save()
    return row


def rebuild(goals: Settings | None = None) -> int:
    """Recompute every day that has any event. Days without a stored goal get today's goals."""
    days = {local_day(t) for t in QuizAttempt.objects.values_list("created_at", flat=True)}
    days |= {local_day(t) for t in ReelView.objects.values_list("created_at", flat=True)}
    for day in sorted(days):
        refresh(day, goals)
    return len(days)


def streak(rows: dict[date, DailyActivity], field: str, today: date) -> int:
    """Days in a row with the goal met, ending today, or yesterday while today isn't met yet."""
    day = today if (r := rows.get(today)) and getattr(r, field) else today - timedelta(days=1)
    count = 0
    while (r := rows.get(day)) and getattr(r, field):
        count += 1
        day -= timedelta(days=1)
    return count


def summary(days: int) -> dict:
    today = timezone.localdate()
    since = today - timedelta(days=days - 1)
    prefs = Settings.load()
    shown = {r.day: r for r in DailyActivity.objects.filter(day__gte=since)}
    # Streaks can reach further back than the grid.
    streak_rows = {r.day: r for r in DailyActivity.objects.filter(day__lte=today).order_by("-day")[:400]}
    now = shown.get(today)
    return {
        "today": today,
        "goals": {"questions": prefs.daily_questions_goal, "reels": prefs.daily_reels_goal},
        "today_progress": {"questions": now.questions_attempted if now else 0,
                           "reels": now.reels_watched if now else 0},
        "streaks": {"questions": streak(streak_rows, "questions_met", today),
                    "reels": streak(streak_rows, "reels_met", today)},
        "days": [{"date": r.day, "questions": r.questions_attempted, "reels": r.reels_watched,
                  "questions_goal": r.questions_goal, "reels_goal": r.reels_goal,
                  "questions_met": r.questions_met, "reels_met": r.reels_met}
                 for r in sorted(shown.values(), key=lambda r: r.day)],
    }
