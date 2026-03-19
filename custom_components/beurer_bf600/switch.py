"""Connection control switch for Beurer/Sanitas BLE Scale."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .coordinator import BeurerScaleCoordinator


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


class ConnectionSwitch(SwitchEntity, RestoreEntity):
    """Switch to enable/disable BLE connection to the scale."""

    _attr_has_entity_name = True
    _attr_translation_key = "connection"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:bluetooth"
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: BeurerScaleCoordinator,
        address: str,
        name: str,
    ) -> None:
        """Initialize the switch."""
        self._coordinator = coordinator
        self._attr_unique_id = f"{address}_connection"
        self._attr_is_on = True
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            name=name,
            manufacturer="Beurer / Sanitas",
            model=name,
        )

    async def async_added_to_hass(self) -> None:
        """Restore previous state."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == "on"
        self._coordinator.enabled = self._attr_is_on

    async def async_turn_on(self, **kwargs) -> None:
        """Enable BLE connection."""
        self._attr_is_on = True
        self._attr_icon = "mdi:bluetooth"
        self._coordinator.enabled = True
        self.async_write_ha_state()
        await self._coordinator.async_request_connect()

    async def async_turn_off(self, **kwargs) -> None:
        """Disable BLE connection."""
        self._attr_is_on = False
        self._attr_icon = "mdi:bluetooth-off"
        self.async_write_ha_state()
        await self._coordinator.async_disconnect()
