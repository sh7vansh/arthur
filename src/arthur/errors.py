"""Structured exception hierarchy for Arthur."""

from typing import Any, Dict, List, Optional, Union


class ArthurError(Exception):
    """Base exception for all Arthur operations."""

    def __init__(self, message: str, tab_id: Optional[Union[int, str]] = None):
        super().__init__(message)
        self.tab_id = tab_id
        self.auto_snapshot: Optional[str] = None


class CDPError(ArthurError):
    """Raised when a CDP command returns an error object."""

    def __init__(self, message: str, code: Optional[int] = None, data: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.data = data


DEFAULT_BROWSER_UNAVAILABLE_MSG = (
    "Chromium browser is unavailable, crashed, or disconnected. "
    "Check if the browser process is running and accessible."
)


class BrowserUnavailableError(ArthurError):
    """Raised when the browser is not running, unreachable, or disconnected."""

    def __init__(
        self,
        message: str = DEFAULT_BROWSER_UNAVAILABLE_MSG,
        tab_id: Optional[Union[int, str]] = None,
    ):
        super().__init__(message, tab_id)


def format_ref_id(ref: Union[str, int]) -> str:
    """Format a Ref-ID into canonical [#X] representation."""
    r_str = str(ref).strip()
    if not r_str.startswith("#") and not r_str.startswith("[#"):
        r_str = f"#{r_str}"
    if not r_str.startswith("["):
        r_str = f"[{r_str}]"
    return r_str


class ElementNotFoundError(ArthurError):
    """Raised when a Ref-ID or CSS selector cannot be located."""

    def __init__(
        self,
        target: str,
        tab_id: Optional[Union[int, str]] = None,
        stale: bool = False,
        suggestions: Optional[List[Dict[str, Any]]] = None,
        url: str = "",
    ):
        tab_str = f" in tab {tab_id}" if tab_id is not None else ""
        url_str = f" (URL: {url})" if url else ""
        msg = f"Element matching '{target}' not found{tab_str}{url_str}."
        if stale:
            msg += " The DOM mutated since the last snapshot was generated."
        if suggestions:
            sug_list = []
            for s in suggestions:
                ref = format_ref_id(s.get("ref", ""))
                role = s.get("role", "element")
                name = s.get("name", "")
                sug_list.append(f"{ref} ({role} '{name}')")
            msg += f" Did you mean: {', '.join(sug_list)}?"

        super().__init__(msg, tab_id)
        self.target = target
        self.stale = stale
        self.suggestions = suggestions or []
        self.url = url


class ActionInterceptionError(ArthurError):
    """Raised when coordinate hit-testing is intercepted by an overlapping element."""

    def __init__(
        self,
        target: str,
        interceptor_tag: str = "",
        interceptor_ref: Optional[Union[str, int]] = None,
        interceptor_desc: str = "",
        tab_id: Optional[Union[int, str]] = None,
    ):
        ref_formatted = format_ref_id(interceptor_ref) if interceptor_ref is not None else ""
        interceptor_label = (
            f"{ref_formatted} ({interceptor_desc})"
            if ref_formatted
            else (f"<{interceptor_tag}> ({interceptor_desc})" if interceptor_desc else f"<{interceptor_tag}>")
        )
        tab_str = f" in tab {tab_id}" if tab_id is not None else ""
        msg = (
            f"Click on target '{target}' was intercepted by overlapping element "
            f"{interceptor_label}{tab_str}. Dismiss or close the overlay before interacting with the target."
        )
        super().__init__(msg, tab_id)
        self.target = target
        self.interceptor_tag = interceptor_tag
        self.interceptor_ref = interceptor_ref
        self.interceptor_desc = interceptor_desc


class NavigationTimeoutError(ArthurError):
    """Raised when navigation or element condition waiting exceeds deadline."""

    def __init__(
        self,
        target: Optional[str] = None,
        timeout: float = 10.0,
        url: str = "",
        ready_state: str = "unknown",
        dom_state: str = "unknown",
        tab_id: Optional[Union[int, str]] = None,
    ):
        tab_str = f" in tab {tab_id}" if tab_id is not None else ""
        msg = f"Timed out after {timeout:.1f}s waiting for '{target or url}'{tab_str}."
        if url or ready_state or dom_state:
            msg += f" (Current URL: {url}, readyState: '{ready_state}', DOM state: '{dom_state}')"
        super().__init__(msg, tab_id)
        self.timeout = timeout
        self.url = url
        self.ready_state = ready_state
        self.dom_state = dom_state


class SecurityException(ArthurError):
    """Raised when an operation violates security policies."""

    def __init__(
        self,
        message: str,
        status: str = "BLOCKED_SECURITY_VIOLATION",
        tab_id: Optional[Union[int, str]] = None,
    ):
        super().__init__(message, tab_id=tab_id)
        self.status = status


class RunawayLoopDetectedError(SecurityException):
    """Raised when a repetitive action, oscillation, or scroll runaway loop is detected."""

    def __init__(
        self,
        message: str,
        status: str = "RUNAWAY_LOOP_DETECTED",
        tab_id: Optional[Union[int, str]] = None,
    ):
        super().__init__(message, status=status, tab_id=tab_id)
