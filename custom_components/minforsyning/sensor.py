"""Sensor platform for Novafos integration."""

from __future__ import annotations
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import CONF_NAME, UnitOfEnergy
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DOMAIN,
    WATER_SENSOR_TYPES,
    HEATING_SENSOR_TYPES,
    meter_statistics_key,
)

from .model import NovafosSensorDescription
from .token_status import token_expiry, token_status

import logging

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, config: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sensor platform."""
    # Use the name for the unique id of each sensor. novafos_<supplierid>?
    name: str = config.data[CONF_NAME]
    if config.data.get("address"):
        name = f"{name} {config.data['address']}"
    coordinator: DataUpdateCoordinator = hass.data[DOMAIN][config.entry_id][
        "coordinator"
    ]
    # coordinator has a 'data' field.  This is set to the returned API data value.
    # _async_update_data updates the field.
    # From this field the sensors will get their values afterwards.

    # The sensors are defined in the const.py file
    sensors: list[NovafosWaterSensor] = []
    # The coordinator data is already populated and this means it is possible to 'auto-discover' which sensors to create:
    if "water" in coordinator.data[0]:
        for description in WATER_SENSOR_TYPES:
            sensors.append(
                NovafosWaterSensor(name, coordinator, description, config.data)
            )
            # _LOGGER.debug("Adding Novafos sensor %s", description.name)

    if "heating" in coordinator.data[0]:
        for description in HEATING_SENSOR_TYPES:
            sensors.append(
                NovafosWaterSensor(name, coordinator, description, config.data)
            )

    sensors.append(LatestDailyConsumptionSensor(name, coordinator, config))
    sensors.append(AccumulatedConsumptionSensor(name, coordinator, config))
    sensors.append(CurrentMonthConsumptionSensor(name, coordinator, config))
    sensors.append(CurrentYearConsumptionSensor(name, coordinator, config))
    sensors.append(TokenStatusSensor(name, coordinator, config))

    async_add_entities(sensors)


class NovafosWaterSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Sensor."""

    entity_description: NovafosSensorDescription

    def __init__(self, name, coordinator, description, entry_data=None):
        """Initialise the coordinator"""
        super().__init__(coordinator)

        """Initialize the sensor."""
        self.entity_description = description
        self._attrs: dict[str, Any] = {}

        _LOGGER.debug(f"Registering Sensor for {description.name}")

        self._attr_name = f"{name} {description.name}"
        self._attr_unique_id = (
            f"{name.lower()}-{description.sensor_type}-{description.key}"
        )
        if entry_data and "measurement_point_id" in entry_data:
            meter_key = meter_statistics_key(entry_data, description.sensor_type)
            key = description.key
            self._attr_unique_id = f"{meter_key}-{key}"
            self.entity_id = f"sensor.{DOMAIN}_{meter_key}_{key}"

        # Note: Data is stored in self.coordinator.data

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes.
        Attributes could include the last total yearly consumption.
        This value may be used in a template sensor which can in turn be
        used in the energy dashboard.
        TODO: If yearly values should be included it is probably a good idea
              to just make that one extra REST API call and the the latest
              year total.  Alternately the sum of all hours since start-of-year
              is to be calculated on every fetch. That is many data points
              at the end of the year.
        """
        _LOGGER.debug(self.coordinator.data)
        if (
            self.entity_description.key == "statistics"
            and self.coordinator.data[1] is not None
        ):
            self._attrs["year_total"] = self.coordinator.data[1][
                self.entity_description.sensor_type
            ]["Data"][-1]["Value"]
        #     self._attrs["last_valid_date"] = self.coordinator.data[self.entity_description.sensor_type][self.entity_description.key]["LastValidDate"]
        else:
            self._attrs = {}
        return self._attrs

        # self._attrs = {}

    @property
    def native_value(self) -> StateType:
        # State needs to be unknown as the data is in the past and not a current measurement.
        # If a state is set, this will go to the statistics too and make things look funny.
        # return self.coordinator.data[2]
        return None


def _sensor_scope(config) -> str:
    return str(config.data.get("measurement_point_id") or config.entry_id)


_COPENHAGEN = ZoneInfo("Europe/Copenhagen")
_DANISH_MONTHS = (
    "januar",
    "februar",
    "marts",
    "april",
    "maj",
    "juni",
    "juli",
    "august",
    "september",
    "oktober",
    "november",
    "december",
)


def _series_points(coordinator, name) -> list:
    points = getattr(coordinator, name, None)
    if not isinstance(points, list):
        return []
    return points


def _daily_points(coordinator) -> list:
    return _series_points(coordinator, "daily_points")


def _month_attributes(points) -> dict[str, Any]:
    """Map each month to kWh so the entity dialog can list the whole year."""
    months: dict[str, float] = {}
    for point in points:
        start = point.get("start")
        value = point.get("value_kwh")
        if not isinstance(start, datetime) or value is None:
            continue
        local = start.astimezone(_COPENHAGEN)
        label = f"{_DANISH_MONTHS[local.month - 1]} {local.year}"
        months[label] = float(value)
    if not months:
        return {}
    return {"måneder": months}


class LatestDailyConsumptionSensor(CoordinatorEntity, SensorEntity):
    """Seneste registrerede dagsforbrug i kWh."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:radiator"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        scope = _sensor_scope(config)
        self._attr_name = f"{name} Seneste dagsforbrug"
        self._attr_unique_id = f"{DOMAIN}_{scope}_seneste_dagsforbrug"
        self.entity_id = f"sensor.{self._attr_unique_id}"

    @property
    def native_value(self) -> StateType:
        points = _daily_points(self.coordinator)
        if not points:
            return None
        return points[-1].get("value_kwh")


class AccumulatedConsumptionSensor(CoordinatorEntity, SensorEntity):
    """Sum af de hentede dagsværdier i kWh."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:chart-line"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        scope = _sensor_scope(config)
        self._attr_name = f"{name} Akkumuleret totalforbrug"
        self._attr_unique_id = f"{DOMAIN}_{scope}_akkumuleret_totalforbrug"
        self.entity_id = f"sensor.{self._attr_unique_id}"

    @property
    def native_value(self) -> StateType:
        points = _daily_points(self.coordinator)
        if not points:
            return None
        total = 0.0
        for point in points:
            value = point.get("value_kwh")
            if value is None:
                continue
            total += float(value)
        return total


class CurrentMonthConsumptionSensor(CoordinatorEntity, SensorEntity):
    """Forbrug i den seneste måned i året, i kWh. Øvrige måneder ligger som attributter."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:calendar-month"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        scope = _sensor_scope(config)
        self._attr_name = f"{name} Månedens forbrug"
        self._attr_unique_id = f"{DOMAIN}_{scope}_maanedens_forbrug"
        self.entity_id = f"sensor.{self._attr_unique_id}"

    @property
    def native_value(self) -> StateType:
        points = _series_points(self.coordinator, "monthly_points")
        if not points:
            return None
        return points[-1].get("value_kwh")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return _month_attributes(_series_points(self.coordinator, "monthly_points"))


class CurrentYearConsumptionSensor(CoordinatorEntity, SensorEntity):
    """Forbrug i det igangværende kalenderår, i kWh."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:calendar-range"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        scope = _sensor_scope(config)
        self._attr_name = f"{name} Årets forbrug"
        self._attr_unique_id = f"{DOMAIN}_{scope}_aarets_forbrug"
        self.entity_id = f"sensor.{self._attr_unique_id}"

    @property
    def native_value(self) -> StateType:
        yearly = _series_points(self.coordinator, "yearly_points")
        if yearly:
            return yearly[-1].get("value_kwh")
        monthly = _series_points(self.coordinator, "monthly_points")
        if not monthly:
            return None
        total = 0.0
        for point in monthly:
            value = point.get("value_kwh")
            if value is None:
                continue
            total += float(value)
        return total


class TokenStatusSensor(CoordinatorEntity, SensorEntity):
    """Gyldighed af Bearer-tokenet ud fra JWT exp-claim."""

    _attr_icon = "mdi:key-chain"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        scope = _sensor_scope(config)
        self._attr_name = f"{name} Token-status"
        self._attr_unique_id = f"{DOMAIN}_{scope}_token_status"
        self.entity_id = f"sensor.{self._attr_unique_id}"

    @property
    def native_value(self) -> StateType:
        token = getattr(self.coordinator, "access_token", "")
        return token_status(token)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        expires = token_expiry(getattr(self.coordinator, "access_token", ""))
        if expires is None:
            return {}
        return {"udløber": expires.isoformat()}
