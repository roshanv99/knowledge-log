"""Thin client for the Django pipeline API (/api/pipeline/*, docs/PIPELINE_DB.md).

The pipeline never touches the database: it claims work and reports results here, with the
runner token from KL_RUNNER_TOKEN (issued by `manage.py runner_token <name>`).
"""

import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status, self.detail = status, detail


class LeaseLost(ApiError):
    """409: this run no longer holds the task (or the run itself was closed)."""


class Api(Protocol):
    def notes(self) -> dict: ...
    def status(self) -> dict: ...
    def download_pdf(self, document_id: int, dest: Path) -> None: ...
    def wanted(self, kind: str) -> dict | None: ...
    def start_run(self, kind: str, params: dict) -> int: ...
    def claim(self, run_id: int, document_id: int | None = None) -> dict: ...
    def heartbeat(self, task_id: int, run_id: int, stage: str, detail: str | None = None) -> None: ...
    def save_notes(self, task_id: int, run_id: int, notes: dict) -> str: ...
    def complete(self, task_id: int, run_id: int, questions: list[dict], review_log: list,
                 skipped_reason: str | None = None, reel: dict | None = None) -> dict: ...
    def upload_media(self, task_id: int, run_id: int, path: Path, kind: str = "video") -> str: ...
    def fail(self, task_id: int, run_id: int, error: str, retryable: bool) -> dict: ...
    def finish(self, run_id: int, stop_reason: str, usage: dict | None = None) -> dict: ...


class HttpApi:
    def __init__(self, base: str, token: str | None, timeout: float = 30):
        self.base, self.token, self.timeout = base.rstrip("/"), token, timeout

    def _request(self, method: str, path: str, data: bytes | None = None, content_type: str | None = None,
                 runner: bool = True) -> urllib.request.Request:
        # Cloudflare (in front of the deployed API) blocks the default "Python-urllib/x.y"
        # User-Agent outright — a known bot signature, nothing to do with this being a runner.
        headers = {"Accept": "application/json", "User-Agent": "knowledge-log-runner/1.0"}
        if data is not None:
            headers["Content-Type"] = content_type or "application/octet-stream"
        if runner:
            if not self.token:
                raise ApiError(401, "KL_RUNNER_TOKEN is not set. Issue one with "
                                    "`cd backend && uv run manage.py runner_token <name>`.")
            headers["Authorization"] = f"Bearer {self.token}"
        return urllib.request.Request(self.base + path, data=data, method=method, headers=headers)

    def _error(self, e: urllib.error.URLError) -> ApiError:
        if isinstance(e, urllib.error.HTTPError):
            raw = e.read().decode(errors="replace")
            try:
                parsed = json.loads(raw)
                detail = parsed.get("detail", parsed) if isinstance(parsed, dict) else parsed
            except json.JSONDecodeError:
                detail = raw[:500]
            detail = detail if isinstance(detail, str) else json.dumps(detail)
            return (LeaseLost if e.code == 409 else ApiError)(e.code, detail)
        return ApiError(0, f"API unreachable at {self.base}: {e.reason}. Is the Django server running?")

    def _call(self, method: str, path: str, body: dict | None = None, *, runner: bool = True,
              raw: bytes | None = None, content_type: str | None = None, timeout: float | None = None):
        if body is not None:
            raw, content_type = json.dumps(body).encode(), "application/json"
        request = self._request(method, path, raw, content_type, runner)
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.URLError as e:
            raise self._error(e) from None

    # App reads (no runner token needed).
    def notes(self) -> dict:
        return self._call("GET", "/notes", runner=False)

    def status(self) -> dict:
        return self._call("GET", "/pipeline/status", runner=False)

    # Runner calls.
    def download_pdf(self, document_id: int, dest: Path) -> None:
        """Stream the document's PDF to dest (via a .part file, so a cut-off download never
        looks complete)."""
        request = self._request("GET", f"/pipeline/documents/{document_id}/pdf")
        part = dest.with_name(dest.name + ".part")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response, part.open("wb") as f:
                shutil.copyfileobj(response, f, 1 << 20)
        except urllib.error.URLError as e:
            part.unlink(missing_ok=True)
            raise self._error(e) from None
        part.replace(dest)

    def wanted(self, kind: str) -> dict | None:
        return self._call("GET", f"/pipeline/wanted?kind={kind}")

    def start_run(self, kind: str, params: dict) -> int:
        return self._call("POST", "/pipeline/runs", {"kind": kind, "params": params})["run_id"]

    def claim(self, run_id: int, document_id: int | None = None) -> dict:
        return self._call("POST", f"/pipeline/runs/{run_id}/claim", {"document_id": document_id})

    def heartbeat(self, task_id: int, run_id: int, stage: str, detail: str | None = None) -> None:
        self._call("POST", f"/pipeline/tasks/{task_id}/heartbeat", {"run_id": run_id, "stage": stage, "detail": detail})

    def save_notes(self, task_id: int, run_id: int, notes: dict) -> str:
        return self._call("PUT", f"/pipeline/tasks/{task_id}/notes", {"run_id": run_id, **notes})["chunk_status"]

    def complete(self, task_id: int, run_id: int, questions: list[dict], review_log: list,
                 skipped_reason: str | None = None, reel: dict | None = None) -> dict:
        return self._call("POST", f"/pipeline/tasks/{task_id}/complete", {
            "run_id": run_id, "questions": questions, "review_log": review_log, "skipped_reason": skipped_reason,
            "reel": reel})

    def upload_media(self, task_id: int, run_id: int, path: Path, kind: str = "video") -> str:
        """PUT the reel's MP4 (or its poster PNG, kind="poster") as the raw body; returns its storage key."""
        content_type = "image/png" if kind == "poster" else "video/mp4"
        return self._call("PUT", f"/pipeline/tasks/{task_id}/media?run_id={run_id}&kind={kind}",
                          raw=Path(path).read_bytes(), content_type=content_type, timeout=300)["storage_key"]

    def fail(self, task_id: int, run_id: int, error: str, retryable: bool) -> dict:
        return self._call("POST", f"/pipeline/tasks/{task_id}/fail",
                          {"run_id": run_id, "error": error[:4000], "retryable": retryable})

    def finish(self, run_id: int, stop_reason: str, usage: dict | None = None) -> dict:
        return self._call("POST", f"/pipeline/runs/{run_id}/finish", {"stop_reason": stop_reason, "usage": usage})
