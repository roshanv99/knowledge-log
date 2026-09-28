from django.contrib import admin

from social.models import FollowedAccount, SocialVideo, SocialVideoView


@admin.register(FollowedAccount)
class FollowedAccountAdmin(admin.ModelAdmin):
    list_display = ["handle", "platform", "active", "created_at"]
    list_filter = ["platform", "active"]


@admin.register(SocialVideo)
class SocialVideoAdmin(admin.ModelAdmin):
    list_display = ["title", "platform", "account", "status", "published_at"]
    list_filter = ["platform", "status"]


@admin.register(SocialVideoView)
class SocialVideoViewAdmin(admin.ModelAdmin):
    list_display = ["social_video", "created_at"]
