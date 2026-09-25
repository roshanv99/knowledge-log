"""Adding and removing note PDFs from the app (Manage notes).

An upload is stored under `notes/<owner>/<sha256>.pdf` (config/storage.py: R2 in production).
A PDF's identity is its content: uploading a file that was removed before brings back the same
Document, with its questions, reels and progress.
"""

import hashlib
import logging
import os
import tempfile
import unicodedata
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from pypdf import PdfReader

from config.storage import get_storage
from content.models import Document, NoteScope

log = logging.getLogger(__name__)

# Every note belongs to one owner until the app has per-user accounts; the segment is in the
# key now so files needn't move when it does.
OWNER = "default"


class UploadError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def note_key(file_hash: str) -> str:
    return f"notes/{OWNER}/{file_hash}.pdf"


def clean_filename(name: str) -> str:
    name = Path(name.replace("\\", "/")).name.strip()
    if any(unicodedata.category(c) == "Cc" for c in name):
        raise UploadError("The file name has characters that aren't allowed.")
    if not name.lower().endswith(".pdf") or len(name) <= 4:
        raise UploadError("Only PDF files can be uploaded.")
    if len(name) > 255:
        raise UploadError("The file name is too long (255 characters at most).")
    return name


def clean_folder(folder: str) -> str:
    folder = folder.strip().strip("/").strip()
    if any(unicodedata.category(c) == "Cc" for c in folder):
        raise UploadError("The folder name has characters that aren't allowed.")
    if len(folder) > 200:
        raise UploadError("The folder name is too long (200 characters at most).")
    return folder


def _page_count(path: str) -> int:
    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise UploadError("This PDF is password-protected. Upload a copy without a password.")
        pages = len(reader.pages)
    except UploadError:
        raise
    except Exception:
        raise UploadError("This file couldn't be read as a PDF.") from None
    if pages < 1:
        raise UploadError("This PDF has no pages.")
    return pages


def _stage(stream, length: int) -> tuple[str, str]:
    """Copy exactly `length` bytes of the request body to a temp file; returns (path, sha256)."""
    stage_dir = Path(settings.MEDIA_ROOT) / "tmp"
    stage_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=stage_dir, suffix=".pdf.part")
    digest, received, head = hashlib.sha256(), 0, b""
    try:
        with os.fdopen(fd, "wb") as out:
            while received < length and (chunk := stream.read(min(1 << 20, length - received))):
                if len(head) < 1024:
                    head += chunk[:1024 - len(head)]
                digest.update(chunk)
                received += len(chunk)
                out.write(chunk)
        if received != length:
            raise UploadError(f"The upload was cut short ({received} of {length} bytes). Try again.")
        if b"%PDF-" not in head:
            raise UploadError("That file isn't a PDF.")
    except BaseException:
        os.unlink(tmp)
        raise
    return tmp, digest.hexdigest()


def _on_top() -> int:
    """The priority that puts a PDF at the top of Manage notes (the end of the pipeline's queue)."""
    first = NoteScope.objects.order_by("priority").values_list("priority", flat=True).first()
    return 0 if first is None else first - 1


def upload(stream, length: int, filename: str, folder: str = "") -> tuple[Document, str]:
    """Store an uploaded PDF. Returns the document and what happened: "added" (new),
    "restored" (a removed PDF is back, with its progress) or "exists" (already there)."""
    filename, folder = clean_filename(filename), clean_folder(folder)
    if not 0 < length <= settings.KL_MAX_NOTE_BYTES:
        raise UploadError(f"PDFs can be up to {settings.KL_MAX_NOTE_BYTES // (1024 * 1024)} MB.", status=413)

    tmp, file_hash = _stage(stream, length)
    try:
        page_count = _page_count(tmp)
        existing = Document.objects.filter(file_hash=file_hash).first()
        if existing and existing.available and existing.storage_key:
            return existing, "exists"
        key = note_key(file_hash)
        get_storage().save(tmp, key)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    with transaction.atomic():
        document = Document.objects.select_for_update().filter(file_hash=file_hash).first()
        if document is None:
            try:
                with transaction.atomic():
                    document = Document.objects.create(file_hash=file_hash, storage_key=key, filename=filename,
                                                       folder=folder, page_count=page_count, available=True)
                    NoteScope.objects.create(document=document, priority=_on_top())
                return document, "added"
            except IntegrityError:  # the same PDF, uploaded twice at once
                document = Document.objects.select_for_update().get(file_hash=file_hash)
        outcome = "exists" if document.available and document.storage_key else "restored"
        document.storage_key, document.available, document.filename = key, True, filename
        document.folder = folder or document.folder
        document.save(update_fields=["storage_key", "available", "filename", "folder"])
        NoteScope.objects.get_or_create(document=document, defaults={"priority": _on_top()})
    return document, outcome


def remove(document: Document) -> None:
    """Delete the stored PDF. The document, its questions and reels stay; it just isn't offered
    to the pipeline until the same PDF is uploaded again."""
    with transaction.atomic():
        document = Document.objects.select_for_update().get(pk=document.pk)
        key = document.storage_key
        document.storage_key, document.available = "", False
        document.save(update_fields=["storage_key", "available"])

    def delete():
        try:
            get_storage().delete(key)
        except Exception:  # the document is already removed; a leftover object only costs storage
            log.exception("Couldn't delete %s from storage", key)

    if key:
        transaction.on_commit(delete)
