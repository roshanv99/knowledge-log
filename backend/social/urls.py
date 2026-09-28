from django.urls import path

from social import views

urlpatterns = [
    path("social/accounts", views.accounts),
    path("social/accounts/<int:account_id>", views.account_detail),
    path("social/accounts/<int:account_id>/videos", views.report_videos),
    path("social/videos", views.videos),
    path("social/videos/<int:video_id>/views", views.video_view),
]
