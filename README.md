# Honeywell Envisalink for Indigo

**Connect a Honeywell Vista alarm panel to Indigo through an Envisalink, and see and control it from Indigo.**

**Version:** 0.5.3 | **Author:** CliveS & Claude | **Needs:** Indigo 2022.1 or later, and an Envisalink 3, 4 or 5

**This plugin is a beta.** I do not have a Honeywell panel myself, so it has been tested by an Indigo user on a real Vista 20P with an Envisalink 4, where it reads the panel correctly and has armed and disarmed it from Indigo. It starts in a safe test mode that cannot send commands, so please read [Safety and test mode](https://highsteads.github.io/HoneywellEnvisalink/safety.html) before you turn that off on a panel that protects your home.

**[Read the full guide](https://highsteads.github.io/HoneywellEnvisalink/)** — setting up, arming safely, what everything means, and what to do when something goes wrong.

---

## What it does

This plugin lets [Indigo](https://www.indigodomo.com) talk to a Honeywell Vista alarm panel through an **Envisalink**, the network module from EyezOn that wires into the panel's keypad connections. It talks to the Envisalink directly over your home network.

- **Shows the state of each partition** — Ready, Not Ready, Armed Away, Armed Stay, Armed Instant, Armed Max, Exit Delay, Entry Delay, ALARM and more — along with the text on the keypad's screen.
- **Shows each zone as open or closed,** so a door, window or motion sensor on the alarm can drive anything else in Indigo. A door closing shows within about 30 seconds, and you can make that quicker.
- **Arms, disarms and bypasses** from an Indigo action, schedule, trigger or control page, by pressing the same keys you would press on the keypad.
- **Runs your triggers** when a partition is armed, disarmed or goes into alarm — fire alarms included — and when the connection to the Envisalink drops.
- **Starts in test mode,** which reads the panel but sends nothing, until you choose to let it send commands.
- **Keeps your codes out of the log.** Each key of a user code is masked before anything is written down, and the Envisalink password never appears in the log or in any file the plugin writes.
- **Records what your panel sends** for a few minutes, from the plugin menu, in a file you can share on the forum to help with the beta.

## What it works with

| | |
|---|---|
| **Envisalink** | Envisalink 3, 4 or 5. Tested on an Envisalink 4. |
| **Panel** | Honeywell Vista panels, such as the Vista 15P, 20P, 21iP, 128BP and 250BP. Tested on a Vista 20P. |
| **Tested on real hardware** | Reading every partition and zone state, **Arm — Stay** and **Disarm**. |
| **Not yet tried on real hardware** | **Arm — Away**, **Arm — Instant**, **Arm — Max** and **Bypass zone**, which press keys in the same way. |

## Installing

1. Go to the [Releases page](https://github.com/Highsteads/HoneywellEnvisalink/releases/latest) and download `HoneywellEnvisalink.indigoPlugin.zip`
2. Unzip the downloaded file — you will get `HoneywellEnvisalink.indigoPlugin`
3. Double-click `HoneywellEnvisalink.indigoPlugin` — Indigo will install it automatically

## Setting it up

1. Create a **New Device** of type **HoneywellEnvisalink (BETA)** for each of these: one **Honeywell Panel (via Envisalink)**, one **Honeywell Partition** for each partition (number 1 in most homes), and one **Honeywell Zone** for each zone you want, with its zone number from your panel.
2. Open **Plugins → HoneywellEnvisalink (BETA) → Configure**, type in the Envisalink's network address — the four numbers, such as `192.168.1.50`, that your router's list of devices shows — and its password, which is `user` unless someone has changed it. Leave **Test mode (SAFE)** ticked and click **Save**.
3. Walk round opening doors and use your real keypad, and check the partition and zone devices follow along. Only when you are happy, turn test mode off and try one **Arm — Stay** and **Disarm** while you stand at the keypad.

The [full guide](https://highsteads.github.io/HoneywellEnvisalink/) goes through each step, explains every setting, and covers what to do if something does not work.

## What's new

**v0.5.3** — The plugin carries a note of where its code lives on GitHub, the same way other Indigo plugins do. Nothing else changed.

**v0.5.2** — A fire alarm shows as ALARM and runs the **Alarm triggered** event, which it did not before.
- **Armed Max** is recognised when the keypad shows MAX as well as MAXIMUM.
- One failing trigger no longer stops the others, or loses the event.
- The version number lost its "-beta" ending, so the Indigo Plugin Store will accept it.

**v0.5.1-beta** — If the Envisalink says it cannot keep up, the Event Log has a warning suggesting you refresh the zones less often.

Every version is listed in the [version history](https://highsteads.github.io/HoneywellEnvisalink/changelog.html).

## Authors & licence

Vibed into existence by **CliveS**, who knew what he wanted, argued until he got it, and tested it on a real house. Typed at inhuman speed by **Claude** (Anthropic), who mostly did as it was told.

© 2026 CliveS · [MIT licence](LICENSE) — copy it, fork it, bend it, break it, fix it, ship it. If it breaks, you get to keep both pieces.
