# Deploy knowledge-log on Hostinger

A fresh VPS, separate from the Hetzner box that runs `log-book`/`fitness-log`. It hosts
knowledge-log behind its own shared edge gateway — a new repo, `hostinger-api-gateway`,
built the same way as `~/Projects/api-gateway` but starting with one app instead of two. See
`docs/PLAN.md` and the plan this deploy was built from for the full architecture diagram.

The content pipeline (`kl mcq`/`kl reel` — manim, Kokoro, torch) stays on the Mac via
launchd. Nothing about it is deployed here; it talks to the deployed API over HTTPS with its
existing runner token.

## 1. Server bootstrap

Same as Hetzner (`~/Projects/log-book/deploy/HETZNER.md` §1): Ubuntu, Docker CE +
docker-compose-plugin, UFW allowing only 22/80/443.

```bash
apt update && apt upgrade -y
apt install -y ca-certificates curl
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt update && apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin rclone

ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

Only **22, 80, 443** should be public. Postgres binds to loopback only (see
`docker-compose.yml`).

## 2. DNS + TLS

Cloudflare, proxied (orange cloud), pointing at the VPS IPv4:

```
kl   A   <server-ipv4>   proxied
```

Cloudflare → SSL/TLS → mode **Full (strict)** → Origin Server → Create Certificate, hostname
`kl.yourdomain.com` (or a wildcard if more apps join this box later). The cert lives in
`hostinger-api-gateway/nginx/certs/` — knowledge-log's own nginx never sees it; it only
listens on plain `:80` and trusts the gateway for TLS (see `deploy/nginx/default.conf.template`).

## 3. The shared gateway (once per box)

```bash
docker network create gateway
git clone <hostinger-api-gateway repo url> /root/hostinger-api-gateway
cd /root/hostinger-api-gateway
cp deploy/env.example .env   # set KNOWLEDGE_LOG_DOMAIN=kl.yourdomain.com
install -m 700 -d nginx/certs
# paste origin.crt / origin.key from step 2
docker compose up -d
curl -s http://localhost/healthz   # -> "gateway ok"
```

## 4. knowledge-log app config

```bash
git clone <knowledge-log repo url> /root/knowledge-log
cd /root/knowledge-log
cp deploy/env.example .env
cp deploy/oauth2-proxy.env.example deploy/oauth2-proxy.env
```

Fill in `.env`: `DOMAIN`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`,
`DJANGO_CSRF_TRUSTED_ORIGINS`, `POSTGRES_PASSWORD`, `STORAGE_BACKEND=r2` + the `R2_*` values
(bucket + API token from the Cloudflare dashboard — R2 → Manage API tokens).

Fill in `deploy/oauth2-proxy.env`: Google OAuth client ID/secret (Google Cloud Console →
Credentials → OAuth client ID → Web application; authorized redirect URI
`https://<DOMAIN>/oauth2/callback`), a generated `OAUTH2_PROXY_COOKIE_SECRET`, and
`OAUTH2_PROXY_EMAIL_DOMAINS` restricted to your own account.

## 5. First bring-up

```bash
cd /root/knowledge-log
docker compose -f docker-compose.yml -f docker-compose.gateway.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.gateway.yml exec knowledge-log-backend python manage.py migrate
docker compose -f docker-compose.yml -f docker-compose.gateway.yml exec knowledge-log-backend python manage.py runner_token "kl@$(hostname)"
```

Save the printed runner token — it's shown once. Put it in the Mac's root `.env` as
`KL_RUNNER_TOKEN`, and point `KL_API_BASE` at `https://<DOMAIN>/api`.

Check:

```bash
docker compose ps
curl -s https://<DOMAIN>/api/health
```

Visiting `https://<DOMAIN>/` should redirect to Google sign-in.

## 6. GitHub Actions secrets

Same four as log-book (Settings → Secrets and variables → Actions):

| Secret | Description |
|--------|--------------|
| `SSH_PRIVATE_KEY` | Deploy key with access to the server |
| `SSH_HOST` | Server IPv4 |
| `SSH_USER` | e.g. `root` |
| `DEPLOY_PATH` | `/root/knowledge-log` |
| `RCLONE_CONFIG_B64` | `base64 -i ~/.config/rclone/rclone.conf \| tr -d '\n'` after `rclone config` creates a `gdrive` remote |

Push to `main` to prove the automated path: `.github/workflows/deploy-production.yml` backs
up, deploys, migrates, and refreshes `hostinger-api-gateway` over the same SSH session.

## 7. Backups

Daily cron (installed by every deploy, or manually via
`sudo bash deploy/install-backup-cron.sh /root/knowledge-log`) dumps Postgres and uploads to
`gdrive:knowledge-log-backups/`. Logs: `/var/log/knowledge-log-backup.log`.

R2 media (reel MP4s/posters) is not separately backed up — R2 is itself durable, and source
notes/scripts live on the Mac.

## 8. Disk space

If `docker compose up --build` fails with "No space left on device":

```bash
docker builder prune -af
docker image prune -af
docker container prune -f
```

`ci-deploy.sh` runs the first two before every rebuild already.
