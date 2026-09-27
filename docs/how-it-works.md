---
title: How it works
nav_order: 5
---

# How it works

You do not need to know any of this to use the plugin. It is here for anyone who likes to know what is going on.

## One connection to the Envisalink

The Envisalink has a connection that other programs can use, on port 4025. The plugin opens that connection to the address you give it, logs in with the Envisalink's password, and keeps the connection open for as long as the plugin runs. It connects to one Envisalink.

Through that connection the Envisalink sends Indigo a copy of what the keypad shows, a list of the zones that are open, a summary of each partition's state, and the alarm reports the panel makes. The plugin turns these into the states on your [devices](devices.md).

Every 20 seconds the plugin sends the Envisalink a short message to keep the connection alive. If it hears nothing back for 60 seconds, it assumes the connection has gone stale and starts again.

## When the connection drops

If the plugin cannot reach the Envisalink, or the connection drops, it waits 5 seconds and tries again, then 10, 20 and 40 seconds, and then every 60 seconds until it gets through. Each time, the panel device shows **Connected** as false, the Event Log has a warning, and the **Envisalink disconnected** event runs.

If the Envisalink refuses the password, the plugin stops trying, because the same password will fail every time. The Event Log says so, and the plugin waits for you to correct the password, as the [When something goes wrong](troubleshooting.md) page explains.

When the Mac goes to sleep, the plugin closes the connection cleanly, and it opens a fresh one when the Mac wakes.

## Keeping zones up to date

Honeywell panels send some zone changes straight away, such as a motion sensor seeing someone, and leave others, such as a door closing, to be worked out from the panel's zone timers. The Envisalink's own app reads those timers, and so does the plugin.

Every 30 seconds, unless you change **Zone status refresh (seconds)** in the [settings](settings.md), the plugin asks for one reading of the zone timers and brings every zone up to date from it. A zone the panel reported in the meantime keeps that newer report. This is why a door closing can take up to the refresh time to show, while motion shows almost at once.

It is one small request each time, and the plugin watches the Envisalink's replies. If the Envisalink ever says it cannot keep up, the Event Log has a warning, at most once every two minutes, suggesting you refresh less often.

## Arming, disarming and bypassing

A Honeywell panel is armed and disarmed by pressing keys. When you run an arm or disarm action, the plugin presses your user code and then one more key on the partition's virtual keypad, a key at a time with a short pause between each, exactly as you would at a real keypad. The [Actions and triggers](actions-and-triggers.md) page lists which key each action presses.

Before it sends anything, the plugin checks that test mode is off, that it is connected, and that the code is 4 or 6 digits. If any of these fails, nothing is sent and the Event Log says why.

## Keeping codes and passwords private

The plugin keeps the last 500 lines sent to and from the Envisalink, for the **Dump recent protocol traffic to log** and **Save diagnostic bundle** menu items. Before any line is kept or logged, each key of a user code is replaced with `*`, and the login is replaced with `<login: ****>`, so neither your codes nor the Envisalink password can reach the log or a shared file.
