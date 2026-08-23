"""Synchronous Python Browser API and Tab Management for Arthur."""

import asyncio
import base64
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from arthur.cdp import CDPClient
from arthur.dom import (
    DOMSnapshotResult,
    dom_get_attribute,
    dom_get_text,
    generate_snapshot,
    get_dom_metrics,
    resolve_target_coordinates,
)
from arthur.errors import (
    ActionInterceptionError,
    ArthurError,
    BrowserUnavailableError,
    CDPError,
    ElementNotFoundError,
    NavigationTimeoutError,
)
from arthur.input import (
    cdp_click,
    cdp_hover,
    cdp_press_key,
    cdp_scroll,
    cdp_select,
    cdp_type,
)
from arthur.launcher import ChromiumInstance, launch_chromium

logger = logging.getLogger("arthur.browser")


class _AsyncCDPRunner:
    """Manages the async CDP event loop running in a dedicated background daemon thread."""

    def __init__(self, executable_path: Optional[str] = None):
        self.executable_path = executable_path
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run_loop, name="arthur-cdp-daemon", daemon=True
        )
        self.instance: Optional[ChromiumInstance] = None
        self.cdp = CDPClient()
        self.tab_manager = TabManager(self)
        self._started = threading.Event()
        self._closed = False
        self._init_error: Optional[Exception] = None

        self.thread.start()
        self._started.wait(timeout=20.0)
        if self._init_error:
            raise self._init_error

    def _run_loop(self) -> None:
        """Run asyncio event loop in daemon thread."""
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._async_init())
            self._started.set()
            self.loop.run_forever()
        except Exception as e:
            self._init_error = e
            self._started.set()
        finally:
            self.loop.run_until_complete(self._async_teardown())

    async def _async_init(self) -> None:
        """Initialize Chromium instance, CDP client, and root session."""
        self.instance = launch_chromium(executable_path=self.executable_path)
        await self.cdp.connect(self.instance.ws_url)

        # Connect tab manager to CDP target lifecycle events
        self.cdp.on("Target.targetCreated", self.tab_manager._on_target_created)
        self.cdp.on("Target.targetDestroyed", self.tab_manager._on_target_destroyed)
        self.cdp.on("Target.targetInfoChanged", self.tab_manager._on_target_info_changed)

        await self.cdp.call("Target.setDiscoverTargets", {"discover": True})

        # Discover initial page target
        targets = await self.cdp.call("Target.getTargets")
        page_targets = [
            t for t in targets.get("targetInfos", []) if t.get("type") == "page"
        ]

        if page_targets:
            first_target = page_targets[0]
            target_id = first_target["targetId"]
            session_id = await self.cdp.attach_to_target(target_id)
            self.tab_manager.register_initial_target(
                target_id=target_id,
                session_id=session_id,
                url=first_target.get("url", "about:blank"),
                title=first_target.get("title", ""),
            )
            await self.cdp.call("Page.enable", session_id=session_id)
            await self.cdp.call("Runtime.enable", session_id=session_id)

    async def _async_teardown(self) -> None:
        """Close connections and kill browser."""
        if self.cdp.is_connected:
            try:
                await self.cdp.close()
            except Exception:
                pass
        if self.instance:
            try:
                self.instance.close()
            except Exception:
                pass

    def run_coro(self, coro: Any, timeout: Optional[float] = None) -> Any:
        """Run coroutine in daemon loop thread-safely."""
        if self._closed or not self.loop.is_running():
            raise BrowserUnavailableError("Browser background event loop is closed.")
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=timeout)
        except TimeoutError as e:
            raise NavigationTimeoutError(f"Operation timed out: {e}") from e
        except Exception:
            raise

    def close(self) -> None:
        """Shut down background thread and browser."""
        if self._closed:
            return
        self._closed = True
        if self.loop.is_running():
            fut = asyncio.run_coroutine_threadsafe(self._async_teardown(), self.loop)
            try:
                fut.result(timeout=3.0)
            except Exception:
                pass
            self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=3.0)


class TabManager:
    """Encapsulates browser tab collection, lifecycle events, and active tab state."""

    def __init__(self, runner: _AsyncCDPRunner):
        self._runner = runner
        self._tabs_lock = threading.RLock()
        self._tab_seq = 0
        # target_id -> tab_info dict
        self._tabs: Dict[str, Dict[str, Any]] = {}
        self._active_target_id: Optional[str] = None

    def register_initial_target(
        self, target_id: str, session_id: str, url: str = "about:blank", title: str = ""
    ) -> None:
        with self._tabs_lock:
            if target_id not in self._tabs:
                self._tab_seq += 1
                self._tabs[target_id] = {
                    "id": self._tab_seq,
                    "target_id": target_id,
                    "session_id": session_id,
                    "url": url,
                    "title": title,
                }
            else:
                self._tabs[target_id]["session_id"] = session_id
                if url:
                    self._tabs[target_id]["url"] = url
                if title:
                    self._tabs[target_id]["title"] = title
            self._active_target_id = target_id

    def _on_target_created(self, params: Dict[str, Any]) -> None:
        t_info = params.get("targetInfo", {})
        if t_info.get("type") != "page":
            return
        target_id = t_info["targetId"]
        with self._tabs_lock:
            if target_id not in self._tabs:
                self._tab_seq += 1
                self._tabs[target_id] = {
                    "id": self._tab_seq,
                    "target_id": target_id,
                    "session_id": None,
                    "url": t_info.get("url", "about:blank"),
                    "title": t_info.get("title", ""),
                }

    def _on_target_destroyed(self, params: Dict[str, Any]) -> None:
        target_id = params.get("targetId")
        if target_id:
            with self._tabs_lock:
                self._tabs.pop(str(target_id), None)
                if self._active_target_id == target_id:
                    self._active_target_id = (
                        next(iter(self._tabs.keys())) if self._tabs else None
                    )

    def _on_target_info_changed(self, params: Dict[str, Any]) -> None:
        t_info = params.get("targetInfo", {})
        target_id = t_info.get("targetId")
        if target_id:
            with self._tabs_lock:
                if target_id in self._tabs:
                    self._tabs[target_id]["url"] = t_info.get("url", self._tabs[target_id]["url"])
                    self._tabs[target_id]["title"] = t_info.get("title", self._tabs[target_id]["title"])

    def list_tabs(self) -> List["Tab"]:
        with self._tabs_lock:
            return [Tab(self._runner, self, tid) for tid in self._tabs.keys()]

    def get_tab(self, tab_id: Union[int, str]) -> "Tab":
        with self._tabs_lock:
            numeric_id: Optional[int] = None
            try:
                numeric_id = int(tab_id)
            except (ValueError, TypeError):
                numeric_id = None

            for tid, info in self._tabs.items():
                if numeric_id is not None and info["id"] == numeric_id:
                    return Tab(self._runner, self, tid)
                if tid == str(tab_id):
                    return Tab(self._runner, self, tid)
        raise BrowserUnavailableError(f"Tab matching '{tab_id}' not found.")

    def get_active_tab(self) -> "Tab":
        with self._tabs_lock:
            if self._active_target_id and self._active_target_id in self._tabs:
                return Tab(self._runner, self, self._active_target_id)
            if self._tabs:
                tid = next(iter(self._tabs.keys()))
                self._active_target_id = tid
                return Tab(self._runner, self, tid)
        raise BrowserUnavailableError("No active browser tabs available.")

    def create_tab(self, url: Optional[str] = None) -> "Tab":
        async def _new() -> str:
            res = await self._runner.cdp.call(
                "Target.createTarget", {"url": "about:blank"}
            )
            target_id = str(res["targetId"])
            sess_id = await self._runner.cdp.attach_to_target(target_id)
            await self._runner.cdp.call("Page.enable", session_id=sess_id)
            await self._runner.cdp.call("Runtime.enable", session_id=sess_id)
            with self._tabs_lock:
                if target_id not in self._tabs:
                    self._tab_seq += 1
                    self._tabs[target_id] = {
                        "id": self._tab_seq,
                        "target_id": target_id,
                        "session_id": sess_id,
                        "url": "about:blank",
                        "title": "",
                    }
                else:
                    self._tabs[target_id]["session_id"] = sess_id
                self._active_target_id = target_id
            return target_id

        tid = str(self._runner.run_coro(_new()))
        t = Tab(self._runner, self, tid)
        if url:
            t.navigate(url)
        return t

    def close_tab(self, tab_id: Union[int, str]) -> None:
        t = self.get_tab(tab_id)
        t.close()

    def ensure_session_id(self, target_id: str) -> str:
        with self._tabs_lock:
            info = self._tabs.get(target_id)
            if not info:
                raise BrowserUnavailableError(f"Tab {target_id} no longer exists.")
            if info.get("session_id"):
                return str(info["session_id"])

        async def _attach() -> str:
            sess_id = await self._runner.cdp.attach_to_target(target_id)
            await self._runner.cdp.call("Page.enable", session_id=sess_id)
            await self._runner.cdp.call("Runtime.enable", session_id=sess_id)
            with self._tabs_lock:
                if target_id in self._tabs:
                    self._tabs[target_id]["session_id"] = sess_id
            return sess_id

        return str(self._runner.run_coro(_attach()))

    def update_tab_info(self, target_id: str, url: str, title: str) -> None:
        with self._tabs_lock:
            if target_id in self._tabs:
                self._tabs[target_id]["url"] = url
                self._tabs[target_id]["title"] = title


class TabMedia:
    """Fast-path media controller attached to a Tab instance.

    Provides zero-DOM-overhead media control for HTML5 <video> / <audio> elements
    and the browser MediaSession API. Directly penetrates open shadow roots (e.g.
    YouTube, Spotify, Netflix web players) without generating expensive DOM snapshots.

    Example:
        >>> # Check playback state and metadata
        >>> print(browser.media.status())
        >>> 
        >>> # Toggle play/pause
        >>> browser.media.toggle()
        >>> 
        >>> # Relative seek (+15s forward or -10s backward)
        >>> browser.media.seek(15.0)
        >>> 
        >>> # Set volume level (0.0 to 1.0)
        >>> browser.media.set_volume(0.8)
    """

    _FIND_MEDIA_JS = """
    function findMediaElement(root = document) {
        let el = root.querySelector('video, audio');
        if (el) return el;
        const all = root.querySelectorAll('*');
        for (const node of all) {
            if (node.shadowRoot) {
                const nested = findMediaElement(node.shadowRoot);
                if (nested) return nested;
            }
        }
        return null;
    }
    """

    def __init__(self, tab: "Tab"):
        self._tab = tab

    def status(self) -> Dict[str, Any]:
        """Fetch real-time media player state via HTML5 Video/Audio & MediaSession APIs.

        Returns:
            Dict containing `found` (bool), `paused` (bool), `currentTime` (float),
            `duration` (float), `volume` (float), `muted` (bool), `title` (str),
            `artist` (str), `album` (str), and `playbackState` ('playing', 'paused', 'none').

        Example:
            >>> state = browser.media.status()
            >>> print(f"Now playing: {state.get('title')} (paused: {state.get('paused')})")
        """
        js = f"""
        (() => {{
            {self._FIND_MEDIA_JS}

            const media = findMediaElement();
            const session = navigator.mediaSession;
            return {{
                found: !!media,
                paused: media ? media.paused : null,
                currentTime: media ? media.currentTime : null,
                duration: media ? media.duration : null,
                volume: media ? media.volume : null,
                muted: media ? media.muted : null,
                title: session?.metadata?.title || document.title,
                artist: session?.metadata?.artist || "",
                album: session?.metadata?.album || "",
                playbackState: session?.playbackState || (media ? (media.paused ? "paused" : "playing") : "none")
            }};
        }})()
        """
        res = self._tab.eval_js(js)
        return res if isinstance(res, dict) else {}

    def toggle(self) -> Dict[str, Any]:
        """Toggle play/pause on the active media element.

        Returns:
            Dict with `success` (bool) and `action` ('played' or 'paused').

        Example:
            >>> browser.media.toggle()
        """
        js = f"""
        (() => {{
            {self._FIND_MEDIA_JS}
            const media = findMediaElement();
            if (!media) return {{success: false, error: "No media element found"}};
            if (media.paused) {{
                media.play();
                return {{success: true, action: "played"}};
            }} else {{
                media.pause();
                return {{success: true, action: "paused"}};
            }}
        }})()
        """
        res = self._tab.eval_js(js)
        return res if isinstance(res, dict) else {"success": False, "error": "Evaluation failed"}

    def play(self) -> Dict[str, Any]:
        """Resume playback on the active media element.

        Example:
            >>> browser.media.play()
        """
        js = f"""
        (() => {{
            {self._FIND_MEDIA_JS}
            const v = findMediaElement();
            if (v) {{ v.play(); return {{success: true}}; }}
            return {{success: false, error: "No media element found"}};
        }})()
        """
        res = self._tab.eval_js(js)
        return res if isinstance(res, dict) else {"success": False, "error": "Evaluation failed"}

    def pause(self) -> Dict[str, Any]:
        """Pause playback on the active media element.

        Example:
            >>> browser.media.pause()
        """
        js = f"""
        (() => {{
            {self._FIND_MEDIA_JS}
            const v = findMediaElement();
            if (v) {{ v.pause(); return {{success: true}}; }}
            return {{success: false, error: "No media element found"}};
        }})()
        """
        res = self._tab.eval_js(js)
        return res if isinstance(res, dict) else {"success": False, "error": "Evaluation failed"}

    def seek(self, seconds: float) -> Dict[str, Any]:
        """Seek relative (+/- seconds) or step playback time.

        Args:
            seconds: Relative time delta in seconds (e.g. +15.0 to skip ahead, -10.0 to rewind).

        Returns:
            Dict with `success` (bool) and updated `currentTime` (float).

        Example:
            >>> browser.media.seek(15.0)  # Skip 15s forward
            >>> browser.media.seek(-10.0) # Rewind 10s
        """
        js = f"""
        (() => {{
            {self._FIND_MEDIA_JS}
            const v = findMediaElement();
            if (!v) return {{success: false, error: "No media element found"}};
            v.currentTime += {float(seconds)};
            return {{success: true, currentTime: v.currentTime}};
        }})()
        """
        res = self._tab.eval_js(js)
        return res if isinstance(res, dict) else {"success": False, "error": "Evaluation failed"}

    def set_volume(self, volume: float) -> Dict[str, Any]:
        """Set media volume level between 0.0 (muted) and 1.0 (max).

        Args:
            volume: Float volume value from 0.0 to 1.0.

        Returns:
            Dict with `success` (bool) and updated `volume` (float).

        Example:
            >>> browser.media.set_volume(0.75)
        """
        vol = max(0.0, min(1.0, float(volume)))
        js = f"""
        (() => {{
            {self._FIND_MEDIA_JS}
            const v = findMediaElement();
            if (v) {{ v.volume = {vol}; v.muted = false; return {{success: true, volume: v.volume}}; }}
            return {{success: false, error: "No media element found"}};
        }})()
        """
        res = self._tab.eval_js(js)
        return res if isinstance(res, dict) else {"success": False, "error": "Evaluation failed"}


class Tab:
    """Scoped synchronous representation of an active browser tab.

    Provides high-level DOM interactions, Ref-ID resolution, navigation,
    and media fast-paths scoped to a single browser tab.

    Example:
        >>> tab = browser.active_tab
        >>> print(tab.snapshot())
        >>> tab.type(2, "Documentation", press_enter=True)
        >>> tab.wait_for_url(r"/docs")
        >>> data = tab.get_text(3)
    """

    def __init__(self, runner: _AsyncCDPRunner, tab_manager: TabManager, target_id: str):
        self._runner = runner
        self._tab_manager = tab_manager
        self._target_id = target_id
        self._media_controller: Optional[TabMedia] = None

    @property
    def target_id(self) -> str:
        """Target ID assigned by Chromium CDP."""
        return self._target_id

    @property
    def id(self) -> int:
        """Sequential integer tab ID assigned by Arthur."""
        with self._tab_manager._tabs_lock:
            info = self._tab_manager._tabs.get(self._target_id)
            return info["id"] if info else 0

    @property
    def url(self) -> str:
        """Current URL of the tab."""
        try:
            val = self.eval_js("window.location.href")
            if val:
                with self._tab_manager._tabs_lock:
                    if self._target_id in self._tab_manager._tabs:
                        self._tab_manager._tabs[self._target_id]["url"] = str(val)
                return str(val)
        except Exception:
            pass
        with self._tab_manager._tabs_lock:
            info = self._tab_manager._tabs.get(self._target_id)
            return info.get("url", "") if info else ""

    @property
    def title(self) -> str:
        """Current document title of the tab."""
        try:
            val = self.eval_js("document.title")
            if val is not None:
                with self._tab_manager._tabs_lock:
                    if self._target_id in self._tab_manager._tabs:
                        self._tab_manager._tabs[self._target_id]["title"] = str(val)
                return str(val)
        except Exception:
            pass
        with self._tab_manager._tabs_lock:
            info = self._tab_manager._tabs.get(self._target_id)
            return info.get("title", "") if info else ""

    @property
    def media(self) -> TabMedia:
        """Fast-path media controller for HTML5 audio/video and MediaSession APIs."""
        if self._media_controller is None:
            self._media_controller = TabMedia(self)
        return self._media_controller

    def _ensure_session_id(self) -> str:
        return self._tab_manager.ensure_session_id(self._target_id)

    def navigate(self, url: str, timeout: float = 30.0) -> str:
        """Navigate tab to URL and wait for page load lifecycle.

        Args:
            url: Web address to navigate to (e.g. "https://example.com").
            timeout: Maximum seconds to wait for page load. Default is 30.0.

        Returns:
            Resolved current URL after navigation.

        Example:
            >>> browser.navigate("https://example.com")
        """
        session_id = self._ensure_session_id()

        async def _nav() -> str:
            load_future: asyncio.Future[None] = self._runner.loop.create_future()

            def _on_load(params: Dict[str, Any]) -> None:
                if not load_future.done():
                    load_future.set_result(None)

            self._runner.cdp.once("Page.loadEventFired", _on_load, session_id=session_id)
            self._runner.cdp.once("Page.domContentEventFired", _on_load, session_id=session_id)

            try:
                nav_res = await self._runner.cdp.call(
                    "Page.navigate", {"url": url}, session_id=session_id
                )
                loader_id = nav_res.get("loaderId")
                if loader_id:
                    try:
                        await asyncio.wait_for(load_future, timeout=min(timeout, 10.0))
                    except asyncio.TimeoutError:
                        pass
                else:
                    await asyncio.sleep(0.05)
            finally:
                self._runner.cdp.off("Page.loadEventFired", _on_load, session_id=session_id)
                self._runner.cdp.off("Page.domContentEventFired", _on_load, session_id=session_id)

            snap_res = await generate_snapshot(self._runner.cdp, session_id=session_id)
            self._tab_manager.update_tab_info(self._target_id, snap_res.url, snap_res.title)
            return snap_res.url

        return str(self._runner.run_coro(_nav(), timeout=timeout + 5.0))

    def snapshot(self) -> str:
        """Generate semantic DOM snapshot outline with deterministic [#N] Ref-IDs.

        Returns:
            Formatted semantic accessibility tree string.

        Example:
            >>> print(browser.snapshot())
        """
        session_id = self._ensure_session_id()

        async def _snap() -> str:
            res: DOMSnapshotResult = await generate_snapshot(
                self._runner.cdp, session_id=session_id
            )
            self._tab_manager.update_tab_info(self._target_id, res.url, res.title)
            return res.snapshot

        return str(self._runner.run_coro(_snap()))

    def click(
        self,
        target: Union[int, str],
        button: str = "left",
        count: int = 1,
    ) -> Dict[str, Any]:
        """Click element by Ref-ID (integer or '[#N]') or CSS selector.

        Args:
            target: Element locator (e.g. `1`, `"[#1]"`, or `"button.submit"`).
            button: Mouse button ('left', 'middle', 'right'). Default is 'left'.
            count: Number of clicks (1 for single click, 2 for double click).

        Returns:
            CDP response dictionary.

        Example:
            >>> browser.click(1)
            >>> browser.click("[#2]")
            >>> browser.click("button#submit-btn")
        """
        session_id = self._ensure_session_id()

        async def _do_click() -> Dict[str, Any]:
            loading = False
            stopped = False
            stop_future = self._runner.loop.create_future()

            def _on_load_start(*args, **kwargs) -> None:
                nonlocal loading
                loading = True

            def _on_load_stop(*args, **kwargs) -> None:
                nonlocal stopped
                stopped = True
                if not stop_future.done():
                    stop_future.set_result(None)

            self._runner.cdp.on("Page.frameStartedLoading", _on_load_start, session_id=session_id)
            self._runner.cdp.on("Page.frameStoppedLoading", _on_load_stop, session_id=session_id)
            self._runner.cdp.on("Page.loadEventFired", _on_load_stop, session_id=session_id)

            res = await cdp_click(
                self._runner.cdp,
                target,
                button=button,
                click_count=count,
                session_id=session_id,
            )


            await asyncio.sleep(0.15)
            self._runner.cdp.off("Page.frameStartedLoading", _on_load_start, session_id=session_id)

            if loading and not stopped:
                try:
                    await asyncio.wait_for(stop_future, timeout=15.0)
                except asyncio.TimeoutError:
                    pass

            self._runner.cdp.off("Page.frameStoppedLoading", _on_load_stop, session_id=session_id)
            self._runner.cdp.off("Page.loadEventFired", _on_load_stop, session_id=session_id)
            return res  # type: ignore[no-any-return]

        return self._runner.run_coro(_do_click())

    def type(
        self,
        target: Union[int, str],
        text: str,
        clear: bool = True,
        press_enter: bool = False,
    ) -> Dict[str, Any]:
        """Type text into an input element.

        Args:
            target: Element locator (e.g. `2`, `"[#2]"`, or `"input[name='q']"`).
            text: String text to type into the element.
            clear: If True, selects and clears existing content before typing.
            press_enter: If True, sends an 'Enter' keypress after typing.

        Returns:
            CDP response dictionary.

        Example:
            >>> browser.type(2, "search query", press_enter=True)
        """
        session_id = self._ensure_session_id()

        async def _do_type() -> Dict[str, Any]:
            loading = False
            stopped = False
            stop_future = self._runner.loop.create_future()

            def _on_load_start(*args, **kwargs) -> None:
                nonlocal loading
                loading = True

            def _on_load_stop(*args, **kwargs) -> None:
                nonlocal stopped
                stopped = True
                if not stop_future.done():
                    stop_future.set_result(None)

            if press_enter:
                self._runner.cdp.on("Page.frameStartedLoading", _on_load_start, session_id=session_id)
                self._runner.cdp.on("Page.frameStoppedLoading", _on_load_stop, session_id=session_id)
                self._runner.cdp.on("Page.loadEventFired", _on_load_stop, session_id=session_id)

            res = await cdp_type(
                self._runner.cdp,
                target,
                text,
                clear=clear,
                press_enter=press_enter,
                session_id=session_id,
            )


            if press_enter:
                await asyncio.sleep(0.15)
                self._runner.cdp.off("Page.frameStartedLoading", _on_load_start, session_id=session_id)

                if loading and not stopped:
                    try:
                        await asyncio.wait_for(stop_future, timeout=15.0)
                    except asyncio.TimeoutError:
                        pass

                self._runner.cdp.off("Page.frameStoppedLoading", _on_load_stop, session_id=session_id)
                self._runner.cdp.off("Page.loadEventFired", _on_load_stop, session_id=session_id)

            return res  # type: ignore[no-any-return]

        return self._runner.run_coro(_do_type())

    def select(self, target: Union[int, str], value: str) -> Dict[str, Any]:
        """Select an option in a dropdown (<select>) element.

        Args:
            target: Element locator for the <select> element.
            value: Option value or label text to select.

        Returns:
            CDP response dictionary.

        Example:
            >>> browser.select(5, "Option B")
        """
        session_id = self._ensure_session_id()
        return self._runner.run_coro(  # type: ignore[no-any-return]
            cdp_select(self._runner.cdp, target, value, session_id=session_id)
        )

    def hover(self, target: Union[int, str]) -> Dict[str, Any]:
        """Hover mouse cursor over target element.

        Args:
            target: Element locator (e.g. `8`, `"[#8]"`, or `".dropdown-toggle"`).

        Returns:
            CDP response dictionary.

        Example:
            >>> browser.hover(8)
        """
        session_id = self._ensure_session_id()
        return self._runner.run_coro(  # type: ignore[no-any-return]
            cdp_hover(self._runner.cdp, target, session_id=session_id)
        )

    def scroll(
        self,
        x: int = 0,
        y: int = 500,
        target: Optional[Union[int, str]] = None,
    ) -> Dict[str, Any]:
        """Scroll viewport or a specific scrollable container element.

        Args:
            x: Horizontal pixel delta to scroll. Default is 0.
            y: Vertical pixel delta to scroll. Default is 500.
            target: Optional container locator to scroll within.

        Returns:
            CDP response dictionary.

        Example:
            >>> browser.scroll(y=800)
            >>> browser.scroll(y=300, target="[#feed-container]")
        """
        session_id = self._ensure_session_id()
        return self._runner.run_coro(  # type: ignore[no-any-return]
            cdp_scroll(self._runner.cdp, x=x, y=y, target=target, session_id=session_id)
        )

    def eval_js(self, expression: str) -> Any:
        """Evaluate arbitrary JavaScript expression directly in the tab context.

        Args:
            expression: JavaScript expression string to evaluate.

        Returns:
            JSON-serializable result of the JavaScript evaluation.

        Example:
            >>> title = browser.eval_js("document.title")
            >>> items = browser.eval_js("Array.from(document.querySelectorAll('h3')).map(e => e.innerText)")
        """
        session_id = self._ensure_session_id()

        async def _eval() -> Any:
            res = await self._runner.cdp.call(
                "Runtime.evaluate",
                {
                    "expression": expression,
                    "returnByValue": True,
                    "awaitPromise": True,
                },
                session_id=session_id,
            )
            result = res.get("result", {})
            if "exceptionDetails" in res:
                ex = res["exceptionDetails"]
                raise CDPError(f"JavaScript evaluation exception: {ex}")
            return result.get("value")

        return self._runner.run_coro(_eval())

    def screenshot(self, format: str = "png") -> bytes:
        """Capture screenshot of the viewport as raw bytes.

        Args:
            format: Image format ('png' or 'jpeg'). Default is 'png'.

        Returns:
            Raw image bytes.

        Example:
            >>> png_data = browser.screenshot()
        """
        session_id = self._ensure_session_id()

        async def _ss() -> bytes:
            res = await self._runner.cdp.call(
                "Page.captureScreenshot",
                {"format": format},
                session_id=session_id,
            )
            data_b64 = res.get("data", "")
            return base64.b64decode(data_b64)

        return bytes(self._runner.run_coro(_ss()))

    def get_text(self, target: Union[int, str]) -> str:
        """Extract inner text content of an element.

        Args:
            target: Element locator (e.g. `3`, `"[#3]"`, or `"h1"`).

        Returns:
            Extracted text content string.

        Example:
            >>> text = browser.get_text(3)
        """
        session_id = self._ensure_session_id()
        return str(self._runner.run_coro(dom_get_text(self._runner.cdp, target, session_id=session_id)))

    def get_attribute(self, target: Union[int, str], name: str) -> Optional[str]:
        """Retrieve the value of an element DOM attribute.

        Args:
            target: Element locator (e.g. `3`, `"[#3]"`, or `"a.download"`).
            name: Name of the attribute (e.g. 'href', 'src', 'data-id').

        Returns:
            Attribute value as a string, or None if not found.

        Example:
            >>> link = browser.get_attribute(3, "href")
        """
        session_id = self._ensure_session_id()
        return self._runner.run_coro(dom_get_attribute(self._runner.cdp, target, name, session_id=session_id))  # type: ignore[no-any-return]

    def wait_for(
        self,
        target: Union[int, str],
        state: str = "visible",
        timeout: float = 10.0,
    ) -> bool:
        """Synchronously wait for an element to reach a target lifecycle state."""
        session_id = self._ensure_session_id()
        
        async def _do_wait() -> bool:
            from arthur.dom import evaluate_dom_operation
            res = await evaluate_dom_operation(
                self._runner.cdp,
                "wait_for",
                {"target": target, "state": state, "timeout": timeout},
                session_id=session_id
            )
            if isinstance(res, dict) and "__error" in res:
                err = res["__error"]
                if err.get("code") == "TIMEOUT":
                    raise NavigationTimeoutError(
                        target=err.get("target", str(target)),
                        timeout=err.get("timeout", timeout),
                        url=err.get("url", self.url),
                        ready_state=err.get("readyState", "unknown"),
                        dom_state=err.get("domState", f"condition '{state}' not met"),
                    )
                raise CDPError(f"Wait failed: {err}")
            return True
            
        return self._runner.run_coro(_do_wait())

    def wait_for_url(self, pattern: str, timeout: float = 15.0) -> str:
        r"""Synchronously wait until the page URL matches a regex pattern.

        Args:
            pattern: Regex pattern to match against current URL.
            timeout: Maximum seconds to wait before timing out. Default is 15.0.

        Returns:
            Matching current URL string.

        Example:
            >>> browser.wait_for_url(r"github\.com/settings")
        """
        regex = re.compile(pattern)
        start = time.time()

        while time.time() - start < timeout:
            cur_url = self.url
            if regex.search(cur_url):
                return cur_url
            time.sleep(0.1)

        raise NavigationTimeoutError(
            target=pattern,
            timeout=timeout,
            url=self.url,
            dom_state=f"did not match pattern '{pattern}'",
            tab_id=self.id,
        )

    def close(self) -> None:
        """Close this tab."""
        async def _close_tab() -> None:
            await self._runner.cdp.call(
                "Target.closeTarget", {"targetId": self._target_id}
            )

        self._runner.run_coro(_close_tab())



    def extract_items(
        self,
        container_selector: str,
        fields: dict,
    ) -> list:
        """Extract structured data rows and attributes across repeated container elements in a single JS pass."""
        import json
        js_payload = f"""
        (() => {{
            const containerSelector = {json.dumps(container_selector)};
            const fields = {json.dumps(fields)};
            const containers = Array.from(document.querySelectorAll(containerSelector));
            const results = [];

            for (const container of containers) {{
                const row = {{}};
                for (const [key, fieldSel] of Object.entries(fields)) {{
                    let targetEl = container;
                    let attrName = null;
                    let sel = (fieldSel || '').trim();

                    if (sel.includes('@')) {{
                        const parts = sel.split('@');
                        const subSel = parts[0].trim();
                        attrName = parts[1].trim();
                        if (subSel && subSel !== '.' && subSel !== 'self' && subSel.toLowerCase() !== 'text') {{
                            targetEl = container.querySelector(subSel);
                        }}
                    }} else if (sel && sel !== '.' && sel !== 'self' && sel.toLowerCase() !== 'text') {{
                        targetEl = container.querySelector(sel);
                    }}

                    if (!targetEl) {{
                        row[key] = "";
                    }} else if (attrName) {{
                        if (attrName.toLowerCase() === 'text') {{
                            row[key] = (targetEl.innerText || targetEl.textContent || "").trim();
                        }} else {{
                            const val = targetEl.getAttribute(attrName);
                            row[key] = (val !== null && val !== undefined ? val : "").toString().trim();
                        }}
                    }} else {{
                        row[key] = (targetEl.innerText || targetEl.textContent || "").trim();
                    }}
                }}
                results.push(row);
            }}
            return results;
        }})()
        """
        res = self.eval_js(js_payload)
        return res if res else []

    def fill_form(
        self,
        mapping: dict,
        submit: str | bool | None = None,
    ) -> dict:
        """Fill an entire form and optionally submit in a single roundtrip."""
        import json
        _DISCOVERY_HELPER_JS = """
function __cb_is_visible(el, style) {
    if (!el || el.nodeType !== 1) return false;
    if (el.hasAttribute('hidden') || el.getAttribute('aria-hidden') === 'true' || el.hasAttribute('inert')) return false;
    if (typeof el.checkVisibility === 'function') {
        if (!el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) {
            if (el.tagName === 'INPUT' && (el.type === 'checkbox' || el.type === 'radio')) return true;
            return false;
        }
    }
    if (!style) style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.visibility === 'collapse' || parseFloat(style.opacity) < 0.05) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) {
        if (el.tagName === 'INPUT' && (el.type === 'checkbox' || el.type === 'radio')) return true;
        return false;
    }
    return true;
}

function __cb_get_accessible_name(el) {
    if (!el) return '';
    const labelledby = el.getAttribute('aria-labelledby');
    if (labelledby) {
        const parts = labelledby.split(/\\s+/).map(id => document.getElementById(id)?.innerText?.trim()).filter(Boolean);
        if (parts.length > 0) return parts.join(' ');
    }
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel && ariaLabel.trim()) return ariaLabel.trim();

    if (el.id && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT')) {
        try {
            const labelEl = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
            if (labelEl && labelEl.innerText.trim()) return labelEl.innerText.trim();
        } catch(e) {}
    }
    const parentLabel = el.closest('label');
    if (parentLabel && parentLabel.innerText.trim()) return parentLabel.innerText.trim();

    if (el.getAttribute('placeholder')) return el.getAttribute('placeholder').trim();
    if (el.getAttribute('title')) return el.getAttribute('title').trim();
    if (el.getAttribute('alt')) return el.getAttribute('alt').trim();

    if (['BUTTON', 'A', 'SUMMARY', 'OPTION'].includes(el.tagName)) {
        const fullText = (el.innerText || el.textContent || '').trim();
        if (fullText) return fullText.slice(0, 120);
    }
    return (el.innerText || el.textContent || el.value || '').trim().slice(0, 120);
}

function __cb_get_computed_role(el) {
    if (!el) return 'generic';
    const explicitRole = el.getAttribute('role');
    if (explicitRole) return explicitRole.toLowerCase().trim();

    const tag = el.tagName.toLowerCase();
    switch (tag) {
        case 'a': return el.hasAttribute('href') ? 'link' : 'generic';
        case 'button': return 'button';
        case 'input': {
            const type = (el.getAttribute('type') || 'text').toLowerCase();
            if (['button', 'submit', 'reset', 'image'].includes(type)) return 'button';
            if (type === 'checkbox') return 'checkbox';
            if (type === 'radio') return 'radio';
            if (type === 'search') return 'searchbox';
            return 'textbox';
        }
        case 'select': return 'combobox';
        case 'textarea': return 'textbox';
        case 'summary': return 'button';
        case 'details': return 'group';
        case 'h1': return 'heading[level=1]';
        case 'h2': return 'heading[level=2]';
        case 'h3': return 'heading[level=3]';
        case 'h4': return 'heading[level=4]';
        case 'h5': return 'heading[level=5]';
        case 'h6': return 'heading[level=6]';
        case 'nav': return 'navigation';
        case 'main': return 'main';
        case 'header': return 'banner';
        case 'footer': return 'contentinfo';
        case 'form': return 'form';
        case 'table': return 'table';
        default: return 'generic';
    }
}

function __cb_tag(el) {
    if (!el) return null;
    if (!window.__cb_handle_counter) window.__cb_handle_counter = 0;
    let bridgeId = el.getAttribute('data-cbridge-id');
    if (!bridgeId) {
        bridgeId = 'cb_' + (++window.__cb_handle_counter) + '_' + Date.now().toString(36);
        el.setAttribute('data-cbridge-id', bridgeId);
    }
    const text = __cb_get_accessible_name(el);
    const role = __cb_get_computed_role(el);
    return {
        selector: '[data-cbridge-id="' + bridgeId + '"]',
        tagName: el.tagName.toLowerCase(),
        role: role,
        text: text.slice(0, 100),
        id: el.id || '',
        name: el.getAttribute('name') || '',
        placeholder: el.getAttribute('placeholder') || '',
        value: el.value || ''
    };
}

function __cb_wait_for(finderFn, timeoutMs) {
    timeoutMs = (typeof timeoutMs === 'number') ? timeoutMs : 1500;
    try {
        const immediate = finderFn();
        if (immediate) return Promise.resolve(immediate);
    } catch(e) {}
    if (timeoutMs <= 0) return Promise.resolve(null);

    return new Promise((resolve) => {
        let timer = null;
        let observer = null;
        let rafId = null;

        const cleanup = () => {
            if (timer) clearTimeout(timer);
            if (observer) observer.disconnect();
            if (rafId && typeof cancelAnimationFrame === 'function') cancelAnimationFrame(rafId);
        };

        const check = () => {
            try {
                const found = finderFn();
                if (found) {
                    cleanup();
                    resolve(found);
                    return true;
                }
            } catch(e) {}
            return false;
        };

        try {
            if (typeof MutationObserver !== 'undefined') {
                observer = new MutationObserver(() => {
                    check();
                });
                const root = document.documentElement || document.body;
                if (root) {
                    observer.observe(root, {
                        childList: true,
                        subtree: true,
                        attributes: true,
                        characterData: true
                    });
                }
            }
        } catch(e) {}

        if (typeof requestAnimationFrame === 'function') {
            const loop = () => {
                if (!check()) {
                    rafId = requestAnimationFrame(loop);
                }
            };
            rafId = requestAnimationFrame(loop);
        }

        timer = setTimeout(() => {
            cleanup();
            try {
                resolve(finderFn());
            } catch(e) {
                resolve(null);
            }
        }, timeoutMs);
    });
}
"""
        js_payload = f"""
        (() => {{
            {_DISCOVERY_HELPER_JS}
            const mapping = {json.dumps(mapping)};
            const submit = {json.dumps(submit)};
            let filledCount = 0;
            const errors = [];

            function findField(key) {{
                if (key.startsWith('[#') || key.startsWith('#') || key.startsWith('.') || key.startsWith('input') || key.startsWith('[data-')) {{
                    try {{
                        const el = document.querySelector(key);
                        if (el && __cb_is_visible(el)) return el;
                    }} catch(e) {{}}
                }}
                const qLower = key.toLowerCase();
                const inputs = document.querySelectorAll('input:not([type="hidden"]), textarea, select, [contenteditable="true"], [role="textbox"], [role="searchbox"], [role="combobox"]');
                let best = null;
                let bestScore = 0;
                for (const el of inputs) {{
                    if (!__cb_is_visible(el)) continue;
                    let score = 0;
                    const ph = (el.getAttribute('placeholder') || '').toLowerCase();
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    const nm = (el.getAttribute('name') || '').toLowerCase();
                    const id = (el.id || '').toLowerCase();
                    if (ph === qLower || aria === qLower || nm === qLower || id === qLower) score = 100;
                    else if (ph.includes(qLower) || aria.includes(qLower) || nm.includes(qLower)) score = 70;
                    
                    if (el.id) {{
                        try {{
                            const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
                            if (l && (l.innerText.toLowerCase() === qLower || l.innerText.toLowerCase().includes(qLower))) score = Math.max(score, 95);
                        }} catch(e) {{}}
                    }}
                    const pLabel = el.closest('label');
                    if (pLabel && (pLabel.innerText.toLowerCase() === qLower || pLabel.innerText.toLowerCase().includes(qLower))) score = Math.max(score, 90);

                    if (score > bestScore) {{
                        bestScore = score;
                        best = el;
                    }}
                }}
                return best;
            }}

            for (const [key, value] of Object.entries(mapping)) {{
                const el = findField(key);
                if (!el) {{
                    errors.push({{ field: key, error: "Field not found" }});
                    continue;
                }}
                const tag = el.tagName.toLowerCase();
                const type = (el.type || '').toLowerCase();
                const role = (el.getAttribute('role') || '').toLowerCase();

                if (typeof value === 'boolean') {{
                    const isChecked = !!el.checked || el.getAttribute('aria-checked') === 'true';
                    if (isChecked !== value) {{
                        el.click();
                    }}
                }} else if (type === 'radio' || role === 'radio') {{
                    el.click();
                }} else if (tag === 'select' || role === 'combobox' || Array.isArray(value)) {{
                    const targetVal = String(Array.isArray(value) ? value[0] : value);
                    let foundOption = false;
                    if (el.options) {{
                        for (let i = 0; i < el.options.length; i++) {{
                            if (el.options[i].value === targetVal || el.options[i].text.trim() === targetVal) {{
                                el.selectedIndex = i;
                                foundOption = true;
                                break;
                            }}
                        }}
                    }}
                    if (!foundOption) el.value = targetVal;
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }} else {{
                    el.focus();
                    el.value = String(value);
                    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }}
                filledCount++;
            }}

            let submitted = false;
            if (submit) {{
                if (submit === true || String(submit).toLowerCase() === 'enter') {{
                    const form = document.querySelector('form');
                    if (form) {{
                        if (typeof form.requestSubmit === 'function') form.requestSubmit();
                        else form.submit();
                        submitted = true;
                    }}
                }} else {{
                    const submitStr = String(submit).toLowerCase();
                    const buttons = document.querySelectorAll('button, input[type="submit"], input[type="button"], [role="button"], a.btn');
                    for (const b of buttons) {{
                        if (!__cb_is_visible(b)) continue;
                        const txt = (b.innerText || b.value || b.getAttribute('aria-label') || '').trim().toLowerCase();
                        if (txt === submitStr || txt.includes(submitStr)) {{
                            b.click();
                            submitted = true;
                            break;
                        }}
                    }}
                }}
            }}

            return {{
                success: errors.length === 0,
                filled: filledCount,
                submitted: submitted,
                errors: errors
            }};
        }})()
        """
        res = self.eval_js(js_payload)
        if isinstance(res, dict) and res.get("errors"):
            first_err = res["errors"][0]
            field_name = first_err.get("field", "form_field")
            from arthur.errors import ElementNotFoundError
            raise ElementNotFoundError(target=field_name, tab_id=self.id, url=self.url)
        return res if isinstance(res, dict) else {"success": True, "filled": len(mapping), "submitted": bool(submit)}

    def help(self) -> str:
        """Return a formatted quick reference of available SDK methods and examples."""
        return (
            "Arthur Browser SDK Quick Reference:\n"
            "====================================\n"
            "  1. DOM Orientation:\n"
            "     browser.snapshot()                -> Formatted semantic outline with [#N] Ref-IDs\n"
            "     browser.url, browser.title        -> Current page URL and document title\n\n"
            "  2. Element Interactions (Target: Ref-ID [#N], integer N, or 'css_selector'):\n"
            "     browser.click(target, button='left', count=1)\n"
            "     browser.type(target, 'text', clear=True, press_enter=False)\n"
            "     browser.select(target, 'value')\n"
            "     browser.hover(target)\n"
            "     browser.scroll(x=0, y=500, target=None)\n\n"
            "  3. Extraction & JavaScript Evaluation:\n"
            "     browser.get_text(target)          -> Extracted text content\n"
            "     browser.get_attribute(target, 'href') -> Attribute value string\n"
            "     browser.eval_js('document.title') -> Evaluate JS in page context\n"
            "     browser.screenshot()              -> Raw PNG screenshot bytes\n\n"
            "  4. Tabs & Navigation:\n"
            "     browser.navigate('https://...')   -> Navigate active tab and wait for load\n"
            "     browser.new_tab('https://...')    -> Open new tab\n"
            "     browser.tabs                      -> List all open Tab handles\n"
            "     browser.active_tab                -> Current active Tab handle\n"
            "     browser.get_tab(tab_id)           -> Scoped Tab handle by ID (or browser.tab(id))\n"
            "     browser.close_tab(tab_id)         -> Close tab\n\n"
            "  5. Synchronization & Waiting:\n"
            "     browser.wait_for(target, state='visible', timeout=10.0)\n"
            "     browser.wait_for_url(r'pattern', timeout=15.0)\n\n"
            "  6. Media Fast-Paths (Zero-DOM Shadow-Root Penetration):\n"
            "     browser.media.status()            -> Media state, player metadata, playbackState\n"
            "     browser.media.toggle()            -> Toggle play/pause\n"
            "     browser.media.play(), pause()     -> Direct playback controls\n"
            "     browser.media.seek(15.0)          -> Relative seek (+/- seconds)\n"
            "     browser.media.set_volume(0.8)     -> Set volume level (0.0 to 1.0)\n"
        )


class Browser:
    """Synchronous Arthur Browser runtime instance and facade.

    Provides procedural control over headless Chromium, multi-tab lifecycle,
    semantic snapshotting, synthetic interactions, and fast media control.

    Canonical Composition Lifecycle:
        >>> from arthur.browser import browser
        >>> # 1. Navigate to target
        >>> browser.navigate("https://example.com")
        >>> # 2. Orient via semantic snapshot
        >>> print(browser.snapshot())
        >>> # 3. Interact via discovered Ref-ID
        >>> browser.type(2, "Hello World", press_enter=True)
        >>> # 4. Synchronize and extract
        >>> browser.wait_for(5)
        >>> print(browser.get_text(5))
    """

    def __init__(self, executable_path: Optional[str] = None):
        self._executable_path = executable_path
        self._runner_instance: Optional[_AsyncCDPRunner] = None
        self._init_lock = threading.RLock()

    def _ensure_runner(self) -> _AsyncCDPRunner:
        with self._init_lock:
            if self._runner_instance is None or self._runner_instance._closed:
                self._runner_instance = _AsyncCDPRunner(self._executable_path)
            return self._runner_instance

    @property
    def _runner(self) -> _AsyncCDPRunner:
        return self._ensure_runner()

    @property
    def tabs(self) -> List[Tab]:
        """List all open tabs."""
        return self._ensure_runner().tab_manager.list_tabs()

    @property
    def active_tab(self) -> Tab:
        """Get currently active Tab instance."""
        return self._ensure_runner().tab_manager.get_active_tab()

    @property
    def target_id(self) -> str:
        """Target ID of the active tab."""
        return self.active_tab.target_id

    @property
    def id(self) -> int:
        """Sequential integer ID of the active tab."""
        return self.active_tab.id

    @property
    def url(self) -> str:
        """Current URL of the active tab."""
        return self.active_tab.url

    @property
    def title(self) -> str:
        """Current document title of the active tab."""
        return self.active_tab.title

    @property
    def media(self) -> TabMedia:
        """Fast-path media controller for HTML5 audio/video on the active tab."""
        return self.active_tab.media

    def get_tab(self, tab_id: Union[int, str]) -> Tab:
        """Get tab by sequential numeric ID or target ID.

        Args:
            tab_id: Sequential integer ID (e.g. 1) or CDP target ID.

        Returns:
            Tab handle instance.

        Example:
            >>> tab = browser.get_tab(1)
        """
        return self._ensure_runner().tab_manager.get_tab(tab_id)

    def tab(self, tab_id: Union[int, str]) -> Tab:
        """Alias for get_tab."""
        return self.get_tab(tab_id)

    def new_tab(self, url: Optional[str] = None) -> Tab:
        """Open a new browser tab and optionally navigate to URL.

        Args:
            url: Optional URL to navigate to immediately upon creation.

        Returns:
            New Tab instance.

        Example:
            >>> new_tab = browser.new_tab("https://example.com")
        """
        return self._ensure_runner().tab_manager.create_tab(url)

    def close_tab(self, tab_id: Union[int, str]) -> None:
        """Close specific tab by ID.

        Args:
            tab_id: Sequential integer ID or target ID of the tab to close.

        Example:
            >>> browser.close_tab(2)
        """
        self._ensure_runner().tab_manager.close_tab(tab_id)

    def close(self) -> None:
        """Shut down browser process and clean up resources."""
        with self._init_lock:
            if self._runner_instance is not None:
                self._runner_instance.close()
                self._runner_instance = None

    # Forwarded active-tab operations
    def navigate(self, url: str, timeout: float = 30.0) -> str:
        """Navigate active tab to URL and wait for page load."""
        return self.active_tab.navigate(url, timeout=timeout)

    def snapshot(self) -> str:
        """Generate semantic DOM snapshot outline on the active tab."""
        return self.active_tab.snapshot()

    def click(
        self,
        target: Union[int, str],
        button: str = "left",
        count: int = 1,
    ) -> Dict[str, Any]:
        """Click element on active tab by Ref-ID or CSS selector."""
        return self.active_tab.click(target, button=button, count=count)

    def type(
        self,
        target: Union[int, str],
        text: str,
        clear: bool = True,
        press_enter: bool = False,
    ) -> Dict[str, Any]:
        """Type text into element on active tab."""
        return self.active_tab.type(target, text, clear=clear, press_enter=press_enter)

    def select(self, target: Union[int, str], value: str) -> Dict[str, Any]:
        """Select dropdown option on active tab."""
        return self.active_tab.select(target, value)

    def hover(self, target: Union[int, str]) -> Dict[str, Any]:
        """Hover over element on active tab."""
        return self.active_tab.hover(target)

    def scroll(
        self,
        x: int = 0,
        y: int = 500,
        target: Optional[Union[int, str]] = None,
    ) -> Dict[str, Any]:
        """Scroll viewport or container on active tab."""
        return self.active_tab.scroll(x=x, y=y, target=target)

    def eval_js(self, expression: str) -> Any:
        """Evaluate arbitrary JavaScript in active tab context."""
        return self.active_tab.eval_js(expression)

    def screenshot(self, format: str = "png") -> bytes:
        """Capture viewport screenshot on active tab."""
        return self.active_tab.screenshot(format=format)

    def get_text(self, target: Union[int, str]) -> str:
        """Get text content of element on active tab."""
        return self.active_tab.get_text(target)

    def get_attribute(self, target: Union[int, str], name: str) -> Optional[str]:
        """Get DOM attribute value on active tab."""
        return self.active_tab.get_attribute(target, name)

    def wait_for(
        self,
        target: Union[int, str],
        state: str = "visible",
        timeout: float = 10.0,
    ) -> bool:
        """Wait for element on active tab to reach condition."""
        return self.active_tab.wait_for(target, state=state, timeout=timeout)

    def wait_for_url(self, pattern: str, timeout: float = 15.0) -> str:
        """Wait for active tab URL to match pattern."""
        return self.active_tab.wait_for_url(pattern, timeout=timeout)

    def help(self) -> str:
        """Return formatted quick reference of available SDK methods."""
        return self.active_tab.help()



    def extract_items(self, container_selector: str, fields: dict) -> list:
        """Extract structured data rows and attributes across repeated container elements."""
        return self.active_tab.extract_items(container_selector, fields)

    def fill_form(self, mapping: dict, submit: str | bool | None = None) -> dict:
        """Fill an entire form and optionally submit in a single roundtrip."""
        return self.active_tab.fill_form(mapping, submit)

# Default global browser singleton
browser = Browser()
