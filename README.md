# Beurer/Sanitas BLE Body Composition Scale

Home Assistant custom integration for Beurer and Sanitas Bluetooth Low Energy body composition scales.

## Supported Devices

| Device | Protocol | Status |
|--------|----------|--------|
| **Sanitas SBF73** | 0xFFFF (BF105) | Tested |
| Sanitas SBF72 | 0xFFFF | Should work |
| Beurer BF105/720 | 0xFFFF | Should work |
| Beurer BF950 | 0xFFFF | Should work |
| Beurer BF600/850 | 0xFFF0 | Untested |
| Beurer BF700/710/800 | 0xFFE0 | Untested |
| Sanitas SBF70/75 | 0xFFE0 | Untested |

## Sensors

| Sensor | Unit | Description |
|--------|------|-------------|
| Weight | kg | Body weight |
| BMI | kg/m² | Body Mass Index |
| Body fat | % | Body fat percentage |
| Muscle | % | Muscle percentage |
| Body water | % | Body water percentage |
| Basal metabolism | kJ | Basal metabolic rate |
| Impedance | Ω | Bioelectrical impedance |
| User | — | Scale user (initials or full name) |
| Last measurement | timestamp | When the last measurement was taken |
| Battery | % | Scale battery level |
| Data synced | on/off | Whether measurement data has been received |
| BLE connection | on/off | Enable/disable BLE listening |

Body composition values (fat, muscle, water, impedance) require a **barefoot** measurement on the scale.

Sensor values **persist across reboots** — the dashboard always shows the last measurement.

## Requirements

- Home Assistant 2025.1.0+
- Bluetooth adapter: **ESPHome BLE Proxy** (tested) or direct USB adapter
- ESPHome firmware **2024.3.0+** (required for BLE pairing support)

## Installation (HACS)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/chalimov/ha-beurer-bf600` as **Integration**
4. Install **Beurer/Sanitas BLE Body Composition Scale**
5. Restart Home Assistant

## Setup

### 1. Add the integration

The scale is auto-discovered when it advertises (step on it). Or manually add via:

**Settings → Devices & Services → Add Integration → Beurer/Sanitas BLE**

### 2. Pair with the scale

After adding, click **Configure** on the integration:

1. Check **Re-pair with scale**
2. Step on the scale
3. Click Submit
4. Enter the PIN shown on the scale display and select your user
5. Submit

The integration will bond with the scale via the ESPHome BLE proxy.

### 3. Assign user names (optional)

Click **Configure** again to assign full names to scale users. The scale identifies users by 3-letter initials (e.g. "AS", "ELA"). You can map these to full names that display in the dashboard.

## How it works

1. You step on the scale — it wakes up and starts advertising via BLE
2. The ESPHome BLE proxy detects the advertisement and notifies Home Assistant
3. The integration connects, pairs (if needed), and sends a consent code
4. The scale sends weight and body composition data as BLE indications
5. Data is parsed, stored persistently, and shown in the dashboard
6. The scale goes back to sleep

The integration accepts measurements from **all scale users** and shows which user each measurement belongs to.

## ESPHome BLE Proxy Notes

This integration includes a monkey-patch for an `aioesphomeapi` bug where the ESPHome proxy crashes on the SBF73's non-standard UUID format. This is applied automatically on startup.

The scale requires BLE **bonding** for indications to work. The ESPHome proxy supports this via `client.pair()` (Just Works mode) since ESPHome 2024.3.0.

## Protocol Documentation

See [PROTOCOL.md](PROTOCOL.md) for the complete reverse-engineered BLE protocol specification.

## License

MIT
