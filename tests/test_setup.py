"""Load the complete integration in real HA with an offline HTTP transport."""

from __future__ import annotations

import json
import shutil
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from homeassistant import bootstrap, loader
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

import custom_components.allegro_onebox_air as component
from custom_components.allegro_onebox_air import config_flow
from custom_components.allegro_onebox_air.api import OneBoxBlockedError, parse_point_html
from custom_components.allegro_onebox_air.const import DOMAIN
from custom_components.allegro_onebox_air.models import MapPoint, SearchResult

ROOT = Path(__file__).resolve().parents[1]
POINT_ID = "1522606"
FIXTURE = (ROOT / "tests/fixtures/onebox_point.html").read_text(encoding="utf-8")
DETAILS = json.loads(
    FIXTURE.split('data-serialize-box-id="KNaG9a8EQaCGVvRN59iUiw==">', 1)[1].split("</script>", 1)[
        0
    ]
)["details"]


class OfflineClient:
    """Only replace Allegro's transport, keeping real HA loading and parsing."""

    def __init__(self):
        self.closed = False
        self.error = None
        self.calls = []

    async def async_get_point(self, point_id):
        self.calls.append(point_id)
        if self.error:
            raise self.error
        details = deepcopy(DETAILS)
        if point_id == "9000001":
            details.update(
                id=point_id,
                pointNumber="ALTESTW1",
                address={
                    "city": "Warszawa",
                    "street": "Synthetic test street",
                },
            )
        details["airQuality"]["metricDate"] = datetime.now(UTC).isoformat()
        body = '<script type="application/json">' + json.dumps({"details": details}) + "</script>"
        return parse_point_html(body, point_id)

    async def async_search_points(self, latitude, longitude, radius):
        return SearchResult((MapPoint("9000001", "ALTESTW1", latitude, longitude),), False)

    async def async_close(self):
        self.closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.async_close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,old_version", [("manual", 1), ("nearby", 2)])
async def test_real_ha_flow_sensors_reload_unload_and_shutdown(
    tmp_path, monkeypatch, mode, old_version
):
    """Exercise registry/setup lifecycle without reaching Allegro or MQTT."""
    config_dir = tmp_path / "ha"
    config_dir.mkdir()
    (config_dir / "configuration.yaml").write_text("{}\n", encoding="utf-8")
    shutil.copytree(ROOT / "custom_components" / DOMAIN, config_dir / "custom_components" / DOMAIN)
    clients = []

    def make_client():
        result = OfflineClient()
        clients.append(result)
        return result

    monkeypatch.setattr(component, "OneBoxClient", make_client)
    monkeypatch.setattr(config_flow, "OneBoxClient", make_client)
    # Keep HA's real registries/flows/platforms; no frontend, telemetry or sockets.
    monkeypatch.setattr(bootstrap, "DEFAULT_INTEGRATIONS", set())
    hass = HomeAssistant(str(config_dir))
    try:
        loader.async_setup(hass)
        result = await bootstrap.async_from_config_dict(
            {
                "homeassistant": {
                    "latitude": 51.07,
                    "longitude": 19.44,
                    "elevation": 220,
                    "unit_system": "metric",
                    "time_zone": "Europe/Warsaw",
                }
            },
            hass,
        )
        assert result is hass
        point_id = POINT_ID if mode == "manual" else "9000001"
        flow = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        assert flow["type"] == "menu" and flow["menu_options"] == ["nearby", "manual"]
        flow = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"next_step_id": mode}
        )
        assert flow["type"] == "form" and flow["step_id"] == mode
        if mode == "nearby":
            flow = await hass.config_entries.flow.async_configure(
                flow["flow_id"],
                {
                    "location": {"latitude": 52.23, "longitude": 21.01},
                    "radius_km": 2,
                },
            )
            assert flow["step_id"] == "select"
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"point_id": point_id}
        )
        assert result["type"] == "create_entry"
        await hass.async_block_till_done()
        entry = hass.config_entries.async_entries(DOMAIN)[0]
        assert entry.state == ConfigEntryState.LOADED
        registry = er.async_get(hass)
        ids = {
            key: registry.async_get_entity_id("sensor", DOMAIN, point_id + "_" + key)
            for key in ("pm25", "pm10", "measured_at")
        }
        assert all(ids.values())
        assert hass.states.get(ids["pm25"]).state == "30"
        assert hass.states.get(ids["pm10"]).state == "38"
        assert hass.states.get(ids["pm25"]).attributes["device_class"] == "pm25"
        assert hass.states.get(ids["measured_at"]).attributes["device_class"] == "timestamp"
        assert len(clients) == (2 if mode == "manual" else 3) and clients[0].closed
        assert entry.runtime_data.update_interval.total_seconds() == 300
        assert entry.runtime_data._cancel_expiry is not None

        duplicate = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
        duplicate = await hass.config_entries.flow.async_configure(
            duplicate["flow_id"], {"next_step_id": "manual"}
        )
        duplicate = await hass.config_entries.flow.async_configure(
            duplicate["flow_id"], {"point_id": point_id}
        )
        assert duplicate["type"] == "abort" and duplicate["reason"] == "already_configured"

        first_client = entry.runtime_data.client
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        assert first_client.closed and entry.state == ConfigEntryState.LOADED
        assert entry.runtime_data.client is not first_client
        assert hass.states.get(ids["pm25"]).state == "30"

        entry.runtime_data.client.error = OneBoxBlockedError("offline test")
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(ids["pm25"]).state == "unavailable"
        assert hass.states.get(ids["pm10"]).state == "unavailable"
        entry.runtime_data.client.error = None
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(ids["pm25"]).state == "30"

        active_client = entry.runtime_data.client
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
        assert active_client.closed and entry.state == ConfigEntryState.NOT_LOADED
        # HA preserves entity-registry entries as unavailable after unloading.
        assert all(hass.states.get(entity_id).state == "unavailable" for entity_id in ids.values())

        # Earlier MQTT and HTTP entries keep the same sensors during migration.
        hass.config_entries.async_update_entry(
            entry,
            version=old_version,
            data={**entry.data, "topic_prefix": "old/onebox"},
            options={"topic_prefix": "old/onebox", "retained_option": True},
        )
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.version == 3 and "topic_prefix" not in entry.data
        assert entry.options == {"retained_option": True}
        assert registry.async_get_entity_id("sensor", DOMAIN, point_id + "_pm25") == ids["pm25"]
        final_client = entry.runtime_data.client
        assert not final_client.closed
        await hass.async_stop(force=True)
        assert final_client.closed
        assert entry.runtime_data._cancel_expiry is None
    finally:
        await hass.async_stop(force=True)
