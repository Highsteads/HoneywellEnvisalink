---
title: Settings
nav_order: 7
---

# Settings

## The plugin's settings

Open these with **Plugins → HoneywellEnvisalink (BETA) → Configure**. Clicking **Save** reconnects to the Envisalink with the new settings. If the address or the password is missing, the Event Log says so and the plugin stays disconnected.

| Setting | What it does |
|---|---|
| **Envisalink IP address or hostname** | The Envisalink's network address, such as `192.168.1.50`, or its name on your network. Without it the plugin does not connect. |
| **TCP port** | The port the Envisalink listens on, 4025 to start with. Only change it if your Envisalink uses another. It must be a whole number from 1 to 65535, and a blank box means 4025. |
| **EVL password** | The Envisalink's password — the one for its own web page, which is `user` unless someone has changed it. Without it the plugin does not connect. The box masks it as you type. |
| **Test mode (SAFE)** | Ticked, the plugin reads the panel but sends no arm, disarm or bypass command. It is ticked to start with. See [Safety and test mode](safety.md) before you untick it. |
| **Zone status refresh (seconds)** | How often the plugin asks the panel for a fresh reading of every zone, 30 to start with. The lowest it goes is 5, so 1 to 4 are treated as 5, and anything that is not a number is treated as 30. Raise it to be gentler on the Envisalink, or set 0 to stop the refresh and rely on the changes the panel sends by itself, in which case a door closing may not show for some time. [How it works](how-it-works.md) explains why. |
| **Verbose protocol logging** | Writes every line sent to and received from the Envisalink to the Event Log, with codes masked. Useful when chasing a problem, but it adds a great many lines. The plugin menu can also switch it on and off. |
| **General debug logging** | Adds lines to the Event Log about what the plugin does with each message. Only useful when chasing a problem. |

### Keeping the password in one file

If you would rather keep the Envisalink password out of Indigo's settings, you can put it in a file called `IndigoSecrets.py` in `/Library/Application Support/Perceptive Automation/`. Several of my plugins read their passwords from this file, and this one reads one setting from it, `ENVISALINK_PASSWORD`.

If you already have the file, add this line to it. If not, create a plain text file with that name in that folder, holding just this line, with your own password between the quotes:

```python
ENVISALINK_PASSWORD = "your-envisalink-password"
```

When the file has the password, it is used, whatever the **EVL password** box says. The plugin reads the file when it starts, so after changing it choose **Plugins → HoneywellEnvisalink (BETA) → Reload**.

## Each device's settings

Open these by double-clicking a device in Indigo.

### Honeywell Panel (via Envisalink)

| Setting | What it does |
|---|---|
| **Panel model** | Your Vista panel's model, for your own reference. It does not change how the plugin works. |
| **Envisalink model** | Your Envisalink's model, for your own reference. It does not change how the plugin works. |

### Honeywell Partition

| Setting | What it does |
|---|---|
| **Partition number (1-8)** | The partition this device follows and sends commands to, 1 to start with. Most homes have one partition, number 1. |

### Honeywell Zone

| Setting | What it does |
|---|---|
| **Zone number (1-250)** | The zone this device follows, as numbered in your panel. It starts at 0, and a zone left at 0 is never updated. |
| **Zone type** | What the zone is — door or window contact, motion detector, glass-break, smoke or heat, CO detector, panic button or other — for your own reference. It does not change how the plugin works. |
