"""Sets link to questions through quiz_set_questions, and each set records its pass (cycle) through
the question pool. Copies today's links from questions.set before that column goes (content 0009)."""

import django.db.models.deletion
from django.db import migrations, models


def copy_links(apps, schema_editor):
    Question = apps.get_model("content", "Question")
    QuizSetQuestion = apps.get_model("quiz", "QuizSetQuestion")
    rows, position = [], {}
    for q in Question.objects.filter(set__isnull=False).order_by("set_id", "id"):
        position[q.set_id] = position.get(q.set_id, -1) + 1
        rows.append(QuizSetQuestion(quiz_set_id=q.set_id, question_id=q.pk, position=position[q.set_id]))
    QuizSetQuestion.objects.bulk_create(rows)


class Migration(migrations.Migration):

    dependencies = [
        ("quiz", "0004_daily_activity"),
        ("content", "0008_daily_activity"),
    ]

    operations = [
        migrations.AddField("quizset", "cycle", models.IntegerField(default=1)),
        migrations.AddField("settings", "question_cycle", models.IntegerField(default=1)),
        migrations.CreateModel(
            name="QuizSetQuestion",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position", models.IntegerField()),
                ("question", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="set_items",
                                               to="content.question")),
                ("quiz_set", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="items",
                                               to="quiz.quizset")),
            ],
            options={"db_table": "quiz_set_questions", "ordering": ["position"]},
        ),
        migrations.AddConstraint("quizsetquestion", models.UniqueConstraint(
            fields=("quiz_set", "question"), name="quiz_set_questions_uniq")),
        migrations.RunPython(copy_links, migrations.RunPython.noop),
    ]
