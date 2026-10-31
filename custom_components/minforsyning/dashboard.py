"""Sidebar overview for the minForsyning sensors."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lovelace.const import LOVELACE_DATA, ConfigNotFound
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL = "min-forsyning"
LAYOUT_VERSION = 1

# The statistics sensor stays unknown on purpose. These are the sensors with a value.
SENSOR_CARDS = (
    ("seneste_dagsforbrug", "Seneste dag"),
    ("seneste_dagspris", "Pris, seneste dag"),
    ("maanedens_forbrug", "Denne måned"),
    ("maanedens_pris", "Pris, denne måned"),
    ("aarets_forbrug", "I år"),
    ("aarets_pris", "Pris, i år"),
    ("akkumuleret_totalforbrug", "Seneste 30 dage"),
    ("boligareal", "Boligareal"),
    ("token_status", "Login"),
)


def sensor_entity_id(entry, suffix: str) -> str:
    """Entity id assigned in sensor.py for one meter."""
    scope = entry.data.get("measurement_point_id") or entry.entry_id
    return f"sensor.{DOMAIN}_{scope}_{suffix}"


def _heading(entry) -> str:
    data = entry.data
    name = data.get("name") or "minForsyning"
    address = data.get("address")
    if address:
        return f"{name}, {address}"
    title = getattr(entry, "title", "") or ""
    return title or name


def build_dashboard_config(entries) -> dict[str, Any]:
    """Lovelace config that shows each meter's current numbers."""
    sections: list[dict[str, Any]] = []
    for entry in entries:
        tiles = [
            {
                "type": "tile",
                "entity": sensor_entity_id(entry, suffix),
                "name": label,
            }
            for suffix, label in SENSOR_CARDS
        ]
        sections.append(
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "heading",
                        "heading": _heading(entry),
                        "icon": "mdi:radiator",
                    },
                    *tiles,
                ],
            }
        )
        sections.append(
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "heading",
                        "heading": "Udvikling",
                        "icon": "mdi:chart-line",
                    },
                    {
                        "type": "history-graph",
                        "hours_to_show": 24 * 30,
                        "entities": [
                            {
                                "entity": sensor_entity_id(
                                    entry, "seneste_dagsforbrug"
                                ),
                                "name": "Seneste dag",
                            },
                            {
                                "entity": sensor_entity_id(entry, "maanedens_forbrug"),
                                "name": "Denne måned",
                            },
                            {
                                "entity": sensor_entity_id(entry, "aarets_forbrug"),
                                "name": "I år",
                            },
                        ],
                    },
                    {
                        "type": "markdown",
                        "content": (
                            "Tryk på et tal for at se de enkelte dage og måneder. "
                            "**Login** viser, om forbindelsen til minForsyning stadig virker."
                        ),
                    },
                ],
            }
        )

    if not sections:
        sections.append(
            {
                "type": "grid",
                "cards": [
                    {
                        "type": "markdown",
                        "content": "Der er ingen måler tilknyttet endnu.",
                    }
                ],
            }
        )

    return {
        "minforsyning_managed": True,
        "minforsyning_layout": LAYOUT_VERSION,
        "minforsyning_entries": sorted(entry.entry_id for entry in entries),
        "views": [
            {
                "title": "Forbrug",
                "path": "forbrug",
                "icon": "mdi:radiator",
                "type": "sections",
                "max_columns": 2,
                "sections": sections,
            }
        ],
    }


def _dashboards_collection(hass: HomeAssistant):
    """The Lovelace dashboard list. Home Assistant does not store it on hass.data."""
    websocket = hass.data.get("websocket_api")
    if not isinstance(websocket, dict):
        return None
    registered = websocket.get("lovelace/dashboards/list")
    if not registered:
        return None
    handler = registered[0]
    owner = getattr(handler, "__self__", None)
    return getattr(owner, "storage_collection", None)


def _should_save(current: dict[str, Any] | None, config: dict[str, Any]) -> bool:
    if current is None:
        return True
    if not current.get("minforsyning_managed"):
        return False
    return (
        current.get("minforsyning_layout") != config["minforsyning_layout"]
        or current.get("minforsyning_entries") != config["minforsyning_entries"]
    )


async def async_ensure_dashboard(hass: HomeAssistant, entries) -> None:
    """Create the sidebar overview, or refresh it when the meters change."""
    collection = _dashboards_collection(hass)
    lovelace = hass.data.get(LOVELACE_DATA)
    if collection is None or lovelace is None:
        _LOGGER.debug("Lovelace er ikke klar, så overblikket springes over")
        return

    config = build_dashboard_config(entries)
    existing = next(
        (
            item
            for item in collection.async_items()
            if item.get("url_path") == DASHBOARD_URL
        ),
        None,
    )
    if existing is None:
        if not entries:
            return
        await collection.async_create_item(
            {
                "url_path": DASHBOARD_URL,
                "title": "minForsyning",
                "icon": "mdi:radiator",
                "show_in_sidebar": True,
                "require_admin": False,
            }
        )

    store = lovelace.dashboards.get(DASHBOARD_URL)
    if store is None:
        _LOGGER.warning("Overblikket blev oprettet, men kunne ikke gemmes")
        return

    try:
        current = await store.async_load(False)
    except ConfigNotFound:
        current = None

    if not _should_save(current, config):
        return
    await store.async_save(config)
