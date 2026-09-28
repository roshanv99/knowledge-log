from datetime import timedelta

from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from social.models import FollowedAccount, SocialVideo, SocialVideoView
from social.serializers import (FollowedAccountInputSerializer, FollowedAccountSerializer,
                                SocialVideoReportSerializer, SocialVideoSerializer)


@api_view(["GET", "POST"])
def accounts(request: Request) -> Response:
    if request.method == "POST":
        payload = FollowedAccountInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        account, created = FollowedAccount.objects.get_or_create(
            platform=payload.validated_data["platform"], handle=payload.validated_data["handle"],
            defaults={"active": True})
        return Response(FollowedAccountSerializer(account).data,
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    items = FollowedAccount.objects.order_by("platform", "handle")
    return Response({"accounts": FollowedAccountSerializer(items, many=True).data})


@api_view(["PATCH", "DELETE"])
def account_detail(request: Request, account_id: int) -> Response:
    account = get_object_or_404(FollowedAccount, pk=account_id)
    if request.method == "DELETE":
        account.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if "active" in request.data:
        account.active = bool(request.data["active"])
        account.save(update_fields=["active"])
    return Response(FollowedAccountSerializer(account).data)


@api_view(["POST"])
def report_videos(request: Request, account_id: int) -> Response:
    """The discovery scraper's write path (pipeline/kl/social/discover.py): report what it found
    for one account. Upserts by (platform, external_id), so a repeated sweep never duplicates."""
    account = get_object_or_404(FollowedAccount, pk=account_id)
    payload = SocialVideoReportSerializer(data=request.data.get("videos", []), many=True)
    payload.is_valid(raise_exception=True)
    created = 0
    with transaction.atomic():
        for item in payload.validated_data:
            _, was_created = SocialVideo.objects.update_or_create(
                platform=account.platform, external_id=item["external_id"],
                defaults={"account": account, "url": item["url"], "embed_url": item["embed_url"],
                          "title": item["title"], "description": item["description"],
                          "published_at": item["published_at"]})
            created += was_created
    return Response({"received": len(payload.validated_data), "created": created})


@api_view(["GET"])
def videos(request: Request) -> Response:
    """The Following feed: approved videos from active accounts, newest first."""
    items = (SocialVideo.objects.filter(status=SocialVideo.Status.APPROVED, account__active=True)
             .select_related("account").annotate(view_count=Count("views"))
             .order_by("-published_at", "-discovered_at"))
    return Response({"videos": SocialVideoSerializer(items, many=True).data})


VIEW_DEBOUNCE = timedelta(seconds=10)


@api_view(["POST"])
def video_view(request: Request, video_id: int) -> Response:
    """Count one watch. Following items have no reliable 80%-watched signal (cross-origin
    iframe), so the app sends this on a dwell timer instead (see ui/src/features/reels)."""
    video = get_object_or_404(SocialVideo, pk=video_id)
    with transaction.atomic():
        SocialVideo.objects.select_for_update().filter(pk=video.pk).first()
        last = video.views.order_by("-created_at").first()
        counted = last is None or timezone.now() - last.created_at >= VIEW_DEBOUNCE
        if counted:
            SocialVideoView.objects.create(social_video=video)
    return Response({"views": video.views.count(), "counted": counted},
                    status=status.HTTP_201_CREATED if counted else status.HTTP_200_OK)
