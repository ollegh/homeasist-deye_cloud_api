from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import DOMAIN, DeyeCloudCoordinator


@dataclass
class DeyeSensorDescription(SensorEntityDescription):
    key_source: str | None = None


# Icon mapping for different sensor types
ICON_MAP = {
    "power": "mdi:lightning-bolt",
    "voltage": "mdi:lightning-bolt-outline", 
    "current": "mdi:current-ac",
    "frequency": "mdi:sine-wave",
    "energy": "mdi:battery-charging",
    "temperature": "mdi:thermometer",
    "percentage": "mdi:percent",
    "default": "mdi:chart-line"
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DeyeCloudCoordinator = data["coordinator"]

    entities: list[DeyeCloudSensor] = []
    # Create initial sensors from current data
    for key, payload in coordinator.data.items():
        entities.append(DeyeCloudSensor(coordinator, key=key, name=payload.get("name", key)))

    async_add_entities(entities)

    # Register listener to add new sensors if new keys appear later
    known_keys: set[str] = set(coordinator.data.keys())

    def _maybe_add_new_sensors() -> None:
        new_entities: list[DeyeCloudSensor] = []
        for key, payload in coordinator.data.items():
            if key in known_keys:
                continue
            known_keys.add(key)
            new_entities.append(DeyeCloudSensor(coordinator, key=key, name=payload.get("name", key)))
        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(_maybe_add_new_sensors)


class DeyeCloudSensor(CoordinatorEntity[DeyeCloudCoordinator], SensorEntity):
    def __init__(self, coordinator: DeyeCloudCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = f"Deye {name}"
        self._attr_unique_id = f"deyecloud2_{key}"
        # Derive device_class/state_class from unit/name
        self._attr_device_class, self._attr_state_class = self._derive_classes(name)
        
        # Set icon based on sensor type
        self._attr_icon = self._derive_icon(name)
        
        self._device_info = DeviceInfo(
            identifiers={(DOMAIN, "deyecloud2")},
            manufacturer="Deye",
            name="Deye Inverter",
            model="Deye Inverter",
            sw_version="1.0",
        )

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._device_info

    @property
    def native_value(self) -> Any:
        payload = self.coordinator.data.get(self._key)
        return None if payload is None else payload.get("value")

    @property
    def native_unit_of_measurement(self) -> str | None:
        payload = self.coordinator.data.get(self._key)
        unit = None if payload is None else payload.get("unit")
        return unit

    def _derive_classes(self, name: str) -> tuple[SensorDeviceClass | None, SensorStateClass | None]:
        payload = self.coordinator.data.get(self._key) or {}
        unit = (payload.get("unit") or "").strip()
        lname = name.lower()

        # Power
        if unit in {"W", "kW", "MW"} or "power" in lname:
            return SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT

        # Voltage
        if unit in {"V", "kV"} or "voltage" in lname:
            return SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT

        # Current
        if unit in {"A", "mA"} or "current" in lname:
            return SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT

        # Frequency
        if unit in {"Hz", "kHz"} or "frequency" in lname:
            return SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT

        # Energy
        if unit in {"Wh", "kWh", "MWh"} or "energy" in lname or "production" in lname:
            return SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING

        # Percentage
        if unit in {"%"} or lname in {"soc", "bmssoc"}:
            return SensorDeviceClass.BATTERY, SensorStateClass.MEASUREMENT

        return None, SensorStateClass.MEASUREMENT

    def _derive_icon(self, name: str) -> str:
        """Derive icon based on sensor name and type"""
        lname = name.lower()
        unit = ""
        payload = self.coordinator.data.get(self._key) or {}
        if payload:
            unit = (payload.get("unit") or "").strip().lower()
        
        # Power sensors
        if unit in {"w", "kw", "mw"} or "power" in lname:
            return ICON_MAP["power"]
        
        # Voltage sensors
        if unit in {"v", "kv"} or "voltage" in lname:
            return ICON_MAP["voltage"]
        
        # Current sensors
        if unit in {"a", "ma"} or "current" in lname:
            return ICON_MAP["current"]
        
        # Frequency sensors
        if unit in {"hz", "khz"} or "frequency" in lname:
            return ICON_MAP["frequency"]
        
        # Energy sensors
        if unit in {"wh", "kwh", "mwh"} or "energy" in lname or "production" in lname:
            return ICON_MAP["energy"]
        
        # Percentage sensors
        if unit == "%" or lname in {"soc", "bmssoc"}:
            return ICON_MAP["percentage"]
        
        # Temperature sensors
        if unit in {"°c", "°f", "c", "f"} or "temp" in lname or "temperature" in lname:
            return ICON_MAP["temperature"]
        
        return ICON_MAP["default"]

    # No entity_category assignment; default behavior keeps all entities visible


