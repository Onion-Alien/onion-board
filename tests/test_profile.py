"""soundboard.core.profile: a throwaway source copy in the temp folder keeps its own
profile, so a branch under test can't prune the real cache or rewrite the settings."""
import sys
import tempfile
from pathlib import Path

from soundboard.core import profile


def test_copy_in_the_temp_folder_uses_the_dev_profile(monkeypatch, tmp_path):
    monkeypatch.delenv(profile.ENV, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(profile, "ROOT", Path(tempfile.gettempdir()) / "sb-some-branch")
    assert profile.base() == tmp_path / profile.DEV_NAME


def test_other_copies_use_the_real_profile(monkeypatch, tmp_path):
    monkeypatch.delenv(profile.ENV, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(profile, "ROOT", Path(tmp_path.anchor) / "projects" / "repo")
    assert profile.base() == tmp_path / profile.NAME


def test_built_app_never_counts_as_a_scratch_copy(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert not profile.scratch_copy(Path(tempfile.gettempdir()) / "x")


def test_scratch_copy_matches_whole_folder_names():
    tmp = Path(tempfile.gettempdir())
    assert profile.scratch_copy(tmp / "sb-x")
    assert not profile.scratch_copy(Path(str(tmp) + "-other") / "sb-x")


def test_env_names_the_folder(monkeypatch, tmp_path):
    monkeypatch.setenv(profile.ENV, str(tmp_path / "mine"))
    assert profile.base() == tmp_path / "mine"
