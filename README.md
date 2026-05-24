# HoneywellEnvisalink

An [Indigo Domotics](https://www.indigodomo.com) plugin that connects **Honeywell Vista alarm panels** to Indigo via an **Envisalink** network module.

Fills a long-standing gap: Indigo already has plugins for DSC panels via Envisalink (DSC plugin) and for Honeywell panels via the now-discontinued AD2USB
serial board (Ademco plugin), but nothing that combines **Honeywell + Envisalink** — until now.

> **⚠ Pre-release software.** This is v0.1.0 — the protocol, plugin structure and test infrastructure are complete, but the plugin has not yet been tested
> against real hardware. The first installs need to be by people willing to be test pilots and feed back what works and what doesn't. See [Testing &
> debugging from afar](#testing--debugging-from-afar) below.

## Hardware support

**Envisalink:** EVL3, EVL4, EVL5 (firmware auto-detected on connect)
**Panels:** Vista 15P, 20P, 21iP, 128BP, 250BP (and any other Vista-compatible model that the Envisalink supports)
**Up to:** 3 partitions, 250 zones

## Features

- Real-time panel state via the Envisalink TPI socket (port 4025)
- Indigo devices for the **Panel** (overall connectivity), each **Partition** (armed/disarmed/alarm/exit/entry/etc.) and each **Zone** (open/closed/bypass/trouble/alarm)
- Live virtual-keypad mirror — the actual 32-char LCD text the keypad shows, the LED state, beep codes
- Actions: **Arm Away, Arm Stay, Arm Instant, Arm Max, Disarm, Bypass Zone**
- Events you can hook triggers to: alarm triggered, partition armed/disarmed, Envisalink disconnected
- Auto-reconnect with exponential backoff
- Contact ID (CID) real-time event capture for full alarm-monitoring fidelity

## Safety design

Alarm panels are not lights — getting it wrong has real consequences. The plugin is built around three safety rails:

1. **Test mode ON by default.** On fresh install, all arm/disarm/bypass commands are blocked — the plugin reads state from the panel but cannot send
   anything to it. You explicitly disable test mode (via plugin config or a menu item) once you've verified state-reading works. This means you cannot
   accidentally trigger or disarm your panel during initial setup.
2. **User codes are never stored.** Codes are entered into each action's config UI individually (with `secure="true"` so they're masked) and pass straight
   through to the panel. They are not held in plugin prefs, not written to any state, not logged.
3. **All outgoing protocol traffic is redacted in logs.** The debug protocol logger replaces user codes with `****` before writing anything. Verified by
   the pytest suite.

## Testing & debugging from afar

I (the author) don't have a Honeywell panel to test against, which is why this is a v0.1.0 explicitly looking for test pilots. To make remote debugging
tractable, the plugin ships with:

### Built-in diagnostic menu items
- **Test connection** — connects, logs in, fetches a zone-timer dump, prints full stats to the Indigo log (bytes rx/tx, frame counts, last connect/recv timestamps)
- **Dump recent protocol traffic to log** — prints the last 500 raw TPI lines (with user codes redacted) so I can see exactly what your panel is sending
- **Save diagnostic bundle** — writes a complete JSON bundle to `/tmp/honeywell_envisalink_diag_<timestamp>.json` containing stats, recent traffic, plugin
  config (minus password), and your partition/zone device list. Safe to share verbatim
- **Toggle verbose protocol logging** — flip live byte-by-byte logging on/off without restarting the plugin
- **Toggle test mode** — flip safety mode without going through the config dialog

### Pytest suite
A comprehensive pytest suite covers the protocol parser/encoder, checksum logic, frame parsing, and code-redaction. Run it from the repo root:

```bash
pip install pytest
pytest -v tests/
```

The suite uses no Indigo APIs and runs on any machine with Python 3.11+.

### Mock EVL server
A standalone Python script in `tools/mock_evl_server.py` impersonates an Envisalink module speaking the Honeywell TPI protocol. Lets you exercise the
plugin without real hardware — run it on any spare machine, point the plugin at `localhost:4025`, and watch a scripted alarm scenario play out:

```bash
python3 tools/mock_evl_server.py --port 4025 --password user --scenario default
```

Scenarios: `default` (zone trips, arm/disarm, simulated alarm), `ready_only` (just sits idle), `stress` (fires events as fast as possible).

## Install

1. Download the latest release zip from the [Releases page](https://github.com/Highsteads/HoneywellEnvisalink/releases)
2. Unzip to get `HoneywellEnvisalink.indigoPlugin`
3. Double-click the bundle — Indigo will install it
4. Open **Plugins → HoneywellEnvisalink → Configure**
5. Enter your Envisalink IP address, port (default `4025`) and password (default `user` for fresh EVLs)
6. Make sure **Test mode** is ON for first install
7. Create devices: one **Honeywell Panel**, one **Honeywell Partition** per partition, one **Honeywell Zone** per zone you want to track
8. Watch the partition device's state update as you walk around the house opening doors and using the keypad
9. Once happy state-reading works, turn off test mode and try a single arm/disarm action

## Configuration

### `IndigoSecrets.py` (optional)
If you keep secrets in the canonical `/Library/Application Support/Perceptive Automation/IndigoSecrets.py` file, set `ENVISALINK_PASSWORD = "..."` there
and the plugin will use it in preference to whatever's in PluginConfig. This is just my personal convention — completely optional, the PluginConfig field
works fine on its own.

## How was this built?

- **Claude Code** (Anthropic) — wrote the plugin, protocol parser, test suite, mock server and docs
- **Reference implementations consulted:**
  - The Eyez-On Envisalink TPI specification (Honeywell)
  - `pyenvisalink` (the library Home Assistant uses for Envisalink integration)
  - The existing Indigo DSC plugin (for overall plugin structure and Envisalink transport patterns)
  - The Indigo AD2USB plugin (for the Honeywell keystroke protocol — same panel-side protocol, just over USB)

## License

MIT — see [LICENSE](LICENSE). Use it, fork it, butcher it.

## Author

[Highsteads](https://github.com/Highsteads) / CliveS

## Reporting issues

Easiest way to get hold of me is via the **[Indigo forum](https://forums.indigodomo.com/)** — either reply in the relevant thread, start a new one, or
send me a DM (forum user **CliveS**). Please include:

- Your **panel model** (Vista 15P / 20P / 21iP / 128BP / 250BP / other)
- Your **Envisalink model** (EVL3 / EVL4 / EVL5)
- What you were doing and what happened
- If something went sideways, attach the output of the **Plugins → HoneywellEnvisalink → Save diagnostic bundle** menu item — it's a JSON file written to
  `/tmp/`, safe to share verbatim (contains no password and no user codes)

GitHub issues are also fine if you prefer, but the forum is where I live day-to-day so I'll see it sooner.
