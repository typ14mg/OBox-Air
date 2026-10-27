"""Validate public One Box measurements independently of Home Assistant."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .const import BASE_URL, BRAND_KEY, FUTURE_TOLERANCE_SECONDS, MAX_AGE_SECONDS


@dataclass(frozen=True)
class Point:
    """A stable Allegro point identity."""

    id: str
    code: str
    address: str

    @property
    def url(self) -> str:
        return BASE_URL + "?pointId=" + self.id


@dataclass(frozen=True)
class Reading:
    """A validated measurement with its source timestamp."""

    pm25: float | int
    pm10: float | int
    measured_at: datetime
    quality: str | None

    def is_fresh(self, now: datetime, max_age: int = MAX_AGE_SECONDS) -> bool:
        age = (now - self.measured_at).total_seconds()
        return -FUTURE_TOLERANCE_SECONDS <= age < max_age

    def expires_at(self, max_age: int = MAX_AGE_SECONDS) -> datetime:
        return self.measured_at + timedelta(seconds=max_age)


@dataclass(frozen=True)
class PointData:
    """Point metadata and an optional current air measurement."""

    point: Point
    reading: Reading | None


@dataclass(frozen=True)
class MapPoint:
    """Public point metadata returned by Allegro's map search."""

    id: str
    code: str
    latitude: float
    longitude: float

    def distance_km(self, latitude: float, longitude: float) -> float:
        """Return the great-circle distance from the chosen search location."""
        lat1, lat2 = math.radians(latitude), math.radians(self.latitude)
        latitude_delta = lat2 - lat1
        longitude_delta = math.radians(self.longitude - longitude)
        haversine = (
            math.sin(latitude_delta / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(longitude_delta / 2) ** 2
        )
        return 6371.0088 * 2 * math.asin(math.sqrt(min(1, haversine)))


@dataclass(frozen=True)
class SearchResult:
    """Map search results, including whether the area contains clusters."""

    points: tuple[MapPoint, ...]
    has_clusters: bool


def parse_point_id(value: str) -> str:
    """Accept a numeric public point ID or its Allegro map link."""
    if not isinstance(value, str):
        raise ValueError("Point ID must be a string or an Allegro map link")
    candidate = value.strip()
    if "://" in candidate:
        url = urlsplit(candidate)
        if url.scheme != "https" or url.hostname not in {"allegro.pl", "www.allegro.pl"}:
            raise ValueError("Use an Allegro map link")
        ids = parse_qs(url.query).get("pointId", [])
        if len(ids) != 1:
            raise ValueError("The map link must contain one pointId")
        candidate = ids[0]
    if not re.fullmatch(r"[0-9]{1,20}", candidate) or int(candidate) == 0:
        raise ValueError("Invalid point ID")
    return str(int(candidate))


def validate_point(point_id: str, code: str, address: str) -> Point:
    """Validate a point identity from saved or live metadata."""
    if not isinstance(address, str):
        raise ValueError("Invalid point address")
    point_id, code, address = parse_point_id(point_id), parse_point_code(code), address.strip()
    if not address or len(address) > 200:
        raise ValueError("Invalid point address")
    return Point(point_id, code, address)


def parse_point_code(value: str) -> str:
    """Normalize a public One Box code without accepting arbitrary query text."""
    if not isinstance(value, str) or not re.fullmatch(
        r"AL[A-Z0-9]{1,30}", code := value.strip().upper()
    ):
        raise ValueError("Invalid point code")
    return code


def parse_details(
    details: Any, point_id: str, *, now: datetime | None = None, max_age: int = MAX_AGE_SECONDS
) -> PointData:
    """Validate embedded point data and map pmLow/pmHigh to PM2.5/PM10."""
    if not isinstance(details, dict) or str(details.get("id")) != point_id:
        raise ValueError("The page contains a different point")
    if details.get("brandKey") != BRAND_KEY:
        raise ValueError("This is not an Allegro One Box")
    address = details.get("address")
    if not isinstance(address, dict):
        raise ValueError("Point address is missing")
    city, street = address.get("city"), address.get("street")
    if (
        not isinstance(city, str)
        or not isinstance(street, str)
        or not city.strip()
        or not street.strip()
    ):
        raise ValueError("Point address is invalid")
    code = details.get("pointNumber")
    if not isinstance(code, str):
        raise ValueError("Point code is missing")
    point = validate_point(point_id, code, f"{city}, {street}")
    air = details.get("airQuality")
    if air is None:
        return PointData(point, None)
    if not isinstance(air, dict):
        raise ValueError("Air measurement is invalid")
    values: list[int | float] = []
    for field in ("pmLow", "pmHigh"):
        channel = air.get(field)
        value = channel.get("value") if isinstance(channel, dict) else None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Missing numeric {field}")
        if not math.isfinite(value) or not 0 <= value <= 999:
            raise ValueError(f"Out of range {field}")
        values.append(value)
    stamp = air.get("metricDate")
    if not isinstance(stamp, str):
        raise ValueError("Missing measurement time")
    measured = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if measured.tzinfo is None:
        raise ValueError("Measurement time must include a timezone")
    quality = air.get("quality")
    reading = Reading(
        pm25=values[0],
        pm10=values[1],
        measured_at=measured.astimezone(UTC),
        quality=quality if isinstance(quality, str) else None,
    )
    if not reading.is_fresh(now or datetime.now(UTC), max_age):
        raise ValueError("Measurement is stale or in the future")
    return PointData(point, reading)
