"""Arthur — Lightweight Headless Chromium Runtime for Gloria and AI Agents."""

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

__version__ = "0.1.0"
__all__ = [
    "ActionInterceptionError",
    "ArthurError",
    "BrowserUnavailableError",
    "CDPError",
    "ElementNotFoundError",
    "NavigationTimeoutError",
    "RunawayLoopDetectedError",
    "SecurityException",
    "__version__",
]
