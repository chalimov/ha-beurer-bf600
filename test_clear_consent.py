"""Test: verify consent clearing by using a user that HAS stored data."""

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

got_weight = asyncio.Event()


def on_weight(char, data):
    if len(data) < 3:
        return
    raw = struct.unpack_from("<H", data, 1)[0]
    weight = raw * 0.005
    offset = 3
    flags = data[0]
    if flags & 0x02:
        offset += 7
    user_id = data[offset] if flags & 0x04 and offset < len(data) else None
    _LOG.info("  >>> WEIGHT: %.2f kg, user_id=%s", weight, user_id)
    got_weight.set()


def on_body(char, data):
    if len(data) < 4:
        return
    fat = struct.unpack_from("<H", data, 2)[0] * 0.1
    _LOG.info("  >>> BODY: fat=%.1f%%", fat)


def on_notify(char, data):
    _LOG.info("  notify %s: %s", str(char.uuid)[:8], data.hex())


def on_ucp(char, data):
    if len(data) >= 3 and data[0] == UCP_RESPONSE:
        names = {1: "Success", 2: "Not Supported", 3: "Invalid Param",
                 4: "Op Failed", 5: "Not Authorized"}
        _LOG.info("  UCP: result=%s", names.get(data[2], str(data[2])))


async def consent(client, uid, code, label):
    cmd = struct.pack("<BBH", UCP_CONSENT, uid, code)
    _LOG.info("[%s] consent user=%d code=%d", label, uid, code)
    await client.write_gatt_char(CHAR_UCP, cmd, response=True)
    await asyncio.sleep(0.5)


async def trigger(client, timeout=5.0):
    got_weight.clear()
    await client.write_gatt_char(CHAR_MEASURE, bytes([0x00]), response=True)
    try:
        await asyncio.wait_for(got_weight.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        _LOG.info("  (no data in %.0fs)", timeout)
        return False


async def main():
    _LOG.info("Scanning... (step on scale)")
    device = await BleakScanner.find_device_by_address(SCALE_ADDR, timeout=15.0)
    if not device:
        _LOG.error("Not found!")
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

        # Write time
        now = datetime.datetime.now()
        td = struct.pack("<HBBBBB", now.year, now.month, now.day,
                         now.hour, now.minute, now.second)
        await client.write_gatt_char(CHAR_TIME, td + bytes([now.isoweekday(), 0, 0]),
                                     response=True)

        # User list
        await client.write_gatt_char(CHAR_USER_LIST, bytes([0x00]), response=True)
        await asyncio.sleep(1.0)

        # 1. Consent ELA (has stored data) → should get data
        _LOG.info("=== 1. Consent ELA → expect data ===")
        await consent(client, 2, USER_CONSENTS[2], "ELA")
        got = await trigger(client)
        _LOG.info("  Result: %s", "GOT DATA" if got else "NO DATA")

        # 2. Clear: send bad consent (user=0)
        _LOG.info("=== 2. Clear: consent user=0 code=0 ===")
        await consent(client, 0, 0, "CLEAR")

        # 3. Consent ELA again → should still get data (clear doesn't delete)
        _LOG.info("=== 3. Re-consent ELA → expect data ===")
        await consent(client, 2, USER_CONSENTS[2], "ELA again")
        got = await trigger(client)
        _LOG.info("  Result: %s", "GOT DATA" if got else "NO DATA")

        # 4. Clear again
        _LOG.info("=== 4. Clear: consent user=0 code=0 ===")
        await consent(client, 0, 0, "CLEAR")

        # 5. Trigger WITHOUT consenting → if cleared, no data
        _LOG.info("=== 5. Trigger without consent → expect NO data if cleared ===")
        got = await trigger(client, timeout=3.0)
        _LOG.info("  Result: %s", "STILL HAS CONSENT (data came)" if got else "CLEARED! (no data)")

        _LOG.info("=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
