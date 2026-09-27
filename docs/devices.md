---
title: Your devices
nav_order: 4
---

# Your devices

The plugin gives you three kinds of device. This page explains what each one shows.

## Honeywell Panel (via Envisalink)

One of these stands for your panel and its Envisalink. You need exactly one.

| Shown as | What it means |
|---|---|
| **Connected** | True while the plugin is logged in to the Envisalink, false when the connection is down or the login failed. This is what the device list shows. |
| **Last CID event** | The last alarm report the panel made, in the Contact ID code panels use to report to a monitoring centre, written like `1130/P1/5`. The first digit is 1 for a new event or 3 for one that has cleared, the next three are the event code (130 is a burglary alarm), then comes the partition, then the zone or user number. Each report also appears in the Event Log. |

## Honeywell Partition

One for each partition you use. Most homes have one.

| Shown as | What it means |
|---|---|
| **Partition state** | The partition's state, from the list below. This is what the device list shows. |
| **Keypad display** | The text on the keypad's screen, such as `****DISARMED****  Ready to Arm`. |
| **Armed** | True when the partition is armed in any mode. |
| **Ready** | True when the keypad's Ready light is on, so the partition can be armed. |
| **Trouble** | True when the panel reports a system trouble. |
| **Bypass** | True when one or more zones are bypassed. |
| **AC Power** | True while the panel has mains power. |
| **Chime** | True when the keypad's chime is on. |
| **ALARM** | True while the keypad shows an alarm. A fire alarm always shows in **Partition state** as ALARM, so use Partition state if you want to catch both. |
| **LED bitmap** | The keypad's lights as a four-digit code, such as `0x1C08`. Useful only when chasing a problem. |
| **Beep code** | What the keypad is beeping: 0 is silent, 1 to 3 is that many beeps, 4 is a continuous fast beep and 5 a continuous slow one. |

### Partition states

| State | What it means |
|---|---|
| **Unknown** | The plugin has not heard from this partition yet. |
| **Ready** | Disarmed, and ready to arm. |
| **Not Ready** | Disarmed, but something is open, so it cannot arm yet. |
| **Armed Away** | Armed with everyone out. |
| **Armed Stay** | Armed with people at home. |
| **Armed Instant** | Armed in Stay mode with no entry delay. |
| **Armed Max** | Armed in Away mode with no entry delay. |
| **Exit Delay** | Arming, and counting down so you can leave. |
| **Entry Delay** | Someone has come in, and the panel is counting down before the alarm sounds. |
| **Exit / Entry Delay** | The panel reports a countdown without saying which kind. |
| **ALARM** | The alarm is going off. Fire alarms show here too. |
| **Alarm Memory** | An alarm has happened, and the keypad is still showing it. |
| **Trouble** | Disarmed, with a system trouble showing. |

## Honeywell Zone

One for each zone you want to see — a door or window contact, a motion sensor, a glass-break sensor and so on. Each one is an ordinary Indigo sensor, so it works anywhere a sensor does.

| Shown as | What it means |
|---|---|
| **Zone state** | **Open** or **Closed**. A motion sensor shows Open while it sees movement. This is what the device list shows, and the sensor is on while the zone is open. Before the first reading it shows **Unknown**. |

The plugin sets zones to Open or Closed only. The zone device's list of states also holds Bypassed, Trouble and Alarm, but this version never sets them, so use the partition's **Bypass** state and **Partition state** for those.

Choosing **Send Status Request** on a zone asks the panel for a fresh reading of its zones, rather than waiting for the next refresh.
