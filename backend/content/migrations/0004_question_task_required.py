import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0003_pipeline_tasks"),
    ]

    operations = [
        migrations.AlterField("question", "task", models.ForeignKey(
            on_delete=django.db.models.deletion.CASCADE, related_name="questions", to="content.generationtask")),
    ]
