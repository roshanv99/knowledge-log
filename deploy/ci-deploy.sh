#!/usr/bin/env bash
# Remote deploy entrypoint: backup → git pull → rebuild → migrate.
# Invoked from GitHub Actions over SSH (see .github/workflows/deploy-production.yml).

set -euo pipefail

: "${DEPLOY_PATH:?DEPLOY_PATH is required}"

cd "$DEPLOY_PATH"

if [[ ! -d .git ]]; then
  echo "ci-deploy.sh: ${DEPLOY_PATH} is not a git repository" >&2
  exit 1
fi

echo "ci-deploy.sh: pre-deploy backup"
bash "${CI_DEPLOY_DIR:-deploy}/backup.sh"

echo "ci-deploy.sh: updating code from origin/main"
git fetch origin main
git checkout main
# Discard any local edits on the server (manual SSH edits, failed prior deploys, etc.)
git reset --hard origin/main

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.gateway.yml)

echo "ci-deploy.sh: pruning unused Docker cache (prevents disk-full build failures)"
docker builder prune -af >/dev/null 2>&1 || true
docker image prune -af >/dev/null 2>&1 || true

echo "ci-deploy.sh: rebuilding and starting services"
"${COMPOSE[@]}" up -d --build

echo "ci-deploy.sh: recreating nginx (template → conf is rendered at container start)"
"${COMPOSE[@]}" up -d --force-recreate --no-deps nginx

echo "ci-deploy.sh: running database migrations"
"${COMPOSE[@]}" exec -T knowledge-log-backend python manage.py migrate

echo "ci-deploy.sh: ensuring daily backup cron is installed"
bash deploy/install-backup-cron.sh "$(pwd)"

echo "ci-deploy.sh: deploy finished"
