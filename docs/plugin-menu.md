---
title: The plugin menu
nav_order: 8
---

# The plugin menu

These are under **Plugins → HoneywellEnvisalink (BETA)**.

| Menu item | What it does |
|---|---|
| **Test connection** | Writes the connection's figures to the Event Log — whether it is connected, how much has been sent and received, how many times it has connected, and when it last connected and last heard from the Envisalink. If it is connected, it also asks the panel for a fresh reading of the zones. If the plugin has no connection set up, it says to check the settings. |
| **Dump recent protocol traffic to log** | Writes the last 500 lines sent to and received from the Envisalink to the Event Log, with codes and the password masked. |
| **Save diagnostic bundle (for sharing)** | Writes a file for me to look at if something goes wrong — see below. |
| **Capture protocol data (for the author)...** | Records what your panel sends for a few minutes while you use your keypad, and writes a file you can share. It never arms or disarms anything. [Helping with the beta](helping-with-the-beta.md) explains how to use it. |
| **Toggle verbose protocol logging** | Switches **Verbose protocol logging** on or off without opening the settings. It stays as you leave it. |
| **Toggle test mode (commands suppressed / live)** | Switches test mode on or off without opening the settings, and says in the Event Log which it now is. It stays as you leave it. See [Safety and test mode](safety.md) first. |
| **Show Plugin Info** | Writes the plugin's version, details of your Mac and Indigo, the Envisalink's address and whether test mode is on to the Event Log, which is useful to include if you ask for help on the Indigo forum. |

## The diagnostic bundle

**Save diagnostic bundle (for sharing)** writes a file named like `honeywell_envisalink_diag_1790000000.json` into the Mac's `/tmp` folder, and the Event Log gives its full name. To find it, choose **Go → Go to Folder** in the Finder and type `/tmp`.

It holds the plugin's version, the port and the test mode and logging settings, the connection figures, the last 500 lines of traffic with codes and the password masked, and the partition and zone numbers of your devices. It leaves out the password, your codes and the Envisalink's address, so you can share it as it is. Only your own Mac account can open it.
