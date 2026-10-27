"""Offline contracts for nationwide map search and public code resolution."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from custom_components.allegro_onebox_air import config_flow
from custom_components.allegro_onebox_air.api import (
    OneBoxBlockedError,
    OneBoxClient,
    OneBoxDataError,
    OneBoxNotFoundError,
    parse_map_result,
    parse_point_html,
)
from custom_components.allegro_onebox_air.config_flow import OneBoxConfigFlow
from custom_components.allegro_onebox_air.const import DOMAIN
from custom_components.allegro_onebox_air.models import MapPoint, SearchResult

# Synthetic point, outside the earlier Radomsko catalogue.
ID = "9000001"
CODE = "ALTESTW1"
LATITUDE, LONGITUDE = 52.23, 21.01
MAP_POINT = {
    "id": ID,
    "carrierPointId": CODE,
    "brandKey": "ALLEGRO_APM",
    "coordinates": {"lat": LATITUDE, "lng": LONGITUDE},
    "airQuality": None,
}
MAP_RESPONSE = {"points": [MAP_POINT], "clusters": [], "metadata": {"brands": []}}


class MapSession:
    def __init__(self, payload=MAP_RESPONSE, *, status=200):
        self.payload, self.status, self.closed, self.calls = payload, status, False, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        self.closed = True

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return SimpleNamespace(status_code=self.status, text=text, url=url)


def test_map_preserves_point_identity_and_incomplete_area():
    complete = parse_map_result(MAP_RESPONSE)
    assert complete == SearchResult((MapPoint(ID, CODE, LATITUDE, LONGITUDE),), False)
    clustered = deepcopy(MAP_RESPONSE)
    clustered["clusters"] = [{"count": 10, "coordinates": {"lat": LATITUDE, "lng": LONGITUDE}}]
    assert parse_map_result(clustered).has_clusters
    other_brand = deepcopy(MAP_RESPONSE)
    other_brand["points"][0]["brandKey"] = "OTHER"
    assert parse_map_result(other_brand).points == ()


@pytest.mark.asyncio
async def test_nearby_request_uses_selected_location_and_polish_onebox_filter():
    session = MapSession()
    async with OneBoxClient(session_factory=lambda **kwargs: session) as client:
        result = await client.async_search_points(LATITUDE, LONGITUDE, 2)
    params = parse_qs(urlsplit(session.calls[0][0]).query)
    assert params["countryCode"] == ["PL"] and params["brandKeys"] == ["ALLEGRO_APM"]
    assert params["filter"] == ["allegro-one"] and params["withAirQuality"] == ["false"]
    assert float(params["swLat"][0]) < LATITUDE < float(params["neLat"][0])
    assert float(params["swLng"][0]) < LONGITUDE < float(params["neLng"][0])
    assert result.points[0].id == ID and session.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "latitude,longitude,radius",
    [
        (True, LONGITUDE, 2),
        (91, LONGITUDE, 2),
        (LATITUDE, float("nan"), 2),
        (LATITUDE, 181, 2),
        (LATITUDE, LONGITUDE, 0),
        (LATITUDE, LONGITUDE, 21),
    ],
)
async def test_invalid_search_is_rejected_before_network(latitude, longitude, radius):
    def no_session(**kwargs):
        pytest.fail("Invalid search must not open an HTTP session")

    async with OneBoxClient(session_factory=no_session) as client:
        with pytest.raises(ValueError):
            await client.async_search_points(latitude, longitude, radius)


@pytest.mark.asyncio
async def test_public_code_lookup_is_case_insensitive_and_not_local_catalogue():
    session = MapSession()
    async with OneBoxClient(session_factory=lambda **kwargs: session) as client:
        assert await client.async_resolve_code(" altestw1 ") == ID
    params = parse_qs(urlsplit(session.calls[0][0]).query)
    assert params["carrierPointIds"] == [CODE]
    assert params["swLat"] == ["49.0"] and params["neLat"] == ["55.0"]
    assert params["swLng"] == ["14.0"] and params["neLng"] == ["24.2"]
    assert session.closed


@pytest.mark.asyncio
async def test_code_lookup_requires_exact_matching_code():
    session = MapSession()
    async with OneBoxClient(session_factory=lambda **kwargs: session) as client:
        with pytest.raises(OneBoxNotFoundError):
            await client.async_resolve_code("ALOTHER")
    assert session.closed


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        "<html>not json</html>",
        {"points": None, "clusters": []},
        {"points": [dict(MAP_POINT, coordinates={"lat": True, "lng": 21})], "clusters": []},
    ],
)
async def test_invalid_map_data_closes_session(response):
    session = MapSession(response)
    async with OneBoxClient(session_factory=lambda **kwargs: session) as client:
        with pytest.raises(OneBoxDataError):
            await client.async_search_points(LATITUDE, LONGITUDE, 2)
    assert session.closed


class SearchClient:
    def __init__(self, *, result=None, error=None):
        self.result = result or parse_map_result(MAP_RESPONSE)
        self.error, self.closed, self.calls = error, False, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def async_search_points(self, latitude, longitude, radius):
        self.calls.append(("nearby", latitude, longitude, radius))
        if self.error:
            raise self.error
        return self.result

    async def async_resolve_code(self, code):
        self.calls.append(("code", code))
        if self.error:
            raise self.error
        return ID

    async def async_get_point(self, point_id):
        assert point_id == ID
        self.calls.append(("point", point_id))
        now = datetime.now(UTC)
        details = {
            "id": ID,
            "brandKey": "ALLEGRO_APM",
            "pointNumber": CODE,
            "address": {"city": "Warszawa", "street": "Synthetic test street"},
            "airQuality": {
                "pmLow": {"value": 5},
                "pmHigh": {"value": 7},
                "metricDate": now.isoformat(),
            },
        }
        return parse_point_html(
            '<script type="application/json">' + json.dumps({"details": details}) + "</script>",
            point_id,
            now=now,
        )


def flow_for(hass):
    flow = OneBoxConfigFlow()
    flow.hass = hass
    flow.context, flow.handler, flow.flow_id = {"source": "user"}, DOMAIN, "map-flow"
    return flow


@pytest.mark.asyncio
async def test_nearby_flow_defaults_to_ha_location_and_accepts_outside_old_area(hass, monkeypatch):
    hass.config.latitude, hass.config.longitude = LATITUDE, LONGITUDE
    client = SearchClient()
    monkeypatch.setattr(config_flow, "OneBoxClient", lambda: client)
    flow = flow_for(hass)
    menu = await flow.async_step_user()
    assert menu["type"] == "menu" and menu["menu_options"] == ["nearby", "manual"]
    form = await flow.async_step_nearby()
    defaults = form["data_schema"]({})
    assert defaults["location"] == {"latitude": LATITUDE, "longitude": LONGITUDE}
    assert defaults["radius_km"] == 2
    selected = await flow.async_step_nearby(defaults)
    assert selected["step_id"] == "select" and client.closed
    invalid = await flow.async_step_select({"point_id": "1522606"})
    assert invalid["errors"] == {"point_id": "invalid_point"}
    created = await flow.async_step_select({"point_id": ID})
    assert created["type"] == "create_entry" and created["data"]["point_id"] == ID
    assert created["data"]["point_code"] == CODE and "Warszawa" in created["data"]["address"]
    assert set(created["data"]) == {"point_id", "point_code", "address"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result,error,key",
    [
        (SearchResult((MapPoint(ID, CODE, LATITUDE, LONGITUDE),), True), None, "area_too_large"),
        (SearchResult((), False), None, "no_points"),
        (None, OneBoxBlockedError("blocked"), "access_blocked"),
        (None, ValueError("invalid coordinates"), "invalid_location"),
    ],
)
async def test_search_cannot_offer_partial_or_failed_results(hass, monkeypatch, result, error, key):
    client = SearchClient(result=result, error=error)
    monkeypatch.setattr(config_flow, "OneBoxClient", lambda: client)
    flow = flow_for(hass)
    response = await flow.async_step_nearby(
        {"location": {"latitude": LATITUDE, "longitude": LONGITUDE}, "radius_km": 2}
    )
    assert response["step_id"] == "nearby" and response["errors"] == {"base": key}
    assert not flow._points and client.closed


@pytest.mark.asyncio
async def test_manual_code_resolves_then_validates_point_and_closes_clients(hass, monkeypatch):
    clients = []

    def factory():
        client = SearchClient()
        clients.append(client)
        return client

    monkeypatch.setattr(config_flow, "OneBoxClient", factory)
    response = await flow_for(hass).async_step_manual({"point_id": " altestw1 "})
    assert response["type"] == "create_entry" and response["data"]["point_id"] == ID
    assert clients[0].calls == [("code", CODE)] and clients[1].calls == [("point", ID)]
    assert all(client.closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value", ["not a onebox", "ALTEST&carrierPointIds=OTHER", "", "https://example.com/?pointId=1"]
)
async def test_invalid_manual_code_does_not_open_client(hass, monkeypatch, value):
    monkeypatch.setattr(
        config_flow, "OneBoxClient", lambda: pytest.fail("Invalid code must not open a client")
    )
    result = await flow_for(hass).async_step_manual({"point_id": value})
    assert result["errors"] == {"point_id": "invalid_point"}


@pytest.mark.asyncio
async def test_selection_sorts_by_distance_and_shows_public_code(hass, monkeypatch):
    nearest = MapPoint("9000002", "ALZZZ", LATITUDE + 0.001, LONGITUDE)
    farther = MapPoint(ID, "ALAAA", LATITUDE + 0.01, LONGITUDE)
    client = SearchClient(result=SearchResult((farther, nearest), False))
    monkeypatch.setattr(config_flow, "OneBoxClient", lambda: client)
    selected = await flow_for(hass).async_step_nearby(
        {
            "location": {"latitude": LATITUDE, "longitude": LONGITUDE},
            "radius_km": 2,
        }
    )
    selector = next(iter(selected["data_schema"].schema.values()))
    assert selector.config["options"] == [
        {"value": "9000002", "label": "ALZZZ · 0.1 km"},
        {"value": ID, "label": "ALAAA · 1.1 km"},
    ]
