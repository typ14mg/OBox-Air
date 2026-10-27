"""Read public, server-rendered Allegro One Box data over HTTP."""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from html.parser import HTMLParser
from types import TracebackType
from typing import Any, Protocol
from urllib.parse import urlencode, urlsplit

from curl_cffi import AsyncSession, CurlError
from curl_cffi.requests import Response

from .const import BASE_URL, BRAND_KEY, MAP_API_URL, MAX_AGE_SECONDS, MAX_RADIUS_KM, MIN_RADIUS_KM
from .models import (
    MapPoint,
    PointData,
    SearchResult,
    parse_details,
    parse_point_code,
    parse_point_id,
)

_MAP_HEADERS = {
    "Accept": "application/vnd.allegro.internal.v1+json",
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Origin": "https://allegro.pl",
    "Referer": BASE_URL,
}


class _HttpSession(Protocol):
    """The scoped transport operations used by the client."""

    async def get(self, url: str, *, headers: dict[str, str]) -> Response: ...

    async def close(self) -> None: ...


type SessionFactory = Callable[..., AbstractAsyncContextManager[_HttpSession]]


class OneBoxApiError(Exception):
    """A public Allegro endpoint could not be read."""


class OneBoxBlockedError(OneBoxApiError):
    """Allegro refused access or returned an interactive challenge."""


class OneBoxNotFoundError(OneBoxApiError):
    """The requested One Box could not be found."""


class OneBoxDataError(OneBoxApiError):
    """Allegro returned malformed map data or invalid measurement data."""


class _JsonScriptParser(HTMLParser):
    """Collect JSON scripts without depending on changing box attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self._parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            script_type = dict(attrs).get("type", "") or ""
            self._parts = [] if script_type.lower() == "application/json" else None

    def handle_data(self, data: str) -> None:
        if self._parts is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._parts is not None:
            self.scripts.append("".join(self._parts))
            self._parts = None


def parse_point_html(
    html: str, point_id: str, *, now: datetime | None = None, max_age: int = MAX_AGE_SECONDS
) -> PointData:
    """Find the requested point's JSON script in the initial HTML."""
    if len(html) > 10_000_000:
        raise OneBoxDataError("The Allegro page is unexpectedly large")
    point_id = parse_point_id(point_id)
    parser = _JsonScriptParser()
    parser.feed(html)
    parser.close()
    for script in parser.scripts:
        try:
            raw: Any = json.loads(script)
        except (ValueError, TypeError):
            continue
        if not isinstance(raw, dict) or not isinstance(details := raw.get("details"), dict):
            continue
        if str(details.get("id")) != point_id:
            continue
        if details.get("brandKey") != BRAND_KEY:
            raise OneBoxNotFoundError("The selected point is not an Allegro One Box")
        try:
            return parse_details(details, point_id, now=now, max_age=max_age)
        except (ValueError, TypeError, OverflowError) as err:
            raise OneBoxDataError(str(err)) from err
    if _is_access_challenge(html):
        raise OneBoxBlockedError("Allegro returned an interactive access challenge")
    raise OneBoxNotFoundError("No data for the requested One Box was present in the page")


class OneBoxClient:
    """Read public point pages and map results with one session per request."""

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self._session_factory = session_factory if session_factory is not None else AsyncSession
        self._active_sessions: list[_HttpSession] = []
        self._closed = False

    async def __aenter__(self) -> OneBoxClient:
        return self

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        await self.async_close()

    async def async_get_point(self, point_id: str) -> PointData:
        """Fetch and validate the selected point's current public measurement."""
        point_id = parse_point_id(point_id)
        response = await self._async_get(
            BASE_URL + "?pointId=" + point_id,
            headers={"Accept-Language": "pl-PL,pl;q=0.9", "Accept": "text/html"},
        )
        return parse_point_html(response.text, point_id)

    async def async_search_points(
        self, latitude: float, longitude: float, radius_km: float
    ) -> SearchResult:
        """Search a small area anywhere in Poland without expanding clusters."""
        if (
            not _finite_number(latitude, -90, 90)
            or not _finite_number(longitude, -180, 180)
            or not _finite_number(radius_km, MIN_RADIUS_KM, MAX_RADIUS_KM)
        ):
            raise ValueError("Invalid search location or radius")
        latitude_delta = radius_km / 111.32
        longitude_delta = radius_km / max(111.32 * math.cos(math.radians(latitude)), 0.01)
        params = _map_params(
            min(latitude + latitude_delta, 90),
            min(longitude + longitude_delta, 180),
            max(latitude - latitude_delta, -90),
            max(longitude - longitude_delta, -180),
        )
        return await self._async_get_map(params)

    async def async_resolve_code(self, code: str) -> str:
        """Resolve one exact public code across Poland without a local catalogue."""
        code = parse_point_code(code)
        params = _map_params(55.0, 24.2, 49.0, 14.0)
        params["carrierPointIds"] = code
        result = await self._async_get_map(params)
        matches = [point.id for point in result.points if point.code == code]
        if len(matches) != 1:
            raise OneBoxNotFoundError("No Allegro One Box matches this code")
        return matches[0]

    async def _async_get_map(self, params: dict[str, str | float]) -> SearchResult:
        response = await self._async_get(
            MAP_API_URL + "?" + urlencode(params), headers=_MAP_HEADERS
        )
        if _is_access_challenge(response.text):
            raise OneBoxBlockedError("Allegro returned an interactive access challenge")
        try:
            raw = json.loads(response.text)
            return parse_map_result(raw)
        except (ValueError, TypeError, OverflowError) as err:
            raise OneBoxDataError("Allegro returned invalid map data") from err

    async def _async_get(self, url: str, *, headers: dict[str, str]) -> Response:
        """Complete a request and release its session before returning its response."""
        if self._closed:
            raise OneBoxApiError("The HTTP client is closed")
        try:
            async with self._session_factory(impersonate="chrome", timeout=30) as session:
                if self._closed:
                    raise OneBoxApiError("The HTTP client is closed")
                self._active_sessions.append(session)
                try:
                    response = await session.get(url, headers=headers)
                    if response.status_code in (401, 403, 429):
                        raise OneBoxBlockedError(
                            f"Allegro refused access (HTTP {response.status_code})"
                        )
                    if response.status_code == 404:
                        raise OneBoxNotFoundError("The One Box page was not found")
                    if response.status_code >= 400:
                        raise OneBoxApiError(f"Allegro returned HTTP {response.status_code}")
                    if urlsplit(str(response.url)).hostname != urlsplit(url).hostname:
                        raise OneBoxBlockedError("Allegro redirected to an external access page")
                    return response
                finally:
                    self._active_sessions.remove(session)
        except (CurlError, TimeoutError, OSError) as err:
            raise OneBoxApiError("Could not connect to Allegro") from err

    async def async_close(self) -> None:
        """Stop accepting requests and release any request interrupted by shutdown."""
        if self._closed:
            return
        self._closed = True
        # Closing an active request also makes HA shutdown/unload release sockets.
        # AsyncSession.close is idempotent; its context manager closes it again safely.
        for session in tuple(self._active_sessions):
            await session.close()


def _finite_number(value: Any, minimum: float, maximum: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and minimum <= value <= maximum
    )


def _is_access_challenge(body: str) -> bool:
    lowered = body.lower()
    return any(
        marker in lowered
        for marker in ("captcha-delivery.com", "<title>access denied", "<title>just a moment")
    )


def _map_params(
    ne_lat: float, ne_lng: float, sw_lat: float, sw_lng: float
) -> dict[str, str | float]:
    return {
        "withAirQuality": "false",
        "filter": "allegro-one",
        "countryCode": "PL",
        "brandKeys": BRAND_KEY,
        "neLat": ne_lat,
        "neLng": ne_lng,
        "swLat": sw_lat,
        "swLng": sw_lng,
    }


def parse_map_result(raw: Any) -> SearchResult:
    """Validate the public map response, preserving incomplete-area information."""
    if not isinstance(raw, dict):
        raise ValueError("Map data is not an object")
    points, clusters = raw.get("points"), raw.get("clusters")
    if not isinstance(points, list) or not isinstance(clusters, list):
        raise ValueError("Map points or clusters are missing")
    result: dict[str, MapPoint] = {}
    for point in points:
        if not isinstance(point, dict):
            raise ValueError("Map point is invalid")
        if point.get("brandKey") != BRAND_KEY:
            continue
        coordinates = point.get("coordinates")
        if not isinstance(coordinates, dict):
            raise ValueError("Map coordinates are missing")
        latitude, longitude = coordinates.get("lat"), coordinates.get("lng")
        if not _finite_number(latitude, -90, 90) or not _finite_number(longitude, -180, 180):
            raise ValueError("Map coordinates are invalid")
        point_id = parse_point_id(str(point.get("id")))
        result[point_id] = MapPoint(
            point_id,
            parse_point_code(point.get("carrierPointId")),
            float(latitude),
            float(longitude),
        )
    return SearchResult(
        tuple(sorted(result.values(), key=lambda point: point.code)), bool(clusters)
    )
