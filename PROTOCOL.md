# Beurer/Sanitas BLE Body Composition Scale Protocol Documentation

Reverse-engineered from the **Sanitas HealthCoach v3.0.1** APK and cross-referenced
with the [openScale](https://github.com/oliexdev/openScale) project's
`BeurerSanitasHandler.kt` and `StandardBeurerSanitasHandler.kt`.

---

## Table of Contents

1. [Supported Devices](#supported-devices)
2. [Protocol Families](#protocol-families)
3. [BLE Services & Characteristics](#ble-services--characteristics)
4. [Family 1: BF600/SBF72/SBF73 (Standard BLE Profile)](#family-1-bf600sbf72sbf73-standard-ble-profile)
5. [Family 2: BF700/SBF70/SBF75 (Proprietary FFE0 Protocol)](#family-2-bf700sbf70sbf75-proprietary-ffe0-protocol)
6. [Measurement Data Formats](#measurement-data-formats)
7. [Connection Sequences](#connection-sequences)
8. [User Management](#user-management)
9. [Advertisement Data](#advertisement-data)

---

## Supported Devices

| Device              | Manufacturer     | Family      | Service  | Notes                    |
|---------------------|------------------|-------------|----------|--------------------------|
| Beurer BF600        | Beurer           | BF600       | 0xFFF0   | Standard BLE + custom    |
| Beurer BF850        | Beurer           | BF600       | 0xFFF0   | Same as BF600            |
| Beurer BF105/720    | Beurer           | BF105       | 0xFFFF   | Standard BLE + custom    |
| Beurer BF950        | Beurer           | BF105       | 0xFFFF   | SBF77/SBF76 variant      |
| Beurer BF500        | Beurer           | BF500       | 0xFFFF   | Simpler, no initials     |
| Beurer BF700        | Beurer           | BF700       | 0xFFE0   | Proprietary protocol     |
| Beurer BF710        | Beurer           | BF700       | 0xFFE0   | Same protocol, diff byte |
| Beurer BF800        | Beurer           | BF700       | 0xFFE0   | Same as BF700            |
| Sanitas SBF70       | Hans Dinslage    | BF700       | 0xFFE0   | Sanitas-branded BF710    |
| **Sanitas SBF73**   | Hans Dinslage    | **BF600**   | **0xFFF0** | **Primary target**     |
| Sanitas SBF72       | Hans Dinslage    | BF600       | 0xFFF0   | Older SBF73 variant      |
| Sanitas SBF75       | Hans Dinslage    | BF700       | 0xFFE0   | SilverCrest SBF75        |
| Runtastic Libra     | Runtastic        | BF700       | 0xFFE0   | Rebranded BF700          |

### Device Name Patterns (BLE Advertisement)

The Sanitas HealthCoach APK identifies devices by these constants:

```
SANITAS_SBF70 = "SBF70"
SANITAS_SBF72 = "SBF72"
SANITAS_SBF73 = "SBF73"
BF700         = "BF700"
```

The openScale project matches:
- Sanitas: `"SANITAS SBF70"`, `"sbf75"`, `"AICDSCALE1"`
- BF700: `"beurer bf700"`, `"beurer bf800"`, `"RT-Libra"`
- BF710: `"beurer bf710"`

---

## Protocol Families

There are two distinct communication protocol families:

### Family 1: Standard BLE Profile (BF600, SBF72, SBF73)

Uses Bluetooth SIG standard services:
- **Weight Scale Service (0x181D)** — weight measurements
- **Body Composition Service (0x181B)** — body fat, water, muscle, bone, impedance
- **User Data Service (0x181E)** — multi-user support via User Control Point
- **Current Time Service (0x1805)** — time synchronization
- **Battery Service (0x180F)** — battery level
- **Device Information Service (0x180A)** — firmware/software version

Plus a custom service **0xFFF0** with proprietary characteristics for:
- User list management
- Taking measurements
- Scale settings
- Activity level
- User initials

### Family 2: Proprietary Protocol (BF700, SBF70, SBF75)

Uses a single custom service **0xFFE0** with a single characteristic **0xFFE1**
for all communication via a framed binary protocol.

---

## BLE Services & Characteristics

### Standard Services (Family 1)

| Service UUID | Name                  | Description                            |
|--------------|-----------------------|----------------------------------------|
| `0x181D`     | Weight Scale          | Weight measurements with indications   |
| `0x181B`     | Body Composition      | Body composition with indications      |
| `0x181E`     | User Data             | Multi-user management via UCP          |
| `0x1805`     | Current Time          | Time sync for timestamps               |
| `0x180F`     | Battery               | Battery level percentage               |
| `0x180A`     | Device Information    | Firmware, software revision            |

### Standard Characteristics

| UUID     | Name                              | Properties        | Description                  |
|----------|-----------------------------------|--------------------|------------------------------|
| `0x2A9D` | Weight Measurement                | Indicate          | Weight data packet           |
| `0x2A9E` | Weight Scale Feature              | Read              | Scale capabilities bitmap    |
| `0x2A9C` | Body Composition Measurement      | Indicate          | Body composition data packet |
| `0x2A9B` | Body Composition Feature          | Read              | BC capabilities bitmap       |
| `0x2A9F` | User Control Point                | Write, Indicate   | User consent & management    |
| `0x2A9A` | User Index                        | Read              | Current user index           |
| `0x2A99` | Database Change Increment         | Read, Write       | Triggers measurement sync    |
| `0x2A85` | Date of Birth                     | Read, Write       | User DOB                     |
| `0x2A8C` | Gender                            | Read, Write       | 0=Male, 1=Female             |
| `0x2A8E` | Height                            | Read, Write       | User height                  |
| `0x2A2B` | Current Time                      | Read, Write       | Scale clock sync             |
| `0x2A19` | Battery Level                     | Read, Notify      | Battery percentage           |
| `0x2A28` | Software Revision String          | Read              | Software version             |
| `0x2A26` | Firmware Revision String          | Read              | Firmware version             |

### Custom Characteristics — BF600/SBF72/SBF73 (Service 0xFFF0)

| UUID     | APK Constant Name                    | Properties     | Description                      |
|----------|--------------------------------------|----------------|----------------------------------|
| `0xFFF2` | CustomBF600_UserList                 | Write, Notify  | User list query/response         |
| `0xFFF3` | CustomBF600_ActivityLevel            | Write          | Set user activity level (1-5)    |
| `0xFFF4` | CustomBF600_TakeMeasurement          | Write          | Request measurement data         |
| `0xFFF5` | CustomBF600_ScaleSetting             | Read, Write    | Scale unit, settings             |
| `0xFFF6` | CustomBF850_UserInitials             | Write          | Set 3-char user initials         |

#### Also used for SBF72 (same UUIDs, different APK constant names):

| APK Constant Name                    | UUID     |
|--------------------------------------|----------|
| CustomSBF72_UserList                 | `0xFFF2` |
| CustomSBF72_ActivityLevel            | `0xFFF3` |
| CustomSBF72_TakeMeasurement          | `0xFFF4` |
| CustomSBF72_ScaleSetting             | `0xFFF5` |
| CustomSBF72_UserInitial              | `0xFFF6` |
| CustomSBF72_ReferWeightBf            | varies   |
| CustomSBF72_Initials                 | varies   |

### Custom Characteristic — BF700/SBF70 (Service 0xFFE0)

| UUID     | Name    | Properties     | Description                           |
|----------|---------|----------------|---------------------------------------|
| `0xFFE1` | Data    | Write, Notify  | All protocol communication            |
| `0xFFE2` | Control | Write          | Additional control (some models)      |

### Client Characteristic Configuration Descriptor

All characteristics with Notify/Indicate require enabling the **CCC descriptor (0x2902)**
before data will be received.

---

## Family 1: BF600/SBF72/SBF73 (Standard BLE Profile)

### Weight Scale Measurement (0x2A9D) — Indications

Sent via indications after subscribing. Format per Bluetooth SIG:

```
Byte 0:       Flags (uint8)
                Bit 0: 0=SI (kg), 1=Imperial (lb)
                Bit 1: Timestamp present
                Bit 2: User ID present
                Bit 3: BMI and Height present
                Bits 4-7: Reserved

Bytes 1-2:    Weight (uint16 LE)
                SI: resolution 0.005 kg (multiply by 0.005)
                Imperial: resolution 0.01 lb (multiply by 0.01)

[Bytes 3-9]:  Timestamp (if flag bit 1 set)
                Bytes 0-1: Year (uint16 LE)
                Byte 2: Month (1-12)
                Byte 3: Day (1-31)
                Byte 4: Hour (0-23)
                Byte 5: Minute (0-59)
                Byte 6: Second (0-59)

[Byte N]:     User ID (uint8, if flag bit 2 set)
                Value 1-8 corresponding to user slot

[Bytes N+1..N+4]: BMI and Height (if flag bit 3 set)
                BMI: uint16 LE, resolution 0.1 kg/m²
                Height: uint16 LE, resolution 0.001 m (SI) or 0.1 inch (Imperial)
```

**Example** (hex): `0E 6C 07 E7 0A 03 0C 1E 00 01 00 E6 B8 06`
- Flags: 0x0E = timestamp + user_id + bmi_height, SI units
- Weight: 0x076C = 1900 → 1900 × 0.005 = 9.5 kg *(example)*
- Timestamp: 2023-10-03 12:30:00
- User ID: 1
- BMI: 0x00E6 = 230 → 23.0 kg/m²
- Height: 0x06B8 = 1720 → 1.720 m

### Body Composition Measurement (0x2A9C) — Indications

```
Bytes 0-1:    Flags (uint16 LE)
                Bit 0:  0=SI, 1=Imperial
                Bit 1:  Timestamp present
                Bit 2:  User ID present
                Bit 3:  Basal Metabolism present
                Bit 4:  Muscle Percentage present
                Bit 5:  Muscle Mass present
                Bit 6:  Fat Free Mass present
                Bit 7:  Soft Lean Mass present
                Bit 8:  Body Water Mass present
                Bit 9:  Impedance present
                Bit 10: Weight present
                Bit 11: Height present
                Bit 12: Multiple Packet Measurement

Bytes 2-3:    Body Fat Percentage (uint16 LE)
                Resolution: 0.1% (divide by 10)

[7 bytes]:    Timestamp (same format as Weight Measurement)

[1 byte]:     User ID (uint8)

[2 bytes]:    Basal Metabolism (uint16 LE, in kJ)

[2 bytes]:    Muscle Percentage (uint16 LE, resolution 0.1%)

[2 bytes]:    Muscle Mass (uint16 LE)
                SI: resolution 0.005 kg
                Imperial: resolution 0.01 lb

[2 bytes]:    Fat Free Mass (uint16 LE, same resolution as weight)

[2 bytes]:    Soft Lean Mass (uint16 LE, same resolution as weight)

[2 bytes]:    Body Water Mass (uint16 LE, same resolution as weight)

[2 bytes]:    Impedance (uint16 LE, in Ohms)

[2 bytes]:    Weight (uint16 LE, same resolution as Weight Measurement)

[2 bytes]:    Height (uint16 LE)
                SI: resolution 0.001 m
                Imperial: resolution 0.1 inch
```

### User Control Point (0x2A9F)

Used for multi-user consent on SBF72/SBF73. Write a command, receive a response indication.

#### Commands (Write)

| Opcode | Name               | Parameters                        |
|--------|--------------------|-----------------------------------|
| `0x01` | Register New User  | `consent_code` (uint16 LE)        |
| `0x02` | Consent            | `user_index` (uint8), `consent_code` (uint16 LE) |
| `0x03` | Delete User Data   | —                                 |

#### Response (Indicate)

```
Byte 0: 0x20 (Response opcode)
Byte 1: Request opcode (echo)
Byte 2: Response value
          0x01 = Success
          0x02 = Op Code not supported
          0x03 = Invalid parameter
          0x04 = Operation failed
          0x05 = User not authorized
[Byte 3]: Parameter (e.g., new user_index for Register)
```

**Consent flow for SBF73:**
1. Enable indications on UCP (write 0x0200 to CCC descriptor 0x2902)
2. Write `[0x02, user_index, consent_code_lo, consent_code_hi]`
3. Receive indication: `[0x20, 0x02, 0x01]` = success

### Database Change Increment (0x2A99)

Reading and incrementing this value triggers the scale to send stored measurements.

```
Read:  uint32 LE — current value
Write: uint32 LE — new value (current + 1)
```

After writing an incremented value, the scale will send Weight Measurement and
Body Composition Measurement indications for any stored data.

### Current Time (0x2A2B)

Written to synchronize the scale's clock:

```
Bytes 0-1: Year (uint16 LE)
Byte 2:    Month (1-12)
Byte 3:    Day (1-31)
Byte 4:    Hour (0-23)
Byte 5:    Minute (0-59)
Byte 6:    Second (0-59)
Byte 7:    Day of Week (1=Monday, 7=Sunday, 0=Unknown)
Byte 8:    Fractions256 (1/256th second, usually 0)
Byte 9:    Adjust Reason (bitmask, usually 0)
```

### Custom User List (0xFFF2)

Write `0x00` to request the user list. Scale responds with notifications:

```
Response format:
Byte 0: Status
          0x02 = No user on scale
          0x01 = List complete (last entry)
          other = User record follows

User record (if status != 0x01 and != 0x02):
Byte 1:    User index on scale
Bytes 2-4: Initials (3 ASCII chars, right-padded with 0x00)
Byte 5:    Padding
Bytes 6-7: Birth year (uint16 BE)
Byte 8:    Birth month (1-12)
Byte 9:    Birth day (1-31)
Byte 10:   Height (cm)
Byte 11:   Gender (0=Male, 1=Female)
Byte 12:   Activity Level (1-5)
```

### Custom Take Measurement (0xFFF4)

Write `0x00` to request the scale to send stored measurements.

### Custom Scale Setting (0xFFF5)

Read/write scale configuration:

```
Byte 0: Unit setting
          0x00 = kg
          0x01 = lb
          0x02 = st
```

### Custom Activity Level (0xFFF3)

Write a single byte (1-5) to set the user's activity level:

```
1 = Sedentary (none/light exercise)
2 = Low active
3 = Active (moderate exercise 3-5 days/week)
4 = Very active (hard exercise 6-7 days/week)
5 = Extra active (very hard exercise / physical job)
```

### Custom User Initials (0xFFF6)

Write 3 ASCII uppercase characters as user initials:

```
Bytes 0-2: Initials (uppercase A-Z, right-padded with spaces)
```

---

## Family 2: BF700/SBF70/SBF75 (Proprietary FFE0 Protocol)

All communication goes through a single characteristic **0xFFE1** on service **0xFFE0**.

### Frame Format

```
Byte 0: Start byte
          High nibble: Device identifier
            0xF0 = BF700/BF800/RT-Libra
            0xE0 = BF710/SBF70/SBF75/Crane
          Low nibble: Command type (varies)

Bytes 1+: Payload (command-specific)
```

### Alternative Start Bytes

Certain commands use a different low nibble:

| Operation    | Low nibble | Combined byte (Sanitas) |
|-------------|------------|-------------------------|
| Normal CMD   | varies     | 0xE? / 0xF?            |
| Init         | 0x06       | 0xE6 / 0xF6            |
| Set Time     | 0x09       | 0xE9 / 0xF9            |
| Disconnect   | 0x0A       | 0xEA / 0xFA            |

### State Machine

The connection follows an 8-step state machine:

```
1. INIT           → Send init command, wait for ACK
2. SET_TIME        → Synchronize scale clock
3. SCALE_STATUS    → Query scale status, set units
4. USER_LIST       → Retrieve list of users on scale
5. SAVED_MEASUREMENTS → Download stored measurements for matched users
6. USER_ENSURE     → Create remote user if needed
7. USER_DETAILS    → Read/write user profile data
8. FINALIZATION    → Request live measurement or disconnect
```

### Init Command

```
Write to 0xFFE1:
  [start_byte | 0x06, 0x01]

Expected response (notification):
  [start_byte | 0x06, ...]   — ACK
```

### Set Time Command

```
Write to 0xFFE1:
  [start_byte | 0x09, year_hi, year_lo, month, day, hour, min, sec]

All multi-byte values are BIG-ENDIAN.
```

### Measurement Data Frame

When stored measurements are transmitted via notification:

```
Notification payload (after start byte), 16 bytes:
Offset  Size    Type       Description
0       4       uint32 BE  Unix timestamp (seconds since epoch)
4       2       uint16 BE  Weight raw (× 50 / 1000 = kg)
6       2       uint16 BE  Impedance (raw Ω)
8       2       uint16 BE  Body fat (÷ 10 = %)
10      2       uint16 BE  Body water (÷ 10 = %)
12      2       uint16 BE  Muscle (÷ 10 = %)
14      2       uint16 BE  Bone mass raw (× 50 / 1000 = kg)
```

### Value Conversion Table

| Field       | Raw formula            | Unit | Resolution |
|-------------|------------------------|------|------------|
| Weight      | `raw × 50 / 1000`     | kg   | 50g        |
| Body fat    | `raw / 10`             | %    | 0.1%       |
| Body water  | `raw / 10`             | %    | 0.1%       |
| Muscle      | `raw / 10`             | %    | 0.1%       |
| Bone mass   | `raw × 50 / 1000`     | kg   | 50g        |
| Impedance   | `raw`                  | Ω    | 1 Ω        |
| Timestamp   | `raw` (Unix seconds)   | s    | 1s         |

### User List Response

```
Notification payload:
Byte 0: Status
          0x02 = No user on scale
          0x01 = List complete
          other = User data follows

User record:
Byte 1:    User index
Bytes 2-4: Initials (3 ASCII chars)
Byte 5:    Padding (0x00)
Bytes 6-7: Birth year (uint16 BE)
Byte 8:    Birth month
Byte 9:    Birth day
Byte 10:   Height (cm)
Byte 11:   Gender (0=Male, 1=Female)
Byte 12:   Activity level (1-5)
```

---

## Connection Sequences

### SBF73 Connection Sequence (from APK reverse engineering)

```
1. Scan for BLE device with name containing "SBF73" or "SANITAS SBF73"
2. Connect via GATT
3. Discover services
4. Enable indications on:
   - Weight Scale Measurement (0x2A9D)
   - Body Composition Measurement (0x2A9C)
   - User Control Point (0x2A9F)
5. Send UCP Consent: [0x02, user_index, consent_lo, consent_hi]
6. Wait for UCP response indication: [0x20, 0x02, 0x01] (success)
7. Write Current Time to 0x2A2B
8. Read Database Change Increment from 0x2A99
9. Write incremented value to 0x2A99 → triggers measurement indications
10. Receive Weight Measurement indications (0x2A9D)
11. Receive Body Composition Measurement indications (0x2A9C)
12. Read Battery Level from 0x2A19
13. Disconnect
```

### SBF73 Custom Service Flow (0xFFF0)

```
1. After standard service discovery...
2. Enable notifications on Custom User List (0xFFF2)
3. Write 0x00 to Custom User List → receive user list notifications
4. Write activity level to 0xFFF3 (single byte 1-5)
5. Write initials to 0xFFF6 (3 ASCII bytes)
6. Write 0x00 to Custom Take Measurement (0xFFF4) → triggers measurement
```

### BF700/SBF70 Connection Sequence

```
1. Scan for BLE device with name matching BF700/SBF70 patterns
2. Connect via GATT
3. Discover services → find 0xFFE0/0xFFE1
4. Enable notifications on 0xFFE1
5. Send INIT: [0xE6, 0x01] (Sanitas) or [0xF6, 0x01] (BF700)
6. Wait for INIT ACK notification
7. Send SET_TIME: [0xE9, year_hi, year_lo, month, day, hour, min, sec]
8. Send SCALE_STATUS query
9. Receive USER_LIST notifications
10. Match users by initials + birth year
11. Request SAVED_MEASUREMENTS for matched user
12. Receive measurement data notifications
13. Send DISCONNECT: [0xEA, ...]
```

---

## User Management

### SBF73 User Model (from APK)

The SBF73 supports up to **8 user slots** on the device.

Each user has:
- **UUID**: 64-bit unique identifier (assigned by the app, synced to cloud)
- **Initials**: 3-character identifier shown on scale display
- **Date of birth**: Year, month, day
- **Height**: in cm
- **Gender**: Male/Female
- **Activity level**: 1-5

From the APK strings, the user management flow:
1. `getUserListBytesData` — Query all users on scale
2. `getCreateUserBytesData(uuid, initials, dob, height, gender, activity)` — Create user
3. `getTakeUserMeasurementBytesData(uuid)` — Take measurement for specific user
4. `getUserMeasurementsBytesData(uuid)` — Get stored measurements
5. `getUpdateUserBytesDate(uuid, ...)` — Update user profile
6. `getDeleteUserBytesData(uuid)` — Remove user from scale
7. `getCheckUserExistsBytesData(uuid)` — Verify user presence
8. `getSetUserWeightBytesData(uuid, weight, bodyFat, timestamp)` — Set reference values
9. `getAssignMeasurementToUserBytesData(uuid, ...)` — Assign unknown measurement

### Consent Codes

The SBF73 uses the standard BLE User Data Service consent mechanism:
- Default consent code: `0x0000`
- The app generates and stores a consent code per user
- Consent must be sent each connection before accessing user data

---

## Advertisement Data

### SBF73 Advertisement

The SBF73 advertises with:
- **Local Name**: `"SANITAS SBF73"` or `"SBF73"`
- **Service UUIDs**: `0x181D` (Weight Scale), `0x181B` (Body Composition)
- **Manufacturer Specific Data**: Contains pairing bit and device state

From the APK's `getAdvertisementByte(char, char)` method and
`AdvertisementRecord` class, the advertisement data includes:
- Device connection state
- Whether the device is in pairing mode
- Number of stored measurements

### BF700/SBF70 Advertisement

Advertises with:
- **Local Name**: `"Beurer BF700"`, `"SBF70"`, etc.
- **Service UUID**: `0xFFE0`

The openScale project configures advertisement parameters via the protocol:
- `getSlowAdvertisementBytesData(enabled, interval)` — control advert rate
- `getTxPowerBytesData()` — query TX power

---

## Data Types Reference

### ScaleUtilities Fields (from APK)

The `ScaleUtilities` class in the APK stores measurement arrays:

```java
private double[] rawWeightArray;       // Weight in kg/lb
private float[]  rawBodyFatArray;      // Body fat %
private float[]  rawWaterArray;        // Body water %
private float[]  rawMuscleArray;       // Muscle mass %
private float[]  rawBoneMassArray;     // Bone mass in kg/lb
private float[]  rawBmiArray;          // BMI
private int[]    rawBmrArray;          // Basal metabolic rate
private int[]    rawImpedanceArray;    // Bioelectrical impedance (Ω)
private int[]    rawTimeStampArray;    // Unix timestamp (seconds)
private long[]   rawListOfUuids;       // User UUIDs
private int[]    rawMeasurementIdArray; // Measurement IDs
private String[] rawUserListInitials;  // User initials
```

### BleUtilities Conversion Methods (from APK)

```java
convertByteToInt(byte) → int          // Unsigned byte to int
convertBytesToInt(byte[]) → int       // Big-endian bytes to int
convertBytesToLong(byte[]) → long     // Big-endian bytes to long
convertIntTo2bytesHexaFormat(int) → byte[2]  // Int to 2 big-endian bytes
convertIntToBytes(int) → byte[4]      // Int to 4 big-endian bytes
convertLongToBytes(long) → byte[8]    // Long to 8 big-endian bytes
getTimeStampInMilliSeconds(int) → long // Seconds × 1000
getTimeStampInSeconds(long) → int     // Millis / 1000
```

---

## Sources

- **Sanitas HealthCoach APK v3.0.1** (`com.beurer.connect.healthmanager`)
  - Decompiled using androguard; classes from `com.ilink.bleapi.*` and
    `com.impirion.deviceClass.scale.ble.*`
- **openScale** (https://github.com/oliexdev/openScale)
  - `BeurerSanitasHandler.kt` — BF700/SBF70 proprietary protocol
  - `StandardBeurerSanitasHandler.kt` — BF600/SBF73 standard profile
- **Bluetooth SIG specifications**
  - Weight Scale Service (WSS) 1.0
  - Body Composition Service (BCS) 1.0
  - User Data Service (UDS) 1.0
