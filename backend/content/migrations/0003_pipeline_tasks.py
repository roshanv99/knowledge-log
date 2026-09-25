"""Chunks become shared reading units; per-kind generation tasks carry the review state.

Order matters: add the new tables and columns, copy the data across, then drop the old
columns (docs/PIPELINE_DB.md, "Data migration"). Learner data (quiz sets, attempts,
settings, note scopes) is untouched.
"""

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


def forwards(apps, schema_editor):
    Chunk = apps.get_model("content", "Chunk")
    GenerationRun = apps.get_model("content", "GenerationRun")
    GenerationTask = apps.get_model("content", "GenerationTask")
    Question = apps.get_model("content", "Question")

    for run in GenerationRun.objects.all():
        run.kind = "quiz"
        run.runner = "kl-agent-sdk"
        run.params = {"document_id": run.document_id, "page_budget": run.page_budget, "target_mcqs": run.target_mcqs}
        run.tasks_done = run.chunks_done
        run.last_seen_at = run.finished_at or run.started_at
        if run.finished_at is None:  # never finished: close it so it can't block new runs
            run.finished_at, run.stop_reason = run.last_seen_at, run.stop_reason or "abandoned"
        run.save()

    for chunk in Chunk.objects.all():
        old = chunk.status
        chunk.status = {"done": "read", "read": "read", "skipped": "unreadable"}.get(
            old, "read" if chunk.notes else "unread")
        chunk.save(update_fields=["status"])

        questions = Question.objects.filter(chunk=chunk)
        if old == "pending" and not questions.exists():
            continue  # the planner creates the task when it reaches these pages
        latest = questions.order_by("-created_at").first()
        task_status = {"done": "done", "skipped": "skipped", "failed": "failed"}.get(old, "pending")
        finished = chunk.updated_at if task_status in ("done", "skipped", "failed") else None
        task = GenerationTask.objects.create(
            chunk=chunk, kind="quiz", status=task_status, attempts=chunk.attempts,
            run_id=latest.run_id if latest else None, review_log=chunk.review_log or [], error=chunk.error,
            created_at=chunk.updated_at, started_at=finished, finished_at=finished)
        questions.update(task=task)


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0002_notescope_reel"),
    ]

    operations = [
        # New columns and tables.
        migrations.AddField("generationrun", "kind", models.CharField(
            choices=[("quiz", "Quiz"), ("reel", "Reel")], default="quiz", max_length=16), preserve_default=False),
        migrations.AddField("generationrun", "runner", models.CharField(default="", max_length=128),
                            preserve_default=False),
        migrations.AddField("generationrun", "params", models.JSONField(default=dict)),
        migrations.AddField("generationrun", "last_seen_at", models.DateTimeField(default=django.utils.timezone.now)),
        migrations.AddField("generationrun", "tasks_done", models.IntegerField(default=0)),
        migrations.AddField("notescope", "priority", models.IntegerField(default=0)),
        migrations.CreateModel(
            name="GenerationTask",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("quiz", "Quiz"), ("reel", "Reel")], max_length=16)),
                ("reel_style", models.CharField(blank=True, max_length=16, null=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("claimed", "Claimed"), ("done", "Done"),
                                                     ("failed", "Failed"), ("skipped", "Skipped")],
                                            default="pending", max_length=16)),
                ("attempts", models.IntegerField(default=0)),
                ("lease_expires_at", models.DateTimeField(blank=True, null=True)),
                ("stage", models.CharField(blank=True, max_length=32, null=True)),
                ("detail", models.TextField(blank=True, null=True)),
                ("review_log", models.JSONField(default=list)),
                ("error", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("chunk", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tasks",
                                            to="content.chunk")),
                ("run", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                          related_name="tasks", to="content.generationrun")),
            ],
            options={"db_table": "generation_tasks"},
        ),
        migrations.AddConstraint("generationtask", models.UniqueConstraint(
            fields=("chunk", "kind"), name="generation_tasks_chunk_kind_uniq")),
        migrations.AddField("question", "task", models.ForeignKey(
            null=True, on_delete=django.db.models.deletion.CASCADE, related_name="questions",
            to="content.generationtask")),
        migrations.AddField("reel", "task", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="reels",
            to="content.generationtask")),
        migrations.AlterField("question", "run", models.ForeignKey(
            blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="questions",
            to="content.generationrun")),

        migrations.RunPython(forwards, migrations.RunPython.noop),

        # Old columns, now copied into tasks and run params.
        migrations.RemoveField("chunk", "review_log"),
        migrations.RemoveField("chunk", "error"),
        migrations.RemoveField("chunk", "attempts"),
        migrations.AlterField("chunk", "status", models.CharField(
            choices=[("unread", "Unread"), ("read", "Read"), ("unreadable", "Unreadable")],
            default="unread", max_length=16)),
        migrations.RemoveField("generationrun", "document"),
        migrations.RemoveField("generationrun", "page_budget"),
        migrations.RemoveField("generationrun", "target_mcqs"),
        migrations.RemoveField("generationrun", "chunks_done"),
        migrations.AddConstraint("generationrun", models.UniqueConstraint(
            condition=models.Q(finished_at__isnull=True), fields=("kind",),
            name="generation_runs_one_active_per_kind")),
    ]
