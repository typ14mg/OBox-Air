"""Diagnostics limited to public point data and integration status."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import OneBoxConfigEntry
from .const import MAX_AGE_SECONDS, POLL_SECONDS


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OneBoxConfigEntry
) -> dict[str, Any]:
    """Exclude search locations, cookies, response bodies, and exception messages."""
    coordinator = entry.runtime_data
    reading = coordinator.data
    return {
        "point": {
            "id": coordinator.point.id,
            "code": coordinator.point.code,
            "source_url": coordinator.point.url,
        },
        "available": coordinator.available,
        "last_update_success": coordinator.last_update_success,
        "last_exception_type": (
            type(coordinator.last_exception).__name__ if coordinator.last_exception else None
        ),
        "poll_interval_seconds": POLL_SECONDS,
        "max_measurement_age_seconds": MAX_AGE_SECONDS,
        "reading": (
            {
                "pm25": reading.pm25,
                "pm10": reading.pm10,
                "measured_at": reading.measured_at.isoformat(),
                "allegro_quality": reading.quality,
            }
            if reading is not None
            else None
        ),
    }
