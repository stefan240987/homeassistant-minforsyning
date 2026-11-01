"""Constants for the Novafos integration."""

from __future__ import annotations
from typing import Final

# Get Sensor classification and unit definitions:
from homeassistant.components.sensor import SensorStateClass
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import UnitOfEnergy
from homeassistant.const import UnitOfVolume

from .model import NovafosSensorDescription

DOMAIN = "minforsyning"

# Default name for sensor prefix texts (possibly other things)
DEFAULT_NAME = "minForsyning"

# External statistic for district heating, shown in the Energy dashboard.
FJERNVARME_STATISTIC_ID = f"{DOMAIN}:fjernvarme_forbrug"

# Halsnæs Forsyning, Priser for varme 2026, Hundested Varme.
# Variabelt bidrag: 1.000,00 kr. pr. MWh inkl. moms, som er 1,00 kr. pr. kWh.
# https://hnf.dk/files/media/document/VARME_Hundested_2026.pdf
HUNDESTED_2026_KR_PER_KWH = 1.0
HUNDESTED_2026_PRICE_SOURCE = "Hundested Varme 2026, variabelt bidrag inkl. moms"
# Fast bidrag pr. m², inkl. moms. Arealet kommer fra BBR.
HUNDESTED_2026_KR_PER_M2 = 37.30


def meter_statistics_key(data, meter_type):
    """Scope new entries to a customer and meter, preserving legacy IDs."""
    if "customer_id" in data and "measurement_point_id" in data:
        return f"{data['customer_id']}_{data['measurement_point_id']}_{meter_type}"
    return meter_type


# NOTE:
#  All consumption data can be derived from the statistics sensor.
#  The sensor will always have state "unknown" because data is only relevant in the past.
#  Instead use the statistics charts and cards to get data out.
WATER_SENSOR_TYPES: Final[tuple[NovafosSensorDescription, ...]] = (
    NovafosSensorDescription(
        sensor_type="water",
        key="statistics",
        name="Water statistics",
        entity_registry_enabled_default=True,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        suggested_display_precision=1,
        device_class=SensorDeviceClass.WATER,
        icon="mdi:water",
        state_class=SensorStateClass.TOTAL,
    ),
)

HEATING_SENSOR_TYPES: Final[tuple[NovafosSensorDescription, ...]] = (
    NovafosSensorDescription(
        sensor_type="heating",
        key="statistics",
        name="Heating statistics",
        entity_registry_enabled_default=False,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        device_class=SensorDeviceClass.ENERGY,
        icon="mdi:lightning-bolt-circle",
        state_class=SensorStateClass.TOTAL,
    ),
)
