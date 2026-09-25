# Deploy knowledge-log on Hostinger

A fresh VPS, separate from the Hetzner box that runs `log-book`/`fitness-log`. It hosts
knowledge-log behind its own shared edge gateway — [`roshanv99/api-gateway-2`](https://github.com/roshanv99/api-gateway-2),
built the same way as `~/Projects/api-gateway` but on an independent host. See `docs/PLAN.md`
and the plan this deploy was built from for the full architecture diagram.

The content pipeline (`kl mcq`/`kl reel` — manim, Kokoro, torch) stays on the Mac via
launchd. Nothing about it is deployed here; it talks to the deployed API over HTTPS with its
existing runner token.

**Nothing is built on this box.** GitHub Actions builds both images and pushes them to
GHCR (`ghcr.io/roshanv99/knowledge-log-{backend,ui}`); the server only ever runs
`docker compose pull && up -d`. Same convention as every other app on this VPS.

## 1. Server bootstrap (one-time)

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
ufw --force enable
```

Only **22, 80, 443** should be public. Postgres binds to loopback only (see
`docker-compose.yml`).

## 2. The `deploy` user (one-time, shared by every app on this box)

GitHub Actions never deploys as root. If this box doesn't have it yet:

```bash
# on the server, as root
adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy
mkdir -p /home/deploy/.ssh && chmod 700 /home/deploy/.ssh
```

Each app gets its own dedicated key, used for nothing else — generate it on your own
machine, never on the server:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/knowledge-log-deploy -C "knowledge-log-ci-deploy" -N ""
cat ~/.ssh/knowledge-log-deploy.pub | ssh root@<ip> \
  "cat >> /home/deploy/.ssh/authorized_keys && chown -R deploy:deploy /home/deploy/.ssh && chmod 600 /home/deploy/.ssh/authorized_keys"
ssh -i ~/.ssh/knowledge-log-deploy deploy@<ip> docker ps   # verify
```

## 3. GHCR auth on the server

CI pushes with the built-in `GITHUB_TOKEN` (no extra secret needed for that direction), but
a package linked to a repo is created **private by default** regardless of the repo's own
visibility, so the `deploy` user needs its own login to pull:

```bash
# a classic PAT with read:packages, from https://github.com/settings/tokens
ssh -i ~/.ssh/knowledge-log-deploy deploy@<ip>
echo "<PAT>" | docker login ghcr.io -u roshanv99 --password-stdin
```

(Or, once the first image has been pushed: GitHub → the package's page → Package settings →
Change visibility → Public. Either works; the login is the more resilient default since it
doesn't depend on remembering to flip a setting.)

## 4. DNS + TLS

Cloudflare, proxied (orange cloud), pointing at the VPS IPv4:

```
kl   A   <server-ipv4>   proxied
```

Cloudflare → SSL/TLS → mode **Full (strict)** → Origin Server → Create Certificate, hostname
`kl.yourdomain.com` (or a wildcard if more apps join this box later). The cert lives in
`api-gateway-2/nginx/certs/` — knowledge-log's own nginx never sees it; it only listens on
plain `:80` and trusts the gateway for TLS (see `deploy/nginx/default.conf.template`).

## 5. The shared gateway (once per box)

```bash
mkdir -p /opt/api-gateway-2 && chown deploy:deploy /opt/api-gateway-2
su - deploy
git clone https://github.com/roshanv99/api-gateway-2.git /opt/api-gateway-2
cd /opt/api-gateway-2
cp deploy/env.example .env   # set KNOWLEDGE_LOG_DOMAIN=kl.yourdomain.com
install -m 700 -d nginx/certs
# paste origin.crt / origin.key from step 4
docker compose up -d
curl -s http://localhost/healthz   # -> "gateway ok"
```

## 6. knowledge-log app config

```bash
mkdir -p /opt/knowledge-log && chown deploy:deploy /opt/knowledge-log   # as root, once
su - deploy
git clone https://github.com/roshanv99/knowledge-log.git /opt/knowledge-log
cd /opt/knowledge-log
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

## 7. First bring-up

Before CI exists, or to bootstrap manually — pull the images GHCR already has (or build
locally once and push, if this is the very first deploy):

```bash
cd /opt/knowledge-log
docker compose -f docker-compose.yml -f docker-compose.gateway.yml pull
docker compose -f docker-compose.yml -f docker-compose.gateway.yml up -d
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

## 8. GitHub Actions secrets

Settings → Secrets and variables → Actions, on `roshanv99/knowledge-log`:

| Secret | Value |
|--------|--------------|
| `SSH_PRIVATE_KEY` | contents of `~/.ssh/knowledge-log-deploy` (the private key) |
| `SSH_HOST` | Server IPv4 |
| `SSH_USER` | `deploy` |
| `DEPLOY_PATH` | `/opt/knowledge-log` |
| `RCLONE_CONFIG_B64` | `base64 -i ~/.config/rclone/rclone.conf \| tr -d '\n'` after `rclone config` creates a `gdrive` remote |

Push to `main` to prove the automated path: `.github/workflows/deploy-production.yml`
builds both images, pushes them to GHCR, then over SSH backs up, pulls, migrates, and
refreshes `api-gateway-2` in the same session.

## 9. Backups

Daily cron (installed by every deploy, or manually via
`sudo bash deploy/install-backup-cron.sh /opt/knowledge-log`) dumps Postgres and uploads to
`gdrive:knowledge-log-backups/`. Logs: `/var/log/knowledge-log-backup.log`.

R2 media (reel MP4s/posters) is not separately backed up — R2 is itself durable, and source
notes/scripts live on the Mac.

## 10. Disk space

Since nothing builds on the server, disk pressure here is unlikely — but pulled images do
accumulate old layers over time:

```bash
docker image prune -af
docker container prune -f
```

`ci-deploy.sh` prunes dangling images after every pull already.
