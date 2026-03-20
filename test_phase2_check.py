"""Phase 2: Connect, consent for each user, check who has the new measurement.
Run AFTER someone steps on the scale (after phase 1)."""

import asyncio
import struct
import datetime
import logging
from bleak import BleakClient, BleakScanner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
_LOG = logging.getLogger("test")

SCALE_ADDR = "CE:31:33:82:85:ED"
CHAR_UCP = "00002a9f-0000-1000-8000-00805f9b34fb"
CHAR_USER_LIST = "00000001-0000-1000-8000-00805f9b34fb"
CHAR_MEASURE = "00000006-0000-1000-8000-00805f9b34fb"
CHAR_WEIGHT = "00002a9d-0000-1000-8000-00805f9b34fb"
CHAR_BODY_COMP = "00002a9c-0000-1000-8000-00805f9b34fb"
CHAR_TIME = "00002a2b-0000-1000-8000-00805f9b34fb"
UCP_CONSENT = 0x02
UCP_RESPONSE = 0x20

USER_CONSENTS = {1: 3691, 2: 6942}

weight_data = {}  # {user_index: (weight, user_id_from_indication)}
got_weight = asyncio.Event()
current_consent_user = 0


def on_weight(char, data):
    if len(data) < 3:
        return
    raw = struct.unpack_from("<H", data, 1)[0]
    weight = raw * 0.005
    flags = data[0]
    offset = 3
    ts_str = ""
    if flags & 0x02 and offset + 7 <= len(data):
        year = struct.unpack_from("<H", data, offset)[0]
        month, day = data[offset+2], data[offset+3]
        hour, minute, sec = data[offset+4], data[offset+5], data[offset+6]
        ts_str = f"{year}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:{sec:02d}"
        offset += 7
    user_id = data[offset] if flags & 0x04 and offset < len(data) else None
    _LOG.info("  WEIGHT: %.2f kg, user_id=%s, ts=%s (consented as %d)",
              weight, user_id, ts_str, current_consent_user)
    weight_data[current_consent_user] = (weight, user_id, ts_str)
    got_weight.set()


def on_body(char, data):
    if len(data) < 4:
        return
    fat = struct.unpack_from("<H", data, 2)[0] * 0.1
    _LOG.info("  BODY: fat=%.1f%%", fat)


def on_ucp(char, data):
    if len(data) >= 3 and data[0] == UCP_RESPONSE:
        names = {1: "Success", 5: "Not Authorized"}
        _LOG.info("  UCP: %s", names.get(data[2], str(data[2])))


def on_notify(char, data):
    pass


async def main():
    global current_consent_user

    _LOG.info("Scanning... (scale should still be awake)")
    device = await BleakScanner.find_device_by_address(SCALE_ADDR, timeout=15.0)
    if not device:
        _LOG.error("Not found! Scale may have gone to sleep.")
        return

    async with BleakClient(device) as client:
        try:
            await client.pair()
        except Exception:
            pass

        await client.start_notify(CHAR_UCP, on_ucp)
        await client.start_notify(CHAR_USER_LIST, on_notify)
        await client.start_notify(CHAR_WEIGHT, on_weight)
        await client.start_notify(CHAR_BODY_COMP, on_body)
        await client.start_notify(CHAR_MEASURE, on_notify)

        now = datetime.datetime.now()
        td = struct.pack("<HBBBBB", now.year, now.month, now.day,
                         now.hour, now.minute, now.second)
        await client.write_gatt_char(CHAR_TIME, td + bytes([now.isoweekday(), 0, 0]),
                                     response=True)

        # Check each user for stored data
        for uid, code in sorted(USER_CONSENTS.items()):
            current_consent_user = uid
            _LOG.info("=== Consent user %d ===", uid)
            cmd = struct.pack("<BBH", UCP_CONSENT, uid, code)
            await client.write_gatt_char(CHAR_UCP, cmd, response=True)
            await asyncio.sleep(0.5)

            got_weight.clear()
            await client.write_gatt_char(CHAR_MEASURE, bytes([0x00]), response=True)
            try:
                await asyncio.wait_for(got_weight.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                _LOG.info("  (no data for user %d)", uid)

        # Summary
        _LOG.info("========= RESULTS =========")
        if not weight_data:
            _LOG.info("No data from any user!")
        for uid, (w, real_uid, ts) in sorted(weight_data.items()):
            _LOG.info("Consented as user %d → got weight=%.2f kg, user_id=%s, ts=%s", uid, w, real_uid, ts)
            if w > 70:
                _LOG.info("  → This is AS (weight > 70)")
            else:
                _LOG.info("  → This is ELA (weight < 70)")

        _LOG.info("===========================")
        if weight_data:
            _LOG.info("If consent was CLEARED: measurement should be under the CORRECT user")
            _LOG.info("If consent was NOT cleared: measurement should be under user 1 (AS)")


if __name__ == "__main__":
    asyncio.run(main())
