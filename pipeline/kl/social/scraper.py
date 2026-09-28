"""Unofficial discovery: find new reels/shorts on a followed account's public profile.

Not part of the deterministic step engine (kl/steps.py) — there's no chunk, no PDF, no Claude
Code session to drive, just a fetch. yt-dlp covers YouTube; instaloader covers Instagram, since
yt-dlp's support for listing an Instagram profile's reels is unreliable (as of writing).

This is an unofficial scrape against Instagram in particular, which is against its ToS. It's kept
low-frequency (see infra/launchd) and, for Instagram, benefits from a logged-in session
(KL_INSTAGRAM_SESSION_FILE / KL_INSTAGRAM_USER) to avoid the aggressive anonymous rate limits —
use a secondary account, not the personal one, to keep any rate-limit/flagging risk contained.
"""

import itertools
import os
from dataclasses import dataclass
from datetime import datetime


@dataclass
class VideoRef:
    external_id: str
    url: str
    embed_url: str
    title: str = ""
    description: str = ""
    published_at: datetime | None = None

    def to_payload(self) -> dict:
        return {"external_id": self.external_id, "url": self.url, "embed_url": self.embed_url,
                "title": self.title, "description": self.description,
                "published_at": self.published_at.isoformat() if self.published_at else None}


def discover_youtube(handle: str, limit: int = 10) -> list[VideoRef]:
    """The channel's Shorts tab, newest first. Flat extraction: fast, one request, no per-video
    upload date (published_at is left None; the feed still orders by discovery time)."""
    import yt_dlp

    url = f"https://www.youtube.com/@{handle.lstrip('@')}/shorts"
    opts = {"extract_flat": True, "quiet": True, "no_warnings": True, "playlist_items": f"1-{limit}"}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    refs = []
    for entry in (info or {}).get("entries") or []:
        video_id = entry.get("id")
        if not video_id:
            continue
        refs.append(VideoRef(
            external_id=video_id,
            url=f"https://www.youtube.com/shorts/{video_id}",
            embed_url=f"https://www.youtube-nocookie.com/embed/{video_id}",
            title=entry.get("title") or "",
        ))
    return refs


def discover_instagram(handle: str, limit: int = 10) -> list[VideoRef]:
    """The profile's recent posts, filtered to reels/videos, newest first."""
    import instaloader

    loader = instaloader.Instaloader(quiet=True, download_pictures=False, download_videos=False,
                                     download_video_thumbnails=False, save_metadata=False,
                                     compress_json=False)
    session_file, username = os.environ.get("KL_INSTAGRAM_SESSION_FILE"), os.environ.get("KL_INSTAGRAM_USER")
    if session_file and username:
        loader.load_session_from_file(username, session_file)

    profile = instaloader.Profile.from_username(loader.context, handle.lstrip("@"))
    refs = []
    for post in itertools.islice(profile.get_posts(), limit):
        if not post.is_video:
            continue
        refs.append(VideoRef(
            external_id=post.shortcode,
            url=f"https://www.instagram.com/reel/{post.shortcode}/",
            embed_url=f"https://www.instagram.com/reel/{post.shortcode}/embed",
            title=(post.caption or "")[:200],
            description=post.caption or "",
            published_at=post.date_utc,
        ))
    return refs
