"""Sensor platform for Novafos integration."""

from __future__ import annotations
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.const import CONF_NAME, UnitOfArea, UnitOfEnergy
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DOMAIN,
    HUNDESTED_2026_KR_PER_M2,
    HUNDESTED_2026_PRICE_SOURCE,
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
                NovafosWaterSensor(name, coordinator, description, config)
            )

    if "heating" in coordinator.data[0]:
        for description in HEATING_SENSOR_TYPES:
            sensors.append(
                NovafosWaterSensor(name, coordinator, description, config)
            )

    sensors.append(LatestDailyConsumptionSensor(name, coordinator, config))
    sensors.append(LatestDailyCostSensor(name, coordinator, config))
    sensors.append(AccumulatedConsumptionSensor(name, coordinator, config))
    sensors.append(CurrentMonthConsumptionSensor(name, coordinator, config))
    sensors.append(CurrentMonthCostSensor(name, coordinator, config))
    sensors.append(CurrentYearConsumptionSensor(name, coordinator, config))
    sensors.append(CurrentYearCostSensor(name, coordinator, config))
    sensors.append(FloorAreaSensor(name, coordinator, config))
    sensors.append(TokenStatusSensor(name, coordinator, config))

    async_add_entities(sensors)


class MinForsyningSensor(CoordinatorEntity, SensorEntity):
    """A meter sensor that stays visible, also when the login has expired."""

    def _bind_meter(self, config, name: str) -> None:
        entry_id = getattr(config, "entry_id", None)
        if not entry_id:
            return
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=name,
            manufacturer="minForsyning",
        )

    @property
    def available(self) -> bool:
        return True


class NovafosWaterSensor(MinForsyningSensor):
    """Representation of a Sensor."""

    entity_description: NovafosSensorDescription

    def __init__(self, name, coordinator, description, config=None):
        """Initialise the coordinator"""
        super().__init__(coordinator)
        self._bind_meter(config, name)
        entry_data = getattr(config, "data", config)

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


def _history_points(coordinator) -> list:
    """Days in the current year, or the last 30 days when the year is missing."""
    points = _series_points(coordinator, "history_points")
    if points:
        return points
    return _daily_points(coordinator)


def _price_per_kwh(coordinator):
    price = getattr(coordinator, "price_per_kwh", None)
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return None
    return float(price)


def _kroner(kwh, price):
    if kwh is None or price is None:
        return None
    return round(float(kwh) * price, 2)


def _currency(coordinator) -> str:
    hass = getattr(coordinator, "hass", None)
    config = getattr(hass, "config", None)
    currency = getattr(config, "currency", None)
    if isinstance(currency, str) and currency:
        return currency
    return "DKK"


def _danish_day_label(start) -> str | None:
    if not isinstance(start, datetime):
        return None
    local = start.astimezone(_COPENHAGEN)
    return f"{local.day}. {_DANISH_MONTHS[local.month - 1]} {local.year}"


def _day_label(point) -> str | None:
    return _danish_day_label(point.get("start"))


def _month_label(point) -> str | None:
    start = point.get("start")
    if not isinstance(start, datetime):
        return None
    local = start.astimezone(_COPENHAGEN)
    return f"{_DANISH_MONTHS[local.month - 1]} {local.year}"


def _labeled_values(points, label_fn, price=None) -> dict[str, float]:
    labeled: dict[str, float] = {}
    for point in points:
        label = label_fn(point)
        if label is None:
            continue
        if price is None:
            value = point.get("value_kwh")
            if value is None:
                continue
            labeled[label] = float(value)
            continue
        kroner = _kroner(point.get("value_kwh"), price)
        if kroner is None:
            continue
        labeled[label] = kroner
    return labeled


def _month_attributes(points) -> dict[str, Any]:
    """Map each month to kWh so the entity dialog can list the whole year."""
    months = _labeled_values(points, _month_label)
    if not months:
        return {}
    return {"måneder": months}


def _rate_attributes(coordinator) -> dict[str, Any]:
    price = _price_per_kwh(coordinator)
    if price is None:
        return {}
    return {
        "pris_pr_kwh": round(price, 4),
        "priskilde": HUNDESTED_2026_PRICE_SOURCE,
    }


def _latest_kwh(points):
    if not points:
        return None
    return points[-1].get("value_kwh")


def _floor_area_m2(coordinator):
    area = getattr(coordinator, "floor_area_m2", None)
    if isinstance(area, bool) or not isinstance(area, (int, float)):
        return None
    if area <= 0:
        return None
    return float(area)


def _fixed_area_cost(coordinator):
    area = _floor_area_m2(coordinator)
    if area is None:
        return None
    return round(area * HUNDESTED_2026_KR_PER_M2, 2)


def _year_cost(coordinator):
    variable = _kroner(_year_kwh(coordinator), _price_per_kwh(coordinator))
    if variable is None:
        return None
    fixed = _fixed_area_cost(coordinator)
    if fixed is None:
        return variable
    return round(variable + fixed, 2)


def _year_kwh(coordinator):
    yearly = _series_points(coordinator, "yearly_points")
    if yearly:
        return yearly[-1].get("value_kwh")
    monthly = _series_points(coordinator, "monthly_points")
    if not monthly:
        return None
    total = 0.0
    for point in monthly:
        value = point.get("value_kwh")
        if value is None:
            continue
        total += float(value)
    return total


class LatestDailyConsumptionSensor(MinForsyningSensor):
    """Seneste registrerede dagsforbrug i kWh."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:radiator"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        self._bind_meter(config, name)
        scope = _sensor_scope(config)
        self._attr_name = f"{name} Seneste dagsforbrug"
        self._attr_unique_id = f"{DOMAIN}_{scope}_seneste_dagsforbrug"
        self.entity_id = f"sensor.{self._attr_unique_id}"

    @property
    def native_value(self) -> StateType:
        return _latest_kwh(_history_points(self.coordinator))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        points = _history_points(self.coordinator)
        if not points:
            return {}
        attrs: dict[str, Any] = {}
        label = _danish_day_label(points[-1].get("start"))
        if label:
            attrs["dato"] = label
        days = _labeled_values(points, _day_label)
        if days:
            attrs["dage"] = days
        return attrs


class LatestDailyCostSensor(MinForsyningSensor):
    """Pris for den seneste dag, i kroner. Tidligere dage ligger som attributter."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cash"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        self._bind_meter(config, name)
        scope = _sensor_scope(config)
        self._attr_name = f"{name} Seneste dagspris"
        self._attr_unique_id = f"{DOMAIN}_{scope}_seneste_dagspris"
        self.entity_id = f"sensor.{self._attr_unique_id}"
        self._attr_native_unit_of_measurement = _currency(coordinator)

    @property
    def native_value(self) -> StateType:
        points = _history_points(self.coordinator)
        return _kroner(_latest_kwh(points), _price_per_kwh(self.coordinator))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        points = _history_points(self.coordinator)
        attrs = _rate_attributes(self.coordinator)
        if not points:
            return attrs
        label = _danish_day_label(points[-1].get("start"))
        if label:
            attrs["dato"] = label
        prices = _labeled_values(
            points,
            _day_label,
            _price_per_kwh(self.coordinator),
        )
        if prices:
            attrs["priser"] = prices
        return attrs


class AccumulatedConsumptionSensor(MinForsyningSensor):
    """Sum af de hentede dagsværdier i kWh."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:chart-line"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        self._bind_meter(config, name)
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


class CurrentMonthConsumptionSensor(MinForsyningSensor):
    """Forbrug i den seneste måned i året, i kWh. Øvrige måneder ligger som attributter."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:calendar-month"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        self._bind_meter(config, name)
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


class CurrentMonthCostSensor(MinForsyningSensor):
    """Pris for den seneste måned, i kroner. Øvrige måneder ligger som attributter."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cash"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        self._bind_meter(config, name)
        scope = _sensor_scope(config)
        self._attr_name = f"{name} Månedens pris"
        self._attr_unique_id = f"{DOMAIN}_{scope}_maanedens_pris"
        self.entity_id = f"sensor.{self._attr_unique_id}"
        self._attr_native_unit_of_measurement = _currency(coordinator)

    @property
    def native_value(self) -> StateType:
        points = _series_points(self.coordinator, "monthly_points")
        return _kroner(_latest_kwh(points), _price_per_kwh(self.coordinator))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = _rate_attributes(self.coordinator)
        prices = _labeled_values(
            _series_points(self.coordinator, "monthly_points"),
            _month_label,
            _price_per_kwh(self.coordinator),
        )
        if prices:
            attrs["priser"] = prices
        return attrs


class CurrentYearConsumptionSensor(MinForsyningSensor):
    """Forbrug i det igangværende kalenderår, i kWh."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_suggested_display_precision = 3
    _attr_icon = "mdi:calendar-range"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        self._bind_meter(config, name)
        scope = _sensor_scope(config)
        self._attr_name = f"{name} Årets forbrug"
        self._attr_unique_id = f"{DOMAIN}_{scope}_aarets_forbrug"
        self.entity_id = f"sensor.{self._attr_unique_id}"

    @property
    def native_value(self) -> StateType:
        return _year_kwh(self.coordinator)


class CurrentYearCostSensor(MinForsyningSensor):
    """Pris for det igangværende kalenderår, i kroner."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:cash"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        self._bind_meter(config, name)
        scope = _sensor_scope(config)
        self._attr_name = f"{name} Årets pris"
        self._attr_unique_id = f"{DOMAIN}_{scope}_aarets_pris"
        self.entity_id = f"sensor.{self._attr_unique_id}"
        self._attr_native_unit_of_measurement = _currency(coordinator)

    @property
    def native_value(self) -> StateType:
        return _year_cost(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = _rate_attributes(self.coordinator)
        area = _floor_area_m2(self.coordinator)
        fixed = _fixed_area_cost(self.coordinator)
        if area is not None:
            attrs["boligareal_m2"] = area
        if fixed is not None:
            attrs["fast_bidrag"] = fixed
        return attrs


class FloorAreaSensor(MinForsyningSensor):
    """Boligareal fra BBR, i kvadratmeter."""

    _attr_native_unit_of_measurement = UnitOfArea.SQUARE_METERS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:floor-plan"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        self._bind_meter(config, name)
        scope = _sensor_scope(config)
        self._attr_name = f"{name} Boligareal"
        self._attr_unique_id = f"{DOMAIN}_{scope}_boligareal"
        self.entity_id = f"sensor.{self._attr_unique_id}"

    @property
    def native_value(self) -> StateType:
        return _floor_area_m2(self.coordinator)


class TokenStatusSensor(MinForsyningSensor):
    """Gyldighed af Bearer-tokenet ud fra JWT exp-claim."""

    _attr_icon = "mdi:key-chain"

    def __init__(self, name, coordinator, config):
        super().__init__(coordinator)
        self._bind_meter(config, name)
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
