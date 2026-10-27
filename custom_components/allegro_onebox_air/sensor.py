"""Sensors populated by One Box source measurements."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import CONCENTRATION_MICROGRAMS_PER_CUBIC_METER, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import OneBoxConfigEntry
from .const import DOMAIN
from .coordinator import OneBoxCoordinator

PARALLEL_UPDATES = 0

SENSORS = (
    SensorEntityDescription(
        key="pm25",
        translation_key="pm25",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="pm10",
        translation_key="pm10",
        device_class=SensorDeviceClass.PM10,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="measured_at",
        translation_key="measured_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: OneBoxConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create the two particulate sensors and source timestamp sensor."""
    coordinator: OneBoxCoordinator = entry.runtime_data
    async_add_entities(OneBoxSensor(coordinator, description) for description in SENSORS)


class OneBoxSensor(CoordinatorEntity[OneBoxCoordinator], SensorEntity):
    """A sensor with a unique ID based on the stable physical point ID."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: OneBoxCoordinator, description: SensorEntityDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        point = coordinator.point
        self._attr_unique_id = f"{point.id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, point.id)},
            name=f"One Box {point.code}",
            manufacturer="Allegro",
            model="Allegro One Box",
            configuration_url=point.url,
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def available(self) -> bool:
        return self.coordinator.available

    @property
    def native_value(self) -> float | int | datetime | None:
        data = self.coordinator.data
        return getattr(data, self.entity_description.key) if data is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        point = self.coordinator.point
        return {
            "point_code": point.code,
            "point_id": point.id,
            "address": point.address,
            "source": "Allegro One Box",
            "source_url": point.url,
            "allegro_quality": self.coordinator.data.quality if self.coordinator.data else None,
        }
