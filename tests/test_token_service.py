"""Chrome extension token delivery."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.minforsyning.const import DOMAIN
from custom_components.minforsyning.services import (
    CHROME_EXTENSION_DOMAIN,
    CHROME_EXTENSION_SERVICE,
    async_setup_services,
    normalize_access_token,
)


def test_normalize_access_token_strips_bearer_prefix():
    assert normalize_access_token("  Bearer abc.def.ghi  ") == "abc.def.ghi"
    assert normalize_access_token("abc.def.ghi") == "abc.def.ghi"
    assert normalize_access_token(None) == ""
    assert normalize_access_token("   ") == ""


def _handler(services, domain, service_name):
    for call in services.async_register.call_args_list:
        if call.args[0] == domain and call.args[1] == service_name:
            return call.args[2]
    raise AssertionError(f"{domain}.{service_name} was not registered")


@pytest.mark.asyncio
async def test_chrome_extension_service_saves_token_and_refreshes():
    coordinator = SimpleNamespace(async_refresh=AsyncMock())
    entry = SimpleNamespace(options={"use_external_statistics": True})
    services = Mock()
    services.has_service.return_value = False
    config_entries = Mock()
    hass = SimpleNamespace(
        services=services,
        config_entries=config_entries,
        data={
            DOMAIN: {
                "entry-0": {"coordinator": coordinator, "config_entry": entry},
            }
        },
    )

    await async_setup_services(hass, coordinator)

    assert _handler(services, DOMAIN, "set_token") is not None
    handler = _handler(services, CHROME_EXTENSION_DOMAIN, CHROME_EXTENSION_SERVICE)
    await handler(
        SimpleNamespace(data={"access_token": "Bearer friskt-token-fra-udvidelsen"})
    )

    saved = config_entries.async_update_entry.call_args.kwargs["options"]
    assert saved["access_token"] == "friskt-token-fra-udvidelsen"
    assert saved["access_token_date_updated"]
    assert saved["use_external_statistics"] is True
    assert coordinator.access_token == "friskt-token-fra-udvidelsen"
    coordinator.async_refresh.assert_awaited_once()
