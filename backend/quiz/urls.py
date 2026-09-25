from django.urls import path

from quiz import views

urlpatterns = [
    path("quiz/today", views.today),
    path("quiz/practice", views.practice),
    path("quiz/sets/<int:set_id>/attempts", views.create_attempt),
    path("settings", views.settings_view),
    path("activity", views.activity_view),
]
