"""Sidebar overview for the minForsyning sensors."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lovelace.const import LOVELACE_DATA, ConfigNotFound
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

DASHBOARD_URL = "min-forsyning"
LAYOUT_VERSION = 2
_MISSING_TEXT = (
    "Der er ikke hentet tal endnu.\n\n"
    "Loginnet holder kun omkring en time. Log ind på minForsyning, "
    "og send loginnet igen med udvidelsen i Chrome. "
    "Tallene kommer frem her, når de er hentet."
)

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


def _ids_for_entry(entry, ids_by_entry) -> dict[str, str]:
    found = (ids_by_entry or {}).get(entry.entry_id, {})
    return {
        suffix: found.get(suffix) or sensor_entity_id(entry, suffix)
        for suffix, _label in SENSOR_CARDS
    }


def build_dashboard_config(entries, ids_by_entry=None, values_missing=False) -> dict[str, Any]:
    """Lovelace config that shows each meter's current numbers."""
    cards: list[dict[str, Any]] = []
    if values_missing and entries:
        cards.append({"type": "markdown", "content": _MISSING_TEXT})
    for entry in entries:
        ids = _ids_for_entry(entry, ids_by_entry)
        cards.append(
            {
                "type": "entities",
                "title": _heading(entry),
                "state_color": True,
                "entities": [
                    {"entity": ids[suffix], "name": label}
                    for suffix, label in SENSOR_CARDS
                ],
            }
        )
        cards.append(
            {
                "type": "history-graph",
                "title": "Udvikling",
                "hours_to_show": 24 * 30,
                "entities": [
                    {"entity": ids["seneste_dagsforbrug"], "name": "Seneste dag"},
                    {"entity": ids["maanedens_forbrug"], "name": "Denne måned"},
                    {"entity": ids["aarets_forbrug"], "name": "I år"},
                ],
            }
        )
        cards.append(
            {
                "type": "markdown",
                "content": (
                    "Tryk på et tal for at se de enkelte dage og måneder. "
                    "**Login** viser, om forbindelsen til minForsyning stadig virker."
                ),
            }
        )

    if not cards:
        cards.append(
            {"type": "markdown", "content": "Der er ingen måler tilknyttet endnu."}
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
                "cards": cards,
            }
        ],
    }


def _collection_from_handler(handler):
    owner = getattr(handler, "__self__", None)
    if owner is None:
        owner = getattr(getattr(handler, "func", None), "__self__", None)
    return getattr(owner, "storage_collection", None)


def _dashboards_collection(hass: HomeAssistant):
    """The Lovelace dashboard list. Home Assistant does not store it on hass.data."""
    websocket = hass.data.get("websocket_api")
    if not isinstance(websocket, dict):
        return None
    for command, registered in websocket.items():
        handler = registered[0] if isinstance(registered, tuple) else registered
        collection = _collection_from_handler(handler)
        if collection is None or not hasattr(collection, "async_create_item"):
            continue
        key = getattr(getattr(collection, "store", None), "key", None)
        if key == "lovelace_dashboards" or command == "lovelace/dashboards/list":
            return collection
    return None


def _show_in_sidebar(hass: HomeAssistant) -> None:
    """Make the overview visible even if Lovelace did not register the panel."""
    if not hasattr(getattr(hass, "bus", None), "async_fire"):
        return
    from homeassistant.components import frontend

    details = {
        "sidebar_title": "minForsyning",
        "sidebar_icon": "mdi:radiator",
        "frontend_url_path": DASHBOARD_URL,
        "config": {"mode": "storage"},
        "require_admin": False,
        "show_in_sidebar": True,
    }
    try:
        frontend.async_register_built_in_panel(hass, "lovelace", **details)
    except ValueError:
        frontend.async_register_built_in_panel(
            hass, "lovelace", update=True, **details
        )


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
        _LOGGER.warning("Lovelace er ikke klar, så overblikket kan ikke vises endnu")
        return

    config = build_dashboard_config(
        entries,
        _entity_ids(hass, entries),
        values_missing=_values_missing(hass, entries),
    )
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

    if _should_save(current, config):
        await store.async_save(config)
    _show_in_sidebar(hass)


def _entity_ids(hass: HomeAssistant, entries) -> dict[str, dict[str, str]]:
    """Real entity ids from the registry, when Home Assistant has registered them."""
    try:
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(hass)
        found: dict[str, dict[str, str]] = {}
        for entry in entries:
            matches: dict[str, str] = {}
            for item in er.async_entries_for_config_entry(registry, entry.entry_id):
                unique_id = item.unique_id or ""
                for suffix, _label in SENSOR_CARDS:
                    if unique_id.endswith(f"_{suffix}"):
                        matches[suffix] = item.entity_id
            if matches:
                found[entry.entry_id] = matches
        return found
    except Exception:
        return {}


def _values_missing(hass: HomeAssistant, entries) -> bool:
    states = getattr(hass, "states", None)
    if states is None or not entries:
        return False
    checked = False
    for entry in entries:
        for suffix in ("seneste_dagsforbrug", "maanedens_forbrug", "aarets_forbrug"):
            state = states.get(sensor_entity_id(entry, suffix))
            if state is None:
                continue
            checked = True
            if state.state not in ("unknown", "unavailable", "none", ""):
                return False
    return checked
