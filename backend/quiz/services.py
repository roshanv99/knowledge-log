"""Quiz rules: building each day's set from in-scope questions, and scoring attempts.

Sets are built on the day they're first asked for, from questions that are in the learner's
study scope and not yet used in the current cycle. When none are left, a new cycle starts and
every in-scope question is available again (old sets keep theirs). Changing the scope rebuilds
today's set unless it has been attempted; past sets that were never attempted hand their
questions back to the pool.
"""

import random
from dataclasses import dataclass
from datetime import date
from typing import Literal

from django.db import transaction
from django.utils import timezone

from content.models import Question
from content.notes import questions_in_scope
from quiz import activity
from quiz.models import QuizAttempt, QuizSet, QuizSetQuestion, Settings


class InvalidAnswers(ValueError):
    pass


def _release(quiz_set: QuizSet) -> None:
    quiz_set.delete()  # its quiz_set_questions rows go with it, so the questions are unused again


@transaction.atomic
def build_set(day: date, size: int | None = None) -> QuizSet | None:
    """Create the set for `day` from in-scope questions not yet used this cycle, oldest first (a short
    set if few remain). If every in-scope question has been used, start a new cycle."""
    prefs = Settings.objects.select_for_update().get(pk=Settings.load().pk)
    size = size or prefs.questions_per_set
    in_scope = questions_in_scope(Question.objects.order_by("created_at", "id"))
    if not in_scope:
        return None
    used = set(QuizSetQuestion.objects.filter(quiz_set__cycle=prefs.question_cycle)
               .values_list("question_id", flat=True))
    pool = [q for q in in_scope if q.pk not in used]
    if not pool:  # everything has had its turn: start again
        prefs.question_cycle += 1
        prefs.save(update_fields=["question_cycle"])
        pool = in_scope
    quiz_set = QuizSet.objects.create(available_on=day, cycle=prefs.question_cycle)
    QuizSetQuestion.objects.bulk_create(
        QuizSetQuestion(quiz_set=quiz_set, question=q, position=i) for i, q in enumerate(pool[:size]))
    return quiz_set


def todays_set(today: date | None = None) -> QuizSet | None:
    """Today's set, building it if needed; if nothing is left to build from, the latest unpassed set."""
    today = today or timezone.localdate()
    for stale in QuizSet.objects.filter(available_on__lt=today, attempts__isnull=True):
        _release(stale)
    current = QuizSet.objects.filter(available_on=today).first()
    if current:
        return current
    return build_set(today) or (
        QuizSet.objects.filter(available_on__lt=today).exclude(attempts__passed=True)
        .order_by("-available_on").first())


RebuildOutcome = Literal["rebuilt", "started", "empty"]


@transaction.atomic
def rebuild_todays_set(today: date | None = None) -> RebuildOutcome:
    """Rebuild today's set from the current scope, unless it has already been attempted."""
    today = today or timezone.localdate()
    current = QuizSet.objects.filter(available_on=today).first()
    if current and current.attempts.exists():
        return "started"
    if current:
        _release(current)
    return "rebuilt" if build_set(today) else "empty"


def empty_reason() -> str:
    """Why there is no quiz: nothing generated yet, or nothing in the learner's scope.
    (Used-up questions never empty the quiz: a new cycle starts.)"""
    if not Question.objects.exists():
        return "no_questions"
    return "nothing_in_scope"


def practice_question(exclude: set[int]) -> tuple[Question | None, int]:
    """A random in-scope question for extra practice, avoiding the ones just seen when possible.
    Nothing is recorded. Returns the question (None if nothing is in scope) and the pool size."""
    pool = questions_in_scope(Question.objects.select_related("chunk__document"))
    fresh = [q for q in pool if q.pk not in exclude] or pool
    return (random.choice(fresh) if fresh else None), len(pool)


@dataclass
class Score:
    correct: int
    total: int
    results: list[dict]


def score_answers(quiz_set: QuizSet, answers: list[dict]) -> Score:
    questions = {q.id: q for q in quiz_set.questions.all()}
    chosen = {}
    for answer in answers:
        qid, choice = answer.get("question_id"), answer.get("choice")
        if qid not in questions:
            raise InvalidAnswers(f"question {qid} is not in this quiz")
        if qid in chosen:
            raise InvalidAnswers(f"question {qid} answered twice")
        if not isinstance(choice, int) or not 0 <= choice < len(questions[qid].options):
            raise InvalidAnswers(f"choice for question {qid} is out of range")
        chosen[qid] = choice
    if missing := set(questions) - set(chosen):
        raise InvalidAnswers(f"unanswered questions: {sorted(missing)}")
    results = [{"question_id": qid, "choice": chosen[qid], "correct_index": q.correct_index,
                "is_correct": chosen[qid] == q.correct_index} for qid, q in questions.items()]
    return Score(sum(r["is_correct"] for r in results), len(results), results)


def record_attempt(quiz_set: QuizSet, answers: list[dict]) -> tuple[QuizAttempt, list[dict]]:
    score = score_answers(quiz_set, answers)
    pass_pct = Settings.load().pass_pct
    attempt = QuizAttempt.objects.create(
        quiz_set=quiz_set,
        answers=[{"question_id": r["question_id"], "choice": r["choice"]} for r in score.results],
        correct=score.correct, total=score.total,
        score_pct=round(100 * score.correct / score.total),
        pass_pct=pass_pct,
        # Compare exactly, not via the rounded percentage.
        passed=score.correct * 100 >= pass_pct * score.total,
    )
    activity.refresh(activity.local_day(attempt.created_at))
    return attempt, score.results
