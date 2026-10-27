"""Select any Polish One Box using Allegro's live map or a public identifier."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.helpers.selector import (
    LocationSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
)

from .api import (
    OneBoxApiError,
    OneBoxBlockedError,
    OneBoxClient,
    OneBoxDataError,
    OneBoxNotFoundError,
)
from .const import (
    CONF_ADDRESS,
    CONF_LOCATION,
    CONF_POINT_CODE,
    CONF_POINT_ID,
    CONF_RADIUS_KM,
    DEFAULT_RADIUS_KM,
    DOMAIN,
    MAX_RADIUS_KM,
    MIN_RADIUS_KM,
)
from .models import MapPoint, parse_point_code, parse_point_id


def _api_error_key(error: OneBoxApiError) -> str:
    if isinstance(error, OneBoxBlockedError):
        return "access_blocked"
    if isinstance(error, OneBoxNotFoundError):
        return "point_not_found"
    if isinstance(error, OneBoxDataError):
        return "invalid_data"
    return "cannot_connect"


class OneBoxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create one entry per physical One Box without an external service."""

    VERSION = 3

    def __init__(self) -> None:
        self._points: tuple[MapPoint, ...] = ()
        self._location: dict[str, float] | None = None
        self._radius_km: float = DEFAULT_RADIUS_KM

    async def _async_validate_and_create(self, value: str) -> ConfigFlowResult:
        try:
            point_id = parse_point_id(value)
        except ValueError:
            code = parse_point_code(value)
            async with OneBoxClient() as client:
                point_id = await client.async_resolve_code(code)
        await self.async_set_unique_id(point_id)
        self._abort_if_unique_id_configured()
        async with OneBoxClient() as client:
            result = await client.async_get_point(point_id)
        point = result.point
        # Null airQuality is a valid point that is temporarily without a reading.
        return self.async_create_entry(
            title=f"{point.code} — {point.address}",
            data={
                CONF_POINT_ID: point.id,
                CONF_POINT_CODE: point.code,
                CONF_ADDRESS: point.address,
            },
        )

    async def _async_handle_value(
        self, value: str
    ) -> tuple[ConfigFlowResult | None, dict[str, str]]:
        try:
            return await self._async_validate_and_create(value), {}
        except ValueError:
            return None, {CONF_POINT_ID: "invalid_point"}
        except OneBoxApiError as err:
            return None, {"base": _api_error_key(err)}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Offer map-based search or a code, ID, or public link."""
        return self.async_show_menu(step_id="user", menu_options=["nearby", "manual"])

    async def async_step_nearby(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Query a bounded area selected on Home Assistant's map."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._location = user_input[CONF_LOCATION]
            self._radius_km = user_input[CONF_RADIUS_KM]
            try:
                async with OneBoxClient() as client:
                    result = await client.async_search_points(
                        self._location["latitude"], self._location["longitude"], self._radius_km
                    )
            except ValueError:
                errors["base"] = "invalid_location"
            except OneBoxApiError as err:
                errors["base"] = _api_error_key(err)
            else:
                if result.has_clusters:
                    # Clustered responses do not enumerate all points in the area.
                    errors["base"] = "area_too_large"
                elif not result.points:
                    errors["base"] = "no_points"
                else:
                    self._points = tuple(sorted(result.points, key=self._distance_km))
                    return await self.async_step_select()

        location = self._location or {
            "latitude": self.hass.config.latitude,
            "longitude": self.hass.config.longitude,
        }
        return self.async_show_form(
            step_id="nearby",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOCATION, default=location): LocationSelector(),
                    vol.Required(CONF_RADIUS_KM, default=self._radius_km): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_RADIUS_KM,
                            max=MAX_RADIUS_KM,
                            step=0.1,
                            mode=NumberSelectorMode.BOX,
                            unit_of_measurement="km",
                        )
                    ),
                }
            ),
        )

    async def async_step_select(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Fetch a selected point's address and validate its live page."""
        errors: dict[str, str] = {}
        if user_input is not None:
            point_id = user_input[CONF_POINT_ID]
            if point_id not in {point.id for point in self._points}:
                errors[CONF_POINT_ID] = "invalid_point"
            else:
                result, errors = await self._async_handle_value(point_id)
                if result is not None:
                    return result
        options = [
            {
                "value": point.id,
                "label": f"{point.code} · {self._distance_km(point):.1f} km",
            }
            for point in self._points
        ]
        return self.async_show_form(
            step_id="select",
            errors=errors,
            data_schema=vol.Schema(
                {vol.Required(CONF_POINT_ID): SelectSelector(SelectSelectorConfig(options=options))}
            ),
        )

    def _distance_km(self, point: MapPoint) -> float:
        """Keep point labels useful without fetching each point's separate page."""
        location = self._location or {
            "latitude": self.hass.config.latitude,
            "longitude": self.hass.config.longitude,
        }
        return point.distance_km(location["latitude"], location["longitude"])

    async def async_step_manual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Resolve a One Box code or validate a numeric ID or public map link."""
        errors: dict[str, str] = {}
        if user_input is not None:
            result, errors = await self._async_handle_value(user_input[CONF_POINT_ID])
            if result is not None:
                return result
        return self.async_show_form(
            step_id="manual",
            errors=errors,
            data_schema=vol.Schema({vol.Required(CONF_POINT_ID): str}),
        )
