# HoneywellEnvisalink

> # 🚧 BETA (shake-down) — v0.5.2 — reading AND arming/disarming now confirmed on a real Honeywell panel
>
> **Tested end to end on a real Vista 20P with an EVL4:** it reads the panel correctly (ready, armed, exit delay, alarm and alarm-memory, doors/windows/motion
> open-closed) **and successfully arms and disarms the panel from Indigo**. Everything the plugin is meant to do is now working on a real system. It's kept in
> beta for a short shake-down — a few days of real-world use — before being declared 1.0.
>
> **Do not install this on a panel you depend on for security without reading the [Safety design](#safety-design) section first.** Test mode is on by
> default for exactly this reason.
>
> It's being actively tested against real Honeywell hardware, so it's no longer flying blind — but more hands are always welcome. If you've got Honeywell
> kit and would like to help, see [Testing & debugging from afar](#testing--debugging-from-afar) below.

An [Indigo Domotics](https://www.indigodomo.com) plugin that connects **Honeywell Vista alarm panels** to Indigo via an **Envisalink** network module.

## What's new in v0.5.2

**A fire alarm was not reporting as an alarm.** The partition state was worked out from the keypad flags, and while a burglary alarm set the partition to ALARM, a fire alarm fell through to the armed and ready branches instead. So the partition never showed ALARM and the alarm event never fired. Fire now raises ALARM the same as any other alarm. If you have triggers hanging off the alarm event, they were blind to fire until this release.

Three more fixes came out of the same pass:

- **Armed-Max was missed on some panels.** The code looked for "MAXIMUM" on the keypad display, but real panels show "MAX" as well. Both now match.
- **A failed trigger could swallow the event for good.** The partition event was latched as sent before it was actually fired, so an exception mid-fire left the latch set and the event never fired and never retried. It now fires first and latches after, and each trigger is isolated so one bad trigger cannot block the rest.
- **Two lists were being read while Indigo was changing them.** The trigger and zone-device lists are updated from Indigo's thread while the network thread walks them. Both are now snapshotted before iterating.

The automated suite is 138 cases.

## What's new in v0.5.1-beta

Self-monitoring for the zone polling. If you turn the zone-status refresh right down for snappier door updates, the plugin now watches the Envisalink's own responses and, the moment the module reports it is struggling to keep up (a buffer overrun, overflow or timeout), it logs a plain-English warning suggesting you ease the interval back off. So you get instant feedback in the Indigo log if you've asked too much of the Envisalink, rather than finding out the hard way — "delay is better than lockout", surfaced automatically.

## What's new in v0.5.0-beta

Faster, more reliable door and window status. In testing, motion sensor status updated in Indigo almost instantly, but a door closing could take a couple of minutes to show as shut. That's because Honeywell panels push some zone changes in real time but leave others to be worked out from the panel's zone timers — which is exactly what the Envisalink's own app polls for. The plugin now does the same: it gently polls the zone-timer dump on a set interval and refreshes any zone the real-time stream hasn't just changed, so a door closing shows up within seconds rather than minutes.

It's a single lightweight read on each interval — deliberately gentle, nothing like the command flood that has caused keypad lockouts with other integrations — and there's a new **"Zone status refresh (seconds)"** setting in the plugin config. It **defaults to 30 seconds and can go as low as 5 seconds** for near-instant door updates, or you can raise it to be even lighter on the Envisalink, or set it to 0 to turn polling off and rely on real-time updates only. And so you can push it hard safely, **the plugin checks for overloading** — it watches the Envisalink's own responses and, the moment the module reports it can't keep up, it logs a warning telling you to ease the interval back off. So you can dial the refresh right down and let the Indigo log tell you if you've gone too far. Motion and most changes still update instantly regardless.

## What's new in v0.4.1-beta

First real capture off a live Vista 20P, and the plugin read the whole thing correctly — every armed state, the alarm and alarm-memory, the disarm, and the right zones open. One small fix came out of it: the panel sends a special "Alarm Canceled" keypad line with a couple of non-numeric fields, which the parser was throwing away. It now takes that in its stride (and every real frame from the capture is baked into the test suite so it can't regress). Reading a real panel is now confirmed working — the remaining unknown is only the outgoing arm/disarm side.

## What's new in v0.4.0-beta

Helping with the beta no longer needs the terminal. There's now a **Capture protocol data** item right in the plugin's menu (Plugins → HoneywellEnvisalink → Capture protocol data). Pick how long to run it, and it records what your panel sends while you use your keypad, then writes a shareable file and tells you whether it's safe to post. It only ever listens — it can't arm or disarm anything, and there's no password in the file. That's the easiest way to send me the data I need to finish the zone and arm/disarm decoding.

Under the hood the menu capture and the standalone `tools/capture_tpi.py` now share the same decode-and-redact code, so they can't drift, and the whole capture path was checked over by an adversarial review before it went anywhere near a live panel.

## What's new in v0.3.0-beta

The plugin met real hardware for the first time — and it exposed that the whole protocol layer was built against the wrong wire format. Real Envisalink Honeywell panels frame every message with a trailing `$` and no checksum, use a 16-bit keypad LED field, and send keystrokes one at a time under different command codes. The first releases assumed a DSC-style 2-character checksum, an 8-bit LED field and bundled keystrokes, so on a real panel it connected, logged in, and then rejected every single frame as a bad checksum (on real hardware the connection went live but zero panel state came through).

- **Protocol rewritten to the real Envisalink Honeywell TPI.** Framing, the 16-bit keypad flags, the partition and Contact ID messages, and the outgoing arm/disarm/keypress commands have all been corrected to what real panels actually speak — verified against the exact frames captured on a real Vista 20P.
- **The mock server now speaks the real framing too**, so the automated tests can never drift back to the old wrong model. The real captured frames are baked in as regression fixtures.
- **A KeepAlive poll** is now sent periodically to keep the module's session open.

This is the change that should take the plugin from "connects but shows nothing" to "actually reads your panel". The credential-redaction and robustness work from v0.2.0-beta (below) all carried through — and testing confirmed the diagnostic bundle came out with the password already masked.

The automated suite is 77 cases against the real protocol, including the real-hardware captures.

## What's new in v0.2.0-beta

A full deep review of the plugin, with the findings adversarially double-checked and then fixed in one pass. The headline is a security fix, but there are a good number of robustness improvements alongside it.

- **Security: the EVL password could leak into the diagnostic bundle and the protocol log.** The login send was being recorded through the same debug path as everything else, and the redactor only masked user codes in keystroke commands, not the bare password. So the one file the plugin told you was safe to share on the forum could have your Envisalink password sitting in it in plain text. The login send is now masked at source — it never reaches the ring buffer, the log, or the bundle. The "safe to share" promise is finally true, and there is now a test that fails if a password ever sneaks back in.
- **A wrong password no longer retries forever.** A failed login used to drop straight back into the reconnect loop and hammer the board with the same bad password indefinitely. It now stops, logs a clear message asking you to fix the password, and waits for you to reload the plugin.
- **A blank or mistyped port no longer stops the plugin loading.** Clearing the port field and saving used to take the whole plugin down on the next reload. It now falls back to 4025, and the config dialog validates the port before it lets you save.
- **Steadier panel-state reading.** Armed-Stay can no longer be misread as Armed-Max, alarm-in-memory is now picked up from the keypad LED as well as the display text, and the Contact ID parser copes with both of the firmware formats an Envisalink can send. An unrecognised zone code now shows as faulted rather than silently reading as a closed door — the safe direction for a security sensor.
- **New trigger events for Arm Instant and Arm Max**, and the Disarmed event now fires even when a partition comes back not-ready because a zone was left open. Repeated identical panel updates no longer re-fire the same trigger over and over.
- **Zones answer a status request cleanly** instead of logging an error, and shutdown is a little tidier around the background network thread.

The automated test suite has grown from 59 to 105 cases to cover all of the above.

## Earlier changes (since v0.1.1-beta)

The first two releases shipped without anyone (including me) having driven the plugin against any kind of EVL — real or simulated. That changed back in May. Wiring it up to the bundled `mock_evl_server.py` for a proper end-to-end run turned up two real bugs and a handful of robustness gaps. All fixed at the time.

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
**Up to:** 8 partitions, 250 zones — the plugin accepts those ranges, and how many your own panel has depends on the model

## Features

- Real-time panel state via the Envisalink TPI socket (port 4025)
- Indigo devices for the **Panel** (overall connectivity), each **Partition** (armed/disarmed/alarm/exit/entry/etc.) and each **Zone** (open/closed/bypass/trouble/alarm)
- Live virtual-keypad mirror — the actual 32-char LCD text the keypad shows, the LED state, beep codes
- Actions: **Arm Away, Arm Stay, Arm Instant, Arm Max, Disarm, Bypass Zone**
- Seven events you can hook triggers to: **Alarm triggered** (burglary or fire), **Partition armed** — away, stay, instant and max each firing separately — **Partition disarmed**, and **Envisalink disconnected**
- Auto-reconnect with exponential backoff
- Contact ID (CID) real-time event capture for full alarm-monitoring fidelity

## Safety design

Alarm panels are not lights — getting it wrong has real consequences. The plugin is built around three safety rails:

1. **Test mode ON by default.** On fresh install, all arm/disarm/bypass commands are blocked — the plugin reads state from the panel but cannot send
   anything to it. You explicitly disable test mode (via plugin config or a menu item) once you've verified state-reading works. This means you cannot
   accidentally trigger or disarm your panel during initial setup.
2. **User codes are never stored.** Codes are entered into each action's config UI individually (with `secure="true"` so they're masked) and pass straight
   through to the panel. They are not held in plugin prefs, not written to any state, not logged.
3. **All outgoing protocol traffic is redacted in logs.** User codes in keystroke commands are replaced with `****`, and the login password is masked at
   source so it never reaches the log, the recent-traffic buffer or the diagnostic bundle. Verified by the pytest suite.

## Testing & debugging from afar

I (the author) don't have a Honeywell panel of my own, so it's being shaken down against real hardware by an Indigo user with a Vista panel — no longer flying
blind, but still in beta while it beds in, and more hands are welcome. To make remote debugging tractable, the plugin ships with:

### Capture protocol data for me (the most useful thing you can do)
The easiest way is right in the plugin: **Plugins → HoneywellEnvisalink → Capture protocol data**. Choose how long to run it, then follow the short list of
keypad actions it shows you (open a zone, arm stay, arm away, let an entry delay run, arm instant, arm max, disarming after each). It records what your panel
sends the whole time, writes a JSON file to `/tmp`, and logs whether it's safe to share. It never sends an arm/disarm — it only listens — and there's no
password in the file. Attach that file to a forum reply and I can turn it straight into fixes and tests.

If you'd rather use the terminal, `tools/capture_tpi.py` does the same thing with a step-by-step guided walk-through (it shares the exact same decoding and
redaction as the menu item):

```bash
python3 tools/capture_tpi.py --host <your-envisalink-ip> --guided
```

### Built-in diagnostic menu items
- **Capture protocol data** — records what your panel sends for a chosen few minutes while you use your keypad, then writes a shareable JSON file (read-only, no password, codes masked)
- **Test connection** — connects, logs in, fetches a zone-timer dump, prints full stats to the Indigo log (bytes rx/tx, frame counts, last connect/recv timestamps)
- **Dump recent protocol traffic to log** — prints the last 500 raw TPI lines (with user codes redacted) so I can see exactly what your panel is sending
- **Save diagnostic bundle** — writes a complete JSON bundle to `/tmp/honeywell_envisalink_diag_<timestamp>.json` containing stats, recent traffic, plugin
  config (minus password), and your partition/zone device list. Safe to share verbatim
- **Toggle verbose protocol logging** — flip live byte-by-byte logging on/off without restarting the plugin
- **Toggle test mode** — flip safety mode without going through the config dialog

### Pytest suite
A comprehensive pytest suite covers the protocol parser/encoder, frame parsing, the 16-bit keypad decode, code-redaction and the capture tool — anchored to
real captured frames. Run it from the repo root:

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
