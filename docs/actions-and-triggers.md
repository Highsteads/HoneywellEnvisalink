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
| **Bypass zone** | your code, then 6, then the zone number | Leaves one zone out, so the panel ignores it while it stays bypassed. Zone numbers below 10 go as two digits, so zone 5 is sent as 05. |

**Disarm** and **Arm — Stay** have been tested on a real panel. The others press keys in the same way but have not yet been sent to one, so try each first while you are at home.

### Setting one up

1. Add an action to a trigger, schedule, action group or control page.
2. In the action's type menu, find **HoneywellEnvisalink (BETA)** under **Device Actions**, and pick the action.
3. Choose the partition device.
4. Type your code into **User code**. It must be 4 or 6 digits, and the box masks it.
5. For **Bypass zone**, also type the zone's number, from 1 to 250, into **Zone to bypass**. The action will not save with anything else.

### What happens when it runs

- **Test mode on** — nothing is sent, and the Event Log says the action was suppressed. See [Safety and test mode](safety.md).
- **Not connected** — nothing is sent, and the Event Log says the action was dropped because the Envisalink is not connected.
- **Code missing or the wrong length** — nothing is sent, and the Event Log says the code is invalid or missing.
- **Otherwise** the keys are sent. The plugin does not check that the panel armed or disarmed, so watch the partition's **Partition state** to confirm it.

## The events

These run a trigger. To use one, create a new trigger, choose **HoneywellEnvisalink (BETA)** as its type, pick the event, and add whatever you want to happen.

| Event | When it runs |
|---|---|
| **Alarm triggered** | A partition goes into alarm, fire alarms included. |
| **Partition armed (away)** | A partition is armed in Away mode. |
| **Partition armed (stay)** | A partition is armed in Stay mode. |
| **Partition armed (instant)** | A partition is armed in Instant mode. |
| **Partition armed (max)** | A partition is armed in Max mode. |
| **Partition disarmed** | A partition is disarmed, even if a door or window was left open. |
| **Envisalink disconnected** | The connection to the Envisalink drops, or an attempt to reconnect fails. |

Before you rely on them:

- **The events do not say which partition.** Each one runs for any partition. If you have more than one partition, read the partition device's **Partition state** in your trigger's conditions, or use a device state trigger as below.
- **Each event runs once per change.** The same state reported again does not run the trigger again.
- **When the plugin starts,** the first reading from each partition runs the event that matches its state. So a **Partition disarmed** trigger runs once at start-up if the panel is disarmed.
- **The armed events can run at the start of the exit delay.** On the tester's panel, the panel reports the armed state as soon as arming begins, so an armed event runs then rather than when the countdown ends.
- **Envisalink disconnected runs on every failed attempt** while the Envisalink cannot be reached — after 5, 10, 20 and 40 seconds and then every minute. If it sends you a notification, expect one for each attempt.

## Triggers on a device's state

Indigo's own **Device State Changed** trigger works with every state on the [Your devices](devices.md) page. It is the way to act on one partition or one zone. For example:

- A trigger on a partition's **Partition state** becoming **Armed Away** can switch the lights off, and one on it becoming **ALARM** can switch every light on.
- A trigger on a zone's **Zone state** becoming **Open** can switch a light on when someone opens the back door, whether the alarm is set or not.
- A trigger on a partition's **AC Power** becoming false tells you the panel has lost mains power.
