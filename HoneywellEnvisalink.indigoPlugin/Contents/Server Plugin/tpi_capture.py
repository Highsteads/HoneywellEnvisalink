#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    tpi_capture.py
# Description: Shared, pure (no I/O) decode + redaction + bundle helpers for
#              capturing Envisalink Honeywell TPI traffic. Used BOTH by the
#              plugin's "Capture protocol data" menu item and by the standalone
#              tools/capture_tpi.py, so the two can never drift.
# Author:      Highsteads / CliveS & Claude Opus 4.8
# Date:        07-07-2026
# Version:     0.5.1-beta

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from honeywell_protocol import (
    parse_frame, parse_keypad_update, parse_zone_state, parse_partition_state,
    parse_realtime_cid, derive_partition_state, flag_names, decode_zone_timer_dump,
    BEEP_CODES, TPI_ZONE_TIMER_DUMP, TPI_RESPONSE_CODES, TPI_STRAIN_CODES, ProtocolError,
)

CAPTURE_VERSION = "1.3"

# Mask runs of 4-8 digits (a plausible code / account / phone number) in free text.
_CODE_RUN = re.compile(r"\d{4,8}")

# Frame types whose fields are fully structural (state / hex) and therefore safe —
# their long hex payloads must NOT trip the digit-run 'review before sharing' scan.
_DECODED_SAFE_TYPES = {"keypad_update", "zone_bitmap", "partition_state",
                       "cid_event", "zone_timer_dump", "command_response"}

# Step instructions shown to the tester (dialog label in the plugin, guided prompts
# in the CLI tool). Doing all of these once gives a real sample of every state.
CAPTURE_STEPS = [
    "Leave the panel alone for a few seconds (resting state).",
    "Open one door/window zone, then close it again.",
    "Arm STAY, let it arm, then disarm.",
    "Arm AWAY, let the exit-delay run right through until armed, then disarm.",
    "Arm AWAY again, open your entry door, let the entry countdown run ~10s, then disarm before the siren.",
    "Arm INSTANT (code then 7), let it arm, then disarm.",
    "Arm MAX (code then 4), let it arm, then disarm.",
]


def mask_codes(text):
    """Mask any 4-8 digit run (a plausible code / account / phone number) in free text."""
    return _CODE_RUN.sub("####", text)


def mask_keypad_raw(raw):
    """Mask code-like runs in the DISPLAY-TEXT tail of a %00 raw line, leaving the
    structural header (partition, flags, zone, beep) intact."""
    parts = raw.split(",", 5)
    if len(parts) == 6:
        parts[5] = mask_codes(parts[5])
    return ",".join(parts)


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
            out["raw"] = mask_keypad_raw(text)      # keep header, mask display tail
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
        if frame.code.startswith("^"):
            # A ^CC,RR command/keepalive response — decode RR so strain shows up.
            rr = frame.payload.strip()[:2]
            out.update({"type": "command_response", "response_code": rr,
                        "response": TPI_RESPONSE_CODES.get(rr, "unknown"),
                        "strain": rr in TPI_STRAIN_CODES})
            return out
        out.update({"type": "other", "payload": frame.payload})
    except ProtocolError as e:
        out["parsed"] = False                        # recognised frame we still can't decode
        out.update({"type": "recognised_but_unparsed", "note": str(e)})
    return out


def build_state_timeline(records):
    """The sequence of distinct derived partition-states over time — the readable
    view of the arm/disarm progression, works with or without step markers."""
    timeline, last = [], None
    for r in records:
        if r.get("type") == "keypad_update":
            ds = r.get("derived_state")
            if ds != last:
                timeline.append({"t": r.get("t"), "state": ds,
                                 "display": r.get("display", ""), "beep": r.get("beep")})
                last = ds
    return timeline


def sensitive_records(bundle):
    """
    Records that could carry a personal number and were NOT structurally decoded,
    so a 'safe to share' verdict matches the data actually shipped:
      - any human-text field (note / display) with a residual 4-8 digit run;
      - any UN-decoded line (poll/command 'other', recognised-but-unparsed, or a
        truly unparsed line), whose raw/payload could contain anything.
    Cleanly-decoded frames are trusted (display already masked, the rest is
    state/hex), so their hex payloads don't false-positive.
    """
    hits = []
    for r in bundle.get("records", []):
        if _CODE_RUN.search(str(r.get("note", ""))) or _CODE_RUN.search(str(r.get("display", ""))):
            hits.append(r)
            continue
        if r.get("type") not in _DECODED_SAFE_TYPES:
            if _CODE_RUN.search(str(r.get("raw", ""))) or _CODE_RUN.search(str(r.get("payload", ""))):
                hits.append(r)
    if bundle.get("evl_banner") and _CODE_RUN.search(bundle["evl_banner"]):
        hits.append({"evl_banner": bundle["evl_banner"]})
    return hits


def make_bundle(records, counts, unparsed, duration_s, port,
                evl_banner=None, source="menu", captured_at=None):
    """Assemble the shareable bundle dict from the pieces both callers hold."""
    return {
        "capture_version": CAPTURE_VERSION,
        "source": source,
        "captured_at": captured_at or datetime.now().isoformat(timespec="milliseconds"),
        "host": "<redacted>",                        # local topology — not needed to debug
        "port": port,
        "evl_banner": evl_banner,
        "duration_s": duration_s,
        "message_code_counts": dict(sorted(counts.items())),
        "unparsed_count": unparsed,
        "record_count": len(records),
        "state_timeline": build_state_timeline(records),
        "records": list(records),
    }


def write_bundle(bundle, out_path):
    """Write the bundle to disk (0600), falling back to a temp file so a capture is
    never lost. Returns the path actually written."""
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
    except OSError:
        fd, tmp = tempfile.mkstemp(prefix="honeywell_tpi_capture_", suffix=".json")
        os.close(fd)
        return _write(tmp)
