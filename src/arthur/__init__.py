"""Arthur — Lightweight Headless Chromium Runtime for Gloria and AI Agents."""

from arthur.browser import Browser, Tab, TabMedia, browser
from arthur.errors import (
    ActionInterceptionError,
    ArthurError,
    BrowserUnavailableError,
    CDPError,
    ElementNotFoundError,
    NavigationTimeoutError,
    RunawayLoopDetectedError,
    SecurityException,
)

__version__ = "0.2.0"
__all__ = [
    "ActionInterceptionError",
    "ArthurError",
    "Browser",
    "BrowserUnavailableError",
    "CDPError",
    "ElementNotFoundError",
    "NavigationTimeoutError",
    "RunawayLoopDetectedError",
    "SecurityException",
    "Tab",
    "TabMedia",
    "browser",
    "__version__",
]
