#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    capture_tpi.py
# Description: SAFE, READ-ONLY Envisalink Honeywell TPI capture tool. Connects to
#              your Envisalink, listens to what your panel sends, decodes it, and
#              writes a shareable file for the plugin author to debug with.
# Author:      Highsteads / CliveS & Claude Opus 4.8
# Date:        07-07-2026
# Version:     1.1
#
# ── WHAT THIS DOES ───────────────────────────────────────────────────────────
#   * Logs in to your Envisalink and LISTENS. It does not arm, disarm, or bypass
#     anything — you perform any arming/disarming yourself on your keypad, and the
#     tool simply records what the panel reports back.
#   * The only bytes it ever sends are the login password and two read-only
#     queries (a KeepAlive poll and a zone-timer-dump request). There is NO code
#     path that sends a keystroke command, and the password is validated so it
#     cannot smuggle one in — so the tool physically cannot change your panel.
#   * It writes a JSON file with NO password in it. Alarm codes never travel
#     inbound, so the panel's messages don't contain your code — but if you type a
#     code into a note, it is masked. Review any NOTE lines before sharing.
#
# ── HOW TO USE ───────────────────────────────────────────────────────────────
#   Simplest — a guided walk-through (recommended):
#       python3 capture_tpi.py --host 10.0.1.110 --guided
#   Just listen passively for 3 minutes:
#       python3 capture_tpi.py --host 10.0.1.110 --duration 180
#   It will prompt for your Envisalink password (not echoed, not stored).
#
#   Needs only Python 3 — no extra packages. Run it on any machine that can reach
#   your Envisalink (the same one Indigo runs on is fine).

import argparse
import getpass
import json
import os
import re
import socket
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

PLUGIN_SRC = Path(__file__).resolve().parent.parent / "HoneywellEnvisalink.indigoPlugin" / "Contents" / "Server Plugin"
sys.path.insert(0, str(PLUGIN_SRC))

from honeywell_protocol import (      # noqa: E402
    parse_frame, parse_keypad_update, parse_zone_state, parse_partition_state,
    parse_realtime_cid, derive_partition_state, flag_names, decode_zone_timer_dump,
    BEEP_CODES, encode_keepalive, encode_dump_zone_timers, ProtocolError,
    TPI_ZONE_TIMER_DUMP,
)

CAPTURE_VERSION = "1.1"
CONNECT_TIMEOUT_S = 5
RECV_TICK_S = 1.0
LOGIN_WAIT_S = 10
KEEPALIVE_INTERVAL_S = 20

# SAFETY ALLOWLIST — the ONLY things this tool may ever put on the wire besides
# the one-off (validated) login password. Both are read-only TPI queries.
_READONLY_COMMANDS = frozenset({encode_keepalive(), encode_dump_zone_timers()})

# Anything in a password that could start a second TPI frame or is non-printable.
_ILLEGAL_PW_CHARS = set("\r\n$^")

# Mask runs of 4-8 digits (a plausible alarm code) in free text a user types.
_CODE_RUN = re.compile(r"\d{4,8}")

# A guided sequence that exercises EVERY state the parser claims to handle, so the
# developer gets real samples of ready / zone open+close / exit-delay / armed-away
# / entry-delay / armed-stay / armed-instant / armed-max / disarm. You do all the
# keypad actions yourself — the tool only listens.
GUIDED_STEPS = [
    ("baseline",     "Leave the panel completely alone (we capture its resting state).", 15),
    ("zone_open",    "Open ONE door or window that is a monitored zone, and leave it open.", 10),
    ("zone_close",   "Now close that same door/window.", 10),
    ("arm_stay",     "On your keypad, ARM STAY. Let it finish arming, then DISARM.", 35),
    ("arm_away",     "On your keypad, ARM AWAY. Let the EXIT delay run right through until it is fully armed.", 50),
    ("entry_delay",  "While it is ARMED AWAY, open your ENTRY door and let the entry countdown run for about 10 seconds — then DISARM before the siren sounds.", 30),
    ("arm_instant",  "On your keypad, ARM INSTANT (usually your code then 7). Let it arm, then DISARM.", 35),
    ("arm_max",      "On your keypad, ARM MAX (usually your code then 4). Let it arm, then DISARM.", 35),
    ("final",        "Leave the panel disarmed and resting.", 10),
]


def mask_codes(text):
    """Mask any 4-8 digit run (a plausible code / account / phone number) in free text."""
    return _CODE_RUN.sub("####", text)


def _mask_keypad_raw(raw):
    """Mask code-like runs in the DISPLAY-TEXT tail of a %00 raw line, leaving the
    structural header (partition, flags, zone, beep) intact."""
    parts = raw.split(",", 5)
    if len(parts) == 6:
        parts[5] = mask_codes(parts[5])
    return ",".join(parts)


def password_is_safe(pw):
    """
    The password is the ONLY user value that reaches the wire. It must be a plain
    printable credential with no character that could start a second TPI frame —
    otherwise a value like 'pw\\r\\n^03,1,1$' would smuggle a keypress command past
    the read-only allowlist. Reject anything unsafe.
    """
    return bool(pw) and pw.isprintable() and not any(c in pw for c in _ILLEGAL_PW_CHARS)


def decode_line(text):
    """Best-effort human-readable decode of one raw TPI line."""
    out = {"raw": text}
    try:
        frame = parse_frame(text)
    except ProtocolError as e:
        out["parsed"] = False
        out["note"] = f"did not parse: {e}"
        return out
    out["code"] = frame.code
    out["parsed"] = True
    try:
        ku = parse_keypad_update(frame)
        if ku:
            out.update({
                "type": "keypad_update", "partition": ku.partition,
                "flags_hex": f"0x{ku.led_bitmap:04X}", "flags": flag_names(ku.led_bitmap),
                "derived_state": derive_partition_state(ku).value,
                "display": mask_codes(ku.display_text.strip()),
                "beep": BEEP_CODES.get(ku.beep_code, ku.beep_code),
                "zone_field": ku.zone,
            })
            out["raw"] = _mask_keypad_raw(text)   # keep header, mask display tail
            return out
        zb = parse_zone_state(frame)
        if zb:
            out.update({"type": "zone_bitmap", "open_zones": sorted(zb.open_zones)})
            return out
        changes = parse_partition_state(frame)
        if changes:
            out.update({"type": "partition_state",
                        "partitions": {c.partition: c.state.value for c in changes}})
            return out
        cid = parse_realtime_cid(frame)
        if cid:
            out.update({"type": "cid_event", "cid": {
                "qualifier": cid.qualifier, "event": cid.event_code,
                "partition": cid.partition, "zone_or_user": cid.zone_or_user}})
            return out
        if frame.code == TPI_ZONE_TIMER_DUMP:
            out.update({"type": "zone_timer_dump", "payload": frame.payload,
                        "zone_timers": decode_zone_timer_dump(frame.payload)})
            return out
        out.update({"type": "other", "payload": frame.payload})
    except ProtocolError as e:
        out["parsed"] = False               # a recognised frame we still can't decode
        out.update({"type": "recognised_but_unparsed", "note": str(e)})
    return out


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

    # ── safety-gated send ────────────────────────────────────────────────────
    def _send_readonly(self, cmd):
        if cmd not in _READONLY_COMMANDS:
            raise RuntimeError("SAFETY: refusing to send a non-read-only command")
        self.sock.sendall(cmd.encode("ascii", "replace"))

    def _elapsed(self):
        return round(time.time() - self.start_ts, 3)

    def _now(self):
        return datetime.now().isoformat(timespec="milliseconds")

    def add_marker(self, note):
        note = mask_codes(note)                       # never record a typed code
        with self.lock:
            self.records.append({"t": self._elapsed(), "ts": self._now(),
                                 "kind": "marker", "note": note})
        print(f"    -- marker: {note}")

    def _record_frame(self, line):
        dec = decode_line(line)
        with self.lock:
            self.records.append({"t": self._elapsed(), "ts": self._now(), "kind": "frame", **dec})
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

    # ── connection ───────────────────────────────────────────────────────────
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
                    # Password is validated (see build_capture) so it cannot carry
                    # framing chars — this is the only user value that reaches the
                    # wire, and it must never be able to become a command.
                    self.sock.sendall((self.password + "\r\n").encode("ascii", "replace"))
                    self.add_marker("login: password sent (redacted)")
                elif text == "OK":
                    self.logged_in.set()
                    print("Login OK — connection live.\n")
                    return True
                elif text in ("FAILED", "Timed Out!"):
                    raise RuntimeError(f"login {text} — check the Envisalink password")
                elif text.strip():
                    # A pre-login welcome/firmware banner — capture it, it names the EVL.
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

    # ── run modes ────────────────────────────────────────────────────────────
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

    # ── output ───────────────────────────────────────────────────────────────
    def _build_transitions(self):
        transitions, cur = [], None
        for r in self.records:
            note = r.get("note", "")
            if r["kind"] == "marker" and note.startswith("STEP START:"):
                cur = {"step": note, "t_start": r["t"], "states": []}
                transitions.append(cur)
            elif r["kind"] == "marker" and note.startswith("STEP END:"):
                cur = None
            elif cur is not None and r.get("type") == "keypad_update":
                ds = r.get("derived_state")
                if not cur["states"] or cur["states"][-1]["state"] != ds:
                    cur["states"].append({"t": r["t"], "state": ds,
                                          "display": r.get("display", ""), "beep": r.get("beep")})
        return transitions

    def build_bundle(self):
        with self.lock:
            return {
                "capture_version": CAPTURE_VERSION,
                "captured_at": datetime.now().isoformat(timespec="milliseconds"),
                "host": "<redacted>",                 # local topology — not needed to debug
                "port": self.port,
                "evl_banner": self.evl_banner,
                "duration_s": self._elapsed(),
                "message_code_counts": dict(sorted(self.counts.items())),
                "unparsed_count": self.unparsed,
                "record_count": len(self.records),
                "state_transitions": self._build_transitions(),
                "records": list(self.records),
            }

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass


def write_bundle(bundle, out_path):
    """Write the bundle, falling back to a temp file so a capture is never lost."""
    def _write(path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, default=str)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path
    try:
        return _write(out_path)
    except OSError as e:
        print(f"    Could not write {out_path} ({e}) — falling back to a temp file ...")
        fd, tmp = tempfile.mkstemp(prefix="honeywell_tpi_capture_", suffix=".json")
        os.close(fd)
        return _write(tmp)


# Frame types whose fields are fully structural (state / hex) and therefore safe —
# their long hex payloads must NOT trip the digit-run scan.
_DECODED_SAFE_TYPES = {"keypad_update", "zone_bitmap", "partition_state",
                       "cid_event", "zone_timer_dump"}


def _sensitive_records(bundle):
    """
    Return records that could carry a personal number and were NOT structurally
    decoded, so the 'safe to share' verdict matches the data actually shipped:
      - any human-text field (note / display) with a residual 4-8 digit run;
      - any UN-decoded line (a poll/command 'other', a recognised-but-unparsed
        frame, or a truly unparsed line), whose raw/payload could contain anything.
    Cleanly-decoded frames are trusted (their display is already masked, the rest
    is state/hex), so their hex payloads don't false-positive.
    """
    hits = []
    for r in bundle["records"]:
        if _CODE_RUN.search(str(r.get("note", ""))) or _CODE_RUN.search(str(r.get("display", ""))):
            hits.append(r)
            continue
        if r.get("type") not in _DECODED_SAFE_TYPES:
            if _CODE_RUN.search(str(r.get("raw", ""))) or _CODE_RUN.search(str(r.get("payload", ""))):
                hits.append(r)
    if bundle.get("evl_banner") and _CODE_RUN.search(bundle["evl_banner"]):
        hits.append({"evl_banner": bundle["evl_banner"]})
    return hits


def build_capture(args, password):
    return Capture(args.host, args.port, password, args.keepalive, args.dump_zones)


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
    args.keepalive = not args.no_keepalive
    args.dump_zones = not args.no_dump_zones

    password = args.password or getpass.getpass("Envisalink password (not shown, not stored): ")
    if not password:
        print("No password given — aborting.")
        return 2
    # SAFETY: the password is the only user value that reaches the wire.
    if not password_is_safe(password):
        print("Password contains illegal characters (newline / $ / ^ / control) — aborting for safety.")
        return 2

    out_path = args.out or f"/tmp/honeywell_tpi_capture_{int(time.time())}.json"
    cap = build_capture(args, password)
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

    bundle = cap.build_bundle()
    written = write_bundle(bundle, out_path)
    sensitive = _sensitive_records(bundle)
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
        print("  (The password is never recorded; alarm codes never travel inbound.)")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
