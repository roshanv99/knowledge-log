"""Storage for generated media (reel MP4s and poster PNGs), keyed as `reels/task-<id>.mp4`
etc. (see `pipeline.services.media_key`).

Two backends behind one interface, chosen by `STORAGE_BACKEND`:
  - LocalDiskStorage: writes under MEDIA_ROOT, served by content.views.media. The default,
    and what local dev uses.
  - R2Storage: Cloudflare R2 over boto3 (S3-compatible API). Used in production — zero
    egress fees (the dominant cost for a video feed), and it keeps the VPS stateless so the
    pipeline can move off the Mac later without migrating any files.

Copied from Study Reels Generator's shared/storage.py (see docs/PLAN.md), adapted to this
repo's key layout and to taking bytes directly rather than a local path (the pipeline runner
streams an HTTP upload straight through, see pipeline.services.save_media).
"""
from pathlib import Path
from typing import Protocol

from django.conf import settings


class Storage(Protocol):
    def save(self, local_path: str | Path, key: str) -> str:
        """Persist the already-validated file at local_path under `key` (streamed, not
        read into memory); returns the storage_key to record in the DB."""
        ...

    def resolve_url(self, key: str) -> str:
        """A URL a browser can play/fetch the object from."""
        ...

    def exists(self, key: str) -> bool: ...


class LocalDiskStorage:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or settings.MEDIA_ROOT)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / key

    def save(self, local_path: str | Path, key: str) -> str:
        import os
        import shutil

        dest = self._path(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(local_path), dest)  # already on the same filesystem (tmp under MEDIA_ROOT)
        os.chmod(dest, 0o644)
        return key

    def resolve_url(self, key: str) -> str:
        # Served by content.views.media (byte-range FileResponse from MEDIA_ROOT).
        return f"/api/media/{key}"

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class R2Storage:
    def __init__(
        self,
        bucket: str = "",
        endpoint_url: str = "",
        access_key: str = "",
        secret_key: str = "",
        public_base_url: str = "",
        presigned_url_ttl_seconds: int = 3600,
    ):
        bucket = bucket or settings.R2_BUCKET
        endpoint_url = endpoint_url or settings.R2_ENDPOINT_URL
        access_key = access_key or settings.R2_ACCESS_KEY_ID
        secret_key = secret_key or settings.R2_SECRET_ACCESS_KEY
        public_base_url = public_base_url or settings.R2_PUBLIC_BASE_URL

        missing = [
            name
            for name, value in [
                ("R2_BUCKET", bucket),
                ("R2_ENDPOINT_URL", endpoint_url),
                ("R2_ACCESS_KEY_ID", access_key),
                ("R2_SECRET_ACCESS_KEY", secret_key),
            ]
            if not value
        ]
        if missing:
            raise RuntimeError(
                "STORAGE_BACKEND=r2 but these are unset in .env: " + ", ".join(missing)
            )

        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.public_base_url = public_base_url
        self.presigned_url_ttl_seconds = presigned_url_ttl_seconds or settings.PRESIGNED_URL_TTL_SECONDS
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            # R2 only implements the v4 signer, and has no regions — "auto" is what
            # Cloudflare's own docs use.
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
            region_name="auto",
        )

    _CONTENT_TYPES = {".mp4": "video/mp4", ".png": "image/png"}

    def _content_type(self, key: str) -> str:
        return self._CONTENT_TYPES.get(Path(key).suffix.lower(), "application/octet-stream")

    def save(self, local_path: str | Path, key: str) -> str:
        self.client.upload_file(
            str(local_path),
            self.bucket,
            key,
            ExtraArgs={"ContentType": self._content_type(key)},
        )
        return key

    def resolve_url(self, key: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url}/{key}"
        # No public domain configured, so the bucket stays private and we hand out a
        # short-lived signed URL instead. Either way the video bytes go straight from R2 to
        # the viewer, never through the API.
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.presigned_url_ttl_seconds,
        )

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False


def get_storage() -> Storage:
    """The configured backend. Everything (API and pipeline uploads) goes through this so
    switching backends is a .env change, not a code change."""
    if settings.STORAGE_BACKEND == "r2":
        return R2Storage()
    if settings.STORAGE_BACKEND == "local":
        return LocalDiskStorage()
    raise ValueError(f"Unknown STORAGE_BACKEND {settings.STORAGE_BACKEND!r} (expected 'local' or 'r2')")
