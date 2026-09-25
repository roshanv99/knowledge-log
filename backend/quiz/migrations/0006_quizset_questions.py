from django.db import migrations, models


class Migration(migrations.Migration):
    """QuizSet.questions, through the table made in 0005 (no database change)."""

    dependencies = [
        ("quiz", "0005_set_questions"),
        ("content", "0009_remove_question_set"),  # frees the `questions` name the old column used
    ]

    operations = [
        migrations.AddField("quizset", "questions", models.ManyToManyField(
            related_name="quiz_sets", through="quiz.QuizSetQuestion", to="content.question")),
    ]
