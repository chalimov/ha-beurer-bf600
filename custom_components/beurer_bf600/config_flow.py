"""Config flow for Beurer/Sanitas BLE Scale."""

from __future__ import annotations

import asyncio
import logging
import struct
from typing import Any

import voluptuous as vol
from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback

from .const import (
    CHAR_CUSTOM_FFFF_USER_LIST,
    CHAR_USER_CONTROL_POINT,
    CONF_CONSENT_CODE,
    CONF_MODEL_FAMILY,
    CONF_USER_CONSENTS,
    CONF_USER_INDEX,
    CONF_USER_NAME,
    CONF_USER_NAMES,
    DEVICE_NAME_PATTERNS,
    DOMAIN,
    MODEL_FAMILY_BF600,
    MODEL_FAMILY_BF700,
    UCP_CONSENT,
    UCP_RESPONSE,
    UCP_SUCCESS,
)

_LOGGER = logging.getLogger(__name__)

WEIGHT_SCALE_UUID = "0000181d-0000-1000-8000-00805f9b34fb"
BODY_COMP_UUID = "0000181b-0000-1000-8000-00805f9b34fb"
CUSTOM_FFE0_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"


def _detect_model_family(name: str) -> str:
    n = name.lower()
    if any(p in n for p in ("sbf72", "sbf73", "bf600", "bf850")):
        return MODEL_FAMILY_BF600
    if any(p in n for p in ("bf700", "bf710", "bf800", "sbf70", "sbf75")):
        return MODEL_FAMILY_BF700
    return MODEL_FAMILY_BF600


def _is_supported(name: str | None) -> bool:
    if not name:
        return False
    return any(p.lower() in name.lower() for p in DEVICE_NAME_PATTERNS)


def _is_scale_service(info: BluetoothServiceInfoBleak) -> bool:
    uuids = {str(u).lower() for u in (info.service_uuids or [])}
    return bool(uuids & {WEIGHT_SCALE_UUID, BODY_COMP_UUID, CUSTOM_FFE0_UUID})


class BeurerScaleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Beurer/Sanitas BLE Scale."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}
        self._address: str | None = None
        self._name: str = "Beurer Scale"
        self._pair_error: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow (used for re-pairing)."""
        return BeurerScalePairFlow(config_entry)

    # --- Bluetooth auto-discovery ---

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        _LOGGER.debug("Discovered: %s (%s)", discovery_info.name, discovery_info.address)
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        self._address = discovery_info.address
        self._name = discovery_info.name or "Beurer Scale"
        self.context["title_placeholders"] = {"name": self._name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        assert self._discovery_info is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._name,
                data={
                    CONF_ADDRESS: self._discovery_info.address,
                    CONF_NAME: self._name,
                    CONF_MODEL_FAMILY: _detect_model_family(self._name),
                    CONF_USER_INDEX: 0,
                    CONF_CONSENT_CODE: 0,
                },
            )
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._name},
        )

    # --- Manual setup ---

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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
                    CONF_USER_INDEX: 0,
                    CONF_CONSENT_CODE: 0,
                },
            )

        self._discovered_devices = {}
        for info in async_discovered_service_info(self.hass, connectable=True):
            if _is_supported(info.name) or _is_scale_service(info):
                self._discovered_devices[info.address] = info
        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ADDRESS): vol.In(
                        {a: f"{i.name} ({a})" for a, i in self._discovered_devices.items()}
                    ),
                }
            ),
        )


class BeurerScalePairFlow(OptionsFlow):
    """Options flow for pairing with the scale.

    Steps:
    1. init: "Step on the scale to wake it, then click Submit"
    2. pairing: Connect, pair, query user list
    3. enter_pin: "Enter the PIN shown on the scale display"
    4. Done — consent code saved
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._address: str = config_entry.data[CONF_ADDRESS]
        self._name: str = config_entry.data.get(CONF_NAME, "Beurer Scale")
        self._pair_result: str | None = None
        self._user_list: list[dict] = []
        self._selected_initials: str | None = None

    def _get_all_initials(self) -> dict[int, str]:
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        result: dict[int, str] = {}
        if coordinator and coordinator.data and coordinator.data.all_user_initials:
            result = coordinator.data.all_user_initials
        elif coordinator and coordinator._last_data and coordinator._last_data.all_user_initials:
            result = coordinator._last_data.all_user_initials
        if not result and coordinator and coordinator._last_data:
            d = coordinator._last_data
            if d.user_initials and d.user_id:
                result = {d.user_id: d.user_initials}
        return {int(k): v for k, v in result.items()}

    def _get_names(self) -> dict[str, str]:
        names: dict[str, str] = dict(self.config_entry.data.get(CONF_USER_NAMES, {}))
        if not names:
            old = self.config_entry.data.get(CONF_USER_NAME, "")
            if old:
                for initials in self._get_all_initials().values():
                    names[initials] = old
                    break
        return names

    def _get_consents(self) -> dict[int, int]:
        """Return per-user consent codes from config."""
        raw = self.config_entry.data.get(CONF_USER_CONSENTS, {})
        result = {int(k): int(v) for k, v in raw.items() if int(v) > 0}
        # Merge legacy single-user consent
        legacy_idx = self.config_entry.data.get(CONF_USER_INDEX, 0)
        legacy_code = self.config_entry.data.get(CONF_CONSENT_CODE, 0)
        if legacy_idx and legacy_code and legacy_idx not in result:
            result[legacy_idx] = legacy_code
        return result

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Assign full names and consent codes to scale users."""
        from homeassistant.data_entry_flow import section

        all_initials = self._get_all_initials()
        names = self._get_names()
        consents = self._get_consents()

        if user_input is not None:
            if user_input.get("repair"):
                return await self.async_step_wake_scale()

            # Extract names and consent codes from sectioned input
            new_names = {}
            new_consents = {}
            for idx, initials in sorted(all_initials.items()):
                sect_key = f"user_{initials}"
                sect_data = user_input.get(sect_key, {})
                if isinstance(sect_data, dict):
                    full = sect_data.get("full_name", "").strip()
                    if full:
                        new_names[initials] = full
                    code = int(sect_data.get("consent_code", 0) or 0)
                    if code > 0:
                        new_consents[str(idx)] = code

            new_data = {**self.config_entry.data}
            new_data[CONF_USER_NAMES] = new_names
            new_data[CONF_USER_CONSENTS] = new_consents
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=new_data
            )
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            return self.async_create_entry(data={})

        # Build schema: one section per user with name + consent code
        schema_dict = {}
        for idx, initials in sorted(all_initials.items()):
            sect_key = f"user_{initials}"
            default_name = names.get(initials, "")
            default_code = consents.get(idx, 0)
            schema_dict[vol.Optional(sect_key)] = section(
                vol.Schema({
                    vol.Optional("full_name", default=default_name): str,
                    vol.Optional("consent_code", default=default_code): int,
                }),
                {"collapsed": False},
            )

        if not all_initials:
            info = "No users found — step on the scale first."
        else:
            info = ""

        schema_dict[vol.Optional("repair", default=False)] = bool

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"name": self._name, "info": info},
        )

    async def async_step_wake_scale(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pairing step 1: Ask user to wake the scale."""
        if user_input is not None:
            return await self.async_step_pairing()

        return self.async_show_form(
            step_id="wake_scale",
            data_schema=vol.Schema({}),
            description_placeholders={"name": self._name},
        )

    async def async_step_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: Connect, pair, read user list."""
        errors: dict[str, str] = {}

        device = async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if device is None:
            errors["base"] = "scale_not_found"
            return self.async_show_form(
                step_id="wake_scale",
                data_schema=vol.Schema({}),
                errors=errors,
                description_placeholders={"name": self._name},
            )

        pair_ok = False
        user_list_data: list[dict] = []

        try:
            client = await establish_connection(
                BleakClient, device, self._address, max_attempts=2,
                use_services_cache=True, dangerous_use_bleak_cache=True,
            )
        except Exception as err:
            _LOGGER.error("Connection failed: %s", err)
            errors["base"] = "connection_failed"
            return self.async_show_form(
                step_id="wake_scale", data_schema=vol.Schema({}), errors=errors,
                description_placeholders={"name": self._name},
            )

        try:
            # Attempt BLE pairing/bonding
            try:
                await client.pair()
                pair_ok = True
                _LOGGER.info("BLE pairing successful with %s", self._address)
            except NotImplementedError:
                _LOGGER.debug("Pairing not supported by backend")
            except Exception as err:
                _LOGGER.warning("BLE pairing failed: %s", err)
                self._pair_result = str(err)

            # Read user list from custom 0xFFFF service
            user_list_data = await self._read_user_list(client)
        finally:
            try:
                await client.disconnect()
            except BleakError:
                pass

        self._user_list = user_list_data
        return await self.async_step_enter_pin()

    async def _read_user_list(self, client: BleakClient) -> list[dict]:
        """Query the custom user list from the scale."""
        users: list[dict] = []
        event = asyncio.Event()

        def _on_user_list(_char, data: bytearray) -> None:
            if len(data) < 1:
                return
            status = data[0]
            if status == 0x01:  # end of list
                event.set()
            elif status == 0x00 and len(data) >= 12:  # user record
                idx = data[1]
                initials = data[2:5].decode("ascii", errors="replace").strip()
                year = struct.unpack(">H", data[5:7])[0]
                month, day = data[7], data[8]
                height = data[9]
                gender = data[10]
                activity = data[11]
                users.append({
                    "index": idx,
                    "initials": initials,
                    "birth_year": year,
                    "height": height,
                })
                _LOGGER.debug("User %d: %s, born %d, %dcm", idx, initials, year, height)
            elif status == 0x02:  # no users
                event.set()

        try:
            await client.start_notify(CHAR_CUSTOM_FFFF_USER_LIST, _on_user_list)
            await client.write_gatt_char(CHAR_CUSTOM_FFFF_USER_LIST, bytes([0x00]), response=True)
            await asyncio.wait_for(event.wait(), timeout=5.0)
        except Exception as err:
            _LOGGER.debug("User list query failed: %s", err)

        return users

    async def async_step_enter_pin(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 3: Enter the PIN from the scale display."""
        errors: dict[str, str] = {}

        if user_input is not None:
            pin = int(user_input.get("pin", 0))
            user_index = int(user_input.get(CONF_USER_INDEX, 1))
            user_name = user_input.get(CONF_USER_NAME, "").strip()

            # Verify the consent code works
            verified = await self._verify_consent(user_index, pin)
            if verified:
                # Save to config entry
                new_data = {**self.config_entry.data}
                new_data[CONF_USER_INDEX] = user_index
                new_data[CONF_CONSENT_CODE] = pin
                new_data[CONF_USER_NAME] = user_name
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=new_data
                )
                await self.hass.config_entries.async_reload(self.config_entry.entry_id)
                return self.async_create_entry(data={})
            else:
                errors["base"] = "consent_rejected"

        # Build user selection: known users + all possible slots (1-8)
        user_options = {}
        for u in self._user_list:
            user_options[str(u["index"])] = f"User {u['index']}: {u['initials']} ({u['height']}cm)"
        # Add unoccupied slots (scale supports up to 8)
        for i in range(1, 9):
            if str(i) not in user_options:
                user_options[str(i)] = f"User {i}: (new slot)"

        return self.async_show_form(
            step_id="enter_pin",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USER_INDEX, default="1"): vol.In(user_options),
                    vol.Required("pin"): vol.All(
                        vol.Coerce(int), vol.Range(min=0, max=999999)
                    ),
                    vol.Optional(CONF_USER_NAME, default=""): str,
                }
            ),
            errors=errors,
            description_placeholders={
                "name": self._name,
                "pair_result": "Paired successfully" if not self._pair_result else f"Pairing: {self._pair_result}",
                "users": ", ".join(f"{u['initials']}(#{u['index']})" for u in self._user_list) or "none found",
            },
        )

    async def _verify_consent(self, user_index: int, consent_code: int) -> bool:
        """Connect and verify the consent code works."""
        device = async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if device is None:
            return False

        try:
            client = await establish_connection(
                BleakClient, device, self._address, max_attempts=2,
                use_services_cache=True, dangerous_use_bleak_cache=True,
            )
        except Exception:
            return False

        success = False
        event = asyncio.Event()

        def _on_ucp(_char, data: bytearray) -> None:
            nonlocal success
            if len(data) >= 3 and data[0] == UCP_RESPONSE and data[1] == UCP_CONSENT:
                success = data[2] == UCP_SUCCESS
                event.set()

        try:
            await client.start_notify(CHAR_USER_CONTROL_POINT, _on_ucp)
            cmd = struct.pack("<BBH", UCP_CONSENT, user_index, consent_code)
            _LOGGER.debug("Verifying consent: user=%d code=%d cmd=%s", user_index, consent_code, cmd.hex())
            await client.write_gatt_char(CHAR_USER_CONTROL_POINT, cmd, response=True)
            await asyncio.wait_for(event.wait(), timeout=5.0)
        except Exception as err:
            _LOGGER.debug("Consent verification failed: %s", err)
        finally:
            try:
                await client.disconnect()
            except BleakError:
                pass

        _LOGGER.info("Consent verification: user=%d code=%d result=%s", user_index, consent_code, success)
        return success
