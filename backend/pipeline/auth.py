"""Runner authentication: `Authorization: Bearer klr_…`, a token scoped to /api/pipeline/*.

Tokens are issued by `manage.py runner_token <name>`; only their SHA-256 is stored.
"""

from datetime import timedelta

from django.utils import timezone
from rest_framework import authentication, exceptions, permissions

from pipeline.models import Runner, hash_token

SEEN_EVERY = timedelta(seconds=30)  # don't write last_seen_at on every call


class RunnerTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode(errors="replace").split()
        if not header or header[0] != self.keyword:
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed("Malformed runner token header.")
        runner = Runner.objects.filter(token_hash=hash_token(header[1]), enabled=True).first()
        if runner is None:
            raise exceptions.AuthenticationFailed("Unknown or disabled runner token.")
        now = timezone.now()
        if runner.last_seen_at is None or now - runner.last_seen_at > SEEN_EVERY:
            Runner.objects.filter(pk=runner.pk).update(last_seen_at=now)
        return runner, header[1]

    def authenticate_header(self, request):
        return self.keyword


class IsRunner(permissions.BasePermission):
    message = "A runner token is required."

    def has_permission(self, request, view):
        return isinstance(request.user, Runner)
