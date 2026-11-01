"""NFR-2: tests never resolve to the real (or dev) data folder."""

from __future__ import annotations

import pytest

from weaksquare import config


def test_tests_use_a_temp_folder(temp_data_dir) -> None:
    assert config.resolve_paths(dev=False).data_dir == temp_data_dir.resolve()


@pytest.mark.parametrize("dev", [False, True])
def test_real_folders_refused_under_pytest(monkeypatch: pytest.MonkeyPatch, dev: bool) -> None:
    monkeypatch.delenv(config.DATA_DIR_ENV)
    with pytest.raises(config.DataDirError):
        config.resolve_paths(dev=dev)


def test_override_pointing_at_real_folder_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(config.DATA_DIR_ENV, str(config.default_data_dir(False)))
    with pytest.raises(config.DataDirError):
        config.resolve_paths(dev=True)


def test_defaults() -> None:
    assert config.default_data_dir(False).name == "WeakSquare"
    assert config.default_data_dir(True).name == "WeakSquare-dev"
    assert "Local" in str(config.default_data_dir(False))  # %LOCALAPPDATA%, not Roaming
