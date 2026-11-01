# Deploy knowledge-log on the home server

Production runs on a MacBook Air M2 at home: lid closed, OrbStack for Docker, no public
ports. The machine itself is set up and documented in
[`roshanv99/home-server`](https://github.com/roshanv99/home-server) (private). That repo has
`setup.sh`, the `cloudflared` edge and the general guide to adding an app. This file covers
only what is specific to knowledge-log.

It moved here from a Hostinger VPS on 2026-11-01. The old runbook, `deploy/HOSTINGER.md`, is
in git history.

```
Internet → Cloudflare → tunnel → cloudflared ──gateway network──► knowledgelog:80 (this app's nginx)
                                                                   ├─ oauth2-proxy (Google SSO)
                                                                   └─ knowledge-log-backend → postgres
GitHub Actions → Tailscale (tag:ci) → SSH mbam2server@homeserver → deploy/ci-deploy.sh
```

## Where things are

| | |
|---|---|
| Public URL | `https://knowledge-log.roshanvarghese.dev` |
| Tunnel route | Cloudflare Zero Trust → Tunnels → `homeserver` → Routes: `knowledge-log.roshanvarghese.dev → http://knowledgelog:80` |
| Server path | `/Users/mbam2server/apps/knowledge-log` (a git clone of `main`) |
| Config | `.env` (from [`env.example`](env.example)) and `deploy/oauth2-proxy.env` there. Neither is in git. |
| Images | `ghcr.io/roshanv99/knowledge-log-{backend,ui}`, `linux/arm64` only |
| Reel media, note PDFs | R2 bucket for media (`STORAGE_BACKEND=r2`) |
| DB backups | R2 bucket `knowledge-log-backups`, prefix `postgres/` |

## Deploys

Every push to `main` runs [`.github/workflows/deploy-production.yml`](../.github/workflows/deploy-production.yml):
1. **build**: both images are built natively on `ubuntu-24.04-arm` and pushed to GHCR.
2. **deploy**:
   - The runner joins the tailnet as `tag:ci`. The ACL lets that tag reach only `tag:homeserver:22`.
   - It then SSHes in and runs [`ci-deploy.sh`](ci-deploy.sh): backup, `git reset --hard origin/main`, `compose pull`, `up -d`, `migrate`, and reinstall the backup cron.

GitHub Actions secrets:

| Secret | Value |
|---|---|
| `SSH_PRIVATE_KEY` | `~/.ssh/knowledge-log-deploy` on the laptop. Its `.pub` is in the server's `authorized_keys`. |
| `SSH_HOST` | The Air's Tailscale IP, `100.98.189.64` |
| `SSH_USER` | `mbam2server` |
| `DEPLOY_PATH` | `/Users/mbam2server/apps/knowledge-log` |
| `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET` | Tailscale OAuth client (Auth Keys: Write, tag `tag:ci`), shared with other home-server apps |

To deploy by hand, from the laptop:

```bash
ssh mbam2server@100.98.189.64
cd ~/apps/knowledge-log && git pull
docker compose -f docker-compose.yml -f docker-compose.gateway.yml pull
docker compose -f docker-compose.yml -f docker-compose.gateway.yml up -d
```

## Backups

[`backup.sh`](backup.sh) runs `pg_dump`, gzips the dump and uploads it with rclone to R2.
- **When:** nightly at 18:30 UTC (00:00 IST) from the user's crontab, and before every deploy.
- **Retention:** dumps older than 90 days are deleted (`BACKUP_RETENTION_DAYS`).
- **Credentials:** the R2 token is scoped to the backups bucket only (Object Read & Write). The
  rclone remote is built from `.env`, so there is no rclone.conf.
- **Log:** `~/logs/knowledge-log-backup.log`

The media in R2 isn't backed up separately, because R2 itself is durable. Keep your own copies
of the note PDFs you upload.

### Restore

```bash
cd ~/apps/knowledge-log && set -a && . ./.env && set +a
export RCLONE_CONFIG_B_TYPE=s3 RCLONE_CONFIG_B_PROVIDER=Cloudflare RCLONE_CONFIG_B_NO_CHECK_BUCKET=true \
  RCLONE_CONFIG_B_ENDPOINT="$R2_ENDPOINT_URL" \
  RCLONE_CONFIG_B_ACCESS_KEY_ID="$BACKUP_R2_ACCESS_KEY_ID" \
  RCLONE_CONFIG_B_SECRET_ACCESS_KEY="$BACKUP_R2_SECRET_ACCESS_KEY"
rclone lsf "b:$BACKUP_R2_BUCKET/postgres/" | tail -5          # pick a dump
C="docker compose -f docker-compose.yml -f docker-compose.gateway.yml"
$C stop knowledge-log-backend nginx
$C exec -T postgres psql -U "$POSTGRES_USER" -d postgres -c "drop database $POSTGRES_DB" -c "create database $POSTGRES_DB"
rclone cat "b:$BACKUP_R2_BUCKET/postgres/<dump>.sql.gz" | gunzip \
  | $C exec -T postgres psql -q -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"
$C up -d
```

## Things that will bite

- **Docker registry login:** don't run `docker login` on the server. It moves the GHCR
  credentials into the macOS Keychain, which is locked over SSH, and every deploy's
  `compose pull` fails. See the home-server README.
- **Scripts in `deploy/`:** they run under macOS's bash 3.2 and BSD tools.
- **Cron:** times are UTC (the server's clock is UTC). Crontab changes over SSH need Full Disk
  Access for remote users, which is on.
- **A DNS change seems not to work:** your home router can cache a "no such name" answer for up
  to 30 minutes. Test from mobile data or with `dig @1.1.1.1`.
