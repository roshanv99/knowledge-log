# knowledge-log

A personal learning app built around your own PDF notes: a daily 10-question quiz drawn from
what you've selected, and a feed of short reels (manim explainers today, more formats
planned) generated from the same material. Content generation is driven by Claude Code
itself — a deterministic step engine claims work from the API, and a Claude Code session
(reading, writing, reviewing, with fresh subagents as critics) does the actual reading and
writing. See [`docs/PLAN.md`](docs/PLAN.md) for the full design and where things stand.

## Stack

- **`backend/`** — Django + Django REST Framework on Postgres 16. One JSON API (`/api/`)
  for the web app today, a future mobile client later.
- **`ui/`** — React (Vite) + TypeScript + Tailwind v4, installable as a PWA. Mobile-first:
  bottom tab navigation on phones, a side rail from 1024px up.
- **`pipeline/`** — `kl`, a Python (uv) CLI: a deterministic step engine that claims work
  from the Django planner and hands each step to a Claude Code session via the
  `mcq-generation`/`reel-generation` skills. No LLM calls happen in Python.
- **`plugin/knowledge-log/`** — the Claude Code plugin: prompts and commands the pipeline
  skills use.

## Quickstart (local dev)

Requires [uv](https://docs.astral.sh/uv/), Node 20+, and Docker (for Postgres).

```bash
# Postgres (port 5434, isolated from other local projects)
docker compose -f infra/docker-compose.yml up -d

# Backend — http://localhost:8010
cd backend && uv sync && uv run manage.py migrate && uv run manage.py runserver 8010

# Web app — http://localhost:5180 (proxies /api to the backend above)
cd ui && npm install && npm run dev
```

Copy `.env.example` to `.env` at the repo root and fill in `KL_RUNNER_TOKEN` (see
`backend/manage.py runner_token`) if you want the content pipeline to run too:

```bash
cd pipeline && uv sync --extra reels && uv run kl mcq start
```

## Deployment

Docker multistage images, GitHub Actions CI/CD, Postgres backed up to Google Drive, reel
media on Cloudflare R2, behind an nginx + oauth2-proxy (Google SSO) edge. Full runbook:
[`deploy/HOSTINGER.md`](deploy/HOSTINGER.md).

## Docs

- [`docs/PLAN.md`](docs/PLAN.md) — architecture and build log
- [`docs/PIPELINE_DB.md`](docs/PIPELINE_DB.md) — the planner/task-claiming model behind
  `/api/pipeline/*`
- [`docs/MANIM_PIPELINE.md`](docs/MANIM_PIPELINE.md) — the manim reel generation pipeline

## License

[MIT](LICENSE)
