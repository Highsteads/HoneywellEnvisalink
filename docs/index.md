---
title: Home
nav_order: 1
---

# Honeywell Envisalink for Indigo

This plugin connects a Honeywell Vista alarm panel to [Indigo](https://www.indigodomo.com) through an **Envisalink**, the small network module from EyezOn that wires into the panel's keypad connections and puts the panel on your home network. Indigo then shows what the alarm keypad shows — ready, armed, in alarm — and which doors, windows and motion sensors are open, and it can arm and disarm the panel for you.

## This plugin is a beta

I do not have a Honeywell panel myself, so the plugin has been tested by an Indigo user on a real **Vista 20P** with an **Envisalink 4**. On that panel it reads every state correctly — ready, exit delay, armed, alarm, alarm memory and open zones — and it has armed the panel in Stay mode and disarmed it from Indigo.

Some things have not yet been tried on real hardware:

- the other Vista panels, and the Envisalink 3 and 5
- the **Arm — Away**, **Arm — Instant**, **Arm — Max** and **Bypass zone** actions, which press keys the same way as the tested Arm — Stay and Disarm, but have not been sent to a real panel

The plugin starts in **test mode**, which lets it read the panel but stops it sending any command. Please read [Safety and test mode](safety.md) before you turn test mode off on a panel that protects your home.

## What it does for you

- **Shows the state of each partition** — Ready, Not Ready, Armed Away, Armed Stay, Armed Instant, Armed Max, Exit Delay, Entry Delay, ALARM and more — along with the text on the keypad's screen.
- **Shows each zone as open or closed**, so a door, window or motion sensor on the alarm can drive lights, notifications and anything else in Indigo.
- **Arms and disarms the panel** from an Indigo action, a schedule, a trigger or a control page, by pressing the same keys you would press on the keypad.
- **Bypasses a zone** when you need to leave one out.
- **Runs your triggers** when a partition is armed, disarmed or goes into alarm — fire alarms included — and when the connection to the Envisalink drops.
- **Keeps your codes out of the log.** Every key of a user code is masked before anything is written down, and the Envisalink password never appears in the log or in any file the plugin writes.
- **Records what your panel sends** for a few minutes, from the plugin menu, in a file you can share on the forum to help with the beta.

The plugin does not change how the panel itself works. It reads a copy of the keypad and presses keys on a virtual keypad, so your own keypads, sensors and siren carry on as before, whether or not Indigo is running.

## Where to go next

| If you want to... | Read |
|---|---|
| Install the plugin and connect it to your panel | [Getting started](getting-started.md) |
| Know what test mode does and how to arm and disarm safely | [Safety and test mode](safety.md) |
| Know what each device shows in Indigo | [Your devices](devices.md) |
| Understand what the plugin is doing behind the scenes | [How it works](how-it-works.md) |
| Arm, disarm and bypass from actions, and run triggers | [Actions and triggers](actions-and-triggers.md) |
| Know what every setting does | [Settings](settings.md) |
| Know what each item in the Plugins menu does | [The plugin menu](plugin-menu.md) |
| Sort out a problem | [When something goes wrong](troubleshooting.md) |
| Send me the details I need to improve the plugin | [Helping with the beta](helping-with-the-beta.md) |
| See what changed in each version | [Version history](changelog.md) |

## Download

The latest version is always on the [Releases page](https://github.com/Highsteads/HoneywellEnvisalink/releases/latest).
