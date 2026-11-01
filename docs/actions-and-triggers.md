---
title: Actions and triggers
nav_order: 6
---

# Actions and triggers

## The actions

Each action works on a **Honeywell Partition** device and needs a user code. Each one presses your code and then the key shown below on that partition's virtual keypad, the same as you would at a real keypad.

| Action | Keys it presses | What it does |
|---|---|---|
| **Disarm** | your code, then 1 | Disarms the partition. |
| **Arm — Away** | your code, then 2 | Arms with everyone out. |
| **Arm — Stay** | your code, then 3 | Arms with people at home. |
| **Arm — Instant** | your code, then 7 | Arms in Stay mode with no entry delay. |
| **Arm — Max** | your code, then 4 | Arms in Away mode with no entry delay. |
| **Bypass zone** | your code, then 6, then the zone number | Leaves one zone out, so the panel ignores it while it stays bypassed. On a Vista 21iP or smaller panel the zone goes as two digits, so zone 5 is sent as 05. On a Vista 128BP or 250BP it goes as three, 005. The plugin goes by the **Panel model** on your panel device, so set that to match. |

**Disarm** and **Arm — Stay** have been tested on a real panel. The others press keys in the same way but have not yet been sent to one, so try each first while you are at home.

### Setting one up

1. Add an action to a trigger, schedule, action group or control page.
2. In the action's type menu, find **HoneywellEnvisalink** under **Device Actions**, and pick the action.
3. Choose the partition device.
4. Type your code into **User code**. It must be exactly 4 ordinary digits, and the box masks it. The dialog refuses anything else.
5. For **Bypass zone**, also type the zone's number, from 1 to 250, into **Zone to bypass**. The action will not save with anything else.

### What happens when it runs

- **Test mode on** — nothing is sent, and the Event Log says the action was suppressed. See [Safety and test mode](safety.md).
- **Not connected** — nothing is sent, and the Event Log says the action was dropped because the Envisalink is not connected.
- **Code missing or the wrong length** — nothing is sent, and the Event Log says the code is invalid or missing.
- **Partition number missing or invalid** — nothing is sent. Open the partition device and set its number from 1 to 8.
- **Command interrupted** — some keys may have arrived. Check the real keypad before trying again.
- **Otherwise** the keys are sent, and the plugin watches the panel for up to 30 seconds:
  - When the partition shows armed, disarmed or bypassed, as you asked, the Event Log says the panel confirmed it.
  - If it does not, the Event Log gives an error and the **Arm, disarm or bypass not confirmed** event runs. A wrong code, an open zone or a missed key can all cause this. Check the real keypad.
  - If the Envisalink refuses a key, the Event Log warns at once.

## The events

These run a trigger. To use one, create a new trigger, choose **HoneywellEnvisalink** as its type, pick the event, and add whatever you want to happen.

| Event | When it runs |
|---|---|
| **Alarm triggered** | A partition goes into alarm, fire alarms included. |
| **Partition armed (away)** | A partition is armed in Away mode. |
| **Partition armed (stay)** | A partition is armed in Stay mode. |
| **Partition armed (instant)** | A partition is armed in Instant mode. |
| **Partition armed (max)** | A partition is armed in Max mode. |
| **Partition disarmed** | A partition stops being armed, even if a door or window was left open, after an alarm, or with a trouble showing. |
| **Envisalink disconnected** | The connection to the Envisalink drops, or the plugin cannot reach it. It runs once for each outage. |
| **Envisalink reconnected** | The plugin gets through again after **Envisalink disconnected**. |
| **Arm, disarm or bypass not confirmed** | An arm, disarm or bypass action was sent, but the panel did not show the result within 30 seconds. |
| **Panel stopped sending status** | The Envisalink is connected, but no keypad status has come from the panel for 60 seconds. The panel, or the wiring between it and the Envisalink, may be offline. It runs once until status returns. A good one to send you a notification. |
| **Panel status resumed** | Keypad status is coming from the panel again after **Panel stopped sending status**. |

Before you rely on them:

- **The events do not say which partition.** Each one runs for any partition. If you have more than one partition, read the partition device's **Partition state** in your trigger's conditions, or use a device state trigger as below.
- **Each event runs once per change.** The same state reported again does not run the trigger again.
- **When the plugin starts,** the first reading from each partition is noted quietly and runs no armed or disarmed event. The exception is an alarm: if a partition is already in alarm, **Alarm triggered** runs.
- **The armed events can run at the start of the exit delay.** On the tester's panel, the panel reports the armed state as soon as arming begins, so an armed event runs then rather than when the countdown ends.
- **Envisalink disconnected runs once per outage.** The plugin keeps retrying — after 5, 10, 20 and 40 seconds and then every minute — but the event does not run again until **Envisalink reconnected** has run.

## Triggers on a device's state

Indigo's own **Device State Changed** trigger works with every state on the [Your devices](devices.md) page. It is the way to act on one partition or one zone. For example:

- A trigger on a partition's **Partition state** becoming **Armed Away** can switch the lights off, and one on it becoming **ALARM** can switch every light on.
- A trigger on a zone's **Zone state** becoming **Open** can switch a light on when someone opens the back door, whether the alarm is set or not.
- A trigger on a partition's **AC Power** becoming false tells you the panel has lost mains power.
