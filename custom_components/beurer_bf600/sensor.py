"""Sensor entities for Beurer/Sanitas BLE Scale."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, PERCENTAGE, EntityCategory, UnitOfMass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BeurerScaleCoordinator
from .protocol import ScaleData


@dataclass(frozen=True, kw_only=True)
class BeurerSensorDescription(SensorEntityDescription):
    """Describe a Beurer scale sensor."""

    value_fn: Callable[[ScaleData], float | int | str | None]
    precision: int = 1


# Ordered from most important to least important
SENSOR_DESCRIPTIONS: tuple[BeurerSensorDescription, ...] = (
    BeurerSensorDescription(
        key="weight",
        translation_key="weight",
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        device_class=SensorDeviceClass.WEIGHT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:scale-bathroom",
        value_fn=lambda d: d.weight_kg,
        precision=2,
    ),
    BeurerSensorDescription(
        key="bmi",
        translation_key="bmi",
        native_unit_of_measurement="kg/m\u00b2",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:human-male-height",
        value_fn=lambda d: d.bmi,
    ),
    BeurerSensorDescription(
        key="body_fat",
        translation_key="body_fat",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:human",
        value_fn=lambda d: d.body_fat_percent,
    ),
    BeurerSensorDescription(
        key="muscle_mass",
        translation_key="muscle_mass",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arm-flex",
        value_fn=lambda d: d.muscle_percent,
    ),
    BeurerSensorDescription(
        key="body_water",
        translation_key="body_water",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-percent",
        value_fn=lambda d: d.body_water_percent,
    ),
    BeurerSensorDescription(
        key="bone_mass",
        translation_key="bone_mass",
        native_unit_of_measurement=UnitOfMass.KILOGRAMS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:bone",
        value_fn=lambda d: d.bone_mass_kg,
        precision=2,
    ),
    BeurerSensorDescription(
        key="basal_metabolism",
        translation_key="basal_metabolism",
        native_unit_of_measurement="kJ",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fire",
        value_fn=lambda d: d.basal_metabolism,
        precision=0,
    ),
    BeurerSensorDescription(
        key="impedance",
        translation_key="impedance",
        native_unit_of_measurement="\u03a9",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:flash",
        value_fn=lambda d: d.impedance,
        precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BeurerSensorDescription(
        key="measurement_time",
        translation_key="measurement_time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-outline",
        value_fn=lambda d: d.timestamp.isoformat() if d.timestamp else None,
        precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BeurerSensorDescription(
        key="battery",
        translation_key="battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.battery_level,
        precision=0,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Beurer scale sensors from a config entry."""
    coordinator: BeurerScaleCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    name = entry.data.get(CONF_NAME, "Beurer Scale")

    async_add_entities(
        BeurerScaleSensor(coordinator, address, name, desc)
        for desc in SENSOR_DESCRIPTIONS
    )


class BeurerScaleSensor(
    CoordinatorEntity[BeurerScaleCoordinator], SensorEntity
):
    """A sensor entity for a Beurer/Sanitas scale measurement."""

    entity_description: BeurerSensorDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: BeurerScaleCoordinator,
        address: str,
        name: str,
        description: BeurerSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{address}_{description.key}"
        self._attr_suggested_display_precision = description.precision
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=name,
            manufacturer="Beurer / Sanitas",
            model=name,
        )
        self._last_value = None

    @property
    def native_value(self):
        """Return the sensor value. Keeps last known value when scale is off."""
        if self.coordinator.data is not None and self.coordinator.data.has_data():
            value = self.entity_description.value_fn(self.coordinator.data)
            if value is not None:
                if isinstance(value, str):
                    self._last_value = value
                else:
                    self._last_value = round(value, self.entity_description.precision)
        return self._last_value

    @property
    def available(self) -> bool:
        """Available once we've ever received data."""
        return self._last_value is not None
