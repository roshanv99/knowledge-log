from rest_framework import serializers

from social.models import FollowedAccount, SocialVideo


class FollowedAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = FollowedAccount
        fields = ["id", "platform", "handle", "channel_id", "active", "created_at"]
        read_only_fields = ["id", "channel_id", "created_at"]


class FollowedAccountInputSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=FollowedAccount.Platform.choices)
    handle = serializers.CharField(max_length=200, trim_whitespace=True)


class SocialVideoSerializer(serializers.ModelSerializer):
    account_handle = serializers.CharField(source="account.handle", read_only=True)
    views = serializers.IntegerField(source="view_count", read_only=True)

    class Meta:
        model = SocialVideo
        fields = ["id", "platform", "account_handle", "url", "embed_url", "title", "description",
                  "published_at", "views"]


class SocialVideoReportSerializer(serializers.Serializer):
    """One find from the discovery scraper (pipeline/kl/social/discover.py)."""

    external_id = serializers.CharField(max_length=200)
    url = serializers.URLField(max_length=500)
    embed_url = serializers.URLField(max_length=500)
    title = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")
    published_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
