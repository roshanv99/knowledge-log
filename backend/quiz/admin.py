from django.contrib import admin

from quiz.models import QuizAttempt, QuizSet, Settings


class AttemptInline(admin.TabularInline):
    model = QuizAttempt
    extra = 0
    fields = ["created_at", "correct", "total", "score_pct", "pass_pct", "passed"]
    readonly_fields = fields


@admin.register(QuizSet)
class QuizSetAdmin(admin.ModelAdmin):
    list_display = ["available_on", "passed"]
    inlines = [AttemptInline]


@admin.register(Settings)
class SettingsAdmin(admin.ModelAdmin):
    list_display = ["pass_pct", "questions_per_set"]
