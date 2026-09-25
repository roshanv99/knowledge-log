"""Notes and what the generation pipeline produced from them.

Django owns this schema. Pipelines never touch the database directly: they claim work and
report results through the pipeline API (backend/pipeline/, docs/PIPELINE_DB.md).
"""

from django.db import models
from django.utils import timezone


class Document(models.Model):
    file_hash = models.CharField(max_length=64, unique=True)
    path = models.TextField()
    filename = models.CharField(max_length=512)
    page_count = models.IntegerField()
    # Highest page N such that every page 1..N is in a finished chunk.
    last_processed_page = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    # Set by the pipeline's notes-sync report (pipeline/services.py::sync_notes), not computed
    # live here — the backend and the notes folder are on different machines once deployed.
    # Defaults true so a document looks normal until the pipeline's first sync says otherwise.
    available = models.BooleanField(default=True)
    folder = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "documents"

    def __str__(self) -> str:
        return self.filename


class Chunk(models.Model):
    """A page window of a PDF plus the notes read from it, shared by every content type."""

    class Status(models.TextChoices):
        UNREAD = "unread"
        READ = "read"
        UNREADABLE = "unreadable"  # cover, table of contents, blank pages

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    page_start = models.IntegerField()
    page_end = models.IntegerField()
    status = models.CharField(max_length=16, choices=Status, default=Status.UNREAD)
    title = models.TextField(null=True, blank=True)
    notes = models.JSONField(null=True, blank=True)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "chunks"
        constraints = [models.UniqueConstraint(fields=["document", "page_start", "page_end"],
                                               name="chunks_document_pages_uniq")]

    def __str__(self) -> str:
        return f"{self.document} p{self.page_start}-{self.page_end}"

    @property
    def pages(self) -> list[int]:
        return list(range(self.page_start, self.page_end + 1))


class Kind(models.TextChoices):
    QUIZ = "quiz"
    REEL = "reel"


class GenerationRun(models.Model):
    """One runner session: it claims tasks of one kind until it stops."""

    kind = models.CharField(max_length=16, choices=Kind)
    runner = models.CharField(max_length=128)  # e.g. "kl@macbook", "claude-session"
    params = models.JSONField(default=dict)
    started_at = models.DateTimeField(default=timezone.now)
    # Every runner call touches this; a run silent for longer than the lease is abandoned.
    last_seen_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    stop_reason = models.CharField(max_length=32, null=True, blank=True)
    tasks_done = models.IntegerField(default=0)
    questions_made = models.IntegerField(default=0)
    reels_made = models.IntegerField(default=0)
    usage = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "generation_runs"
        constraints = [models.UniqueConstraint(fields=["kind"], condition=models.Q(finished_at__isnull=True),
                                               name="generation_runs_one_active_per_kind")]


class GenerationTask(models.Model):
    """Produce one kind of output for one chunk. Claimed by a run under a renewable lease."""

    class Status(models.TextChoices):
        PENDING = "pending"
        CLAIMED = "claimed"
        DONE = "done"
        FAILED = "failed"
        SKIPPED = "skipped"  # nothing worth making from these pages

    chunk = models.ForeignKey(Chunk, on_delete=models.CASCADE, related_name="tasks")
    kind = models.CharField(max_length=16, choices=Kind)
    reel_style = models.CharField(max_length=16, null=True, blank=True)  # character | manim | diagram
    status = models.CharField(max_length=16, choices=Status, default=Status.PENDING)
    attempts = models.IntegerField(default=0)
    run = models.ForeignKey(GenerationRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks")
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    stage = models.CharField(max_length=32, null=True, blank=True)
    detail = models.TextField(null=True, blank=True)
    review_log = models.JSONField(default=list)
    error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "generation_tasks"
        constraints = [models.UniqueConstraint(fields=["chunk", "kind"], name="generation_tasks_chunk_kind_uniq")]

    def __str__(self) -> str:
        return f"{self.kind} {self.chunk}"


class Question(models.Model):
    chunk = models.ForeignKey(Chunk, on_delete=models.CASCADE, related_name="questions")
    task = models.ForeignKey(GenerationTask, on_delete=models.CASCADE, related_name="questions")
    run = models.ForeignKey(GenerationRun, on_delete=models.SET_NULL, null=True, blank=True,
                            related_name="questions")
    stem = models.TextField()
    options = models.JSONField()
    correct_index = models.IntegerField()
    explanation = models.TextField()
    source_pages = models.JSONField()
    difficulty = models.CharField(max_length=16)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "questions"

    def __str__(self) -> str:
        return self.stem[:80]


class Reel(models.Model):
    """A generated video. Like questions, it records the note pages it teaches."""

    chunk = models.ForeignKey(Chunk, on_delete=models.CASCADE, related_name="reels")
    task = models.ForeignKey(GenerationTask, on_delete=models.CASCADE, null=True, blank=True, related_name="reels")
    kind = models.CharField(max_length=16)  # character | manim | diagram
    title = models.TextField()
    key_point = models.TextField(null=True, blank=True)  # the one sentence the reel teaches
    storage_key = models.TextField()  # path under MEDIA_ROOT, e.g. reels/task-12.mp4
    duration_s = models.FloatField(null=True, blank=True)
    source_pages = models.JSONField(default=list)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "reels"


class ReelView(models.Model):
    """One counted watch: the learner watched at least 80% of the reel in one play-through."""

    reel = models.ForeignKey(Reel, on_delete=models.CASCADE, related_name="views")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "reel_views"
        indexes = [models.Index(fields=["created_at"], name="reel_views_created_idx")]


class NoteScope(models.Model):
    """What the learner studies from one PDF: whether it's on, which pages, and for what.

    Kept apart from `documents` because the pipeline shares that table. Also caches the
    file's size and mtime so the notes folder can be rescanned without rehashing every PDF.
    """

    document = models.OneToOneField(Document, on_delete=models.CASCADE, primary_key=True, related_name="scope")
    selected = models.BooleanField(default=True)
    page_from = models.IntegerField(default=1)
    # None means "through the last page", so the range grows if the PDF gains pages.
    page_to = models.IntegerField(null=True, blank=True)
    include_quiz = models.BooleanField(default=True)
    include_reels = models.BooleanField(default=True)
    # Position in Manage notes, top first (drag to reorder). New PDFs go on top; the pipeline
    # works from the bottom up (content/notes.py `list_order`).
    priority = models.IntegerField(default=0)
    file_size = models.BigIntegerField(null=True, blank=True)
    file_mtime = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "note_scopes"

    @property
    def last_page(self) -> int:
        return self.page_to or self.document.page_count

    def covers(self, pages: list[int]) -> bool:
        """True when every page an item comes from lies inside the chosen range."""
        return bool(pages) and all(self.page_from <= p <= self.last_page for p in pages)
