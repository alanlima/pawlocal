import pytest
from fastapi import HTTPException

from pawlocal.api.rate_limit import InMemoryWriteRateLimiter


def test_write_rate_limiter_returns_retry_after_after_the_configured_limit(monkeypatch):
    from pawlocal.config import settings

    monkeypatch.setattr(settings, "write_rate_limit_per_minute", 1)
    limiter = InMemoryWriteRateLimiter()
    limiter.check("user-1", now=100)

    with pytest.raises(HTTPException) as error:
        limiter.check("user-1", now=101)

    assert error.value.status_code == 429
    assert error.value.headers["Retry-After"] == "59"
