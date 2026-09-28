"""The Following feed: accounts the learner has chosen to see reels from.

Discovery happens outside Django (pipeline/kl/social/), an unofficial scraper that reports what
it finds through this app's API. Django never scrapes or embeds video itself — it just stores
what was found and hands the learner's app an embed_url to play.
"""

from django.db import models
from django.utils import timezone


class FollowedAccount(models.Model):
    class Platform(models.TextChoices):
        YOUTUBE = "youtube"
        INSTAGRAM = "instagram"

    platform = models.CharField(max_length=16, choices=Platform)
    handle = models.CharField(max_length=200)
    # Resolved on first successful scrape (a YouTube channel id); left blank until then.
    channel_id = models.CharField(max_length=200, blank=True, default="")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "followed_accounts"
        constraints = [models.UniqueConstraint(fields=["platform", "handle"], name="followed_accounts_platform_handle_uniq")]

    def __str__(self) -> str:
        return f"{self.platform}:{self.handle}"


class SocialVideo(models.Model):
    """One reel/short discovered from a followed account."""

    class Label(models.TextChoices):
        EDUCATIONAL = "educational"
        SPAM = "spam"
        UNSURE = "unsure"

    class Status(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"

    account = models.ForeignKey(FollowedAccount, on_delete=models.CASCADE, related_name="videos")
    platform = models.CharField(max_length=16, choices=FollowedAccount.Platform)
    external_id = models.CharField(max_length=200)
    url = models.URLField(max_length=500)
    embed_url = models.URLField(max_length=500)
    title = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    published_at = models.DateTimeField(null=True, blank=True)
    # Unused for now: the account list is already curated, so every discovered video defaults to
    # approved. Kept for a future classifier (docs/PLAN.md) rather than added speculatively now.
    label = models.CharField(max_length=16, choices=Label, default=Label.UNSURE)
    confidence = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status, default=Status.APPROVED)
    discovered_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "social_videos"
        constraints = [models.UniqueConstraint(fields=["platform", "external_id"], name="social_videos_platform_external_id_uniq")]
        indexes = [models.Index(fields=["published_at"], name="social_videos_published_idx")]

    def __str__(self) -> str:
        return self.title[:80] or self.url


class SocialVideoView(models.Model):
    """One counted watch, the Following-feed equivalent of content.ReelView."""

    social_video = models.ForeignKey(SocialVideo, on_delete=models.CASCADE, related_name="views")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "social_video_views"
        indexes = [models.Index(fields=["created_at"], name="social_video_views_created_idx")]
