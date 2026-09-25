from django.urls import path

from content import views

urlpatterns = [
    path("notes", views.notes),
    path("notes/upload", views.upload_note),
    path("notes/<int:document_id>/file", views.remove_note_file),
    path("notes/<int:document_id>", views.update_scope),
    path("notes/<int:document_id>/position", views.move),
    path("notes/<int:document_id>/items", views.note_items),
    path("reels", views.reels),
    path("reels/<int:reel_id>/views", views.reel_view),
    path("media/<path:key>", views.media),
]
