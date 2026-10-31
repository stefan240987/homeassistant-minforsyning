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


async def async_setup_services(hass: HomeAssistant, coordinator: DataUpdateCoordinator):
    if hass.services.has_service(DOMAIN, "set_token"):
        return True
    DATA_SCHEMA = vol.Schema(
        {
            vol.Required("access_token", default=""): str,
            vol.Required("access_token_date_updated", default=""): str,
            vol.Optional("config_entry_id"): str,
        }
    )

    @callback
    async def async_update_token(call: ServiceCall):
        """Handle the service action call."""
        # Update the coordinator data fields.
        _LOGGER.debug("Update via action service call initiated.")

        entries = hass.data.get(DOMAIN, {})
        entry_id = call.data.get("config_entry_id")
        if entry_id is not None:
            if entry_id not in entries:
                raise HomeAssistantError("minForsyning config entry is not loaded")
            entries = {entry_id: entries[entry_id]}
        updated = call.data["access_token_date_updated"] or datetime.now().strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        for runtime in entries.values():
            entry_coordinator = runtime["coordinator"]
            entry_coordinator.access_token = call.data["access_token"]
            entry_coordinator.access_token_date_updated = updated
            config_entry = runtime.get("config_entry")
            if config_entry is not None and hasattr(hass, "config_entries"):
                options = dict(config_entry.options)
                options["access_token"] = call.data["access_token"]
                options["access_token_date_updated"] = updated
                hass.config_entries.async_update_entry(config_entry, options=options)
            await entry_coordinator.async_refresh()

    # Add service to receive a login token
    if hass.services.has_service(DOMAIN, "update_token"):
        hass.services.async_remove(DOMAIN, "update_token")
    hass.services.async_register(
        DOMAIN, "set_token", async_update_token, schema=DATA_SCHEMA
    )

    # Indicate setup completed okay.
    _LOGGER.debug("minForsyning action service setup completed")
    return True
