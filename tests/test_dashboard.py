"""The sidebar overview lists the sensors that actually have a value."""

from types import SimpleNamespace

import pytest
from homeassistant.components.lovelace.const import ConfigNotFound

from custom_components.minforsyning.dashboard import (
    DASHBOARD_URL,
    async_ensure_dashboard,
    build_dashboard_config,
    sensor_entity_id,
)


def _entry():
    return SimpleNamespace(
        entry_id="abc",
        title="minForsyning: Testvej 1 (heating)",
        data={
            "name": "minForsyning",
            "address": "Testvej 1",
            "measurement_point_id": "99",
        },
    )


def test_dashboard_lists_the_sensors_with_a_value():
    config = build_dashboard_config([_entry()])
    text = str(config)

    assert config["minforsyning_managed"] is True
    assert "Testvej 1" in text
    for suffix in (
        "seneste_dagsforbrug",
        "seneste_dagspris",
        "akkumuleret_totalforbrug",
        "maanedens_forbrug",
        "maanedens_pris",
        "aarets_forbrug",
        "aarets_pris",
        "boligareal",
        "token_status",
    ):
        assert sensor_entity_id(_entry(), suffix) in text
    assert "statistics" not in text


class _Collection:
    def __init__(self):
        self.items = []

    def async_items(self):
        return list(self.items)

    async def async_create_item(self, data):
        item = {"id": "dash-1", **data}
        self.items.append(item)
        return item


class _Store:
    def __init__(self):
        self.current = None
        self.saves = 0

    async def async_load(self, force):
        if self.current is None:
            raise ConfigNotFound
        return self.current

    async def async_save(self, config):
        self.current = config
        self.saves += 1


def _hass(collection, store):
    owner = SimpleNamespace(storage_collection=collection)
    handler = SimpleNamespace(__self__=owner)
    lovelace = SimpleNamespace(dashboards={})

    async def create(data):
        item = await _Collection.async_create_item(collection, data)
        lovelace.dashboards[DASHBOARD_URL] = store
        return item

    collection.async_create_item = create
    return SimpleNamespace(
        data={
            "websocket_api": {"lovelace/dashboards/list": (handler, None)},
            "lovelace": lovelace,
        }
    )


@pytest.mark.asyncio
async def test_dashboard_is_created_and_not_rewritten():
    collection = _Collection()
    store = _Store()
    hass = _hass(collection, store)

    await async_ensure_dashboard(hass, [_entry()])
    await async_ensure_dashboard(hass, [_entry()])

    assert store.saves == 1
    assert collection.items[0]["url_path"] == DASHBOARD_URL
    assert collection.items[0]["title"] == "minForsyning"
    assert store.current["views"][0]["title"] == "Forbrug"


@pytest.mark.asyncio
async def test_a_hand_edited_dashboard_is_left_alone():
    collection = _Collection()
    store = _Store()
    store.current = {"views": [{"title": "Mit eget"}]}
    hass = _hass(collection, store)
    collection.items.append({"id": "dash-1", "url_path": DASHBOARD_URL})
    hass.data["lovelace"].dashboards[DASHBOARD_URL] = store

    await async_ensure_dashboard(hass, [_entry()])

    assert store.saves == 0
    assert store.current["views"][0]["title"] == "Mit eget"


@pytest.mark.asyncio
async def test_dashboard_is_skipped_when_lovelace_is_missing():
    hass = SimpleNamespace(data={})
    await async_ensure_dashboard(hass, [_entry()])
