from __future__ import annotations

RATE_LIMITED = "rate_limited"
PROVIDER_5XX = "provider_5xx"
PROVIDER_4XX = "provider_4xx"
PROVIDER_ERROR = "provider_error"
BAD_STREAM = "bad_stream"
BAD_TOOL_CALL = "bad_tool_call"
STREAM_ERROR = "stream_error"

#: Codes a provider call can carry. Providers also send their own strings, so wire
#: consumers must treat `error.code` as open-ended; these are the ones Kira names.
PROVIDER_CODES = (
    PROVIDER_ERROR,
    RATE_LIMITED,
    PROVIDER_5XX,
    PROVIDER_4XX,
    BAD_STREAM,
    BAD_TOOL_CALL,
    STREAM_ERROR,
)


class KiraError(Exception):
    code = "internal_error"
    status = 500
    retryable = False

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code

    def to_dict(self) -> dict:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "status": self.status,
                "retryable": self.retryable,
            }
        }


class ConfigError(KiraError):
    code = "config_error"
    status = 400


class AuthError(KiraError):
    code = "unauthorized"
    status = 401


class ModelNotFound(KiraError):
    code = "model_not_found"
    status = 400


class SecretStoreUnavailable(KiraError):
    code = "secret_store_unavailable"
    status = 500


class UnsupportedVersion(KiraError):
    """A `/vN` prefix this engine does not serve.

    404, not 400: as far as the caller is concerned there is no such route, and the message is what tells it
    which prefix there is. Never retryable by itself — retrying a path that does not exist is what a stale
    client does forever.
    """

    code = "unsupported_version"
    status = 404


class AllProvidersExhausted(KiraError):
    code = "providers_exhausted"
    status = 503
    retryable = True

    def __init__(self, message: str, chain: list[dict]) -> None:
        super().__init__(message)
        self.chain = chain


class BudgetExhausted(KiraError):
    """Every candidate had already reached its monthly cap.

    Not retryable: waiting does not help, the counter resets next month or the cap moves.
    """

    code = "budget_exhausted"
    status = 429
    retryable = False

    def __init__(self, message: str, chain: list[dict]) -> None:
        super().__init__(message)
        self.chain = chain


class ProviderCallError(Exception):
    """A single provider attempt failed. retryable decides failover eligibility."""

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        code: str = PROVIDER_ERROR,
    ) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message
        self.status = status
        self.retryable = retryable
        self.code = code
