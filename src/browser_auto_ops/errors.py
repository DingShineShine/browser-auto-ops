class BrowserAutoOpsError(Exception):
    """Base exception for browser-auto-ops."""


class ProviderError(BrowserAutoOpsError):
    """Raised when a browser provider cannot start, connect, or stop."""


class SessionNotFoundError(BrowserAutoOpsError):
    """Raised when a requested session id does not exist."""


class ElementNotFoundError(BrowserAutoOpsError):
    """Raised when an indexed state element cannot be resolved."""


class UnsafeActionError(BrowserAutoOpsError):
    """Raised when an action is blocked by safety policy."""

