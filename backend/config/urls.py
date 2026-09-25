from django.contrib import admin
from django.urls import include, path

from config.health import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health", health),
    path("api/", include("quiz.urls")),
    path("api/", include("content.urls")),
    path("api/", include("pipeline.urls")),
]
