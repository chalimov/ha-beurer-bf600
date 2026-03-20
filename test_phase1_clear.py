"""Phase 1: Consent as AS, then clear, then disconnect.
After this, step on the scale. Then run test_phase2_check.py."""

import asyncio
import struct
import datetime
import logging
from bleak import BleakClient, BleakScanner

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
_LOG = logging.getLogger("test")

SCALE_ADDR = "CE:31:33:82:85:ED"
CHAR_UCP = "00002a9f-0000-1000-8000-00805f9b34fb"
CHAR_TIME = "00002a2b-0000-1000-8000-00805f9b34fb"
UCP_CONSENT = 0x02
UCP_RESPONSE = 0x20


def on_ucp(char, data):
    if len(data) >= 3 and data[0] == UCP_RESPONSE:
        names = {1: "Success", 5: "Not Authorized"}
        _LOG.info("  UCP result: %s", names.get(data[2], str(data[2])))


async def main():
    _LOG.info("Scanning... (step on scale to wake)")
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

        # Write time
        now = datetime.datetime.now()
        td = struct.pack("<HBBBBB", now.year, now.month, now.day,
                         now.hour, now.minute, now.second)
        await client.write_gatt_char(CHAR_TIME, td + bytes([now.isoweekday(), 0, 0]),
                                     response=True)

        # Consent as AS (sets active user to AS)
        _LOG.info("Consenting as AS (user=1)...")
        cmd = struct.pack("<BBH", UCP_CONSENT, 1, 3691)
        await client.write_gatt_char(CHAR_UCP, cmd, response=True)
        await asyncio.sleep(0.5)

        # Clear: send bogus consent to reset active user
        _LOG.info("Clearing consent (user=0, code=0)...")
        cmd = struct.pack("<BBH", UCP_CONSENT, 0, 0)
        await client.write_gatt_char(CHAR_UCP, cmd, response=True)
        await asyncio.sleep(0.5)

        _LOG.info("Disconnecting. Now step on the scale, then run test_phase2_check.py")


if __name__ == "__main__":
    asyncio.run(main())
