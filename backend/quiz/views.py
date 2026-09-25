from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from quiz import activity, services
from quiz.models import QuizSet, Settings
from quiz.serializers import (AttemptInputSerializer, AttemptSerializer, QuestionSerializer, QuizSetSerializer,
                              SettingsSerializer)


@api_view(["GET"])
def today(request: Request) -> Response:
    quiz_set = services.todays_set()
    return Response({
        "quiz_set": QuizSetSerializer(quiz_set).data if quiz_set else None,
        "pass_pct": Settings.load().pass_pct,
        "empty_reason": None if quiz_set else services.empty_reason(),
    })


@api_view(["POST"])
def create_attempt(request: Request, set_id: int) -> Response:
    quiz_set = get_object_or_404(QuizSet, pk=set_id)
    payload = AttemptInputSerializer(data=request.data)
    payload.is_valid(raise_exception=True)
    try:
        attempt, results = services.record_attempt(quiz_set, payload.validated_data["answers"])
    except services.InvalidAnswers as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({**AttemptSerializer(attempt).data, "results": results}, status=status.HTTP_201_CREATED)


@api_view(["GET", "PUT"])
def settings_view(request: Request) -> Response:
    settings = Settings.load()
    if request.method == "PUT":
        serializer = SettingsSerializer(settings, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        if {"daily_questions_goal", "daily_reels_goal"} & request.data.keys():
            activity.refresh(timezone.localdate())  # today follows the new goals; past days keep theirs
    return Response(SettingsSerializer(settings).data)


@api_view(["GET"])
def activity_view(request: Request) -> Response:
    """The daily tracker: goals, today's progress, streaks, and one row per active day."""
    try:
        days = min(max(int(request.query_params.get("days", 182)), 7), 400)
    except ValueError:
        return Response({"detail": "days must be a number."}, status=status.HTTP_400_BAD_REQUEST)
    return Response(activity.summary(days))


@api_view(["GET"])
def practice(request: Request) -> Response:
    """One random question for extra practice once today's quiz is done. Only questions from ticked
    PDFs, with Quiz ticked and pages in range. Not recorded anywhere. `exclude` lists the ids just
    seen (comma-separated) so they don't come straight back."""
    try:
        exclude = {int(i) for i in request.query_params.get("exclude", "").split(",") if i}
    except ValueError:
        return Response({"detail": "exclude must be comma-separated ids."}, status=status.HTTP_400_BAD_REQUEST)
    question, pool = services.practice_question(set(list(exclude)[:200]))
    if question is None:
        return Response({"question": None, "pool": 0})
    return Response({"question": QuestionSerializer(question).data, "pool": pool})
