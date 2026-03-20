# Beurer/Sanitas SBF73 BLE Protocol Documentation

Reverse-engineered from the **Sanitas HealthCoach v3.0.1** APK, the
[openScale](https://github.com/oliexdev/openScale) project, and **live Android
logcat captures** of the official app communicating with a Sanitas SBF73 scale.

---

## Device Information

| Property | Value |
|----------|-------|
| Device name | `SBF73` (advertises as `"SBF73"`) |
| MAC address | `CE:31:33:82:85:ED` (example) |
| Manufacturer | Hans Dinslage GmbH (Beurer/Sanitas) |
| Company ID | `0x0613` |
| BLE Appearance | `0x0C80` (Generic Weight Scale) |
| Hardware revision | 1.0 |
| Firmware revision | 7.8 |
| Software revision | 5.9 |
| Max users | 8 |
| Protocol family | **BF105/BF950 variant** (custom service 0xFFFF) |

---

## BLE Services & Characteristics

### Discovered GATT Services

| Service UUID | Name | Characteristics |
|-------------|------|-----------------|
| `0x1800` | Generic Access | Device Name, Appearance, etc. |
| `0x1801` | Generic Attribute | Service Changed (indicate) |
| `0x180A` | Device Information | Model, FW, HW, SW revisions |
| `0x180F` | Battery | Battery Level (read) |
| `0x1805` | Current Time | Current Time (read/write/notify) |
| `0x181C` | User Data | DOB, Gender, Height, DB Change, User Index, UCP |
| `0x181D` | Weight Scale | Weight Feature (read), Weight Measurement (indicate) |
| `0x181B` | Body Composition | BC Feature (read), BC Measurement (indicate) |
| **`0xFFFF`** | **Custom (BF105)** | **User List, Initials, Activity, Measure, Settings** |
| `0xFF00` | Custom (OTA?) | Single write characteristic |

### Custom Service 0xFFFF — Characteristic Map

| UUID | Name | Properties | Description |
|------|------|------------|-------------|
| `0x0000` | Scale Setting | read, write | Unit config (kg/lb/st) |
| `0x0001` | User List | read, write, **notify** | Query/receive user list |
| `0x0002` | User Initials | read, write | 3-char ASCII initials |
| `0x0004` | Activity Level | read, write | Activity 1-5 |
| `0x0005` | Target Weight | read, write | Target weight (BF105 only) |
| `0x0006` | Measurement Request | read, write, **notify** | Trigger measurement |
| `0x000B` | Reference Weight/BF | read | Reference weight & body fat |

**IMPORTANT**: The SBF73 uses service `0xFFFF` (BF105 variant), NOT `0xFFF0` (BF600)
or `0xFFE0` (BF700). This was confirmed via live GATT discovery.

---

## Connection Sequence (Verified via Logcat)

Captured from the Sanitas HealthCoach app (PID 15885) on 2026-03-19.

### Step 1: Subscribe to Characteristics (in order)

```
1. 0x2A9D  Weight Scale Measurement    (indicate)
2. 0x2A99  Database Change Increment   (notify)
3. 0x2A9C  Body Composition Measurement (indicate)
4. 0x2A9F  User Control Point          (indicate)
5. 0x0001  Custom User List            (notify)
6. 0x0006  Custom Measurement Request  (notify)
7. 0x2A2B  Current Time                (notify)
```

Each subscription writes `0x0002` (indicate) or `0x0001` (notify) to the CCC
descriptor (0x2902) of the characteristic.

### Step 2: Write Current Time

```
Write to 0x2A2B: EA 07 03 13 11 01 29 00 00 00
                  └─year─┘ mo dy hr mn sc dow frac adj
```

Format: `<H year` `B month` `B day` `B hour` `B minute` `B second` `B day_of_week` `B fractions256` `B adjust_reason`

Day of week: 1=Monday..7=Sunday (per BLE spec).

### Step 3: Query User List

```
Write to 0x0001: 00
```

Scale responds with notifications on 0x0001:

**User record** (status byte 0x00):
```
Byte 0:    0x00 (user record follows)
Byte 1:    User index (1-8)
Bytes 2-4: Initials (3 ASCII chars, right-padded with spaces)
Bytes 5-6: Birth year (uint16 BIG-ENDIAN)
Byte 7:    Birth month
Byte 8:    Birth day
Byte 9:    Height (cm)
Byte 10:   Gender (0=Male, 1=Female)
Byte 11:   Activity level (1-5)
```

**End of list** (status byte 0x01):
```
Byte 0: 0x01
```

**Example** (from live capture):
```
User 1: 00 01 41 53 20 B9 07 06 12 B4 00 05
         │  │  └─AS ─┘ └1977┘ Jun 18 180 M  5
User 2: 00 02 45 4C 41 B9 07 01 1A A4 01 04
         │  │  └─ELA┘  └1977┘ Jan 26 164 F  4
End:    01
```

### Step 4: UCP Consent

```
Write to 0x2A9F: 02 01 6B 0E
                  │  │  └──consent code (uint16 LE)──┘
                  │  └─ user_index
                  └── opcode 0x02 = Consent
```

Scale responds with indication on 0x2A9F:
```
Response: 20 02 01
          │  │  └─ result: 0x01 = Success
          │  └── request opcode echo
          └── response opcode 0x20
```

**Consent code `0x0E6B` (3691)** is user-specific, generated during initial
pairing with the Sanitas app. The code is tied to the BLE bond — any bonded
device can use the same code for the same user.

Error codes:
- `0x01` = Success
- `0x05` = User Not Authorized (wrong consent code or not bonded)

### Step 5: Read Scale Info

```
Read 0x2A99: 01 00 00 00          → Database Change Increment = 1
Read 0x0000: 00 00 01 00 1E 00 FF FF → Scale Settings (unit=kg, etc.)
Read 0x000B: C0 3D 92 00          → Reference Weight/BF
Read 0x2A27: 31 2E 30             → Hardware: "1.0"
Read 0x2A19: 64                   → Battery: 100%
Read 0x2A26: 37 2E 38             → Firmware: "7.8"
Read 0x2A28: 35 2E 39             → Software: "5.9"
```

### Step 6: Receive Measurements (Indications)

After consent, the scale sends stored measurements as indications. ~4 seconds
after consent acceptance:

#### Weight Scale Measurement (0x2A9D)

```
Data: 0E 92 3D EA 07 03 13 11 01 2F 01 F3 00 08 07
```

```
Byte 0:      Flags = 0x0E (binary: 00001110)
               Bit 0: 0 = SI (kg)
               Bit 1: 1 = Timestamp present
               Bit 2: 1 = User ID present
               Bit 3: 1 = BMI and Height present

Bytes 1-2:   Weight = 0x3D92 = 15762 → 15762 × 0.005 = 78.81 kg
Bytes 3-9:   Timestamp: 2026-03-19 17:01:47
Byte 10:     User ID: 1
Bytes 11-12: BMI = 0x00F3 = 243 → 24.3 kg/m²
Bytes 13-14: Height = 0x0708 = 1800 → 1.800 m
```

#### Body Composition Measurement (0x2A9C)

```
Data: 98 03 00 00 71 1B 00 00 92 3D 00 00 00 00
```

```
Bytes 0-1:   Flags = 0x0398 (binary: 0000001110011000)
               Bit 3:  1 = Basal Metabolism present
               Bit 4:  1 = Muscle Percentage present
               Bit 7:  1 = Soft Lean Mass present
               Bit 8:  1 = Body Water Mass present
               Bit 9:  1 = Impedance present

Bytes 2-3:   Body Fat % = 0x0000 = 0 → 0.0% (shoes-on measurement)
Bytes 4-5:   Basal Metabolism = 0x1B71 = 7025 kJ
Bytes 6-7:   Muscle % = 0x0000 = 0 → 0.0%
Bytes 8-9:   Soft Lean Mass (not used)
Bytes 10-11: Body Water Mass = 0x3D92 → convert to % using weight
Bytes 12-13: Impedance = 0x0000 = 0 Ω (shoes-on: no bioimpedance)
```

**With full body composition** (barefoot measurement):
```
Body fat:    15.0%
Muscle:      43.5%
Body water:  46.7%
Impedance:   4840 Ω
BMR:         6963 kJ
```

---

## BLE Bonding (ESPHome Proxy)

### Requirement

The scale requires **BLE bonding** for indications to work. Without bonding,
`start_notify` succeeds but no data is ever received.

### ESPHome Proxy Support

- `bleak-esphome` supports `client.pair()` since ESPHome **2024.3.0**
- Pairing uses **Just Works** mode (no PIN required at BLE level)
- The scale shows `P-XX` on its display during pairing (user slot assignment)
- Bond is persistent — subsequent connections work without re-pairing

### aioesphomeapi UUID Bug

The ESPHome BLE proxy crashes with `IndexError` in `_convert_bluetooth_uuid`
when the SBF73 sends GATT services with empty UUID protobuf fields. This is
worked around by monkey-patching `aioesphomeapi.model._convert_bluetooth_uuid`
in the integration's `__init__.py`.

---

## Advertisement Data

```
Flags:              0x06
Appearance:         0x0C80 (Weight Scale)
LE Device Address:  00:ED:85:82:33:31:CE
Service UUIDs:      0x181D (Weight Scale)
Complete Name:      "SBF73"
TX Power:           0 dBm
Manufacturer Data:  Company=0x0613, Data=0100
Service Data:       UUID=0x181D, Data=0102
  Byte 0: User count on scale
  Byte 1: Flags (has stored measurements, pairing bit, etc.)
```

---

## Multi-User Support

The scale supports up to **8 user slots**. Each user has:
- **Index** (1-8)
- **Initials** (3 ASCII characters)
- **Date of birth** (year, month, day)
- **Height** (cm)
- **Gender** (0=Male, 1=Female)
- **Activity level** (1-5)

The UCP consent code is per-user and per-bond. The integration stores
consent codes for all users (`CONF_USER_CONSENTS`) and retrieves
measurements from each user per session, keeping the freshest one.

### Consent Persistence & User Detection

**Critical discovery**: UCP consent persists in the scale's firmware across
BLE disconnects and power cycles. The last-consented user becomes the
"active user" for ALL future measurements, overriding the scale's own
weight-based user detection. This means:

- If the integration consents as user 1 (AS), the scale assigns all
  subsequent measurements to AS — even if a different person weighs.
- Body composition (fat %, muscle %, water %) is calculated using the
  consented user's profile (height, age, gender), so wrong consent =
  wrong body comp values.

**Fix**: Send `consent(user=0, code=0)` at the end of each BLE session.
The scale rejects this with "Not Authorized" (result=0x05), but as a side
effect, the active user is cleared. On the next weigh-in, the scale falls
back to its own weight-based user detection and correctly identifies who
is standing on it.

---

## Integration Connection Sequence (HA / ESPHome Proxy)

The Home Assistant integration follows this sequence:

1. **BLE advertisement callback** triggers connection when scale wakes
2. **`establish_connection()`** via `bleak-retry-connector` with `dangerous_use_bleak_cache=True`
3. **`client.pair()`** — establishes BLE bond (Just Works, required for indications)
4. **Subscribe** to: Weight (0x2A9D), Body Comp (0x2A9C), UCP (0x2A9F), User List (0x0001), Measure (0x0006)
5. **Write current time** to 0x2A2B (local timezone)
6. **Write `0x00` to User List** (0x0001) → receive all user records (initials, height, etc.)
7. **For each user with a consent code**:
   - **UCP Consent** — `[0x02, user_index, consent_lo, consent_hi]` to 0x2A9F
   - **Write `0x00` to Measure** (0x0006) → trigger stored measurement delivery
   - **Wait up to 5s** for Weight + Body Composition indications
8. **Pick freshest measurement** (by timestamp) across all users
9. **Clear consent** — `[0x02, 0x00, 0x00, 0x00]` to 0x2A9F (resets active user)
10. **Read battery** from 0x2A19
11. **Disconnect**

Data is persisted to HA Store (`.storage/beurer_bf600_<address>`) so sensor values survive reboots.

### Monkey-patch for aioesphomeapi

```python
# In __init__.py — patches _convert_bluetooth_uuid to handle empty UUID fields
import aioesphomeapi.model as _esphome_model
_original = _esphome_model._convert_bluetooth_uuid
def _safe(value):
    try: return _original(value)
    except (IndexError, AttributeError, TypeError):
        uuid_list = getattr(value, "uuid", None) or []
        if len(uuid_list) == 2:
            from uuid import UUID
            return str(UUID(int=(uuid_list[0] << 64) | uuid_list[1]))
        return "00000000-0000-1000-8000-00805f9b34fb"
_esphome_model._convert_bluetooth_uuid = _safe
```

---

## Related Devices

These scales share the same or similar protocol families:

| Device | Custom Service | Protocol |
|--------|---------------|----------|
| **Sanitas SBF73** | 0xFFFF | BF105 variant (this doc) |
| Sanitas SBF72 | 0xFFFF | Same as SBF73 |
| Beurer BF105/720 | 0xFFFF | Same custom service |
| Beurer BF950 | 0xFFFF | Same custom service |
| Beurer BF600/850 | 0xFFF0 | Different custom chars |
| Beurer BF700/710/800 | 0xFFE0 | Proprietary framed protocol |
| Sanitas SBF70/75 | 0xFFE0 | Same as BF700 |

---

## Sources

- **Sanitas HealthCoach APK v3.0.1** — decompiled via androguard
- **Android logcat capture** — live GATT trace from app PID 15885, 2026-03-19
- **openScale** — BeurerSanitasHandler.kt, StandardBeurerSanitasHandler.kt
- **Bluetooth SIG specifications** — WSS 1.0, BCS 1.0, UDS 1.0
