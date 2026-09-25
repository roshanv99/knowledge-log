from django.urls import path

from pipeline import views

urlpatterns = [
    # Runners (runner token).
    path("pipeline/wanted", views.wanted),
    path("pipeline/runs", views.start_run),
    path("pipeline/runs/<int:run_id>/claim", views.claim),
    path("pipeline/runs/<int:run_id>/finish", views.finish),
    path("pipeline/tasks/<int:task_id>/heartbeat", views.heartbeat),
    path("pipeline/tasks/<int:task_id>/notes", views.notes),
    path("pipeline/tasks/<int:task_id>/complete", views.complete),
    path("pipeline/tasks/<int:task_id>/fail", views.fail),
    path("pipeline/tasks/<int:task_id>/media", views.media),
    path("pipeline/notes/sync", views.sync_notes),
    # Manage notes.
    path("pipeline/status", views.pipeline_status),
    path("pipeline/requests", views.request_run),
    path("pipeline/tasks/<int:task_id>/retry", views.retry),
]
