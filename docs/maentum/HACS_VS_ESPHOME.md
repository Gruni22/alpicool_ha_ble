# HACS integration or ESPHome?

Both routes speak the same protocol with the box. The difference is **who** holds the Bluetooth connection.

- **HACS integration** (e.g. [Gruni22/alpicool_ha_ble](https://github.com/Gruni22/alpicool_ha_ble)): Home Assistant connects itself, via the built-in Bluetooth adapter or via an ESPHome Bluetooth proxy.
- **ESPHome** (e.g. [neftaly/esphome-alpicool](https://github.com/neftaly/esphome-alpicool)): An ESP32 next to the box connects and reports the values to Home Assistant via the ESPHome API or Wi-Fi.

## Comparison

| Criterion | HACS integration | ESPHome firmware |
|---|---|---|
| Additional hardware | none if the HA machine has Bluetooth and is within range; otherwise an ESP32 as Bluetooth proxy | one ESP32 per box (or several boxes on one ESP32) |
| Range | BLE range to the HA machine or proxy | ESP32 sits right at the box, only Wi-Fi has to reach |
| Setup | install HACS, add the integration, select the box | write YAML, flash the ESP32, adopt it in HA |
| Updates | via HACS with one click | recompile and reflash the ESP32 |
| Logic and debugging | in Python, logs and diagnostics directly in HA | in C++, logs in the ESPHome dashboard |
| Connection stability | depends on the BLE stack of the HA machine; somewhat more latency via proxies | ESP32 holds one connection, typically stable; no data if Wi-Fi fails |
| Camper without a permanently running HA server | only if HA runs in the vehicle | ESP32 can run independently, but needs a receiver (HA or MQTT) |
| Power consumption in the vehicle | none in addition | ESP32 draws power continuously (order of magnitude below 1 W, not measured) |
| Phone app in parallel | no, as long as HA is connected (box allows only one client); Gruni22 keeps the connection open permanently | no, as long as the ESP32 is connected |
| License situation today | Gruni22: MIT (since 2026-09-25) | neftaly: no license file (same situation) |
| Maturity | 52 commits, tests, actively maintained | according to the README tested on a CX40, less activity |

## Recommendation

1. **HACS integration by Gruni22** as the default route. It needs no custom firmware, can be updated via HACS and also works through an existing ESPHome Bluetooth proxy. This is the route we contribute to.
2. **ESPHome only** if the box is outside Home Assistant's Bluetooth range and an ESP32 is running there anyway, or if the connection via the proxy does not become stable. An example is in [`esphome/cooler_box.yaml`](esphome/cooler_box.yaml).

A dedicated ESPHome Bluetooth proxy is a good middle ground: the ESP32 sits at the box, but the logic stays in the HACS integration.

The **IceCubeX** speaks this protocol (status query confirmed on one device on 2026-09-25, see [RESEARCH.md](RESEARCH.md), section 5).
