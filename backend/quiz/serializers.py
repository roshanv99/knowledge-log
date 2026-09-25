from rest_framework import serializers

from content.models import Question
from quiz.models import QuizAttempt, QuizSet, Settings


class QuestionSerializer(serializers.ModelSerializer):
    topic = serializers.CharField(source="chunk.title", default=None)
    document = serializers.CharField(source="chunk.document.filename")

    class Meta:
        model = Question
        # The answer ships with the question: the app gives instant feedback, and this is a
        # personal study tool. The server still scores every attempt itself.
        fields = ["id", "stem", "options", "correct_index", "explanation", "source_pages",
                  "difficulty", "topic", "document"]


class AttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuizAttempt
        fields = ["id", "correct", "total", "score_pct", "pass_pct", "passed", "answers", "created_at"]


class QuizSetSerializer(serializers.ModelSerializer):
    questions = serializers.SerializerMethodField()
    attempts = AttemptSerializer(many=True, read_only=True)
    passed = serializers.BooleanField(read_only=True)

    class Meta:
        model = QuizSet
        fields = ["id", "available_on", "passed", "questions", "attempts"]

    def get_questions(self, obj: QuizSet):
        items = obj.items.select_related("question__chunk__document").order_by("position")
        return QuestionSerializer([item.question for item in items], many=True).data


class AnswerSerializer(serializers.Serializer):
    question_id = serializers.IntegerField()
    choice = serializers.IntegerField()


class AttemptInputSerializer(serializers.Serializer):
    answers = AnswerSerializer(many=True)


class SettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Settings
        fields = ["pass_pct", "questions_per_set", "pipeline_enabled", "pipeline_auto", "max_tasks_per_run",
                  "max_runs_per_day", "reel_limit", "daily_questions_goal", "daily_reels_goal"]
