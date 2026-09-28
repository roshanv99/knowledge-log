"""One idempotent sweep of every active followed account (kl social discover)."""

from kl.api import Api
from kl.social import scraper

_DISCOVER = {"youtube": scraper.discover_youtube, "instagram": scraper.discover_instagram}


def run(api: Api, limit: int = 10) -> str:
    accounts = api.list_accounts()["accounts"]
    active = [a for a in accounts if a["active"]]
    if not active:
        return "No active followed accounts."

    lines = []
    for account in active:
        try:
            refs = _DISCOVER[account["platform"]](account["handle"], limit)
        except Exception as e:  # a scrape failure on one account shouldn't stop the sweep
            lines.append(f"{account['platform']}:{account['handle']}: FAILED ({e})")
            continue
        result = api.report_videos(account["id"], [r.to_payload() for r in refs])
        lines.append(f"{account['platform']}:{account['handle']}: {result['received']} seen, "
                     f"{result['created']} new")
    return "\n".join(lines)
