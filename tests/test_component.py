"""Offline HTTP integration tests using actual Home Assistant classes."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.allegro_onebox_air import api
from custom_components.allegro_onebox_air import config_flow as flow_module
from custom_components.allegro_onebox_air import coordinator as coordinator_module
from custom_components.allegro_onebox_air.api import (
    OneBoxApiError,
    OneBoxBlockedError,
    OneBoxClient,
    OneBoxDataError,
    OneBoxNotFoundError,
    parse_point_html,
)
from custom_components.allegro_onebox_air.config_flow import OneBoxConfigFlow
from custom_components.allegro_onebox_air.const import DOMAIN
from custom_components.allegro_onebox_air.coordinator import OneBoxCoordinator
from custom_components.allegro_onebox_air.sensor import SENSORS, OneBoxSensor

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "tests/fixtures/onebox_point.html").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 27, 7, 10, tzinfo=UTC)
POINT_ID = "1522606"
OBSERVED = json.loads(
    HTML.split('data-serialize-box-id="KNaG9a8EQaCGVvRN59iUiw==">', 1)[1].split("</script>", 1)[0]
)


def html_for(details=None, *, extra=""):
    value = deepcopy(OBSERVED["details"] if details is None else details)
    return (
        "<html><body>"
        + extra
        + '<script type="application/json">'
        + json.dumps({"details": value})
        + "</script></body></html>"
    )


def observed(**air_changes):
    details = deepcopy(OBSERVED["details"])
    details["airQuality"].update(air_changes)
    return details


def entry():
    result = ConfigEntry(
        version=3,
        minor_version=1,
        domain=DOMAIN,
        title="Test One Box",
        source="user",
        unique_id=POINT_ID,
        options={},
        discovery_keys=MappingProxyType({}),
        subentries_data=[],
        data={"point_id": POINT_ID, "point_code": "AL012ERA", "address": "Radomsko, Brzeźnicka 61"},
    )
    object.__setattr__(result, "state", ConfigEntryState.SETUP_IN_PROGRESS)
    return result


def test_real_server_rendered_html_and_channels():
    result = parse_point_html(HTML, POINT_ID, now=NOW)
    assert result.point.id == POINT_ID and result.point.code == "AL012ERA"
    assert "Brzeźnicka 61" in result.point.address
    assert (result.reading.pm25, result.reading.pm10) == (30, 38)
    assert result.reading.measured_at == datetime(2026, 10, 27, 7, 5, 5, 278000, tzinfo=UTC)


def test_parser_skips_unrelated_and_malformed_scripts():
    noise = '<script type="application/json">not JSON</script><script type="application/json">{"details":null}</script>'
    assert parse_point_html(html_for(extra=noise), POINT_ID, now=NOW).reading.pm25 == 30


@pytest.mark.parametrize("low,high", [(0, 0), (15, 14)])
def test_real_zero_and_independent_channels(low, high):
    result = parse_point_html(
        html_for(observed(pmLow={"value": low}, pmHigh={"value": high})), POINT_ID, now=NOW
    )
    assert (result.reading.pm25, result.reading.pm10) == (low, high)


def test_null_air_is_valid_point_without_measurements():
    details = deepcopy(OBSERVED["details"])
    details["airQuality"] = None
    result = parse_point_html(html_for(details), POINT_ID, now=NOW)
    assert result.point.id == POINT_ID and result.reading is None


@pytest.mark.parametrize("bad", [None, True, "30", -1, 1000, float("nan"), float("inf")])
def test_invalid_measurement_is_never_zero_or_missing_point(bad):
    with pytest.raises(OneBoxDataError):
        parse_point_html(html_for(observed(pmLow={"value": bad})), POINT_ID, now=NOW)


@pytest.mark.parametrize(
    "stamp",
    [None, "invalid", "2026-10-27T07:05:00", "2026-10-27T06:39:59Z", "2026-10-27T07:15:01Z"],
)
def test_bad_stale_or_future_timestamp(stamp):
    with pytest.raises(OneBoxDataError):
        parse_point_html(html_for(observed(metricDate=stamp)), POINT_ID, now=NOW)


def test_selected_id_and_brand_checked():
    with pytest.raises(OneBoxNotFoundError):
        parse_point_html(HTML, "780740", now=NOW)
    details = deepcopy(OBSERVED["details"])
    details["brandKey"] = "ALLEGRO_UNAFFILIATED"
    with pytest.raises(OneBoxNotFoundError):
        parse_point_html(html_for(details), POINT_ID, now=NOW)


@pytest.mark.parametrize(
    "body", ["", "<html>not a point</html>", '<script type="application/json">{bad}</script>']
)
def test_missing_payload_rejected(body):
    with pytest.raises(OneBoxNotFoundError):
        parse_point_html(body, POINT_ID, now=NOW)


class FakeSession:
    def __init__(self, response=None, error=None):
        self.response = response or SimpleNamespace(
            status_code=200,
            text=HTML,
            url=f"https://allegro.pl/kampania/one/znajdz-nas?pointId={POINT_ID}",
        )
        self.error, self.calls, self.closed = error, [], False

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return self.response

    async def close(self):
        self.closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,error_type",
    [
        (403, OneBoxBlockedError),
        (429, OneBoxBlockedError),
        (404, OneBoxNotFoundError),
        (500, OneBoxApiError),
    ],
)
async def test_client_http_status_and_cleanup(status, error_type):
    session = FakeSession(
        SimpleNamespace(
            status_code=status, text="blocked", url="https://allegro.pl/kampania/one/znajdz-nas"
        )
    )
    client = OneBoxClient(session_factory=lambda **kwargs: session)
    try:
        with pytest.raises(error_type):
            await client.async_get_point(POINT_ID)
    finally:
        await client.async_close()
    assert session.closed


@pytest.mark.asyncio
async def test_client_network_error_cleanup():
    session = FakeSession(error=TimeoutError("offline"))
    client = OneBoxClient(session_factory=lambda **kwargs: session)
    try:
        with pytest.raises(OneBoxApiError):
            await client.async_get_point(POINT_ID)
    finally:
        await client.async_close()
    assert session.closed


@pytest.mark.asyncio
async def test_client_success_and_id_url(monkeypatch):
    original = api.parse_point_html
    monkeypatch.setattr(
        api, "parse_point_html", lambda body, ident, **kw: original(body, ident, now=NOW)
    )
    session = FakeSession()
    async with OneBoxClient(session_factory=lambda **kwargs: session) as client:
        data = await client.async_get_point(POINT_ID)
    assert data.reading.pm10 == 38 and session.calls[0][0] == data.point.url and session.closed


class FakeClient:
    def __init__(self, data=None, error=None):
        self.data = data or parse_point_html(HTML, POINT_ID, now=NOW)
        self.error, self.closed, self.calls = error, False, []

    async def async_get_point(self, point_id):
        self.calls.append(point_id)
        if self.error:
            raise self.error
        return self.data

    async def async_close(self):
        self.closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.async_close()


@pytest.mark.asyncio
async def test_polling_shared_values_metadata_and_cleanup(hass, monkeypatch):
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: NOW)
    client = FakeClient()
    coord = OneBoxCoordinator(hass, entry(), client.data.point, client)
    await coord.async_config_entry_first_refresh()
    assert coord.available and client.calls == [POINT_ID]
    sensors = [OneBoxSensor(coord, desc) for desc in SENSORS]
    assert [s.native_value for s in sensors[:2]] == [30, 38] and len(client.calls) == 1
    assert sensors[0].unique_id == f"{POINT_ID}_pm25"
    assert sensors[0].device_info["identifiers"] == {(DOMAIN, POINT_ID)}
    assert sensors[0].native_unit_of_measurement == CONCENTRATION_MICROGRAMS_PER_CUBIC_METER
    client.error = OneBoxBlockedError("blocked")
    await coord.async_refresh()
    assert not coord.available
    await coord.async_stop()
    assert client.closed


@pytest.mark.asyncio
async def test_first_refresh_failure_retryable(hass):
    client = FakeClient(error=OneBoxBlockedError("blocked"))
    coord = OneBoxCoordinator(hass, entry(), client.data.point, client)
    try:
        with pytest.raises(ConfigEntryNotReady):
            await coord.async_config_entry_first_refresh()
        assert not coord.available
    finally:
        await coord.async_stop()
    assert client.closed


@pytest.mark.asyncio
async def test_config_success_duplicate_and_client_cleanup(hass, monkeypatch):
    clients = []

    def make_client():
        client = FakeClient()
        clients.append(client)
        return client

    monkeypatch.setattr(flow_module, "OneBoxClient", make_client)
    flow = OneBoxConfigFlow()
    flow.hass = hass
    flow.context, flow.handler, flow.flow_id = {"source": "user"}, DOMAIN, "test-flow"
    result = await flow.async_step_manual({"point_id": POINT_ID})
    assert result["type"] == "create_entry" and result["data"]["point_id"] == POINT_ID
    assert "topic_prefix" not in result["data"] and clients and all(c.closed for c in clients)
    existing = entry()
    hass.config_entries._entries[existing.entry_id] = existing
    flow2 = OneBoxConfigFlow()
    flow2.hass = hass
    flow2.context, flow2.handler, flow2.flow_id = {"source": "user"}, DOMAIN, "test-flow2"
    from homeassistant.data_entry_flow import AbortFlow

    with pytest.raises(AbortFlow) as exc:
        await flow2.async_step_manual({"point_id": POINT_ID})
    assert exc.value.reason == "already_configured"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,key",
    [
        (OneBoxBlockedError("blocked"), "access_blocked"),
        (OneBoxNotFoundError("missing"), "point_not_found"),
        (OneBoxDataError("old"), "invalid_data"),
        (OneBoxApiError("offline"), "cannot_connect"),
    ],
)
async def test_config_errors_close_client(hass, monkeypatch, error, key):
    client = FakeClient(error=error)
    monkeypatch.setattr(flow_module, "OneBoxClient", lambda: client)
    flow = OneBoxConfigFlow()
    flow.hass = hass
    flow.context, flow.handler, flow.flow_id = {"source": "user"}, DOMAIN, "error-flow"
    result = await flow.async_step_manual({"point_id": POINT_ID})
    assert result["type"] == "form" and result["errors"]["base"] == key and client.closed


@pytest.mark.parametrize(
    "body",
    [
        "<title>Access denied</title>",
        "<title>Just a moment...</title>",
        '<script src="https://geo.captcha-delivery.com/captcha.js"></script>',
    ],
)
def test_access_challenge_without_data(body):
    with pytest.raises(OneBoxBlockedError):
        parse_point_html(body, POINT_ID, now=NOW)


@pytest.mark.asyncio
async def test_every_request_uses_and_closes_a_fresh_session(monkeypatch):
    original = api.parse_point_html
    monkeypatch.setattr(
        api, "parse_point_html", lambda body, ident, **kw: original(body, ident, now=NOW)
    )
    sessions = []

    def factory(**kwargs):
        assert kwargs == {"impersonate": "chrome", "timeout": 30}
        result = FakeSession()
        sessions.append(result)
        return result

    async with OneBoxClient(session_factory=factory) as client:
        first = await client.async_get_point(POINT_ID)
        assert sessions[0].closed
        second = await client.async_get_point(POINT_ID)
        assert first == second
    assert len(sessions) == 2 and sessions[0] is not sessions[1]
    assert all(session.closed for session in sessions)
    with pytest.raises(OneBoxApiError, match="closed"):
        await client.async_get_point(POINT_ID)


@pytest.mark.asyncio
async def test_parse_failure_closes_request_session():
    session = FakeSession(
        SimpleNamespace(
            status_code=200, text="<html>missing point</html>", url="https://allegro.pl/"
        )
    )
    async with OneBoxClient(session_factory=lambda **kwargs: session) as client:
        with pytest.raises(OneBoxNotFoundError):
            await client.async_get_point(POINT_ID)
    assert session.closed


@pytest.mark.asyncio
async def test_external_challenge_redirect_closes_request_session():
    session = FakeSession(
        SimpleNamespace(status_code=200, text=HTML, url="https://example.com/challenge")
    )
    async with OneBoxClient(session_factory=lambda **kwargs: session) as client:
        with pytest.raises(OneBoxBlockedError):
            await client.async_get_point(POINT_ID)
    assert session.closed


@pytest.mark.asyncio
async def test_stop_closes_an_active_request():
    import asyncio

    started = asyncio.Event()

    class BlockingSession(FakeSession):
        async def get(self, url, **kwargs):
            started.set()
            await asyncio.Event().wait()

    session = BlockingSession()
    client = OneBoxClient(session_factory=lambda **kwargs: session)
    task = asyncio.create_task(client.async_get_point(POINT_ID))
    await started.wait()
    await client.async_close()
    assert session.closed
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not client._active_sessions


@pytest.mark.asyncio
async def test_source_expiry_notifies_entities_and_stops_timer(hass, monkeypatch):
    from datetime import timedelta

    now = [NOW]
    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: now[0])
    timers, cancellations, notifications = [], [], []

    def track(instance, callback, when):
        assert instance is hass
        timers.append((callback, when))
        return lambda: cancellations.append(when)

    monkeypatch.setattr(coordinator_module, "async_track_point_in_utc_time", track)
    client = FakeClient()
    coord = OneBoxCoordinator(hass, entry(), client.data.point, client)
    await coord.async_config_entry_first_refresh()
    unsubscribe = coord.async_add_listener(lambda: notifications.append(coord.available))
    try:
        assert timers[0][1] == client.data.reading.measured_at + timedelta(minutes=30)
        now[0] = timers[0][1]
        timers[0][0](now[0])
        assert notifications == [False] and not coord.available
        assert coord._cancel_expiry is None
        now[0] = NOW
        await coord.async_refresh()
        assert coord.available and len(timers) == 2
        await coord.async_stop()
        assert cancellations == [timers[1][1]] and coord._shutdown_requested and client.closed
    finally:
        unsubscribe()
        await coord.async_stop()


@pytest.mark.asyncio
async def test_manual_link_fetches_metadata_and_invalid_link_is_local(hass, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(flow_module, "OneBoxClient", lambda: client)
    flow = OneBoxConfigFlow()
    flow.hass = hass
    flow.context, flow.handler, flow.flow_id = {"source": "user"}, DOMAIN, "manual-flow"
    result = await flow.async_step_user()
    assert result["type"] == "menu" and result["menu_options"] == ["nearby", "manual"]
    result = await flow.async_step_manual(
        {"point_id": f"https://allegro.pl/kampania/one/znajdz-nas?pointId={POINT_ID}"}
    )
    assert result["type"] == "create_entry"
    assert (
        result["data"]["point_code"] == "AL012ERA" and "Brzeźnicka 61" in result["data"]["address"]
    )
    assert client.closed
    invalid = OneBoxConfigFlow()
    invalid.hass = hass
    invalid.context, invalid.handler, invalid.flow_id = {"source": "user"}, DOMAIN, "manual-invalid"
    result = await invalid.async_step_manual(
        {"point_id": f"https://example.com/?pointId={POINT_ID}"}
    )
    assert result["errors"] == {"point_id": "invalid_point"}
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_point_without_air_can_be_added_but_sensors_unavailable(hass, monkeypatch):
    details = deepcopy(OBSERVED["details"])
    details["airQuality"] = None
    data = parse_point_html(html_for(details), POINT_ID, now=NOW)
    client = FakeClient(data=data)
    monkeypatch.setattr(flow_module, "OneBoxClient", lambda: client)
    flow = OneBoxConfigFlow()
    flow.hass = hass
    flow.context, flow.handler, flow.flow_id = {"source": "user"}, DOMAIN, "null-flow"
    result = await flow.async_step_manual({"point_id": POINT_ID})
    assert result["type"] == "create_entry" and client.closed
    client2 = FakeClient(data=data)
    coord = OneBoxCoordinator(hass, entry(), data.point, client2)
    await coord.async_config_entry_first_refresh()
    assert coord.last_update_success and coord.data is None
    assert not coord.available and not OneBoxSensor(coord, SENSORS[0]).available
    await coord.async_stop()


@pytest.mark.asyncio
async def test_diagnostics_excludes_private_options_and_exception_messages(hass, monkeypatch):
    from custom_components.allegro_onebox_air.diagnostics import async_get_config_entry_diagnostics

    monkeypatch.setattr(coordinator_module.dt_util, "utcnow", lambda: NOW)
    client = FakeClient()
    config_entry = entry()
    coord = OneBoxCoordinator(hass, config_entry, client.data.point, client)
    try:
        await coord.async_config_entry_first_refresh()
        config_entry.runtime_data = coord
        coord.last_exception = RuntimeError("secret-cookie-and-search-location")
        result = await async_get_config_entry_diagnostics(hass, config_entry)
        assert result["reading"]["pm25"] == 30 and result["available"]
        assert result["last_exception_type"] == "RuntimeError"
        assert "secret-cookie-and-search-location" not in json.dumps(result)
        assert "address" not in result["point"]
    finally:
        await coord.async_stop()
