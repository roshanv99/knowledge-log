"""Django settings for the knowledge-log API.

Configuration comes from the environment (and the repo-root .env). Defaults match the local
Postgres in infra/docker-compose.yml.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
load_dotenv(REPO_ROOT / ".env")

env = os.environ.get

SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = env("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [h for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]
# The Django admin's session login needs its own origin allowlist (CSRF referer checks look
# at the scheme, which ALLOWED_HOSTS doesn't cover) — set to https://<domain> in production.
CSRF_TRUSTED_ORIGINS = [o for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "content",
    "quiz",
    "pipeline",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "knowledge_log"),
        "USER": env("POSTGRES_USER", "kl"),
        "PASSWORD": env("POSTGRES_PASSWORD", "kl"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5434"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
# "Today's quiz" is decided in the learner's local time zone.
TIME_ZONE = env("KL_TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = Path(env("KL_STATIC_ROOT", REPO_ROOT / "data" / "static")).expanduser()
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Pipeline planner (docs/PIPELINE_DB.md): chunk size in pages, and how long a claim lasts without a heartbeat.
KL_CHUNK_PAGES = int(env("KL_CHUNK_PAGES", "4"))
KL_LEASE_SECONDS = int(env("KL_LEASE_SECONDS", "600"))
KL_MAX_TASK_ATTEMPTS = 3

# Uploaded note PDFs and generated media (reel MP4s): local disk in dev, Cloudflare R2 in
# production (config/storage.py, docs/PLAN.md).
MEDIA_ROOT = Path(env("KL_MEDIA_ROOT", REPO_ROOT / "data" / "media")).expanduser()
KL_MAX_MEDIA_BYTES = int(env("KL_MAX_MEDIA_BYTES", str(200 * 1024 * 1024)))
# Uploads come through Cloudflare, which refuses request bodies over 100 MB on its free plan.
KL_MAX_NOTE_BYTES = int(env("KL_MAX_NOTE_BYTES", str(95 * 1024 * 1024)))

STORAGE_BACKEND = env("STORAGE_BACKEND", "local")  # "local" or "r2"
R2_BUCKET = env("R2_BUCKET", "")
R2_ENDPOINT_URL = env("R2_ENDPOINT_URL", "")
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", "")
# Public R2.dev or custom domain for the bucket; empty means the bucket is private and
# resolve_url() falls back to a short-lived presigned URL instead.
R2_PUBLIC_BASE_URL = env("R2_PUBLIC_BASE_URL", "")
PRESIGNED_URL_TTL_SECONDS = int(env("PRESIGNED_URL_TTL_SECONDS", "3600"))

REST_FRAMEWORK = {
    # Single-user and local-only for now. Token auth arrives with hosting (see docs/PLAN.md).
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
}

CORS_ALLOWED_ORIGINS = [o for o in env("CORS_ORIGINS", "http://localhost:5180").split(",") if o]
