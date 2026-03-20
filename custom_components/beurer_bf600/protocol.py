"""BLE protocol implementation for Beurer/Sanitas body composition scales.

Supports two protocol families:
- BF600/SBF72/SBF73: Standard BLE Weight Scale Profile (0x181D) +
  Body Composition Service (0x181B) + custom 0xFFF0 service
- BF700/SBF70/SBF75: Proprietary protocol on 0xFFE0/0xFFE1
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import struct
from dataclasses import dataclass, field

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic

from .const import (
    BCM_FLAG_BASAL_METABOLISM,
    BCM_FLAG_BODY_WATER_MASS,
    BCM_FLAG_HEIGHT,
    BCM_FLAG_IMPEDANCE,
    BCM_FLAG_IMPERIAL,
    BCM_FLAG_MUSCLE_MASS,
    BCM_FLAG_MUSCLE_PERCENTAGE,
    BCM_FLAG_MULTIPLE_PACKET,
    BCM_FLAG_SOFT_LEAN_MASS,
    BCM_FLAG_TIMESTAMP,
    BCM_FLAG_USER_ID,
    BCM_FLAG_WEIGHT,
    CHAR_BATTERY_LEVEL,
    CHAR_BODY_COMPOSITION_MEASUREMENT,
    CHAR_CURRENT_TIME,
    CHAR_CUSTOM_FFE1,
    CHAR_CUSTOM_FFFF_MEASURE_REQ,
    CHAR_CUSTOM_FFFF_USER_LIST,
    CHAR_CUSTOM_TAKE_MEASUREMENT,
    CHAR_DATABASE_CHANGE_INCREMENT,
    CHAR_USER_CONTROL_POINT,
    CHAR_WEIGHT_MEASUREMENT,
    MODEL_FAMILY_BF600,
    MODEL_FAMILY_BF700,
    START_NIBBLE_BF700,
    START_NIBBLE_SANITAS,
    UCP_CONSENT,
    UCP_RESPONSE,
    UCP_SUCCESS,
    WSM_FLAG_BMI_HEIGHT,
    WSM_FLAG_IMPERIAL,
    WSM_FLAG_TIMESTAMP,
    WSM_FLAG_USER_ID,
)

_LOGGER = logging.getLogger(__name__)

WEIGHT_RESOLUTION_KG = 0.005  # Standard BLE: 5g resolution
WEIGHT_RESOLUTION_LB = 0.01


@dataclass
class ScaleData:
    """Body composition measurement data from the scale."""

    weight_kg: float | None = None
    body_fat_percent: float | None = None
    body_water_percent: float | None = None
    muscle_percent: float | None = None
    bone_mass_kg: float | None = None
    bmi: float | None = None
    basal_metabolism: int | None = None
    impedance: int | None = None
    battery_level: int | None = None
    timestamp: datetime.datetime | None = None
    user_id: int | None = None
    user_initials: str | None = None
    all_user_initials: dict[int, str] | None = None  # {1: "AS", 2: "ELA"}
    connected: bool = False

    def has_data(self) -> bool:
        """Return True if any measurement data is present."""
        return self.weight_kg is not None or self.body_fat_percent is not None

    def merge(self, other: ScaleData) -> None:
        """Merge non-None values from another ScaleData."""
        for attr in (
            "weight_kg", "body_fat_percent", "body_water_percent",
            "muscle_percent", "bone_mass_kg", "bmi", "basal_metabolism",
            "impedance", "battery_level", "timestamp", "user_id", "user_initials",
            "all_user_initials",
        ):
            val = getattr(other, attr)
            if val is not None:
                setattr(self, attr, val)


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

async def read_scale(
    client: BleakClient,
    model_family: str = MODEL_FAMILY_BF600,
    user_index: int = 1,
    consent_code: int = 0,
    user_consents: dict[int, int] | None = None,
) -> ScaleData:
    """Connect to a scale and read all available measurement data.

    user_consents: dict mapping user_index → consent_code for all known users.
    Falls back to user_index/consent_code if not provided (single-user mode).
    """
    # Log discovered GATT services for diagnostics
    if client.services:
        for service in client.services:
            chars = ", ".join(
                f"{c.uuid}({c.properties})" for c in service.characteristics
            )
            _LOGGER.debug("GATT service %s: %s", service.uuid, chars)
    else:
        _LOGGER.debug("No GATT services discovered (services=%s)", client.services)

    # Build consents dict: merge legacy single-user with multi-user
    consents = dict(user_consents or {})
    if user_index and consent_code and user_index not in consents:
        consents[user_index] = consent_code

    ctx = _ReadContext(client, user_index, consent_code=consent_code,
                       user_consents=consents)

    if model_family == MODEL_FAMILY_BF700:
        await _read_bf700(ctx)
    else:
        await _read_bf600(ctx)

    # Read battery
    try:
        raw = await client.read_gatt_char(CHAR_BATTERY_LEVEL)
        if raw and len(raw) >= 1:
            ctx.data.battery_level = raw[0]
    except Exception:
        _LOGGER.debug("Could not read battery level")

    ctx.data.connected = True
    return ctx.data


# ---------------------------------------------------------------------------
# Internal read context
# ---------------------------------------------------------------------------

@dataclass
class _ReadContext:
    client: BleakClient
    user_index: int
    consent_code: int = 0
    user_consents: dict[int, int] = field(default_factory=dict)
    data: ScaleData = field(default_factory=ScaleData)
    event: asyncio.Event = field(default_factory=asyncio.Event)


# ---------------------------------------------------------------------------
# BF600 / SBF72 / SBF73 — standard BLE profile
# ---------------------------------------------------------------------------

async def _read_bf600(ctx: _ReadContext) -> None:
    """Read using standard BLE Weight Scale / Body Composition services.

    Protocol sequence:
    1. Subscribe to all notification/indication characteristics
    2. Write current time, query user list
    3. Consent for each user, collect stored measurements
    4. Pick the freshest measurement, resolve user initials
    5. Clear consent so the scale uses its own user detection next time
    """
    client = ctx.client

    # Subscribe to ALL notify/indicate characteristics
    subs = [
        (CHAR_WEIGHT_MEASUREMENT, "Weight(0x2A9D)", _on_weight_measurement),
        (CHAR_BODY_COMPOSITION_MEASUREMENT, "BodyComp(0x2A9C)", _on_body_composition),
        (CHAR_USER_CONTROL_POINT, "UCP(0x2A9F)", _on_ucp_response),
        (CHAR_CUSTOM_FFFF_USER_LIST, "FFFF/UserList(0x0001)", _on_custom_notification),
        (CHAR_CUSTOM_FFFF_MEASURE_REQ, "FFFF/Measure(0x0006)", _on_custom_notification),
    ]
    for char_uuid, name, handler in subs:
        try:
            await client.start_notify(char_uuid, lambda c, d, h=handler: h(ctx, c, d))
            _LOGGER.debug("Subscribed: %s", name)
        except Exception as e:
            _LOGGER.debug("Subscribe %s failed: %s", name, e)

    # Write current time
    await _write_current_time(client)

    # Query user list
    try:
        await client.write_gatt_char(
            CHAR_CUSTOM_FFFF_USER_LIST, bytes([0x00]), response=True
        )
        _LOGGER.debug("Wrote trigger to FFFF/UserList")
    except Exception as e:
        _LOGGER.debug("Write FFFF/UserList failed: %s", e)

    # Wait for the scale to finish weighing and store the result.
    # With consent cleared from the previous session, the scale uses its
    # own weight-based user detection. We must not consent during this
    # time or it would override the detection.
    _LOGGER.debug("Waiting 20s for scale to complete measurement...")
    await asyncio.sleep(20.0)

    # Consent for each user and collect stored measurements
    consents = ctx.user_consents
    if not consents:
        consents = {ctx.user_index: ctx.consent_code}

    best: ScaleData | None = None
    for uid, code in sorted(consents.items()):
        result = await _consent_and_read(ctx, uid, code)
        if result and result.has_data():
            _LOGGER.debug(
                "User %d data: weight=%.2f ts=%s",
                uid, result.weight_kg or 0,
                result.timestamp.isoformat() if result.timestamp else "none",
            )
            best = result
            # Stop after first user with data — consenting for more users
            # would re-tag the same measurement under a different user.
            break

    if best:
        ctx.data.merge(best)

    # Resolve user_initials from all_user_initials + user_id
    if ctx.data.user_id and ctx.data.all_user_initials and not ctx.data.user_initials:
        ctx.data.user_initials = ctx.data.all_user_initials.get(ctx.data.user_id)

    # Clear consent so the scale uses its own weight-based user detection
    # for the next measurement. Without this, the last-consented user would
    # be used for all future measurements regardless of who steps on.
    await _clear_consent(client)


async def _clear_consent(client: BleakClient) -> None:
    """Clear the active UCP consent by sending consent for user 0.

    The scale rejects this (Not Authorized) but the side effect is that
    the active user is reset, allowing the scale to use its own weight-based
    user detection for the next measurement.
    """
    try:
        cmd = struct.pack("<BBH", UCP_CONSENT, 0, 0)
        await client.write_gatt_char(CHAR_USER_CONTROL_POINT, cmd, response=True)
        _LOGGER.debug("Consent cleared (user=0)")
    except Exception as e:
        _LOGGER.debug("Clear consent failed: %s", e)


def _is_newer(a: ScaleData, b: ScaleData) -> bool:
    """Return True if measurement a is newer than b."""
    if a.timestamp and b.timestamp:
        return a.timestamp > b.timestamp
    return a.timestamp is not None


async def _consent_and_read(
    ctx: _ReadContext, user_index: int, consent_code: int
) -> ScaleData | None:
    """Consent as a specific user, trigger measurement, return data."""
    client = ctx.client

    # Reset event and data for this user
    ctx.event.clear()
    user_data = ScaleData()
    saved_data = ctx.data
    user_data.all_user_initials = saved_data.all_user_initials
    ctx.data = user_data

    try:
        consent_cmd = struct.pack("<BBH", UCP_CONSENT, user_index, consent_code)
        _LOGGER.debug(
            "UCP consent: user=%d code=%d/0x%04X",
            user_index, consent_code, consent_code,
        )
        await client.write_gatt_char(
            CHAR_USER_CONTROL_POINT, consent_cmd, response=True
        )
    except Exception as e:
        _LOGGER.debug("UCP consent failed for user %d: %s", user_index, e)
        ctx.data = saved_data
        return None

    # Trigger stored measurement retrieval
    try:
        await client.write_gatt_char(
            CHAR_CUSTOM_FFFF_MEASURE_REQ, bytes([0x00]), response=True
        )
    except Exception:
        pass

    # Short wait — data is already stored, no need for long timeout
    try:
        await asyncio.wait_for(ctx.event.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        _LOGGER.debug("No stored data for user %d", user_index)

    await asyncio.sleep(0.3)

    result = ctx.data
    ctx.data = saved_data
    if result.all_user_initials:
        saved_data.all_user_initials = result.all_user_initials
    return result if result.has_data() else None


# ---------------------------------------------------------------------------
# BF700 / SBF70 / SBF75 — proprietary 0xFFE0/FFE1 protocol
# ---------------------------------------------------------------------------

async def _read_bf700(ctx: _ReadContext) -> None:
    """Read using proprietary BF700/SBF70 protocol on 0xFFE0/FFE1."""
    client = ctx.client

    try:
        await client.start_notify(
            CHAR_CUSTOM_FFE1,
            lambda c, d: _on_ffe1_notification(ctx, c, d),
        )
    except Exception:
        _LOGGER.debug("FFE1 characteristic unavailable")
        return

    # Send init command (Sanitas nibble by default)
    init_cmd = bytes([START_NIBBLE_SANITAS | 0x06, 0x01])
    try:
        await client.write_gatt_char(CHAR_CUSTOM_FFE1, init_cmd, response=False)
    except Exception:
        _LOGGER.debug("Failed to send init command")
        return

    try:
        await asyncio.wait_for(ctx.event.wait(), timeout=20.0)
    except asyncio.TimeoutError:
        _LOGGER.debug("Timeout waiting for BF700 data")


# ---------------------------------------------------------------------------
# Notification parsers
# ---------------------------------------------------------------------------

def _on_weight_measurement(
    ctx: _ReadContext, _char: BleakGATTCharacteristic, data: bytearray
) -> None:
    """Parse standard BLE Weight Scale Measurement (0x2A9D)."""
    if len(data) < 3:
        return

    m = ScaleData()
    offset = 0
    flags = data[offset]
    offset += 1

    raw_weight = struct.unpack_from("<H", data, offset)[0]
    offset += 2
    if flags & WSM_FLAG_IMPERIAL:
        m.weight_kg = raw_weight * WEIGHT_RESOLUTION_LB * 0.453592
    else:
        m.weight_kg = raw_weight * WEIGHT_RESOLUTION_KG

    if flags & WSM_FLAG_TIMESTAMP and offset + 7 <= len(data):
        year = struct.unpack_from("<H", data, offset)[0]
        month, day = data[offset + 2], data[offset + 3]
        hour, minute, second = data[offset + 4], data[offset + 5], data[offset + 6]
        offset += 7
        try:
            m.timestamp = datetime.datetime(year, month, day, hour, minute, second).astimezone()
        except ValueError:
            pass

    if flags & WSM_FLAG_USER_ID and offset < len(data):
        m.user_id = data[offset]
        offset += 1

    if flags & WSM_FLAG_BMI_HEIGHT and offset + 4 <= len(data):
        m.bmi = struct.unpack_from("<H", data, offset)[0] * 0.1
        offset += 4  # skip BMI (2) + height (2), height not stored

    _LOGGER.debug("Weight measurement: %.2f kg, user=%s", m.weight_kg, m.user_id)

    if m.user_id and ctx.data.all_user_initials:
        m.user_initials = ctx.data.all_user_initials.get(m.user_id)

    ctx.data.merge(m)
    ctx.event.set()


def _on_body_composition(
    ctx: _ReadContext, _char: BleakGATTCharacteristic, data: bytearray
) -> None:
    """Parse standard BLE Body Composition Measurement (0x2A9C)."""
    if len(data) < 4:
        return

    m = ScaleData()
    offset = 0
    flags = struct.unpack_from("<H", data, offset)[0]
    offset += 2

    # Body fat % (always present)
    m.body_fat_percent = struct.unpack_from("<H", data, offset)[0] * 0.1
    offset += 2

    if flags & BCM_FLAG_TIMESTAMP and offset + 7 <= len(data):
        year = struct.unpack_from("<H", data, offset)[0]
        month, day = data[offset + 2], data[offset + 3]
        hour, minute, second = data[offset + 4], data[offset + 5], data[offset + 6]
        offset += 7
        try:
            m.timestamp = datetime.datetime(year, month, day, hour, minute, second).astimezone()
        except ValueError:
            pass

    if flags & BCM_FLAG_USER_ID and offset < len(data):
        m.user_id = data[offset]
        offset += 1

    if flags & BCM_FLAG_BASAL_METABOLISM and offset + 2 <= len(data):
        m.basal_metabolism = struct.unpack_from("<H", data, offset)[0]
        offset += 2

    muscle_pct = None
    if flags & BCM_FLAG_MUSCLE_PERCENTAGE and offset + 2 <= len(data):
        muscle_pct = struct.unpack_from("<H", data, offset)[0] * 0.1
        offset += 2

    muscle_mass_kg = None
    if flags & BCM_FLAG_MUSCLE_MASS and offset + 2 <= len(data):
        raw = struct.unpack_from("<H", data, offset)[0]
        muscle_mass_kg = raw * (WEIGHT_RESOLUTION_LB * 0.453592 if flags & BCM_FLAG_IMPERIAL else WEIGHT_RESOLUTION_KG)
        offset += 2

    if flags & 0x0040 and offset + 2 <= len(data):  # Fat Free Mass flag
        offset += 2

    if flags & BCM_FLAG_SOFT_LEAN_MASS and offset + 2 <= len(data):
        offset += 2

    water_kg = None
    if flags & BCM_FLAG_BODY_WATER_MASS and offset + 2 <= len(data):
        raw = struct.unpack_from("<H", data, offset)[0]
        water_kg = raw * (WEIGHT_RESOLUTION_LB * 0.453592 if flags & BCM_FLAG_IMPERIAL else WEIGHT_RESOLUTION_KG)
        offset += 2

    if flags & BCM_FLAG_IMPEDANCE and offset + 2 <= len(data):
        m.impedance = struct.unpack_from("<H", data, offset)[0]
        offset += 2

    if flags & BCM_FLAG_WEIGHT and offset + 2 <= len(data):
        raw = struct.unpack_from("<H", data, offset)[0]
        m.weight_kg = raw * (WEIGHT_RESOLUTION_LB * 0.453592 if flags & BCM_FLAG_IMPERIAL else WEIGHT_RESOLUTION_KG)
        offset += 2

    if flags & BCM_FLAG_HEIGHT and offset + 2 <= len(data):
        offset += 2

    # Convert body water from absolute kg to percentage
    if water_kg is not None and m.weight_kg and m.weight_kg > 0:
        m.body_water_percent = (water_kg / m.weight_kg) * 100
    elif water_kg is not None:
        m.body_water_percent = water_kg  # fallback: store raw

    # Store muscle as percentage
    if muscle_pct is not None and muscle_pct > 0:
        m.muscle_percent = muscle_pct
    elif muscle_mass_kg and m.weight_kg and m.weight_kg > 0:
        m.muscle_percent = (muscle_mass_kg / m.weight_kg) * 100

    _LOGGER.debug(
        "Body composition: fat=%.1f%%, water=%.1f%%, muscle=%.1f%%",
        m.body_fat_percent or 0, m.body_water_percent or 0, m.muscle_percent or 0,
    )

    if flags & BCM_FLAG_MULTIPLE_PACKET:
        ctx.data.merge(m)
        return

    ctx.data.merge(m)
    ctx.event.set()


def _on_custom_notification(
    ctx: _ReadContext, _char: BleakGATTCharacteristic, data: bytearray
) -> None:
    """Handle notification from custom FFFF service (BF105/SBF73 variant)."""
    _LOGGER.debug(
        "Custom FFFF notification: char=%s len=%d data=%s",
        _char.uuid, len(data), data.hex(),
    )
    # Parse user list entries to capture all users
    if str(_char.uuid).startswith("00000001") and len(data) >= 12 and data[0] == 0x00:
        idx = data[1]
        initials = data[2:5].decode("ascii", errors="replace").strip()
        if ctx.data.all_user_initials is None:
            ctx.data.all_user_initials = {}
        ctx.data.all_user_initials[idx] = initials
        _LOGGER.debug("User %d initials: %s", idx, initials)


def _on_ucp_response(
    ctx: _ReadContext, _char: BleakGATTCharacteristic, data: bytearray
) -> None:
    """Handle User Control Point response."""
    if len(data) >= 3 and data[0] == UCP_RESPONSE:
        if data[2] == UCP_SUCCESS:
            _LOGGER.debug("UCP consent accepted")
        else:
            _LOGGER.warning("UCP consent rejected: %d", data[2])


def _on_ffe1_notification(
    ctx: _ReadContext, _char: BleakGATTCharacteristic, data: bytearray
) -> None:
    """Parse proprietary BF700/SBF70 notification on FFE1.

    Measurement payload (16 bytes after start byte):
    [0:4]   timestamp (uint32 BE, Unix seconds)
    [4:6]   weight (uint16 BE, × 50 / 1000 = kg)
    [6:8]   impedance (uint16 BE, raw Ω)
    [8:10]  body fat (uint16 BE, ÷ 10 = %)
    [10:12] body water (uint16 BE, ÷ 10 = %)
    [12:14] muscle (uint16 BE, ÷ 10 = %)
    [14:16] bone mass (uint16 BE, × 50 / 1000 = kg)
    """
    if len(data) < 2:
        return

    start_byte = data[0]
    high_nibble = start_byte & 0xF0
    _LOGGER.debug("FFE1: start=0x%02X len=%d data=%s", start_byte, len(data), data.hex())

    # Only accept notifications from known device families
    if high_nibble not in (START_NIBBLE_SANITAS, START_NIBBLE_BF700):
        return

    payload = data[1:]
    if len(payload) < 16:
        return

    # Validate: first 4 bytes should be a plausible Unix timestamp (after year 2000)
    ts_raw = struct.unpack(">I", payload[0:4])[0]
    if ts_raw < 946684800:  # 2000-01-01 00:00:00 UTC
        return  # Not a measurement frame

    m = ScaleData()

    if ts_raw > 0:
        m.timestamp = datetime.datetime.fromtimestamp(
            ts_raw, tz=datetime.timezone.utc
        )

    m.weight_kg = struct.unpack(">H", payload[4:6])[0] * 50.0 / 1000.0
    m.impedance = struct.unpack(">H", payload[6:8])[0]
    m.body_fat_percent = struct.unpack(">H", payload[8:10])[0] / 10.0
    m.body_water_percent = struct.unpack(">H", payload[10:12])[0] / 10.0

    muscle_pct = struct.unpack(">H", payload[12:14])[0] / 10.0
    if muscle_pct > 0:
        m.muscle_percent = muscle_pct

    m.bone_mass_kg = struct.unpack(">H", payload[14:16])[0] * 50.0 / 1000.0

    _LOGGER.debug(
        "FFE1 measurement: w=%.2fkg fat=%.1f%% water=%.1f%% muscle=%.1f%% bone=%.2fkg",
        m.weight_kg, m.body_fat_percent, m.body_water_percent,
        m.muscle_percent or 0, m.bone_mass_kg,
    )

    if m.weight_kg and m.weight_kg > 0:
        ctx.data.merge(m)
        ctx.event.set()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _write_current_time(client: BleakClient) -> None:
    """Write current time to the scale for synchronization."""
    try:
        now = datetime.datetime.now()
        time_data = struct.pack(
            "<HBBBBB", now.year, now.month, now.day, now.hour, now.minute, now.second
        )
        time_data += bytes([now.isoweekday(), 0, 0])  # 1=Mon..7=Sun per BLE spec
        await client.write_gatt_char(CHAR_CURRENT_TIME, time_data, response=True)
    except Exception:
        _LOGGER.debug("Could not write current time")
