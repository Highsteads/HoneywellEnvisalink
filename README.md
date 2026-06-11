# HoneywellEnvisalink

> # 🚧 BETA — v0.1.4-beta — needs beta testers with real hardware
>
> This plugin has **never been tested against an actual Honeywell panel**. The protocol implementation, plugin structure, safety rails and test
> infrastructure are all in place, and a 59-case automated test suite covers the protocol parser/encoder end to end — but only somebody with a real
> Vista panel and Envisalink module can verify that what the code thinks the panel says matches what your panel actually says.
>
> **Do not install this on a panel you depend on for security without reading the [Safety design](#safety-design) section first.** Test mode is on by
> default for exactly this reason.
>
> If you've got Honeywell hardware and are up for being a beta tester, see [Testing & debugging from afar](#testing--debugging-from-afar) below.

An [Indigo Domotics](https://www.indigodomo.com) plugin that connects **Honeywell Vista alarm panels** to Indigo via an **Envisalink** network module.

## What's new since v0.1.1-beta

The first two releases shipped without anyone (including me) having driven the plugin against any kind of EVL — real or simulated. That changed this week. Wiring it up to the bundled `mock_evl_server.py` for a proper end-to-end run turned up two real bugs and a handful of robustness gaps. All fixed in this release.

- **Login was silently failing** (0.1.4-beta). The password send was being dropped by an over-eager safety check on the public send path. Direct sendall during the login handshake instead. If you tried v0.1.0 or v0.1.1 and it just sat there saying "send dropped — not connected", this is why.
- **Orphan plugin host processes on restart** (0.1.3-beta). The TPI socket recv loop only woke promptly when the socket was explicitly shut down, but during reconnect backoff there is no socket to shut down. Hardened with a 1-second recv tick so the loop checks the stop event regardless, plus a 60-second stale-connection detector that's independent of the recv timeout. Join timeout reduced to 3 seconds with a warning logged if the worker thread doesn't exit cleanly.
- **Disconnect callbacks during shutdown suppressed** (0.1.3-beta) — they were calling back into Indigo APIs from a thread mid-shutdown, which is a known way to deadlock the host's own cleanup.
- **Conventions tidy-up** (0.1.2-beta) — applied Jay's 25-May-2026 plugin-store conventions: leaner startup banner (full diagnostic banner now on demand via Show Plugin Info), README moved to repo root only, LICENSE added.

End-to-end against the mock: connect → login → zone-timer dump → keypad updates → zone trips → arm exit-delay → armed-away → alarm → CID event → reset, with partition and zone Indigo devices taking the correct state at each step.

Fills a long-standing gap: Indigo already has plugins for DSC panels via Envisalink (DSC plugin) and for Honeywell panels via the now-discontinued AD2USB
serial board (Ademco plugin), but nothing that combines **Honeywell + Envisalink** — until now.

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

I (the author) don't have a Honeywell panel to test against, which is why this is a v0.1.4-beta explicitly looking for test pilots. To make remote debugging
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
works fine on its own. To create that file, copy `IndigoSecrets_example.py` (shipped with the CliveS plugins) into `/Library/Application Support/Perceptive Automation/` and rename the copy to `IndigoSecrets.py`.

## How was this built?

- **Claude Code** (Anthropic) — wrote the plugin, protocol parser, test suite, mock server and docs
- **Reference implementations consulted:**
  - The Eyez-On Envisalink TPI specification (Honeywell)
  - `pyenvisalink` (the library Home Assistant uses for Envisalink integration)
  - The existing Indigo DSC plugin (for overall plugin structure and Envisalink transport patterns)
  - The Indigo AD2USB plugin (for the Honeywell keystroke protocol — same panel-side protocol, just over USB)

## Reporting issues

Easiest way to get hold of me is via the **[Indigo forum](https://forums.indigodomo.com/)** — either reply in the relevant thread, start a new one, or
send me a DM (forum user **CliveS**). Please include:

- Your **panel model** (Vista 15P / 20P / 21iP / 128BP / 250BP / other)
- Your **Envisalink model** (EVL3 / EVL4 / EVL5)
- What you were doing and what happened
- If something went sideways, attach the output of the **Plugins → HoneywellEnvisalink → Save diagnostic bundle** menu item — it's a JSON file written to
  `/tmp/`, safe to share verbatim (contains no password and no user codes)

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
