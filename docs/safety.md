---
title: Safety and test mode
nav_order: 3
---

# Safety and test mode

An alarm panel is not a light switch. A command that goes wrong can leave a house unprotected, so the plugin is built to start safe and to keep your codes private, and this page explains what it does and what it leaves to you.

## Test mode

**Test mode is on when you first install the plugin.** In test mode the plugin reads the panel and keeps your Indigo devices up to date, but it will not send **Disarm**, any of the four **Arm** actions, or **Bypass zone**. Each one blocked leaves a warning in the Event Log, such as `TEST MODE: 'disarm' suppressed`.

Leave it on until you have watched the plugin follow your panel correctly through a few days of normal use.

To turn test mode off, either untick **Test mode (SAFE)** in **Plugins → HoneywellEnvisalink (BETA) → Configure** and click **Save**, or choose **Plugins → HoneywellEnvisalink (BETA) → Toggle test mode (commands suppressed / live)**. When you use the menu item to make commands live, the Event Log warns **Test mode now OFF — COMMANDS NOW LIVE, can arm/disarm panel!** The same menu item turns test mode back on, and either way the setting stays as you leave it.

## Your user codes

- **Each action holds its own code.** You type a user code into each Disarm, Arm or Bypass zone action, and the code is kept with that action in Indigo. The box masks it as you type.
- **A code must be 4 or 6 digits.** Anything else is refused, and the Event Log says the code is invalid or missing.
- **Codes never go anywhere else.** They are not kept in the plugin's settings or in any device state, and each key of a code is masked with `*` before any line reaches the log, the recent traffic list or a diagnostic file.
- **I suggest giving Indigo its own user code on the panel,** so you can remove it later without changing anyone else's.

The Envisalink password is treated the same way. It is never written to the log or to any file the plugin makes.

## What the plugin does and does not check

When you run an arm or disarm action, the plugin types your code and one more key on the partition's virtual keypad, the same as you would at a real keypad. Then it stops.

- **It does not check the partition is ready first.** If a door is open, the panel may not arm. Check the partition's **Ready** state, or its **Partition state**, before you rely on an arm.
- **It does not confirm the result or try again.** Watch the partition's **Partition state**, or run a trigger on it, to confirm the panel did what you asked. The [Actions and triggers](actions-and-triggers.md) page shows how.
- **It does not queue commands.** If the connection to the Envisalink is down, the command is dropped and the Event Log says so.
- **A bypassed zone is not watched by the panel** while it stays bypassed. Check the keypad display after a bypass.

## What has been tested

On the tester's Vista 20P with an Envisalink 4, **Arm — Stay** and **Disarm** have both worked from Indigo. **Arm — Away**, **Arm — Instant**, **Arm — Max** and **Bypass zone** press keys in exactly the same way, but have not yet been sent to a real panel. Try each one first while you are at home, standing at the keypad.

## If Indigo or the Envisalink stops

The panel carries on protecting the house on its own. Your keypads, sensors and siren do not depend on Indigo. If the connection drops, the plugin tries to reconnect by itself, and the **Envisalink disconnected** event lets you have Indigo tell you.
