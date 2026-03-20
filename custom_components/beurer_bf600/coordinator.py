"""Data coordinator for Beurer/Sanitas BLE Scale.

Uses push-based BLE connection: connects when the scale advertises
(user steps on it), reads measurements, then disconnects.
Persists last measurement to HA Store so values survive reboots.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_CONSENT_CODE,
    CONF_MODEL_FAMILY,
    CONF_USER_INDEX,
    CONF_USER_NAME,
    CONF_USER_NAMES,
    DOMAIN,
    MODEL_FAMILY_BF600,
    RECONNECT_INTERVAL,
)
from .protocol import ScaleData, read_scale

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


class BeurerScaleCoordinator(DataUpdateCoordinator[ScaleData]):
    """Coordinator that connects to the scale on BLE advertisement."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        address: str,
        name: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{address}",
            update_interval=timedelta(seconds=RECONNECT_INTERVAL),
        )
        self._address = address
        self._name = name
        self._model_family: str = entry.data.get(CONF_MODEL_FAMILY, MODEL_FAMILY_BF600)
        self._user_index: int = entry.data.get(CONF_USER_INDEX, 1)
        self._consent_code: int = entry.data.get(CONF_CONSENT_CODE, 0)
        self._user_name: str = entry.data.get(CONF_USER_NAME, "")
        self._user_names: dict[str, str] = entry.data.get(CONF_USER_NAMES, {})
        self._client: BleakClient | None = None
        self._connect_lock = asyncio.Lock()
        self._connected = False
        self.enabled = True
        self._last_data: ScaleData | None = None
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{address}")

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def address(self) -> str:
        return self._address

    @property
    def device_name(self) -> str:
        return self._name

    @property
    def user_name(self) -> str:
        """Return display name for current measurement's user."""
        # Check user_names dict first (maps initials to full name)
        if self._last_data and self._last_data.user_initials:
            mapped = self._user_names.get(self._last_data.user_initials, "")
            if mapped:
                return mapped
        # Fall back to single user_name config
        return self._user_name

    @property
    def user_names(self) -> dict[str, str]:
        return self._user_names

    async def async_load_stored_data(self) -> None:
        """Load last measurement from persistent storage."""
        stored = await self._store.async_load()
        if stored and isinstance(stored, dict):
            data = ScaleData()
            data.weight_kg = stored.get("weight_kg")
            data.body_fat_percent = stored.get("body_fat_percent")
            data.body_water_percent = stored.get("body_water_percent")
            data.muscle_percent = stored.get("muscle_percent")
            data.bone_mass_kg = stored.get("bone_mass_kg")
            data.bmi = stored.get("bmi")
            data.basal_metabolism = stored.get("basal_metabolism")
            data.impedance = stored.get("impedance")
            data.battery_level = stored.get("battery_level")
            data.user_id = stored.get("user_id")
            data.user_initials = stored.get("user_initials")
            data.all_user_initials = stored.get("all_user_initials")
            ts = stored.get("timestamp")
            if ts:
                try:
                    data.timestamp = datetime.fromisoformat(ts)
                except (ValueError, TypeError):
                    pass
            if data.has_data():
                self._last_data = data
                _LOGGER.debug("Restored stored data: weight=%.2f", data.weight_kg or 0)

    async def _save_data(self, data: ScaleData) -> None:
        """Save measurement to persistent storage."""
        await self._store.async_save({
            "weight_kg": data.weight_kg,
            "body_fat_percent": data.body_fat_percent,
            "body_water_percent": data.body_water_percent,
            "muscle_percent": data.muscle_percent,
            "bone_mass_kg": data.bone_mass_kg,
            "bmi": data.bmi,
            "basal_metabolism": data.basal_metabolism,
            "impedance": data.impedance,
            "battery_level": data.battery_level,
            "user_id": data.user_id,
            "user_initials": data.user_initials,
            "all_user_initials": data.all_user_initials,
            "timestamp": data.timestamp.isoformat() if data.timestamp else None,
        })

    @callback
    def handle_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: object,
    ) -> None:
        if not self.enabled:
            return
        _LOGGER.debug("BLE advertisement from %s, triggering connection", self._address)
        self.hass.async_create_task(self._connect())

    async def _async_update_data(self) -> ScaleData:
        if not self.enabled:
            return self._last_data or ScaleData()

        if not self._connected:
            try:
                await self._connect()
            except Exception as err:
                _LOGGER.debug("Periodic connect failed: %s: %s", type(err).__name__, err)

        return self._last_data or ScaleData()

    async def _connect(self) -> None:
        if self._connect_lock.locked() or not self.enabled:
            return

        async with self._connect_lock:
            device = async_ble_device_from_address(
                self.hass, self._address, connectable=True
            )
            if device is None:
                _LOGGER.debug("Scale %s not available", self._address)
                return

            def _ble_device_callback():
                return async_ble_device_from_address(
                    self.hass, self._address, connectable=True
                ) or device

            try:
                client = await establish_connection(
                    BleakClient,
                    device,
                    self._address,
                    disconnected_callback=self._on_disconnect,
                    max_attempts=2,
                    ble_device_callback=_ble_device_callback,
                    use_services_cache=True,
                    dangerous_use_bleak_cache=True,
                )
            except Exception as err:
                _LOGGER.debug(
                    "Connection to %s failed: %s: %s",
                    self._address, type(err).__name__, err,
                )
                return

            self._client = client
            self._connected = True
            _LOGGER.debug("Connected to %s", self._address)

            # Pair/bond with the scale — required for indications to work
            try:
                await client.pair()
                _LOGGER.debug("Paired with %s", self._address)
            except NotImplementedError:
                _LOGGER.debug("Pairing not supported by BLE backend")
            except Exception as err:
                _LOGGER.debug("Pairing failed (may already be bonded): %s", err)

            try:
                data = await read_scale(
                    client,
                    model_family=self._model_family,
                    user_index=self._user_index,
                    consent_code=self._consent_code,
                )
                if data.has_data():
                    self._last_data = data
                    self.async_set_updated_data(data)
                    self.hass.async_create_task(self._save_data(data))
                    _LOGGER.debug("Scale data: %s", data)
            except Exception:
                _LOGGER.exception("Error reading scale %s", self._address)
            finally:
                try:
                    await client.disconnect()
                except BleakError:
                    pass
                self._client = None
                self._connected = False

    def _on_disconnect(self, _client: BleakClient) -> None:
        self._connected = False
        self._client = None
        _LOGGER.debug("Scale %s disconnected", self._address)

    async def async_disconnect(self) -> None:
        self.enabled = False
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except BleakError:
                pass
        self._client = None
        self._connected = False

    async def async_request_connect(self) -> None:
        self.enabled = True
        await self._connect()
