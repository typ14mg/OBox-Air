"""Coordinate native HTTP polling and source-time measurement expiration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import OneBoxApiError, OneBoxClient
from .const import MAX_AGE_SECONDS, POLL_SECONDS
from .models import Point, Reading

_LOGGER = logging.getLogger(__name__)


class OneBoxCoordinator(DataUpdateCoordinator[Reading | None]):
    """Poll Allegro directly, without an external scraper or broker."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, point: Point, client: OneBoxClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"One Box {point.code}",
            update_interval=timedelta(seconds=POLL_SECONDS),
        )
        self.point = point
        self.client = client
        self.data = None
        self._stopped = False
        self._cancel_expiry: CALLBACK_TYPE | None = None
        self._unsub_ha_stop: CALLBACK_TYPE | None = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STOP, self._async_ha_stop
        )

    @property
    def available(self) -> bool:
        return bool(
            not self._stopped
            and self.last_update_success
            and self.data is not None
            and self.data.is_fresh(dt_util.utcnow(), MAX_AGE_SECONDS)
        )

    async def _async_update_data(self) -> Reading | None:
        try:
            result = await self.client.async_get_point(self.point.id)
        except OneBoxApiError as err:
            raise UpdateFailed(str(err)) from err
        if result.point.id != self.point.id:
            raise UpdateFailed("Allegro returned a different point")
        return result.reading

    @callback
    def _async_refresh_finished(self) -> None:
        self._clear_expiry()
        if self.available and self.data is not None:
            self._cancel_expiry = async_track_point_in_utc_time(
                self.hass, self._measurement_expired, self.data.expires_at(MAX_AGE_SECONDS)
            )

    @callback
    def _measurement_expired(self, _now: datetime) -> None:
        self._cancel_expiry = None
        self.async_update_listeners()

    @callback
    def _clear_expiry(self) -> None:
        if self._cancel_expiry is not None:
            self._cancel_expiry()
            self._cancel_expiry = None

    async def _async_ha_stop(self, _event: Event) -> None:
        # The once-only event subscription has already removed itself.
        self._unsub_ha_stop = None
        await self.async_stop()

    async def async_stop(self) -> None:
        """Cancel polling and expiration, then close any active HTTP request."""
        if self._stopped:
            return
        self._stopped = True
        self._clear_expiry()
        if self._unsub_ha_stop is not None:
            self._unsub_ha_stop()
            self._unsub_ha_stop = None
        try:
            await self.async_shutdown()
        finally:
            await self.client.async_close()
