---
title: Helping with the beta
nav_order: 10
---

# Helping with the beta

I do not have a Honeywell panel, so the plugin was fixed and proven on real hardware using recordings of what a tester's Vista 20P sends. If you have a different Vista panel, or an Envisalink 3 or 5, a recording from yours is the most useful thing you can give me. Thank you to everyone who has already sent one.

## Recording what your panel sends

**Plugins → HoneywellEnvisalink (BETA) → Capture protocol data (for the author)...** records everything your panel sends for a few minutes while you use your real keypad. It only listens. It never arms or disarms anything, and it needs no password, because the plugin is already logged in.

1. Make sure the plugin is connected — the panel device's **Connected** state is true.
2. Choose the menu item, pick how long to record for — 2, 3, 5 or 8 minutes — and start it.
3. The Event Log lists the steps. Do them on your keypad while it records:
   1. Leave the panel alone for a few seconds.
   2. Open one door or window zone, then close it again.
   3. Arm Stay, let it arm, then disarm.
   4. Arm Away, let the exit delay run right through until it is armed, then disarm.
   5. Arm Away again, open your entry door, let the entry countdown run about 10 seconds, then disarm before the siren.
   6. Arm Instant (your code, then 7), let it arm, then disarm.
   7. Arm Max (your code, then 4), let it arm, then disarm.
4. When the time is up, the Event Log gives the name of the file it wrote in the Mac's `/tmp` folder, named like `honeywell_tpi_capture_1790000000.json`. To find it, choose **Go → Go to Folder** in the Finder and type `/tmp`.

The Event Log then says one of two things:

- **"Safe to share"** — the file holds no password and nothing that looks like a code. Attach it to a reply on the forum.
- **"REVIEW BEFORE SHARING"** — some lines hold a run of 4 to 8 digits, which could be a code. Open the file in a text editor and check those lines before you post it.

The file leaves out the Envisalink's address, and any run of 4 to 8 digits in the keypad text is masked. Only one recording can run at a time.

## From the Terminal instead

The [GitHub repository](https://github.com/Highsteads/HoneywellEnvisalink) has the same recorder as a script in its `tools` folder, for anyone who would rather use the Terminal. It walks you through the same steps one at a time, asks for the Envisalink's password without showing it, and can only listen:

```bash
python3 tools/capture_tpi.py --host <your-envisalink-address> --guided
```

## Reporting a problem

Post on the [Indigo forum](https://forums.indigodomo.com), or send me a message there (I am **CliveS**), with:

- your panel model and your Envisalink model
- what you did and what happened
- the file from **Plugins → HoneywellEnvisalink (BETA) → Save diagnostic bundle (for sharing)**, which holds no password, no codes and no address

You can also [raise an issue on GitHub](https://github.com/Highsteads/HoneywellEnvisalink/issues).
