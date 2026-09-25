from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0008_daily_activity"),
        ("quiz", "0005_set_questions"),  # the links are copied first
    ]

    operations = [
        migrations.RemoveField("question", "set"),
    ]
