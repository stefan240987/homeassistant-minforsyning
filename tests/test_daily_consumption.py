"""Daily district-heating fetch and Bearer-token status."""

import base64
import json
from datetime import datetime, timedelta, timezone

import tests.utils
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest

from custom_components.minforsyning.const import DOMAIN, FJERNVARME_STATISTIC_ID
from custom_components.minforsyning.coordinator import NovafosUpdateCoordinator
from custom_components.minforsyning.pynovafos.novafos import (
    LOGIN_URL,
    PLANT_NUMBER,
    UTILITY_ID,
    UTILITY_LOS_ID_PLANT,
    UTILITY_NUMBER,
    Novafos,
    utility_login_code,
)
from custom_components.minforsyning.sensor import (
    CurrentMonthConsumptionSensor,
    CurrentYearConsumptionSensor,
)
from custom_components.minforsyning.services import async_setup_services
from custom_components.minforsyning.token_status import (
    STATUS_EXPIRED,
    STATUS_INVALID,
    STATUS_VALID,
    token_status,
)


def _jwt(payload):
    body = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    return f"header.{body.rstrip('=')}.signature"


def test_utility_login_code_matches_portal():
    assert utility_login_code() == "0698000"
    assert LOGIN_URL == "https://minforsyning-2.kmd.dk/login?plant=698&utility=0"


def test_last_30_days_posts_daily_zoom_and_converts_mwh(mocker, freezer):
    freezer.move_to("2026-10-31T12:00:00+01:00")
    api = Novafos(timezone="Europe/Copenhagen")
    api._access_token = "Bearer test-token"
    api._customer_id = "10"
    api._customer_number = "20"
    api._active_meters = [
        {
            "type": "heating",
            "InstallationId": 1,
            "MeasurementPointId": 2,
            "Unit": {"Id": 3, "Name": "MWH"},
        }
    ]
    payload = {
        "Series": [
            {
                "Data": [
                    {
                        "DateFrom": "2026-01-01T00:00:00",
                        "DateTo": "2026-12-31T23:59:59",
                        "Value": 11.278,
                        "UnitName": "MWH",
                        "Label": "2026",
                        "IsComplete": False,
                    },
                    {
                        "DateFrom": "2026-01-02T00:00:00",
                        "Value": None,
                        "UnitName": "MWH",
                    },
                    {"Value": 4, "UnitName": "MWH"},
                    {
                        "DateFrom": "2026-01-03T00:00:00",
                        "Value": 2.5,
                        "UnitName": "kWh",
                    },
                    {
                        "DateFrom": "2026-01-04T00:00:00",
                        "Value": 9,
                        "UnitName": "m³",
                    },
                ]
            }
        ],
        "Total": {"Value": 13.605},
    }
    response = Mock(status_code=200)
    response.json.return_value = payload
    post = mocker.patch("requests.post", return_value=response)

    points = api.get_last_30_days_daily()

    assert post.call_args.args[0].endswith("/api/consumption/consumptionTimeSeries")
    assert "?" not in post.call_args.args[0]
    body = post.call_args.kwargs["json"]
    assert body["ZoomLevel"] == 2
    headers = post.call_args.kwargs["headers"]
    assert headers["Plant-Number"] == PLANT_NUMBER
    assert headers["Utility-Id"] == UTILITY_ID
    assert headers["Utility-Number"] == UTILITY_NUMBER
    assert headers["Utility-Los-Id-Plant"] == UTILITY_LOS_ID_PLANT
    assert headers["Customer-Id"] == "10"
    assert headers["Accept"] == "application/json"
    assert headers["Authorization"] == "Bearer test-token"

    tz = ZoneInfo("Europe/Copenhagen")
    end_local = datetime(2026, 10, 31, 23, 59, 59, tzinfo=tz)
    start_local = (end_local - timedelta(days=29)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    assert body["DateFrom"] == api._utc_to_isostr(start_local.astimezone(timezone.utc))
    assert body["DateTo"] == api._utc_to_isostr(end_local.astimezone(timezone.utc))
    assert (end_local.date() - start_local.date()).days == 29

    assert points == [
        {
            "start": datetime(2026, 1, 1, tzinfo=tz).astimezone(timezone.utc),
            "value_kwh": 11278.0,
        },
        {
            "start": datetime(2026, 1, 3, tzinfo=tz).astimezone(timezone.utc),
            "value_kwh": 2.5,
        },
    ]


def test_october_daily_fixture_matches_kmd_response():
    api = Novafos(timezone="Europe/Copenhagen")
    payload = tests.utils.load_data_structure("consumption_day_october_2026.json")
    payload["Series"][0]["Data"].append(
        {"DateFrom": "2026-10-15T00:00:00+02:00", "Value": None, "UnitName": "MWH"}
    )
    points = api._points_from_consumption_payload(payload)

    assert points[0]["value_kwh"] == 16
    assert points[0]["start"] == datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc)
    october_26 = next(point for point in points if point["value_kwh"] == 33)
    assert october_26["start"] == datetime(2026, 10, 25, 23, 0, tzinfo=timezone.utc)
    incomplete_october_31 = datetime(2026, 10, 30, 23, 0, tzinfo=timezone.utc)
    assert all(point["start"] != incomplete_october_31 for point in points)
    assert len(points) == 30
    assert sum(point["value_kwh"] for point in points) == pytest.approx(918)
    assert payload["Total"]["Value"] * 1000 == pytest.approx(918)


@pytest.mark.asyncio
async def test_october_daily_statistics_skip_incomplete_zero(monkeypatch):
    added = Mock()
    import custom_components.minforsyning.coordinator as coordinator_module

    monkeypatch.setattr(coordinator_module, "async_add_external_statistics", added)
    api = Novafos(timezone="Europe/Copenhagen")
    payload = tests.utils.load_data_structure("consumption_day_october_2026.json")
    points = api._points_from_consumption_payload(payload)
    coordinator = SimpleNamespace(hass=SimpleNamespace())
    await NovafosUpdateCoordinator._insert_fjernvarme_statistics(coordinator, points)
    _hass, metadata, rows = added.call_args.args
    assert metadata["statistic_id"] == "minforsyning:fjernvarme_forbrug"
    assert len(rows) == 30
    assert rows[-1]["sum"] == pytest.approx(918)
    assert all(
        row["start"] != datetime(2026, 10, 30, 23, 0, tzinfo=timezone.utc) for row in rows
    )


def test_hourly_naive_dates_parse_as_copenhagen():
    api = Novafos(timezone="Europe/Copenhagen")
    payload = tests.utils.load_data_structure("consumption_hour_2026-10-30.json")
    points = api._points_from_consumption_payload(payload)
    assert points[0]["start"] == datetime(2026, 10, 29, 23, 0, tzinfo=timezone.utc)
    assert points[0]["value_kwh"] == pytest.approx(34)
    assert len(points) == 24


def _heating_api():
    api = Novafos(timezone="Europe/Copenhagen")
    api._access_token = "Bearer test-token"
    api._customer_id = "10"
    api._customer_number = "20"
    api._active_meters = [
        {
            "type": "heating",
            "InstallationId": 1,
            "MeasurementPointId": 2,
            "Unit": {"Id": 3, "Name": "MWH"},
        }
    ]
    return api


def test_current_year_months_and_year_use_separate_zoom(mocker, freezer):
    freezer.move_to("2026-10-31T12:00:00+01:00")
    api = _heating_api()
    month_payload = {
        "Series": [
            {
                "Data": [
                    {
                        "DateFrom": "2026-01-01T00:00:00+01:00",
                        "DateTo": "2026-01-31T23:59:59+01:00",
                        "Value": 1.5,
                        "UnitName": "MWH",
                        "IsComplete": True,
                    },
                    {
                        "DateFrom": "2026-10-01T00:00:00+02:00",
                        "DateTo": "2026-10-31T23:59:59+01:00",
                        "Value": 0.918,
                        "UnitName": "MWH",
                        "IsComplete": False,
                    },
                    {
                        "DateFrom": "2026-11-01T00:00:00+01:00",
                        "Value": 0.0,
                        "UnitName": "MWH",
                        "IsComplete": False,
                    },
                ]
            }
        ]
    }
    year_payload = {
        "Series": [
            {
                "Data": [
                    {
                        "DateFrom": "2026-01-01T00:00:00+01:00",
                        "DateTo": "2026-12-31T23:59:59+01:00",
                        "Value": 11.278,
                        "UnitName": "MWH",
                        "Label": "2026",
                        "IsComplete": False,
                    }
                ]
            }
        ]
    }
    response = Mock(status_code=200)
    response.json.side_effect = [month_payload, year_payload]
    post = mocker.patch("requests.post", return_value=response)

    months = api.get_current_year_months()
    year = api.get_current_year_total()

    assert post.call_count == 2
    assert post.call_args_list[0].kwargs["json"]["ZoomLevel"] == 1
    assert post.call_args_list[1].kwargs["json"]["ZoomLevel"] == 0
    tz = ZoneInfo("Europe/Copenhagen")
    start_local = datetime(2026, 1, 1, tzinfo=tz)
    end_local = datetime(2026, 12, 31, 23, 59, 59, tzinfo=tz)
    for call in post.call_args_list:
        body = call.kwargs["json"]
        assert body["DateFrom"] == api._utc_to_isostr(start_local.astimezone(timezone.utc))
        assert body["DateTo"] == api._utc_to_isostr(end_local.astimezone(timezone.utc))

    assert months == [
        {
            "start": datetime(2026, 1, 1, tzinfo=tz).astimezone(timezone.utc),
            "value_kwh": 1500.0,
        },
        {
            "start": datetime(2026, 9, 30, 22, 0, tzinfo=timezone.utc),
            "value_kwh": 918.0,
        },
    ]
    assert year == [
        {
            "start": datetime(2026, 1, 1, tzinfo=tz).astimezone(timezone.utc),
            "value_kwh": 11278.0,
        }
    ]


def test_month_and_year_sensors_show_kwh():
    tz = ZoneInfo("Europe/Copenhagen")
    monthly = [
        {
            "start": datetime(2026, 1, 1, tzinfo=tz).astimezone(timezone.utc),
            "value_kwh": 1500.0,
        },
        {
            "start": datetime(2026, 10, 1, tzinfo=tz).astimezone(timezone.utc),
            "value_kwh": 918.0,
        },
    ]
    yearly = [
        {
            "start": datetime(2026, 1, 1, tzinfo=tz).astimezone(timezone.utc),
            "value_kwh": 11278.0,
        }
    ]
    coordinator = SimpleNamespace(monthly_points=monthly, yearly_points=yearly)
    config = SimpleNamespace(data={}, entry_id="entry-id")
    month = CurrentMonthConsumptionSensor("minForsyning", coordinator, config)
    year = CurrentYearConsumptionSensor("minForsyning", coordinator, config)

    assert month.native_value == 918.0
    assert month.extra_state_attributes == {
        "måneder": {"januar 2026": 1500.0, "oktober 2026": 918.0}
    }
    assert year.native_value == 11278.0

    fallback = CurrentYearConsumptionSensor(
        "minForsyning",
        SimpleNamespace(monthly_points=monthly, yearly_points=[]),
        config,
    )
    assert fallback.native_value == 2418.0


def test_missing_series_does_not_raise():
    api = Novafos(timezone="Europe/Copenhagen")
    assert api._points_from_consumption_payload({}) == []
    assert api._points_from_consumption_payload({"Series": []}) == []
    assert api._points_from_consumption_payload({"Series": [{"Data": None}]}) == []
    assert api._kwh_from_point({"Value": None, "UnitName": "MWH"}) is None
    assert api._kwh_from_point({}) is None


@pytest.mark.asyncio
async def test_fjernvarme_statistics_accumulate_kwh(monkeypatch):
    added = Mock()
    coordinator = SimpleNamespace(
        hass=SimpleNamespace(),
    )
    import custom_components.minforsyning.coordinator as coordinator_module
    from homeassistant.components.recorder.models import StatisticMeanType

    monkeypatch.setattr(coordinator_module, "async_add_external_statistics", added)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    points = [
        {"start": start, "value_kwh": 11278.0},
        {"start": start + timedelta(days=1), "value_kwh": 2.5},
    ]
    await NovafosUpdateCoordinator._insert_fjernvarme_statistics(coordinator, points)
    _hass, metadata, rows = added.call_args.args
    assert metadata["statistic_id"] == FJERNVARME_STATISTIC_ID
    assert metadata["statistic_id"] == "minforsyning:fjernvarme_forbrug"
    assert metadata["name"] == "Fjernvarme Forbrug"
    assert metadata["source"] == DOMAIN
    assert metadata["has_sum"] is True
    assert metadata["mean_type"] is StatisticMeanType.NONE
    assert metadata["unit_of_measurement"] == "kWh"
    assert rows[0]["sum"] == 11278.0
    assert rows[1]["sum"] == 11280.5


def test_token_status_reads_exp_without_verifying_signature():
    now = datetime(2026, 10, 31, tzinfo=timezone.utc)
    valid = _jwt({"exp": int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())})
    expired = _jwt({"exp": int(datetime(2026, 10, 1, tzinfo=timezone.utc).timestamp())})
    assert token_status(valid, now=now) == STATUS_VALID
    assert token_status(f"Bearer {expired}", now=now) == STATUS_EXPIRED
    assert token_status("not-a-token", now=now) == STATUS_INVALID
    assert token_status("", now=now) == STATUS_INVALID
    assert token_status(None, now=now) == STATUS_INVALID
    assert token_status(_jwt({"sub": "user"}), now=now) == STATUS_INVALID


@pytest.mark.asyncio
async def test_set_token_persists_options():
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
    assert services.async_register.call_args.args[1] == "set_token"
    handler = services.async_register.call_args.args[2]
    await handler(
        SimpleNamespace(
            data={"access_token": "nye-token", "access_token_date_updated": ""}
        )
    )
    saved = config_entries.async_update_entry.call_args.kwargs["options"]
    assert saved["access_token"] == "nye-token"
    assert saved["access_token_date_updated"]
    assert saved["use_external_statistics"] is True
    assert coordinator.access_token == "nye-token"
    coordinator.async_refresh.assert_awaited_once()
