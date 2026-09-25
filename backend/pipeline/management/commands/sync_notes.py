"""Record which PDFs are in KL_NOTES_DIR right now (content/notes.py). Run by deploy/notes-sync.sh
after it mirrors the Google Drive notes folder onto the server."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from content import notes
from pipeline import services


class Command(BaseCommand):
    help = "Scan KL_NOTES_DIR and mark each known PDF available or not."

    def handle(self, *args, **options):
        notes_dir = settings.KL_NOTES_DIR
        # A missing folder is a broken mount, not "every PDF was deleted": refuse rather than
        # mark everything unavailable.
        if not notes_dir.is_dir():
            raise CommandError(f"{notes_dir} is not a directory; nothing synced.")
        result = services.sync_notes(notes.scan(notes_dir), str(notes_dir))
        self.stdout.write(f"{result['available']} available, {result['registered']} new, "
                          f"{result['went_unavailable']} no longer found.")
