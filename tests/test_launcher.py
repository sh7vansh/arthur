"""Tests for arthur.launcher — Chromium Process Lifecycle & Sandbox."""

import os
import shutil
import subprocess
import pytest

from arthur.errors import BrowserUnavailableError
from arthur.launcher import (
    ChromiumInstance,
    discover_chromium_binary,
    launch_chromium,
)


def test_discover_chromium_binary_finds_local_binary():
    binary = discover_chromium_binary()
    assert binary is not None
    assert os.path.exists(binary)
    assert os.access(binary, os.X_OK)


def test_discover_chromium_binary_env_override(monkeypatch):
    monkeypatch.setenv("CHROMIUM_PATH", "/non/existent/chromium/path")
    with pytest.raises(BrowserUnavailableError):
        discover_chromium_binary(fallback_system=False)


def test_discover_chromium_binary_custom_override(tmp_path):
    fake_bin = tmp_path / "fake-chrome"
    fake_bin.write_text("#!/bin/sh\necho fake chrome\n")
    fake_bin.chmod(0o755)

    res = discover_chromium_binary(custom_path=str(fake_bin))
    assert res == str(fake_bin)


def test_launch_and_cleanup_chromium_instance():
    instance: ChromiumInstance = launch_chromium()
    try:
        assert instance.is_alive
        assert instance.ws_url.startswith("ws://127.0.0.1:")
        assert instance.port > 0
        assert os.path.exists(instance.user_data_dir)
        assert os.path.exists(os.path.join(instance.user_data_dir, "DevToolsActivePort"))
    finally:
        user_data_dir = instance.user_data_dir
        instance.close()

    assert not instance.is_alive
    assert not os.path.exists(user_data_dir)
