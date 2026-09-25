# syntax=docker/dockerfile:1
# Build context: backend/ (see docker-compose.yml). Two stages: uv resolves and installs
# into a venv, then that venv is copied into a slim runtime with no build toolchain.
FROM python:3.13-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.9-python3.13-bookworm-slim /usr/local/bin/uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev
COPY . .
RUN uv sync --frozen --no-dev

FROM python:3.13-slim
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" \
    HOME=/tmp \
    DJANGO_DEBUG=0 \
    KL_MEDIA_ROOT=/data/media \
    KL_STATIC_ROOT=/data/static
RUN addgroup --system kl && adduser --system --ingroup kl kl \
    && mkdir -p /data/media/tmp /data/static && chown -R kl:kl /data
COPY --from=build /app /app
RUN chown -R kl:kl /app
USER kl
RUN python manage.py collectstatic --noinput
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
