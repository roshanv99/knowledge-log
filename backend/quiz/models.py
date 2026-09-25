from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class QuizSet(models.Model):
    """One day's quiz: a fixed group of questions (built on the day by services.build_set).

    `cycle` is the pass through the question pool the set belongs to: a question is used once per
    cycle, and when every in-scope question has been used a new cycle starts. Old sets keep their
    questions, so quiz history is never rewritten."""

    available_on = models.DateField(unique=True)
    cycle = models.IntegerField(default=1)
    questions = models.ManyToManyField("content.Question", through="QuizSetQuestion", related_name="quiz_sets")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "quiz_sets"
        ordering = ["available_on"]

    def __str__(self) -> str:
        return f"Quiz for {self.available_on}"

    @property
    def passed(self) -> bool:
        return self.attempts.filter(passed=True).exists()


class QuizSetQuestion(models.Model):
    """A question's place in a set. Add a user to QuizSet when the app gets accounts; "used" is then
    per learner automatically, because it is read from these rows."""

    quiz_set = models.ForeignKey(QuizSet, on_delete=models.CASCADE, related_name="items")
    question = models.ForeignKey("content.Question", on_delete=models.CASCADE, related_name="set_items")
    position = models.IntegerField()

    class Meta:
        db_table = "quiz_set_questions"
        ordering = ["position"]
        constraints = [models.UniqueConstraint(fields=["quiz_set", "question"], name="quiz_set_questions_uniq")]


class QuizAttempt(models.Model):
    quiz_set = models.ForeignKey(QuizSet, on_delete=models.CASCADE, related_name="attempts")
    # [{"question_id": int, "choice": int}], choice indexing the question's stored options.
    answers = models.JSONField()
    correct = models.IntegerField()
    total = models.IntegerField()
    score_pct = models.IntegerField()
    # The pass mark in force when this attempt was scored.
    pass_pct = models.IntegerField()
    passed = models.BooleanField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "quiz_attempts"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["created_at"], name="quiz_attempts_created_idx")]


class Settings(models.Model):
    """Single-row learner preferences."""

    pass_pct = models.IntegerField(default=70, validators=[MinValueValidator(10), MaxValueValidator(100)])
    questions_per_set = models.IntegerField(default=10, validators=[MinValueValidator(1), MaxValueValidator(50)])
    # Pipeline switches (docs/PIPELINE_DB.md): a kill switch and caps on how much one day can run.
    pipeline_enabled = models.BooleanField(default=True)
    # Off: runs start only from "Run now". On: the local Mac runner's poll also starts one
    # whenever work is waiting. Separate from pipeline_auto_cloud (a scheduled cloud routine's
    # own switch) so turning one on doesn't silently turn the other on too.
    pipeline_auto = models.BooleanField(default=False)
    pipeline_auto_cloud = models.BooleanField(default=False)
    max_tasks_per_run = models.IntegerField(default=10, validators=[MinValueValidator(1), MaxValueValidator(100)])
    max_runs_per_day = models.IntegerField(default=6, validators=[MinValueValidator(1), MaxValueValidator(48)])
    # Total reels to make (0 = no limit). Reels are costly, so the pipeline stops once there are this many.
    reel_limit = models.IntegerField(default=5, validators=[MinValueValidator(0), MaxValueValidator(1000)])
    # The current pass through the question pool (see QuizSet.cycle).
    question_cycle = models.IntegerField(default=1)
    # Daily goals for the tracker on the Quiz page.
    daily_questions_goal = models.IntegerField(default=10, validators=[MinValueValidator(1), MaxValueValidator(500)])
    daily_reels_goal = models.IntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(100)])

    class Meta:
        db_table = "settings"
        verbose_name_plural = "settings"

    @classmethod
    def load(cls) -> "Settings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class DailyActivity(models.Model):
    """What the learner did on one day (in their time zone), against the goals in force that day.

    A summary kept up to date as things happen (quiz/activity.py); the raw events in quiz_attempts
    and reel_views stay the source of truth, and `manage.py rebuild_activity` recomputes it.
    Goals are copied per day, so changing a goal never rewrites past days. Add a user column and
    make (user, day) unique when the app gets accounts.
    """

    day = models.DateField(unique=True)
    questions_attempted = models.IntegerField(default=0)  # distinct questions answered that day
    reels_watched = models.IntegerField(default=0)  # watches past 80%, rewatches included
    questions_goal = models.IntegerField()
    reels_goal = models.IntegerField()
    questions_met = models.BooleanField(default=False)
    reels_met = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "daily_activity"
        ordering = ["day"]
