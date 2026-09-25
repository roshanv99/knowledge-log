import pytest


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, settings):
    """Every test stores files on local disk under its own tmp dir, whatever .env says: no test
    may reach R2 or the real media folder."""
    settings.STORAGE_BACKEND = "local"
    settings.MEDIA_ROOT = tmp_path / "media"
