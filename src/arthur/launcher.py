"""Headless Chromium process lifecycle and ephemeral sandbox management."""

import atexit
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import List, Optional

from arthur.errors import BrowserUnavailableError

logger = logging.getLogger("arthur.launcher")

# Global set of active instances for atexit cleanup
_ACTIVE_INSTANCES: set["ChromiumInstance"] = set()
_SIGNALS_REGISTERED = False


def _cleanup_all_active_instances() -> None:
    """Terminate and clean up all active Chromium instances."""
    for inst in list(_ACTIVE_INSTANCES):
        try:
            inst.close()
        except Exception:
            pass


def _register_signal_handlers() -> None:
    """Register signal handlers to guarantee process cleanup on termination."""
    global _SIGNALS_REGISTERED
    if _SIGNALS_REGISTERED:
        return
    _SIGNALS_REGISTERED = True

    atexit.register(_cleanup_all_active_instances)

    if hasattr(signal, "SIGINT"):
        def _sig_handler(signum: int, frame: object) -> None:
            _cleanup_all_active_instances()
            sys.exit(128 + signum)

        try:
            signal.signal(signal.SIGINT, _sig_handler)
            signal.signal(signal.SIGTERM, _sig_handler)
            if hasattr(signal, "SIGHUP"):
                signal.signal(signal.SIGHUP, _sig_handler)
        except (ValueError, AttributeError):
            # Not in main thread or unsupported platform
            pass


def discover_chromium_binary(
    custom_path: Optional[str] = None, fallback_system: bool = True
) -> str:
    """Discover local Chromium/Chrome executable path across env and system locations."""
    if custom_path:
        if os.path.isfile(custom_path) and os.access(custom_path, os.X_OK):
            return os.path.abspath(custom_path)
        raise BrowserUnavailableError(
            f"Specified Chromium executable not found or not executable: {custom_path}"
        )

    # 1. Environment variables
    for env_var in ["CHROMIUM_PATH", "CHROME_PATH", "GOOGLE_CHROME_BIN", "CHROME_BIN"]:
        path = os.environ.get(env_var)
        if path:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return os.path.abspath(path)
            if not fallback_system:
                raise BrowserUnavailableError(
                    f"Chromium binary at {env_var}={path} not found or not executable."
                )

    if not fallback_system:
        raise BrowserUnavailableError("No Chromium executable found in environment overrides.")

    # 2. Executable name search in PATH
    candidate_names = [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
        "google-chrome-unstable",
        "google-chrome-beta",
        "brave-browser",
        "brave",
        "microsoft-edge",
        "microsoft-edge-stable",
    ]
    for name in candidate_names:
        which_path = shutil.which(name)
        if which_path and os.path.isfile(which_path) and os.access(which_path, os.X_OK):
            return os.path.abspath(which_path)

    # 3. Standard platform absolute paths
    platform_paths: List[str] = []
    if sys.platform.startswith("linux"):
        platform_paths.extend(
            [
                "/usr/bin/google-chrome",
                "/usr/bin/google-chrome-stable",
                "/usr/bin/chromium",
                "/usr/bin/chromium-browser",
                "/snap/bin/chromium",
                "/var/lib/flatpak/exports/bin/org.chromium.Chromium",
                os.path.expanduser("~/.local/share/flatpak/exports/bin/org.chromium.Chromium"),
                "/usr/bin/microsoft-edge",
                "/usr/bin/microsoft-edge-stable",
            ]
        )
    elif sys.platform == "darwin":
        platform_paths.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            ]
        )
    elif sys.platform == "win32":
        for prog in [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")]:
            if prog:
                platform_paths.append(os.path.join(prog, "Google", "Chrome", "Application", "chrome.exe"))
                platform_paths.append(os.path.join(prog, "Microsoft", "Edge", "Application", "msedge.exe"))
        local_app = os.environ.get("LOCALAPPDATA", "")
        if local_app:
            platform_paths.append(os.path.join(local_app, "Google", "Chrome", "Application", "chrome.exe"))

    for p in platform_paths:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return os.path.abspath(p)

    raise BrowserUnavailableError(
        "No Chromium or Google Chrome binary found on system. "
        "Please install Chromium or set the CHROMIUM_PATH environment variable."
    )


class ChromiumInstance:
    """Manages an ephemeral Chromium subprocess lifecycle."""

    def __init__(
        self,
        process: subprocess.Popen,  # type: ignore[type-arg]
        user_data_dir: str,
        port: int,
        ws_url: str,
    ):
        self.process = process
        self.user_data_dir = user_data_dir
        self.port = port
        self.ws_url = ws_url
        self._closed = False
        _ACTIVE_INSTANCES.add(self)
        _register_signal_handlers()

    @property
    def is_alive(self) -> bool:
        """Check if subprocess is still running."""
        return not self._closed and self.process.poll() is None

    def close(self) -> None:
        """Terminate Chromium subprocess and purge user data directory."""
        if self._closed:
            return
        self._closed = True
        _ACTIVE_INSTANCES.discard(self)

        # 1. Terminate process
        if self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=3.0)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    self.process.kill()
                    self.process.wait(timeout=2.0)
                except Exception:
                    pass
            except Exception:
                pass

        # 2. Remove temporary user data directory
        if self.user_data_dir and os.path.isdir(self.user_data_dir):
            try:
                shutil.rmtree(self.user_data_dir, ignore_errors=True)
            except Exception as e:
                logger.debug("Failed to remove user data dir %s: %s", self.user_data_dir, e)


def launch_chromium(
    executable_path: Optional[str] = None,
    port: int = 0,
    user_data_dir: Optional[str] = None,
    window_size: str = "1280,800",
    extra_args: Optional[List[str]] = None,
    timeout: float = 15.0,
) -> ChromiumInstance:
    """Launch headless Chromium subprocess with ephemeral user data dir and remote debugging."""
    binary = discover_chromium_binary(executable_path)

    temp_dir_created = False
    if not user_data_dir:
        user_data_dir = tempfile.mkdtemp(prefix="arthur-chromium-")
        temp_dir_created = True

    cmd: List[str] = [
        binary,
        "--headless=new",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        f"--window-size={window_size}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-breakpad",
        "--disable-client-side-phishing-detection",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-dev-shm-usage",
        "--disable-domain-reliability",
        "--disable-extensions",
        "--disable-features=AudioServiceOutOfProcess,IsolateOrigins,site-per-process,Translate,BackForwardCache",
        "--disable-hang-monitor",
        "--disable-ipc-flooding-protection",
        "--disable-popup-blocking",
        "--disable-prompt-on-repost",
        "--disable-renderer-backgrounding",
        "--disable-sync",
        "--force-color-profile=srgb",
        "--metrics-recording-only",
        "--no-service-autorun",
        "--password-store=basic",
        "--use-mock-keychain",
        "--hide-scrollbars",
        "--mute-audio",
    ]

    # Container / root sandbox fallback
    try:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            cmd.append("--no-sandbox")
    except Exception:
        pass

    if extra_args:
        cmd.extend(extra_args)

    cmd.append("about:blank")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        if temp_dir_created and os.path.isdir(user_data_dir):
            shutil.rmtree(user_data_dir, ignore_errors=True)
        raise BrowserUnavailableError(f"Failed to launch Chromium process: {e}") from e

    # Wait for DevToolsActivePort file
    dev_tools_port_file = os.path.join(user_data_dir, "DevToolsActivePort")
    start_time = time.time()
    assigned_port: Optional[int] = None
    ws_path: Optional[str] = None

    while time.time() - start_time < timeout:
        if proc.poll() is not None:
            if temp_dir_created and os.path.isdir(user_data_dir):
                shutil.rmtree(user_data_dir, ignore_errors=True)
            raise BrowserUnavailableError(
                f"Chromium process exited prematurely with code {proc.returncode}."
            )

        if os.path.isfile(dev_tools_port_file):
            try:
                with open(dev_tools_port_file, "r", encoding="utf-8") as f:
                    lines = [line.strip() for line in f.readlines() if line.strip()]
                if len(lines) >= 2:
                    assigned_port = int(lines[0])
                    ws_path = lines[1]
                    break
            except Exception:
                pass
        time.sleep(0.05)

    if assigned_port is None or not ws_path:
        # Cleanup
        try:
            proc.terminate()
            proc.wait(timeout=2.0)
        except Exception:
            pass
        if temp_dir_created and os.path.isdir(user_data_dir):
            shutil.rmtree(user_data_dir, ignore_errors=True)
        raise BrowserUnavailableError(
            f"Timed out after {timeout:.1f}s waiting for Chromium DevToolsActivePort initialization."
        )

    # If ws_path doesn't start with '/', add it
    if not ws_path.startswith("/"):
        ws_path = f"/{ws_path}"

    ws_url = f"ws://127.0.0.1:{assigned_port}{ws_path}"

    return ChromiumInstance(
        process=proc,
        user_data_dir=user_data_dir,
        port=assigned_port,
        ws_url=ws_url,
    )
