"""Beurer/Sanitas BLE Body Composition Scale integration for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothCallbackMatcher, BluetoothScanningMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import BeurerScaleCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.SWITCH]

_PATCHED = False

# Pre-import at module level to avoid blocking call inside event loop
try:
    import aioesphomeapi.model as _esphome_model
except ImportError:
    _esphome_model = None


def _patch_esphome_uuid_parser() -> None:
    """Monkey-patch aioesphomeapi to handle malformed BLE UUIDs.

    The ESPHome BLE proxy can crash with IndexError when a device sends
    a GATT service with an empty or malformed UUID protobuf field.
    This patch makes _convert_bluetooth_uuid resilient to such cases.
    """
    global _PATCHED
    if _PATCHED or _esphome_model is None:
        return

    _original = _esphome_model._convert_bluetooth_uuid

    def _safe_convert_bluetooth_uuid(value):
        try:
            return _original(value)
        except (IndexError, AttributeError, TypeError):
            # Fallback: try to reconstruct from whatever data is available
            uuid_list = getattr(value, "uuid", None) or []
            short = getattr(value, "short_uuid", 0)
            _LOGGER.debug(
                "UUID parse fallback: short_uuid=%s, uuid=%s",
                short, uuid_list,
            )
            if len(uuid_list) == 2:
                high, low = uuid_list
                from uuid import UUID as _UUID
                return str(_UUID(int=(high << 64) | low))
            if len(uuid_list) == 1:
                return f"{uuid_list[0]:08x}-0000-1000-8000-00805f9b34fb"
            # short_uuid=0 with empty uuid list means the ESPHome proxy
            # couldn't parse this UUID. Return zero UUID as short BLE UUID.
            return "00000000-0000-1000-8000-00805f9b34fb"

    _esphome_model._convert_bluetooth_uuid = _safe_convert_bluetooth_uuid
    _PATCHED = True
    _LOGGER.debug("Patched aioesphomeapi UUID parser for BLE proxy compatibility")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Beurer Scale from a config entry."""
    _patch_esphome_uuid_parser()

    address: str = entry.data[CONF_ADDRESS]
    name: str = entry.data.get(CONF_NAME, "Beurer Scale")

    coordinator = BeurerScaleCoordinator(hass, entry, address, name)

    # Register BLE advertisement callback to trigger connections
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            coordinator.handle_bluetooth_event,
            BluetoothCallbackMatcher(address=address, connectable=True),
            BluetoothScanningMode.ACTIVE,
        )
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: BeurerScaleCoordinator = hass.data[DOMAIN][entry.entry_id]
    coordinator.enabled = False

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    await coordinator.async_disconnect()
    return unload_ok
