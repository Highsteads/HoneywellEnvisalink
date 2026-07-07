#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_capture.py
# Description: Pytest suite for tools/capture_tpi.py — the safe read-only capture
#              tool. Verifies decoding, redaction, the read-only safety gate, the
#              CRLF-injection guard, and the write fallback.
# Author:      Highsteads / CliveS & Claude Opus 4.8

import json
import sys
import pytest
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "HoneywellEnvisalink.indigoPlugin" / "Contents" / "Server Plugin"))

import capture_tpi
from capture_tpi import (
    decode_line, Capture, _READONLY_COMMANDS, mask_codes, password_is_safe,
    write_bundle, _sensitive_records,
)
from honeywell_protocol import encode_keepalive, encode_dump_zone_timers, encode_disarm, encode_keypress


REAL_KEYPAD = "%00,01,1C08,08,00,****DISARMED****  Ready to Arm  $"


def new_capture(password="pw"):
    return Capture("192.168.1.50", 4025, password, keepalive=False, dump_zones=False)


# ────────────────────────────────────────────────────────────────────────────
# Decoding
# ────────────────────────────────────────────────────────────────────────────

class TestDecode:
    def test_real_keypad_frame(self):
        d = decode_line(REAL_KEYPAD)
        assert d["parsed"] and d["type"] == "keypad_update"
        assert d["partition"] == 1 and d["flags_hex"] == "0x1C08"
        assert "ready" in d["flags"] and "ac_present" in d["flags"]
        assert d["derived_state"] == "ready" and "DISARMED" in d["display"]

    def test_unknown_flag_bits_surface(self):
        assert any(f.startswith("unknown(") for f in decode_line(REAL_KEYPAD)["flags"])

    def test_command_response_is_other(self):
        d = decode_line("^FF,05$")
        assert d["parsed"] and d["type"] == "other"

    def test_partition_state(self):
        d = decode_line("%02,0500000000000000$")
        assert d["type"] == "partition_state" and d["partitions"] == {1: "armed_away"}

    def test_zone_bitmap(self):
        d = decode_line("%01,0100000000000000$")
        assert d["type"] == "zone_bitmap" and 1 in d["open_zones"]

    def test_cid(self):
        d = decode_line("%03,113001005$")
        assert d["type"] == "cid_event" and d["cid"]["event"] == 130

    def test_zone_timer_dump_decoded(self):
        # zone 1 word 0100 -> 0x0001, zone 2 word 0500 -> 0x0005
        d = decode_line("%FF,01000500" + "0" * 120 + "$")
        assert d["type"] == "zone_timer_dump"
        assert d["zone_timers"] == {1: 1, 2: 5}

    def test_unparseable_line_flagged(self):
        d = decode_line("total garbage no dollar")
        assert d["parsed"] is False and "did not parse" in d["note"]

    def test_recognised_but_unparsed_counts_as_unparsed(self):
        # A framed %00 with a non-hex flags field: recognised, but decode fails.
        d = decode_line("%00,01,ZZZZ,00,00,Ready$")
        assert d["type"] == "recognised_but_unparsed"
        assert d["parsed"] is False       # so it lands in unparsed_count


# ────────────────────────────────────────────────────────────────────────────
# SAFETY — read-only gate + CRLF-injection guard
# ────────────────────────────────────────────────────────────────────────────

class TestReadOnlySafety:
    def test_allowlist_is_only_keepalive_and_dump(self):
        assert _READONLY_COMMANDS == frozenset({encode_keepalive(), encode_dump_zone_timers()})

    def test_no_keypress_in_allowlist(self):
        assert encode_keypress(1, "1") not in _READONLY_COMMANDS
        for cmd in encode_disarm("1234", 1):
            assert cmd not in _READONLY_COMMANDS

    def test_send_readonly_rejects_keypress(self):
        cap = new_capture()
        with pytest.raises(RuntimeError):
            cap._send_readonly(encode_keypress(1, "5"))
        with pytest.raises(RuntimeError):
            cap._send_readonly("^03,1,1$\r\n")

    def test_send_readonly_accepts_allowlisted(self):
        cap = new_capture()
        sent = []
        cap.sock = type("S", (), {"sendall": lambda _self, b: sent.append(b)})()
        cap._send_readonly(encode_keepalive())
        cap._send_readonly(encode_dump_zone_timers())
        assert sent == [b"^00,$\r\n", b"^02,$\r\n"]

    def test_source_never_constructs_or_sends_a_keypress(self):
        src = Path(capture_tpi.__file__).read_text(encoding="utf-8")
        for forbidden in ("encode_keypress", "encode_keystroke", "encode_disarm",
                          "encode_arm", "encode_bypass", "send_keypresses"):
            assert forbidden not in src, f"tool references {forbidden}"
        assert src.count("sendall(") <= 2

    def test_password_crlf_injection_rejected(self):
        # The exact attack the adversarial review found.
        assert password_is_safe("mypass\r\n^03,1,1$") is False
        assert password_is_safe("has$dollar") is False
        assert password_is_safe("has^caret") is False
        assert password_is_safe("has\nnewline") is False
        assert password_is_safe("") is False

    def test_password_normal_accepted(self):
        assert password_is_safe("user") is True
        assert password_is_safe("S3cret-Pass_1") is True


# ────────────────────────────────────────────────────────────────────────────
# Redaction — codes in notes, conditional "safe to share"
# ────────────────────────────────────────────────────────────────────────────

class TestRedaction:
    def test_mask_codes(self):
        assert mask_codes("disarmed with 4471") == "disarmed with ####"
        assert mask_codes("used code 123456 today") == "used code #### today"

    def test_short_numbers_not_masked(self):
        # zone numbers, partition numbers etc. (1-3 digits) stay legible
        assert mask_codes("opened zone 01") == "opened zone 01"

    def test_add_marker_masks_a_typed_code(self):
        cap = new_capture()
        cap.add_marker("NOTE: I disarmed using 4471")
        rec = [r for r in cap.records if r["kind"] == "marker"][-1]
        assert "4471" not in rec["note"]
        assert "####" in rec["note"]

    def test_display_code_is_masked(self):
        # A panel line that (unusually) echoes a code in the display must be masked.
        d = decode_line("%00,01,1008,00,00,ENTER CODE 4471$")
        assert "4471" not in d["display"]
        assert "4471" not in d["raw"]        # the raw display tail is masked too
        assert d["raw"].startswith("%00,01,1008,00,00,")   # header preserved

    def test_verdict_flags_undecoded_line_with_digit_run(self):
        cap = new_capture()
        cap.records.append({"kind": "frame", "type": "other", "parsed": True,
                            "raw": "^ZZ,ACCT 4471$", "payload": "ACCT 4471"})
        assert _sensitive_records(cap.build_bundle())

    def test_verdict_ignores_hex_payload_of_decoded_frames(self):
        # A %FF zone-timer dump / %02 partition frame is full of hex digit runs but
        # is structurally safe — it must NOT trip the 'review before sharing' verdict.
        cap = new_capture()
        cap._record_frame("%FF," + "0100050000000000" * 8 + "$")
        cap._record_frame("%02,0500000000000000$")
        assert _sensitive_records(cap.build_bundle()) == []

    def test_verdict_flags_residual_note_code(self):
        cap = new_capture()
        cap.records.append({"kind": "marker", "note": "code is 9999"})   # injected unmasked
        assert _sensitive_records(cap.build_bundle())

    def test_recorded_frames_never_contain_password(self):
        # The password never arrives inbound; assert it isn't anywhere regardless.
        cap = new_capture(password="sup3rpass")
        cap._record_frame(REAL_KEYPAD)
        assert "sup3rpass" not in json.dumps(cap.build_bundle())

    def test_host_is_redacted_in_bundle(self):
        cap = Capture("192.168.100.160", 4025, "pw", keepalive=False, dump_zones=False)
        assert cap.build_bundle()["host"] == "<redacted>"
        assert "192.168.100.160" not in json.dumps(cap.build_bundle())


# ────────────────────────────────────────────────────────────────────────────
# Robustness — write fallback, transitions
# ────────────────────────────────────────────────────────────────────────────

class TestOutput:
    def test_write_fallback_on_bad_path(self, tmp_path):
        cap = new_capture()
        cap.add_marker("hello")
        bundle = cap.build_bundle()
        # A path whose parent cannot be created (a file used as a directory)
        blocker = tmp_path / "afile"
        blocker.write_text("x")
        bad = str(blocker / "sub" / "out.json")
        written = write_bundle(bundle, bad)
        assert Path(written).exists()          # fell back to a temp file
        assert written != bad

    def test_write_creates_missing_parent(self, tmp_path):
        cap = new_capture()
        bundle = cap.build_bundle()
        target = str(tmp_path / "newdir" / "capture.json")
        written = write_bundle(bundle, target)
        assert written == target and Path(target).exists()

    def test_transitions_summary(self):
        cap = new_capture()
        cap.records = [
            {"kind": "marker", "note": "STEP START: arm_away - x", "t": 1.0},
            {"kind": "frame", "type": "keypad_update", "derived_state": "exit_delay", "t": 1.5, "display": "", "beep": "3 beeps"},
            {"kind": "frame", "type": "keypad_update", "derived_state": "exit_delay", "t": 2.0, "display": "", "beep": "3 beeps"},
            {"kind": "frame", "type": "keypad_update", "derived_state": "armed_away", "t": 8.0, "display": "", "beep": "off"},
            {"kind": "marker", "note": "STEP END: arm_away", "t": 9.0},
        ]
        trans = cap._build_transitions()
        assert len(trans) == 1
        # de-duplicated consecutive states: exit_delay then armed_away
        assert [s["state"] for s in trans[0]["states"]] == ["exit_delay", "armed_away"]
