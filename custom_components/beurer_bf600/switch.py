"""Connection control switch for Beurer/Sanitas BLE Scale."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BeurerScaleCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the connection switch."""
    coordinator: BeurerScaleCoordinator = hass.data[DOMAIN][entry.entry_id]
    address = entry.data[CONF_ADDRESS]
    name = entry.data.get(CONF_NAME, "Beurer Scale")
    async_add_entities([ConnectionSwitch(coordinator, address, name)])


class ConnectionSwitch(CoordinatorEntity[BeurerScaleCoordinator], SwitchEntity, RestoreEntity):
    """Switch to enable/disable BLE connection to the scale.

    When ON: the integration listens for BLE advertisements and connects
    automatically when the scale wakes up (someone steps on it).
    When OFF: BLE advertisements are ignored, no connections made.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "connection"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: BeurerScaleCoordinator,
        address: str,
        name: str,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{address}_connection"
        self._attr_is_on = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=name,
            manufacturer="Beurer / Sanitas",
            model=name,
        )

    @property
    def icon(self) -> str:
        """Return icon based on state."""
        return "mdi:bluetooth" if self._attr_is_on else "mdi:bluetooth-off"

    @property
    def available(self) -> bool:
        """Always available."""
        return True

    async def async_added_to_hass(self) -> None:
        """Restore previous state."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"
        self.coordinator.enabled = self._attr_is_on
        _LOGGER.debug("Connection switch restored: %s", "on" if self._attr_is_on else "off")

    async def async_turn_on(self, **kwargs) -> None:
        """Enable BLE connection — scale will sync next time it wakes."""
        self._attr_is_on = True
        self.coordinator.enabled = True
        self.async_write_ha_state()
        _LOGGER.debug("BLE connection enabled")

    async def async_turn_off(self, **kwargs) -> None:
        """Disable BLE connection — stop listening for scale."""
        self._attr_is_on = False
        self.coordinator.enabled = False
        self.async_write_ha_state()
        _LOGGER.debug("BLE connection disabled")
        # Disconnect if currently connected
        await self.coordinator.async_disconnect()
