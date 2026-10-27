"""OBox Air integration for public Allegro One Box measurements."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .api import OneBoxClient
from .const import CONF_ADDRESS, CONF_POINT_CODE, CONF_POINT_ID
from .coordinator import OneBoxCoordinator
from .models import validate_point

PLATFORMS = [Platform.SENSOR]
type OneBoxConfigEntry = ConfigEntry[OneBoxCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: OneBoxConfigEntry) -> bool:
    """Fetch the One Box directly, then create its sensors."""
    try:
        point = validate_point(
            entry.data[CONF_POINT_ID], entry.data[CONF_POINT_CODE], entry.data[CONF_ADDRESS]
        )
    except (ValueError, KeyError) as err:
        raise ConfigEntryError("Invalid saved One Box identity") from err
    client = OneBoxClient()
    coordinator = OneBoxCoordinator(hass, entry, point, client)
    try:
        await coordinator.async_config_entry_first_refresh()
        entry.runtime_data = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_stop()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OneBoxConfigEntry) -> bool:
    """Remove the entry's entities and release its polling resources."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Preserve IDs and entities when upgrading the earlier MQTT prototype."""
    if entry.version > 3:
        return False
    if entry.version < 3:
        data = dict(entry.data)
        data.pop("topic_prefix", None)
        options = dict(entry.options)
        options.pop("topic_prefix", None)
        hass.config_entries.async_update_entry(
            entry, data=data, options=options, version=3, minor_version=1
        )
    return True
