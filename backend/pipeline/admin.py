from django.contrib import admin

from pipeline.models import Runner, RunRequest


@admin.register(Runner)
class RunnerAdmin(admin.ModelAdmin):
    list_display = ["name", "kind", "enabled", "last_seen_at"]
    exclude = ["token_hash"]


@admin.register(RunRequest)
class RunRequestAdmin(admin.ModelAdmin):
    list_display = ["id", "kind", "requested_by", "created_at", "expires_at", "consumed_by_run"]
