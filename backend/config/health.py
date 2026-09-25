from django.http import JsonResponse


def health(request):
    """Liveness only (no DB round-trip) — used by the Docker healthcheck and, unauthenticated,
    by the app nginx so the edge gateway's own health probe doesn't need a session."""
    return JsonResponse({"status": "ok"})
