"""Config flow for Beurer/Sanitas BLE Scale."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_NAME

from .const import (
    CONF_MODEL_FAMILY,
    CONF_USER_INDEX,
    DEVICE_NAME_PATTERNS,
    DOMAIN,
    MODEL_FAMILY_BF600,
    MODEL_FAMILY_BF700,
)

_LOGGER = logging.getLogger(__name__)

# UUIDs used for discovery filtering
WEIGHT_SCALE_UUID = "0000181d-0000-1000-8000-00805f9b34fb"
BODY_COMP_UUID = "0000181b-0000-1000-8000-00805f9b34fb"
CUSTOM_FFE0_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"


def _detect_model_family(name: str) -> str:
    """Detect the model family from the device name."""
    n = name.lower()
    if any(p in n for p in ("sbf72", "sbf73", "bf600", "bf850")):
        return MODEL_FAMILY_BF600
    if any(p in n for p in ("bf700", "bf710", "bf800", "sbf70", "sbf75")):
        return MODEL_FAMILY_BF700
    return MODEL_FAMILY_BF600


def _is_supported(name: str | None) -> bool:
    """Check if a device name matches a supported scale."""
    if not name:
        return False
    n = name.lower()
    return any(p.lower() in n for p in DEVICE_NAME_PATTERNS)


def _is_scale_service(info: BluetoothServiceInfoBleak) -> bool:
    """Check if the device advertises scale-related service UUIDs."""
    uuids = {str(u).lower() for u in (info.service_uuids or [])}
    return bool(uuids & {WEIGHT_SCALE_UUID, BODY_COMP_UUID, CUSTOM_FFE0_UUID})


class BeurerScaleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Beurer/Sanitas BLE Scale."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle bluetooth auto-discovery."""
        _LOGGER.debug("Discovered: %s (%s)", discovery_info.name, discovery_info.address)
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or "Beurer Scale"
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm bluetooth discovery."""
        assert self._discovery_info is not None
        name = self._discovery_info.name or "Beurer Scale"

        if user_input is not None:
            return self.async_create_entry(
                title=name,
                data={
                    CONF_ADDRESS: self._discovery_info.address,
                    CONF_NAME: name,
                    CONF_MODEL_FAMILY: _detect_model_family(name),
                    CONF_USER_INDEX: user_input.get(CONF_USER_INDEX, 1),
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_USER_INDEX, default=1): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=8)
                    ),
                }
            ),
            description_placeholders={"name": name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual setup: show discovered devices."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()

            name = "Beurer Scale"
            if address in self._discovered_devices:
                name = self._discovered_devices[address].name or name

            return self.async_create_entry(
                title=name,
                data={
                    CONF_ADDRESS: address,
                    CONF_NAME: name,
                    CONF_MODEL_FAMILY: _detect_model_family(name),
                    CONF_USER_INDEX: user_input.get(CONF_USER_INDEX, 1),
                },
            )

        # Discover available scales
        self._discovered_devices = {}
        for info in async_discovered_service_info(self.hass, connectable=True):
            if _is_supported(info.name) or _is_scale_service(info):
                self._discovered_devices[info.address] = info

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        device_options = {
            addr: f"{info.name} ({addr})"
            for addr, info in self._discovered_devices.items()
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(device_options),
                    vol.Optional(CONF_USER_INDEX, default=1): vol.All(
                        vol.Coerce(int), vol.Range(min=1, max=8)
                    ),
                }
            ),
        )
