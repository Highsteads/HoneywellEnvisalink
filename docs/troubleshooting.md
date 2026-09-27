---
title: When something goes wrong
nav_order: 9
---

# When something goes wrong

Each section starts with what you see, then what it means and what to do.

## The log says "Waiting for configuration" or "Waiting for EVL password"

The plugin has no Envisalink address, or no password, so it has not tried to connect. Fill both in with **Plugins → HoneywellEnvisalink (BETA) → Configure** and click **Save**.

## Connected stays false, and the log keeps saying "reconnecting in"

The plugin cannot reach the Envisalink. It keeps trying by itself, every minute at most.

- Check the Envisalink has power and is connected to your network.
- Check **Envisalink IP address or hostname** matches the address in your router's list of devices. If the router has moved it, change the setting and click **Save**, and ask the router to keep that address from now on.
- Check **TCP port** is 4025, unless you know your Envisalink uses another.

## The log says "login FAILED — stopping reconnect"

The Envisalink refused the password, so the plugin has stopped trying until you correct it.

- If you typed the password into **Configure**, correct it there and click **Save**. The plugin connects again at once.
- If the password is in `IndigoSecrets.py`, that one is used whatever **Configure** says. Correct it in the file, then choose **Plugins → HoneywellEnvisalink (BETA) → Reload**.

## The partition shows its state but the panel device's Connected is false

The panel device only changes when the plugin logs in or loses the connection, so one added after the plugin connected waits for the next login. Open **Configure** and click **Save** to reconnect.

## A partition device never changes

Check its **Partition number (1-8)** matches the partition on your panel. Most homes use 1.

## A zone device never changes

Check its **Zone number (1-250)** matches the zone's number in your panel. A zone left at 0 is never updated.

## A door shows open for a while after it has closed

Honeywell panels do not always report a door closing straight away, so the plugin reads the zone timers every **Zone status refresh (seconds)** — 30 to start with. Lower it, to 5 at the least, for quicker updates. If it is set to 0, the refresh is off, so set it back to a number.

## The log warns that the Envisalink "may be under too much traffic"

The Envisalink has said it cannot keep up. Raise **Zone status refresh (seconds)** in **Configure**, or set it to 0 to stop the refresh.

## The log says "no traffic for 60s — assuming connection stale"

The Envisalink went quiet for a minute. The plugin reconnects by itself, and you need do nothing unless it keeps happening, in which case check the Envisalink's power and network cable.

## An arm or disarm action does nothing

Look in the Event Log for the reason:

- **"TEST MODE: ... suppressed"** — test mode is on. See [Safety and test mode](safety.md).
- **"dropped — EVL not connected"** — the plugin was not connected when the action ran, so nothing was sent.
- **"invalid or missing user_code"** — open the action and check the code is 4 or 6 digits.

If none of these appears, the keys were sent. Check the partition's **Keypad display** state, which shows what the panel made of them. If a door or window is open, the panel may not arm, so check the partition's **Ready** state first.

## The Envisalink disconnected trigger runs again and again

While the Envisalink cannot be reached, the event runs on every failed attempt to reconnect. Once the plugin gets through, it stops.

## Still stuck?

Choose **Plugins → HoneywellEnvisalink (BETA) → Save diagnostic bundle (for sharing)**, and post the file it writes on the [Indigo forum](https://forums.indigodomo.com), with your panel model, your Envisalink model and a description of what you see. The file holds no password, no codes and no address, so you can share it as it is. You can also [raise an issue on GitHub](https://github.com/Highsteads/HoneywellEnvisalink/issues).
