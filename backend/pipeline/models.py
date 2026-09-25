"""Who may run the pipeline, and requests from the app to run it.

Runners pull work over /api/pipeline/* with a bearer token; the server never pushes work to
them and never holds a Claude credential (docs/PIPELINE_DB.md, "Runners and triggering").
"""

import hashlib
import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone

from content.models import GenerationRun, Kind

REQUEST_TTL = timedelta(hours=6)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Runner(models.Model):
    class RunnerKind(models.TextChoices):
        CLAUDE_SESSION = "claude-session"
        API_WORKER = "api-worker"
        CLOUD_ROUTINE = "cloud-routine"  # a scheduled claude.ai routine, not the local Mac runner

    name = models.CharField(max_length=128, unique=True)  # e.g. "kl@macbook"
    kind = models.CharField(max_length=16, choices=RunnerKind)
    token_hash = models.CharField(max_length=64, unique=True)
    enabled = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "runners"

    def __str__(self) -> str:
        return self.name

    def issue_token(self) -> str:
        """Set a fresh token and return it; only its hash is stored."""
        token = "klr_" + secrets.token_urlsafe(32)
        self.token_hash = hash_token(token)
        return token

    # DRF treats request.user as authenticated when this is truthy.
    is_authenticated = True


def _request_expiry():
    return timezone.now() + REQUEST_TTL


class RunRequest(models.Model):
    """ "Run now" from Manage notes. A runner's poll consumes it by starting a run."""

    kind = models.CharField(max_length=16, choices=Kind)
    requested_by = models.CharField(max_length=128, default="app")
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField(default=_request_expiry)
    consumed_by_run = models.ForeignKey(GenerationRun, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name="requests")

    class Meta:
        db_table = "run_requests"
