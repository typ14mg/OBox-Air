"""A minimal real Home Assistant instance for offline integration tests."""

import pytest_asyncio
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant


@pytest_asyncio.fixture
async def hass(tmp_path):
    instance = HomeAssistant(str(tmp_path))
    instance.config_entries = ConfigEntries(instance, {})
    yield instance
    await instance.async_stop(force=True)
