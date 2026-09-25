# MAENTUM cooler boxes with this integration

Guide, research and tools for connecting MAENTUM cooler boxes (made by Plug-in Festivals GmbH) to Home Assistant via Bluetooth Low Energy.

> **As of 2026-09-25, please read:** For older Plug In Festivals boxes there are user reports that they speak the open **Alpicool protocol**. For the **IceCube X 50** this has been confirmed on one device since 2026-09-25: it offers service 0x1234 and answers the status query in the Alpicool format (see [RESEARCH.md](RESEARCH.md), section 5). Setting the target temperature (command 0x05) works too. The remaining settings (command 0x02) have not yet been tested on the box. Check other models with step 1 first. Not affiliated with or supported by MAENTUM.

## Contents

| Path | Contents |
|---|---|
| [`tools/maentum_probe.py`](../../tools/maentum_probe.py) | Probe script: finds the box, lists its GATT services, reads and decodes the status |
| [`tools/alpicool_protocol.py`](../../tools/alpicool_protocol.py) | Dependency-free protocol codec, tested with real captures |
| [`RESEARCH.md`](RESEARCH.md) | all sources, each with its reliability (confirmed / reported / unknown) |
| [`PROTOCOL.md`](PROTOCOL.md) | the protocol, with a source for each detail |
| [`HACS_VS_ESPHOME.md`](HACS_VS_ESPHOME.md) | pros and cons of the HACS integration vs. ESPHome |
| [`esphome/cooler_box.yaml`](esphome/cooler_box.yaml) | example configuration for the ESPHome route |

## Step 1: Does my box speak the Alpicool protocol?

**Option A, without a computer (1 minute):**

1. Close the MAENTUM app on your phone (the box allows only **one** connection).
2. Install the app **nRF Connect for Mobile** (Nordic Semiconductor) and scan.
3. Find the box in the list (stand right next to it and filter by signal strength; or briefly switch the box off and see which device disappears), note its name, tap **Connect**. Android also shows the MAC address, the iPhone does not.
4. If a service **`0x1234`** with the characteristics **`0x1235`** and **`0x1236`** appears, the box speaks the protocol. Continue with step 2.

**Option B, with the probe script** (Linux, macOS or Windows with Bluetooth, Python ≥ 3.11):

```bash
git clone https://github.com/Gruni22/alpicool_ha_ble.git && cd alpicool_ha_ble
python3 -m venv .venv && . .venv/bin/activate
pip install bleak

python tools/maentum_probe.py scan               # boxes nearby, known ones marked "fridge?"
python tools/maentum_probe.py scan --all         # all BLE devices, in case the name is unknown
python tools/maentum_probe.py services AA:BB:CC:DD:EE:FF   # list GATT services (read-only)
python tools/maentum_probe.py query AA:BB:CC:DD:EE:FF      # read and decode the status (read-only)
python tools/maentum_probe.py -v query AA:BB:CC:DD:EE:FF --loop 10   # with raw data, every 10 s
```

`query` prints the status as JSON (target/current, voltage, mode …). If the values match the box's display, the box is compatible. `set-target --temp 4` changes the target temperature as a test; this is the only writing command and must be invoked explicitly.

**If `0x1234` is missing:** The box uses a different protocol. In that case please post the output of `services` (or a screenshot from nRF Connect) in an issue. Further analysis requires a Bluetooth capture of the MAENTUM app (Android: Developer options → "Enable Bluetooth HCI snoop log").

## Step 2: Install the integration

Prerequisite: Home Assistant with Bluetooth, either an adapter on the HA machine within range of the box or an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy/) near the box.

1. Open [HACS](https://hacs.xyz/) → menu at the top right → **Custom repositories**.
2. Add the repository `https://github.com/Gruni22/alpicool_ha_ble`, type **Integration**.
3. Search for "Alpicool BLE", install it, restart Home Assistant.
4. **Settings → Devices & services → Add integration → "Alpicool BLE"**.
5. Enter the box's MAC address from step 1 and give it a name. If the box shows "APP" on its display, briefly press the button on the box.

You then get a climate entity (on/off, target temperature, Max/Eco), sensors for battery and voltage, a button lock, battery protection, as well as hysteresis and start delay.

## Known limitations

- While Home Assistant is connected, the phone app cannot connect, and vice versa (a property of the box, BrassMonkeyFridgeMonitor).
- The Pekaway forum reports occasional connection drops. A Bluetooth proxy near the box usually helps.

## Troubleshooting

| Symptom | Cause / remedy |
|---|---|
| Box is not found | close the phone app; switch the box on; move closer; `scan --all` |
| `services` reports "NOT present" | different protocol, see step 1 |
| `query` gets no answer | switch the box off and on; try with `--bind` and press the button on the box |
| HA does not find the box although Bluetooth is set up | HA needs a receiver that can **connect**: a built-in adapter, a USB stick or an ESPHome Bluetooth proxy in range (with `active: true`). Shelly devices only listen and are not enough. The setup message says which case applies. |
| Values in HA go stale | set the integration's logs to debug (`logger: logs: custom_components.alpicool_ble: debug`) |

## Tests of the probe script

```bash
pip install -r requirements-test.txt
pytest -q tests/test_tools_protocol.py tests/test_tools_probe.py
```

## Sources and thanks

- Protocol: [klightspeed/BrassMonkeyFridgeMonitor](https://github.com/klightspeed/BrassMonkeyFridgeMonitor) (MIT)
- Test vectors and practical details: [neftaly/esphome-alpicool](https://github.com/neftaly/esphome-alpicool)
- Home Assistant integration: [Gruni22/alpicool_ha_ble](https://github.com/Gruni22/alpicool_ha_ble)
- Motivation: [Pekaway forum](https://forum.pekaway.de/t/maentum-pluginfestival-kuhlboxen-per-bluetooth-einbinden-und-steuern/2302), [smarthomeundmore.de](https://smarthomeundmore.de/home-assistant-kuehlbox-smart-bluetooth-esphome/)

No code was taken from the projects without a license file, only documented facts, each with a source.
