"""Binary sensor for Beurer/Sanitas BLE Scale connection status."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BeurerScaleCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the connection status binary sensor."""
    coordinator: BeurerScaleCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    name = entry.data.get(CONF_NAME, "Beurer Scale")
    async_add_entities([ConnectionStatusSensor(coordinator, address, name)])


class ConnectionStatusSensor(
    CoordinatorEntity[BeurerScaleCoordinator], BinarySensorEntity
):
    """Binary sensor showing whether the scale has synced data.

    ON = scale has sent measurement data (sensors are populated)
    OFF = no data received yet
    """

    _attr_has_entity_name = True
    _attr_translation_key = "connected"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: BeurerScaleCoordinator,
        address: str,
        name: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{address}_connected"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=name,
            manufacturer="Beurer / Sanitas",
            model=name,
        )

    @property
    def is_on(self) -> bool:
        """Return True if we have received data from the scale."""
        return (
            self.coordinator.data is not None
            and self.coordinator.data.has_data()
        )

    @property
    def available(self) -> bool:
        """Always available so we can show the state."""
        return True
