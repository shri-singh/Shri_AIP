"""Fixtures for API tests. Async tests use AnyIO's pytest plugin on asyncio."""
import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _reset_auth_and_settings_cache():
    from app.modules._shared.settings import get_settings
    from app.modules.identity import deps

    get_settings.cache_clear()
    yield
    deps.set_oidc_validator(None)
    deps.set_existing_auth_adapter(None)  # type: ignore[arg-type]
