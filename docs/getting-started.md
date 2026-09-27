---
title: Getting started
nav_order: 2
---

# Getting started

You only do this once. The plugin starts in test mode, so nothing you do on this page can arm or disarm your panel.

## What you need

- Indigo 2022.1 or later, on a Mac on the same home network as the Envisalink.
- A Honeywell Vista panel with an Envisalink 3, 4 or 5 already fitted and connected to your network.
- The Envisalink's **network address** — the four numbers separated by dots, such as `192.168.1.50`. Your router's list of connected devices shows it.
- The Envisalink's **password** — the one for its own web page, which is `user` unless someone has changed it.
- Your **partition number**. Most homes have one partition, number 1.
- The **zone numbers** of the doors, windows and sensors you want in Indigo. Your installer's zone list or the panel's programming has them.

It helps a great deal to ask your router to keep giving the Envisalink the same address, which most routers call a **reserved address** or **DHCP reservation**. The plugin connects to the address you give it, so if the router moves the Envisalink the plugin cannot reach it until you change the setting.

## 1. Install the plugin

1. Go to the [Releases page](https://github.com/Highsteads/HoneywellEnvisalink/releases/latest) and download `HoneywellEnvisalink.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `HoneywellEnvisalink.indigoPlugin`
3. Double-click `HoneywellEnvisalink.indigoPlugin` — Indigo will install it automatically

Indigo asks whether to enable the plugin. Say yes. It appears in the Plugins menu as **HoneywellEnvisalink (BETA)**.

## 2. Add your devices

Add the devices first, so they are ready when the plugin connects. For each one, choose **New Device** in Indigo, set **Type** to **HoneywellEnvisalink (BETA)**, pick the model, and click **Save**.

1. **Honeywell Panel (via Envisalink)** — add exactly one. Choose your **Panel model** and **Envisalink model**. These are for your own reference and do not change how the plugin works.
2. **Honeywell Partition** — add one for each partition you use. Set **Partition number (1-8)**, which is 1 in most homes.
3. **Honeywell Zone** — add one for each zone you want to see. Type the zone's number into **Zone number (1-250)**. It starts at 0, and the device will not save until you type a number from 1 to 250. **Zone type** is for your own reference.

## 3. Connect to the Envisalink

Open **Plugins → HoneywellEnvisalink (BETA) → Configure**.

1. Type the Envisalink's network address into **Envisalink IP address or hostname**.
2. Leave **TCP port** at 4025 unless you know your Envisalink uses another.
3. Type the Envisalink's password into **EVL password**.
4. Leave **Test mode (SAFE)** ticked.
5. Click **Save**.

The plugin connects straight away, and the Event Log shows **EVL login OK**. Every setting is explained on the [Settings](settings.md) page.

## 4. Check it works

- The panel device's **Connected** state is true.
- Each partition device shows its state, such as **Ready**, and its **Keypad display** state holds the same text as your keypad's screen.
- Open a door or walk past a motion sensor on the alarm, and its zone device shows **Open**. Motion shows almost at once. A door closing can take up to 30 seconds to show, for the reason given on [How it works](how-it-works.md).
- Arm the panel from a real keypad and disarm it again. The partition device follows each step.

If nothing appears, the [When something goes wrong](troubleshooting.md) page goes through the usual causes.

## 5. When you are happy it reads the panel correctly

Read [Safety and test mode](safety.md), then turn test mode off and try a single **Arm — Stay** and **Disarm** while you stand at the keypad and watch it.
