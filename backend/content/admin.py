from django.contrib import admin

from content.models import Chunk, Document, GenerationRun, GenerationTask, NoteScope, Question, Reel, ReelView


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ["filename", "page_count", "last_processed_page", "created_at"]


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ["document", "page_start", "page_end", "status", "title"]
    list_filter = ["status", "document"]


@admin.register(GenerationRun)
class GenerationRunAdmin(admin.ModelAdmin):
    list_display = ["id", "kind", "runner", "stop_reason", "tasks_done", "questions_made", "started_at", "finished_at"]
    list_filter = ["kind", "stop_reason"]


@admin.register(GenerationTask)
class GenerationTaskAdmin(admin.ModelAdmin):
    list_display = ["id", "kind", "chunk", "status", "attempts", "stage", "lease_expires_at", "updated_at"]
    list_filter = ["kind", "status"]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ["stem", "difficulty", "chunk"]
    list_filter = ["difficulty", "quiz_sets"]


@admin.register(NoteScope)
class NoteScopeAdmin(admin.ModelAdmin):
    list_display = ["document", "selected", "page_from", "page_to", "include_quiz", "include_reels", "priority"]


@admin.register(Reel)
class ReelAdmin(admin.ModelAdmin):
    list_display = ["title", "kind", "chunk", "source_pages"]


@admin.register(ReelView)
class ReelViewAdmin(admin.ModelAdmin):
    list_display = ["reel", "created_at"]
