"""render_scene's error capture: no real manim invoked, subprocess.run is mocked.

Regression for the 2026-09-28 bug: manim logs hundreds of "Animation N: Partial movie file
written" INFO lines to stdout for a busy scene, while the actual traceback goes to stderr.
_trim_traceback keeps only the last 60 lines of whatever it's given, so if stdout is appended
after stderr, the real error never survives the window — the reported failure is 60 lines of
progress-log noise with no exception in it anywhere.
"""

from dataclasses import dataclass

from kl.reels import media


@dataclass
class FakeCompletedProcess:
    returncode: int
    stdout: str
    stderr: str


def test_error_survives_pages_of_stdout_noise(tmp_path, monkeypatch):
    # Far more than _trim_traceback's 60-line window, mimicking a multi-beat scene's per-animation logging.
    noisy_stdout = "\n".join(f"INFO Animation {i}: Partial movie file written" for i in range(300))
    real_traceback = "Traceback (most recent call last):\n  ...\nNameError: name 'boom' is not defined"

    def fake_run(*a, **k):
        return FakeCompletedProcess(returncode=1, stdout=noisy_stdout, stderr=real_traceback)

    monkeypatch.setattr(media.subprocess, "run", fake_run)

    result = media.render_scene("code", tmp_path / "beats.json", tmp_path / "attempt1")

    assert not result.ok
    assert "NameError: name 'boom' is not defined" in result.error


def test_error_favours_the_traceback_over_older_stdout_noise(tmp_path, monkeypatch):
    """Even when stdout alone exceeds the 60-line window, the tail must still be the traceback,
    not whatever stdout line happened to land last before stderr was appended."""
    noisy_stdout = "\n".join(f"INFO Animation {i}: Partial movie file written" for i in range(300))
    real_traceback = "Traceback (most recent call last):\n  ...\nNameError: name 'boom' is not defined"

    def fake_run(*a, **k):
        return FakeCompletedProcess(returncode=1, stdout=noisy_stdout, stderr=real_traceback)

    monkeypatch.setattr(media.subprocess, "run", fake_run)

    result = media.render_scene("code", tmp_path / "beats.json", tmp_path / "attempt1")

    assert result.error.strip().endswith("NameError: name 'boom' is not defined")
