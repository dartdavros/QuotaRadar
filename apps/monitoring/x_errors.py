"""Sanitized X errors shared by timeline and bounded news search."""
import time

class XApiError(RuntimeError):
    """Base class for sanitized X API failures."""


class XApiConfigurationError(XApiError):
    """Required credentials or proxy configuration are unavailable."""


class XApiAuthenticationError(XApiError):
    """The configured X bearer token was rejected."""


class XApiForbiddenError(XApiError):
    """The X application has insufficient access."""


class XApiNotFoundError(XApiError):
    """The requested X resource does not exist."""


class XApiResponseError(XApiError):
    """X returned a permanent or malformed response."""


class XApiTemporaryError(XApiError):
    """X or the proxy failed temporarily."""


class XApiRateLimitError(XApiTemporaryError):
    """X rate limit response with a safe retry deadline."""

    def __init__(self, reset_at: int | None) -> None:
        super().__init__("X API rate limit exceeded.")
        self.reset_at = reset_at

    def retry_after_seconds(self, *, now: float | None = None) -> int:
        current = int(now if now is not None else time.time())
        if self.reset_at is None:
            return 60
        return max(self.reset_at - current + 1, 1)
