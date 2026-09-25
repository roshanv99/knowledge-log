"""Manage notes lists newest PDFs first and the pipeline works from the bottom up.

Rewrite every priority from the date each PDF was added (newest = 0, at the top), so the oldest
PDF, the one already in progress, sits at the bottom and is worked on first.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    Document = apps.get_model("content", "Document")
    NoteScope = apps.get_model("content", "NoteScope")
    for priority, document in enumerate(Document.objects.order_by("-created_at", "path")):
        scope, _ = NoteScope.objects.get_or_create(document=document)
        scope.priority = priority
        scope.save(update_fields=["priority"])


class Migration(migrations.Migration):

    dependencies = [
        ("content", "0006_reel_views"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
