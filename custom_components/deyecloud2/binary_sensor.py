from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, DeyeCloudCoordinator


@dataclass
class DeyeBinarySensorDescription(BinarySensorEntityDescription):
    key_source: str | None = None


BINARY_SENSOR_MAP: dict[str, DeyeBinarySensorDescription] = {
    "device_online": DeyeBinarySensorDescription(
        key="device_online",
        name="Device Online",
        icon="mdi:power",
        device_class="connectivity",
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DeyeCloudCoordinator = data["coordinator"]

    entities: list[DeyeCloudBinarySensor] = []
    
    # Create binary sensors from predefined map
    for key, description in BINARY_SENSOR_MAP.items():
        entities.append(
            DeyeCloudBinarySensor(
                coordinator,
                key=key,
                description=description,
            )
        )

    async_add_entities(entities)


class DeyeCloudBinarySensor(CoordinatorEntity[DeyeCloudCoordinator], BinarySensorEntity):
    def __init__(
        self, 
        coordinator: DeyeCloudCoordinator, 
        key: str, 
        description: DeyeBinarySensorDescription
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = f"Deye {description.name}"
        self._attr_unique_id = f"deyecloud2_{key}"
        self._attr_icon = description.icon
        self._attr_device_class = description.device_class
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, "deyecloud2")},
            manufacturer="Deye",
            name="Deye Inverter",
        )

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._device_info

    @property
    def is_on(self) -> bool | None:
        payload = self.coordinator.data.get(self._key)
        if payload is None:
            return None
        value = payload.get("value")
        if isinstance(value, bool):
            return value
        return bool(value) if value is not None else None
