"""Data coordinator for Beurer/Sanitas BLE Scale.

Uses push-based BLE connection: connects when the scale advertises
(user steps on it), reads measurements, then disconnects.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_MODEL_FAMILY,
    CONF_USER_INDEX,
    DOMAIN,
    MODEL_FAMILY_BF600,
    RECONNECT_INTERVAL,
)
from .protocol import ScaleData, read_scale

_LOGGER = logging.getLogger(__name__)


class BeurerScaleCoordinator(DataUpdateCoordinator[ScaleData]):
    """Coordinator that connects to the scale on BLE advertisement."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        address: str,
        name: str,
    ) -> None:
        """Initialize the coordinator."""
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
        self._client: BleakClient | None = None
        self._connect_lock = asyncio.Lock()
        self._connected = False
        self.enabled = True
        self._last_data: ScaleData | None = None

    @property
    def connected(self) -> bool:
        """Return whether the BLE device is connected."""
        return self._connected

    @property
    def address(self) -> str:
        """Return the BLE address."""
        return self._address

    @property
    def device_name(self) -> str:
        """Return the device name."""
        return self._name

    @callback
    def handle_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: object,
    ) -> None:
        """Handle a BLE advertisement from the scale.

        When the scale advertises, it means someone stepped on it or
        it has data ready. Trigger a connection attempt.
        """
        if not self.enabled:
            return
        _LOGGER.debug("BLE advertisement from %s, triggering connection", self._address)
        self.hass.async_create_task(self._connect())

    async def _async_update_data(self) -> ScaleData:
        """Periodic fallback: attempt connection if not connected."""
        if not self.enabled:
            return self._last_data or ScaleData()

        if not self._connected:
            try:
                await self._connect()
            except Exception as err:
                _LOGGER.debug("Periodic connect failed: %s: %s", type(err).__name__, err)

        return self._last_data or ScaleData()

    async def _connect(self) -> None:
        """Connect to the scale, read data, disconnect."""
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
                _LOGGER.debug("Connection to %s failed: %s: %s", self._address, type(err).__name__, err)
                return

            self._client = client
            self._connected = True
            _LOGGER.debug("Connected to %s", self._address)

            try:
                data = await read_scale(
                    client,
                    model_family=self._model_family,
                    user_index=self._user_index,
                )
                if data.has_data():
                    self._last_data = data
                    self.async_set_updated_data(data)
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
        """Handle unexpected BLE disconnection."""
        self._connected = False
        self._client = None
        _LOGGER.debug("Scale %s disconnected", self._address)

    async def async_disconnect(self) -> None:
        """Disconnect from the scale."""
        self.enabled = False
        if self._client and self._client.is_connected:
            try:
                await self._client.disconnect()
            except BleakError:
                pass
        self._client = None
        self._connected = False

    async def async_request_connect(self) -> None:
        """Request a connection attempt (called by switch entity)."""
        self.enabled = True
        await self._connect()
