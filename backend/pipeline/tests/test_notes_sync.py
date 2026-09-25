"""`manage.py sync_notes` over a real folder of PDFs, and the runners' PDF download."""

from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from pypdf import PdfWriter
from rest_framework.test import APIClient

from content.models import Document
from pipeline.tests.test_api import API, runner_client

pytestmark = pytest.mark.django_db


def make_pdf(path: Path, pages: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    with path.open("wb") as f:
        writer.write(f)
    return path


@pytest.fixture
def notes(tmp_path, settings):
    settings.KL_NOTES_DIR = tmp_path / "notes"
    make_pdf(settings.KL_NOTES_DIR / "Tech" / "Redis.pdf", 3)
    make_pdf(settings.KL_NOTES_DIR / "Top.pdf", 2)
    return settings.KL_NOTES_DIR


def test_sync_registers_every_pdf_with_its_folder_and_pages(notes):
    call_command("sync_notes")
    docs = {d.filename: d for d in Document.objects.all()}
    assert (docs["Redis.pdf"].folder, docs["Redis.pdf"].page_count) == ("Tech", 3)
    assert (docs["Top.pdf"].folder, docs["Top.pdf"].page_count) == ("", 2)
    assert all(d.available for d in docs.values())


def test_deleted_pdf_goes_unavailable_on_the_next_sync(notes):
    call_command("sync_notes")
    (notes / "Top.pdf").unlink()
    call_command("sync_notes")
    assert not Document.objects.get(filename="Top.pdf").available
    assert Document.objects.get(filename="Redis.pdf").available


def test_missing_folder_changes_nothing(notes, settings):
    call_command("sync_notes")
    settings.KL_NOTES_DIR = notes.parent / "not-mounted"
    with pytest.raises(CommandError):
        call_command("sync_notes")
    assert Document.objects.filter(available=True).count() == 2


def test_runner_downloads_the_pdf(notes):
    call_command("sync_notes")
    redis = Document.objects.get(filename="Redis.pdf")
    url = f"{API}/documents/{redis.pk}/pdf"
    assert APIClient().get(url).status_code in (401, 403)

    response = runner_client("kl@test").get(url)
    assert response.status_code == 200 and response["Content-Type"] == "application/pdf"
    assert b"".join(response.streaming_content) == (notes / "Tech" / "Redis.pdf").read_bytes()


def test_no_download_for_unavailable_or_outside_files(notes, tmp_path):
    call_command("sync_notes")
    client = runner_client("kl@test")
    top = Document.objects.get(filename="Top.pdf")
    Document.objects.filter(pk=top.pk).update(available=False)
    assert client.get(f"{API}/documents/{top.pk}/pdf").status_code == 404

    outside = make_pdf(tmp_path / "secret.pdf", 1)
    Document.objects.filter(filename="Redis.pdf").update(path=str(outside))
    redis = Document.objects.get(filename="Redis.pdf")
    assert client.get(f"{API}/documents/{redis.pk}/pdf").status_code == 404
