import threading

import pytest
from django.db import connection

from content.models import Document, GenerationTask, NoteScope
from pipeline import planner, services


@pytest.mark.django_db(transaction=True)
def test_parallel_claims_never_share_a_task():
    for name in ("A.pdf", "B.pdf"):
        document = Document.objects.create(file_hash=name, filename=name, page_count=16)
        NoteScope.objects.create(document=document)
    run = services.start_run("quiz", "test", {})

    claimed, errors, barrier = [], [], threading.Barrier(6)

    def worker():
        try:
            barrier.wait()
            for _ in range(3):
                task = planner.claim("quiz", run)
                if isinstance(task, GenerationTask):
                    claimed.append(task.pk)
        except Exception as e:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(e)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(claimed) == len(set(claimed)) == 8  # 2 PDFs x 4 windows, each claimed exactly once
