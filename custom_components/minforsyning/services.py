from homeassistant.core import HomeAssistant, callback, ServiceCall
import voluptuous as vol
from datetime import datetime

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.exceptions import HomeAssistantError


from .const import DOMAIN

# Development help
import logging

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "none"

# The Novafos Chrome extension posts to this service and only sends access_token.
CHROME_EXTENSION_DOMAIN = "novafos"
CHROME_EXTENSION_SERVICE = "update_token"


def normalize_access_token(access_token):
    """Return the raw token. The extension can include a Bearer prefix."""
    if not isinstance(access_token, str):
        return ""
    token = access_token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


async def async_setup_services(hass: HomeAssistant, coordinator: DataUpdateCoordinator):
    if hass.services.has_service(
        DOMAIN, "set_token"
    ) and hass.services.has_service(CHROME_EXTENSION_DOMAIN, CHROME_EXTENSION_SERVICE):
        return True
    data_schema = vol.Schema(
        {
            vol.Required("access_token", default=""): str,
            vol.Optional("access_token_date_updated", default=""): str,
            vol.Optional("config_entry_id"): str,
        }
    )
    chrome_schema = vol.Schema(
        {
            vol.Required("access_token"): str,
            vol.Optional("config_entry_id"): str,
        }
    )

    @callback
    async def async_update_token(call: ServiceCall):
        """Handle the service action call."""
        # Update the coordinator data fields.
        _LOGGER.debug("Update via action service call initiated.")
        token = normalize_access_token(call.data.get("access_token", ""))
        if token == "":
            raise HomeAssistantError("access_token mangler")

        entries = hass.data.get(DOMAIN, {})
        entry_id = call.data.get("config_entry_id")
        if entry_id is not None:
            if entry_id not in entries:
                raise HomeAssistantError("minForsyning config entry is not loaded")
            entries = {entry_id: entries[entry_id]}
        updated = call.data.get("access_token_date_updated") or datetime.now().strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        for runtime in entries.values():
            entry_coordinator = runtime["coordinator"]
            entry_coordinator.access_token = token
            entry_coordinator.access_token_date_updated = updated
            config_entry = runtime.get("config_entry")
            if config_entry is not None and hasattr(hass, "config_entries"):
                options = dict(config_entry.options)
                options["access_token"] = token
                options["access_token_date_updated"] = updated
                hass.config_entries.async_update_entry(config_entry, options=options)
            await entry_coordinator.async_refresh()

    # Add service to receive a login token.
    # The Chrome extension service is registered first. set_token stays last.
    if hass.services.has_service(DOMAIN, "update_token"):
        hass.services.async_remove(DOMAIN, "update_token")
    if not hass.services.has_service(CHROME_EXTENSION_DOMAIN, CHROME_EXTENSION_SERVICE):
        hass.services.async_register(
            CHROME_EXTENSION_DOMAIN,
            CHROME_EXTENSION_SERVICE,
            async_update_token,
            schema=chrome_schema,
        )
    if not hass.services.has_service(DOMAIN, "set_token"):
        hass.services.async_register(
            DOMAIN, "set_token", async_update_token, schema=data_schema
        )

    # Indicate setup completed okay.
    _LOGGER.debug("minForsyning action service setup completed")
    return True
