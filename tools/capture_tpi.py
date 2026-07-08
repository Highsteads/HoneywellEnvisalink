#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    capture_tpi.py
# Description: SAFE, READ-ONLY Envisalink Honeywell TPI capture tool. Connects to
#              your Envisalink, listens to what your panel sends, decodes it, and
#              writes a shareable file for the plugin author to debug with.
#              (The decode/redaction/bundle logic is shared with the plugin's own
#              "Capture protocol data" menu item via tpi_capture.py.)
# Author:      Highsteads / CliveS & Claude Opus 4.8
# Date:        07-07-2026
# Version:     1.2
#
# ── WHAT THIS DOES ───────────────────────────────────────────────────────────
#   * Logs in to your Envisalink and LISTENS. It does not arm, disarm, or bypass
#     anything — you perform any arming/disarming yourself on your keypad, and the
#     tool simply records what the panel reports back.
#   * The only bytes it ever sends are the (validated) login password and two
#     read-only queries. There is NO code path that sends a keystroke command, so
#     it physically cannot change your panel.
#   * The output JSON has NO password in it. Alarm codes never travel inbound, and
#     any code-like digits you type into a note are masked.
#
#   TIP: the plugin now also has a "Capture protocol data" menu item that does the
#   same thing without the terminal — use that if you'd rather not run this.
#
# ── HOW TO USE ───────────────────────────────────────────────────────────────
#   Guided walk-through (recommended):  python3 capture_tpi.py --host <ip> --guided
#   Passive listen for 3 minutes:       python3 capture_tpi.py --host <ip> --duration 180
#   It prompts for your Envisalink password (not echoed, not stored). Python 3 only.

import argparse
import getpass
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PLUGIN_SRC = Path(__file__).resolve().parent.parent / "HoneywellEnvisalink.indigoPlugin" / "Contents" / "Server Plugin"
sys.path.insert(0, str(PLUGIN_SRC))

from honeywell_protocol import encode_keepalive, encode_dump_zone_timers   # noqa: E402
from tpi_capture import (      # noqa: E402  (shared decode/redaction/bundle logic)
    decode_line, mask_codes, sensitive_records, make_bundle, write_bundle,
)

CONNECT_TIMEOUT_S = 5
RECV_TICK_S = 1.0
LOGIN_WAIT_S = 10
KEEPALIVE_INTERVAL_S = 20

# SAFETY ALLOWLIST — the ONLY things this tool may ever put on the wire besides
# the one-off (validated) login password. Both are read-only TPI queries.
_READONLY_COMMANDS = frozenset({encode_keepalive(), encode_dump_zone_timers()})

# Anything in a password that could start a second TPI frame or is non-printable.
_ILLEGAL_PW_CHARS = set("\r\n$^")

# Guided sequence (name, instruction, dwell-seconds). You do the keypad actions.
GUIDED_STEPS = [
    ("baseline",    "Leave the panel completely alone (we capture its resting state).", 15),
    ("zone_open",   "Open ONE door or window that is a monitored zone, and leave it open.", 10),
    ("zone_close",  "Now close that same door/window.", 10),
    ("arm_stay",    "On your keypad, ARM STAY. Let it finish arming, then DISARM.", 35),
    ("arm_away",    "On your keypad, ARM AWAY. Let the EXIT delay run right through until it is fully armed.", 50),
    ("entry_delay", "While it is ARMED AWAY, open your ENTRY door and let the entry countdown run about 10 seconds — then DISARM before the siren.", 30),
    ("arm_instant", "On your keypad, ARM INSTANT (usually your code then 7). Let it arm, then DISARM.", 35),
    ("arm_max",     "On your keypad, ARM MAX (usually your code then 4). Let it arm, then DISARM.", 35),
    ("final",       "Leave the panel disarmed and resting.", 10),
]


def password_is_safe(pw):
    """
    The password is the ONLY user value that reaches the wire. It must be a plain
    printable credential with no character that could start a second TPI frame —
    otherwise a value like 'pw\\r\\n^03,1,1$' would smuggle a keypress command past
    the read-only allowlist. Reject anything unsafe.
    """
    return bool(pw) and pw.isprintable() and not any(c in pw for c in _ILLEGAL_PW_CHARS)


class Capture:
    def __init__(self, host, port, password, keepalive, dump_zones):
        self.host = host
        self.port = port
        self.password = password
        self.keepalive = keepalive
        self.dump_zones = dump_zones
        self.records = []
        self.counts = {}
        self.unparsed = 0
        self.evl_banner = None
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.sock = None
        self.start_ts = time.time()
        self.logged_in = threading.Event()

    def _send_readonly(self, cmd):
        if cmd not in _READONLY_COMMANDS:
            raise RuntimeError("SAFETY: refusing to send a non-read-only command")
        self.sock.sendall(cmd.encode("ascii", "replace"))

    def _elapsed(self):
        return round(time.time() - self.start_ts, 3)

    def add_marker(self, note):
        note = mask_codes(note)                       # never record a typed code
        with self.lock:
            self.records.append({"t": self._elapsed(), "ts": datetime.now().isoformat(timespec="milliseconds"),
                                 "kind": "marker", "note": note})
        print(f"    -- marker: {note}")

    def _record_frame(self, line):
        dec = decode_line(line)
        with self.lock:
            self.records.append({"t": self._elapsed(),
                                 "ts": datetime.now().isoformat(timespec="milliseconds"),
                                 "kind": "frame", **dec})
            code = dec.get("code", "unparsed")
            self.counts[code] = self.counts.get(code, 0) + 1
            if not dec.get("parsed", False):
                self.unparsed += 1
        self._print_live(dec)

    def _print_live(self, dec):
        t = dec.get("type")
        if t == "keypad_update":
            print(f"    [{dec['code']}] P{dec['partition']} {dec['derived_state']:<16} "
                  f"{dec['flags_hex']} {','.join(dec['flags'])}  \"{dec['display']}\"")
        elif t == "zone_bitmap":
            print(f"    [{dec['code']}] zones open: {dec['open_zones']}")
        elif t == "partition_state":
            print(f"    [{dec['code']}] partitions: {dec['partitions']}")
        elif t == "command_response":
            flag = "   <-- EVL STRAIN" if dec.get("strain") else ""
            print(f"    [{dec['code']}] response: {dec.get('response','')}{flag}")
        elif t == "cid_event":
            print(f"    [{dec['code']}] CID {dec['cid']}")
        elif t == "zone_timer_dump":
            print(f"    [{dec['code']}] zone timers (non-zero): {dec['zone_timers']}")
        elif t == "recognised_but_unparsed":
            print(f"    [{dec['code']}] recognised but decode failed: {dec.get('note','')}")
        elif not dec.get("parsed", False):
            print(f"    [UNPARSED] {dec['raw']!r}  ({dec.get('note', '')})")
        else:
            print(f"    [{dec.get('code', '?')}] {dec.get('type', '')} {dec.get('payload', '')}")

    def connect_and_login(self):
        print(f"Connecting to {self.host}:{self.port} ...")
        self.sock = socket.create_connection((self.host, self.port), timeout=CONNECT_TIMEOUT_S)
        self.sock.settimeout(RECV_TICK_S)
        buf = b""
        deadline = time.time() + LOGIN_WAIT_S
        while time.time() < deadline and not self.logged_in.is_set():
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                raise RuntimeError("connection closed during login")
            buf += chunk
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                text = line.decode("ascii", "replace")
                if text == "Login:":
                    self.sock.sendall((self.password + "\r\n").encode("ascii", "replace"))
                    self.add_marker("login: password sent (redacted)")
                elif text == "OK":
                    self.logged_in.set()
                    print("Login OK — connection live.\n")
                    return True
                elif text in ("FAILED", "Timed Out!"):
                    raise RuntimeError(f"login {text} — check the Envisalink password")
                elif text.strip():
                    self.evl_banner = mask_codes(text.strip())
                    self.add_marker(f"pre-login banner: {self.evl_banner}")
        raise RuntimeError("login did not complete")

    def recv_loop(self):
        buf = b""
        last_keepalive = time.time()
        while not self.stop.is_set():
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                if self.keepalive and time.time() - last_keepalive > KEEPALIVE_INTERVAL_S:
                    try:
                        self._send_readonly(encode_keepalive())
                    except OSError:
                        self.stop.set()
                        break
                    last_keepalive = time.time()
                continue
            except OSError:
                self.stop.set()
                break
            if not chunk:
                print("    (connection closed by the Envisalink — ending capture)")
                self.stop.set()
                break
            buf += chunk
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                text = line.decode("ascii", "replace").rstrip("\r\n")
                if text:
                    self._record_frame(text)

    def _maybe_dump_zones(self):
        if self.dump_zones:
            try:
                self._send_readonly(encode_dump_zone_timers())
                self.add_marker("sent read-only zone-timer dump request")
            except OSError:
                pass

    def run_guided(self):
        threading.Thread(target=self.recv_loop, daemon=True).start()
        self._maybe_dump_zones()
        print("=" * 72)
        print("GUIDED CAPTURE — I'll ask you to do things on your keypad one step at")
        print("a time. Nothing is ever sent to your panel; you do the arming yourself.")
        print("=" * 72)
        for name, instruction, dwell in GUIDED_STEPS:
            if self.stop.is_set():
                print("\nConnection lost — ending the walk-through early.")
                break
            try:
                input(f"\n>>> NEXT: {instruction}\n    Press ENTER when you're ready to start this step (Ctrl-C to finish early) ...")
            except (EOFError, KeyboardInterrupt):
                print("\nFinishing early.")
                break
            self.add_marker(f"STEP START: {name} - {instruction}")
            print(f"    Capturing for {dwell}s — do it now ...")
            if self.stop.wait(dwell):
                print("    Connection lost mid-step — ending.")
                break
            self.add_marker(f"STEP END: {name}")
        self.stop.set()

    def run_passive(self, duration):
        threading.Thread(target=self.recv_loop, daemon=True).start()
        self._maybe_dump_zones()
        print("=" * 72)
        print(f"PASSIVE CAPTURE for {duration}s. Go and use your panel/keypad however")
        print("you like — open doors, arm, disarm. Type a note + ENTER any time to")
        print("label the moment (e.g. 'armed stay now'). DO NOT type your alarm code.")
        print("Ctrl-C to finish early.")
        print("=" * 72)
        end = time.time() + duration

        def note_reader():
            while not self.stop.is_set():
                try:
                    note = input()
                except (EOFError, KeyboardInterrupt):
                    return
                if note.strip():
                    self.add_marker(f"NOTE: {note.strip()}")

        threading.Thread(target=note_reader, daemon=True).start()
        try:
            while time.time() < end and not self.stop.is_set():
                self.stop.wait(0.5)
        except KeyboardInterrupt:
            pass
        self.stop.set()

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass

    def bundle(self):
        with self.lock:
            return make_bundle(self.records, self.counts, self.unparsed, self._elapsed(),
                               self.port, evl_banner=self.evl_banner, source="cli")


def main():
    ap = argparse.ArgumentParser(
        description="Safe, read-only Envisalink Honeywell TPI capture for debugging.")
    ap.add_argument("--host", required=True, help="Envisalink IP address or hostname")
    ap.add_argument("--port", type=int, default=4025, help="TCP port (default 4025)")
    ap.add_argument("--password", default=None, help="EVL password (prompted if omitted)")
    ap.add_argument("--guided", action="store_true", help="guided step-by-step walk-through")
    ap.add_argument("--duration", type=int, default=180,
                    help="passive capture length in seconds (default 180; ignored with --guided)")
    ap.add_argument("--no-keepalive", action="store_true",
                    help="do NOT send the read-only KeepAlive poll (default: send it)")
    ap.add_argument("--no-dump-zones", action="store_true",
                    help="do NOT send the read-only zone-timer-dump request (default: send it)")
    ap.add_argument("--out", default=None, help="output file (default /tmp/honeywell_tpi_capture_<ts>.json)")
    args = ap.parse_args()

    password = args.password or getpass.getpass("Envisalink password (not shown, not stored): ")
    if not password:
        print("No password given — aborting.")
        return 2
    if not password_is_safe(password):
        print("Password contains illegal characters (newline / $ / ^ / control) — aborting for safety.")
        return 2

    out_path = args.out or f"/tmp/honeywell_tpi_capture_{int(time.time())}.json"
    cap = Capture(args.host, args.port, password, not args.no_keepalive, not args.no_dump_zones)
    try:
        cap.connect_and_login()
    except KeyboardInterrupt:
        print("\nAborted before capture started — nothing to save.")
        return 130
    except Exception as e:
        print(f"Could not connect / log in: {e}")
        return 1

    try:
        if args.guided:
            cap.run_guided()
        else:
            cap.run_passive(args.duration)
    except KeyboardInterrupt:
        cap.stop.set()
    finally:
        cap.stop.set()
        cap.close()

    bundle = cap.bundle()
    written = write_bundle(bundle, out_path)
    sensitive = sensitive_records(bundle)
    print("\n" + "=" * 72)
    print(f"Capture written to: {written}")
    print(f"  {bundle['record_count']} records over {bundle['duration_s']}s")
    print(f"  message types seen: {bundle['message_code_counts']}")
    print(f"  lines that did NOT decode (the interesting ones): {bundle['unparsed_count']}")
    if sensitive:
        print(f"  ⚠ REVIEW BEFORE SHARING — {len(sensitive)} record(s) contain a 4-8 digit run that")
        print("    could be an account/phone/serial number. Open the file and check these before posting:")
        for r in sensitive[:8]:
            print(f"      t={r.get('t','?')}  {r.get('note') or r.get('display') or r.get('raw') or r.get('payload') or r.get('evl_banner')}")
    else:
        print("  No password and no code-like digit runs detected — safe to share on the forum.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
