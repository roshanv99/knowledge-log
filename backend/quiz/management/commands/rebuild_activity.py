"""Recompute the daily_activity summary from quiz attempts and reel views."""

from django.core.management.base import BaseCommand

from quiz import activity


class Command(BaseCommand):
    help = "Rebuild daily_activity from the raw events (quiz_attempts, reel_views)."

    def handle(self, *args, **options):
        self.stdout.write(f"Rebuilt {activity.rebuild()} days.")
