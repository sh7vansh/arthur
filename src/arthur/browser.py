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


class Tab:
    """Synchronous representation of an active browser tab."""

    def __init__(self, runner: _AsyncCDPRunner, tab_manager: TabManager, target_id: str):
        self._runner = runner
        self._tab_manager = tab_manager
        self._target_id = target_id

    @property
    def target_id(self) -> str:
        return self._target_id

    @property
    def id(self) -> int:
        with self._tab_manager._tabs_lock:
            info = self._tab_manager._tabs.get(self._target_id)
            return info["id"] if info else 0

    @property
    def url(self) -> str:
        with self._tab_manager._tabs_lock:
            info = self._tab_manager._tabs.get(self._target_id)
            return info.get("url", "") if info else ""

    @property
    def title(self) -> str:
        with self._tab_manager._tabs_lock:
            info = self._tab_manager._tabs.get(self._target_id)
            return info.get("title", "") if info else ""

    def _ensure_session_id(self) -> str:
        return self._tab_manager.ensure_session_id(self._target_id)

    def navigate(self, url: str, timeout: float = 30.0) -> str:
        """Navigate tab to URL and wait for page load."""
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
        """Generate semantic DOM snapshot outline."""
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
        """Click element by Ref-ID or CSS selector."""
        session_id = self._ensure_session_id()
        return self._runner.run_coro(  # type: ignore[no-any-return]
            cdp_click(
                self._runner.cdp,
                target,
                button=button,
                click_count=count,
                session_id=session_id,
            )
        )

    def type(
        self,
        target: Union[int, str],
        text: str,
        clear: bool = True,
        press_enter: bool = False,
    ) -> Dict[str, Any]:
        """Type text into element by Ref-ID or CSS selector."""
        session_id = self._ensure_session_id()
        return self._runner.run_coro(  # type: ignore[no-any-return]
            cdp_type(
                self._runner.cdp,
                target,
                text,
                clear=clear,
                press_enter=press_enter,
                session_id=session_id,
            )
        )

    def select(self, target: Union[int, str], value: str) -> Dict[str, Any]:
        """Select option in <select> dropdown."""
        session_id = self._ensure_session_id()
        return self._runner.run_coro(  # type: ignore[no-any-return]
            cdp_select(self._runner.cdp, target, value, session_id=session_id)
        )

    def hover(self, target: Union[int, str]) -> Dict[str, Any]:
        """Hover over element."""
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
        """Scroll viewport or target element."""
        session_id = self._ensure_session_id()
        return self._runner.run_coro(  # type: ignore[no-any-return]
            cdp_scroll(self._runner.cdp, x=x, y=y, target=target, session_id=session_id)
        )

    def eval_js(self, expression: str) -> Any:
        """Evaluate arbitrary JavaScript in page context."""
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
        """Capture screenshot of the viewport."""
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
        """Get text content of element."""
        session_id = self._ensure_session_id()
        return str(self._runner.run_coro(dom_get_text(self._runner.cdp, target, session_id=session_id)))

    def get_attribute(self, target: Union[int, str], name: str) -> Optional[str]:
        """Get DOM attribute value of element."""
        session_id = self._ensure_session_id()
        return self._runner.run_coro(dom_get_attribute(self._runner.cdp, target, name, session_id=session_id))  # type: ignore[no-any-return]

    def wait_for(
        self,
        target: Union[int, str],
        state: str = "visible",
        timeout: float = 10.0,
    ) -> bool:
        """Wait for element to satisfy condition ('visible', 'attached', 'hidden')."""
        session_id = self._ensure_session_id()
        start = time.time()

        while time.time() - start < timeout:
            try:
                coord = self._runner.run_coro(
                    resolve_target_coordinates(
                        self._runner.cdp, target, session_id=session_id
                    )
                )
                if state == "visible" and coord:
                    return True
                if state == "attached" and coord:
                    return True
            except ElementNotFoundError:
                if state == "hidden":
                    return True
            except Exception:
                pass
            time.sleep(0.1)

        intro = {}
        try:
            intro = self._runner.run_coro(
                get_dom_metrics(self._runner.cdp, session_id=session_id)
            )
        except Exception:
            pass

        raise NavigationTimeoutError(
            target=str(target),
            timeout=timeout,
            url=self.url,
            ready_state=intro.get("readyState", "unknown"),
            dom_state=f"condition '{state}' not met",
            tab_id=self.id,
        )

    def wait_for_url(self, pattern: str, timeout: float = 15.0) -> str:
        """Wait until page URL matches regex pattern."""
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


class Browser:
    """Synchronous Arthur Browser runtime instance and facade."""

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
        return self.active_tab.target_id

    @property
    def id(self) -> int:
        return self.active_tab.id

    @property
    def url(self) -> str:
        return self.active_tab.url

    @property
    def title(self) -> str:
        return self.active_tab.title

    def get_tab(self, tab_id: Union[int, str]) -> Tab:
        """Get tab by sequential numeric ID or target ID."""
        return self._ensure_runner().tab_manager.get_tab(tab_id)

    def tab(self, tab_id: Union[int, str]) -> Tab:
        """Alias for get_tab."""
        return self.get_tab(tab_id)

    def new_tab(self, url: Optional[str] = None) -> Tab:
        """Open a new browser tab and optionally navigate to URL."""
        return self._ensure_runner().tab_manager.create_tab(url)

    def close_tab(self, tab_id: Union[int, str]) -> None:
        """Close specific tab by ID."""
        self._ensure_runner().tab_manager.close_tab(tab_id)

    def close(self) -> None:
        """Shut down browser and clean up."""
        with self._init_lock:
            if self._runner_instance is not None:
                self._runner_instance.close()
                self._runner_instance = None

    # Forwarded active-tab operations
    def navigate(self, url: str, timeout: float = 30.0) -> str:
        return self.active_tab.navigate(url, timeout=timeout)

    def snapshot(self) -> str:
        return self.active_tab.snapshot()

    def click(
        self,
        target: Union[int, str],
        button: str = "left",
        count: int = 1,
    ) -> Dict[str, Any]:
        return self.active_tab.click(target, button=button, count=count)

    def type(
        self,
        target: Union[int, str],
        text: str,
        clear: bool = True,
        press_enter: bool = False,
    ) -> Dict[str, Any]:
        return self.active_tab.type(target, text, clear=clear, press_enter=press_enter)

    def select(self, target: Union[int, str], value: str) -> Dict[str, Any]:
        return self.active_tab.select(target, value)

    def hover(self, target: Union[int, str]) -> Dict[str, Any]:
        return self.active_tab.hover(target)

    def scroll(
        self,
        x: int = 0,
        y: int = 500,
        target: Optional[Union[int, str]] = None,
    ) -> Dict[str, Any]:
        return self.active_tab.scroll(x=x, y=y, target=target)

    def eval_js(self, expression: str) -> Any:
        return self.active_tab.eval_js(expression)

    def screenshot(self, format: str = "png") -> bytes:
        return self.active_tab.screenshot(format=format)

    def get_text(self, target: Union[int, str]) -> str:
        return self.active_tab.get_text(target)

    def get_attribute(self, target: Union[int, str], name: str) -> Optional[str]:
        return self.active_tab.get_attribute(target, name)

    def wait_for(
        self,
        target: Union[int, str],
        state: str = "visible",
        timeout: float = 10.0,
    ) -> bool:
        return self.active_tab.wait_for(target, state=state, timeout=timeout)

    def wait_for_url(self, pattern: str, timeout: float = 15.0) -> str:
        return self.active_tab.wait_for_url(pattern, timeout=timeout)


# Default global browser singleton
browser = Browser()
