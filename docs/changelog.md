---
title: Version history
nav_order: 11
---

# Version history

The newest version is at the top. Every version so far is a beta.

## 0.5.3 — 11 September 2026

The plugin carries a note of where its code lives on GitHub, the same way other Indigo plugins do. Nothing else changed.

## 0.5.2 — 27 July 2026

- **A fire alarm shows as an alarm.** Before, a fire alarm never set **Partition state** to ALARM and never ran the **Alarm triggered** event. If you have triggers on that event, they now run for fire as well.
- **Armed Max is recognised** when the keypad shows MAX as well as MAXIMUM, as some panels do.
- **A trigger that fails no longer loses the event.** One failing trigger no longer stops the others, and the event is no longer marked as sent until it has been.
- **Steadier when you add or change devices and triggers** while the panel is sending.
- On 2 August the version number lost its "-beta" ending, so the Indigo Plugin Store will accept it, and the **About** item in the Plugins menu opens this project's page.

## 0.5.1-beta — 8 July 2026

The plugin watches the Envisalink's replies, and if the Envisalink says it cannot keep up, the Event Log has a warning suggesting you raise **Zone status refresh (seconds)**, at most once every two minutes.

## 0.5.0-beta — 8 July 2026

A door closing shows within seconds rather than minutes. The plugin reads the panel's zone timers every 30 seconds, the same way the Envisalink's own app does, and a new **Zone status refresh (seconds)** setting changes how often, down to 5 seconds, or 0 to turn it off.

## 0.4.1-beta — 7 July 2026

The first recording from a real Vista 20P showed the plugin reading every state correctly — ready, exit delay, Armed Stay, Armed Away, ALARM, alarm memory, disarm and Armed Instant — and the right zones open.

- The keypad's "Alarm Canceled" message is no longer thrown away.
- A partition code the plugin does not know no longer overwrites a good state.

Later the same day the tester armed the panel in Stay mode and disarmed it from Indigo, the first time the plugin sent commands to a real panel.

## 0.4.0-beta — 7 July 2026

New **Capture protocol data (for the author)...** item in the plugin menu, which records what your panel sends for a few minutes and writes a file you can share, without the Terminal. It only listens.

## 0.3.1-beta — 7 July 2026

A Terminal script in the repository's `tools` folder records what a panel sends, for testers helping with the beta. It only listens. The plugin itself did not change.

## 0.3.0-beta — 7 July 2026

The plugin was rewritten to talk to the Envisalink the way real Honeywell panels do. Earlier versions connected and logged in, but on a real panel they understood nothing the Envisalink sent, and their arm and disarm commands would have done nothing.

- The plugin reads the keypad, zones, partitions and alarm reports correctly, checked against a real Vista 20P.
- Arm, disarm and bypass press keys one at a time, as the panel expects.
- The plugin sends a short message every 20 seconds to keep the connection open.

## 0.2.0-beta — 25 June 2026

- **The Envisalink password could appear in the log and in the diagnostic bundle.** It is now masked before anything is written down.
- A wrong password no longer makes the plugin retry for ever. It stops and asks you to correct it.
- A blank or mistyped port no longer stops the plugin loading. It uses 4025, and the settings refuse a port that is not a number.
- Armed Stay can no longer be mistaken for Armed Max, and alarm memory is picked up more reliably.
- New **Partition armed (instant)** and **Partition armed (max)** events. **Partition disarmed** runs even when a door is left open, and the same state reported again no longer re-runs a trigger.
- Zones answer **Send Status Request**.

## 0.1.7-beta — 10 June 2026

A code tidy-up with automatic checks on every change. Nothing you use changed.

## 0.1.6-beta — 29 May 2026

Five device states were renamed inside the plugin — **Last CID event**, **AC Power**, **LED bitmap**, **Beep code** and **Zone state**. Triggers and control pages made with an earlier version that use them need setting up again.

## 0.1.5-beta — 28 May 2026

When the Mac goes to sleep, the plugin closes its connection to the Envisalink cleanly and opens a fresh one when the Mac wakes. Before, the Envisalink could refuse to reconnect after a sleep.

## 0.1.4-beta — 26 May 2026

Fixes the login. Earlier versions never finished logging in to the Envisalink.

## 0.1.3-beta — 26 May 2026

The plugin shuts down cleanly when Indigo restarts it, rather than leaving an old copy running.

## 0.1.2-beta — 25 May 2026

The start-up log is shorter, with the full details under **Show Plugin Info**, and a device only restarts when you change its partition, zone or model.

## 0.1.1-beta — 25 May 2026

Saving the settings without an address or password no longer starts a connection that can only fail, and a plugin that has not been set up yet says so as an ordinary note rather than an error.

## 0.1.0-beta — 24 May 2026

First release.
