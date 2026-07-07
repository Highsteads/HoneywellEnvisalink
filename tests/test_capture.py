#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_capture.py
# Description: Pytest suite for the shared tpi_capture module + the standalone
#              tools/capture_tpi.py — decoding, redaction, the read-only safety
#              gate, the CRLF-injection guard, and the write fallback.
# Author:      Highsteads / CliveS & Claude Opus 4.8

import json
import sys
import pytest
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "HoneywellEnvisalink.indigoPlugin" / "Contents" / "Server Plugin"))
sys.path.insert(0, str(REPO / "tools"))

import capture_tpi
import tpi_capture
from tpi_capture import (
    decode_line, mask_codes, mask_keypad_raw, sensitive_records, make_bundle,
    write_bundle, build_state_timeline,
)
from capture_tpi import Capture, password_is_safe, _READONLY_COMMANDS
from honeywell_protocol import encode_keepalive, encode_dump_zone_timers, encode_disarm, encode_keypress


REAL_KEYPAD = "%00,01,1C08,08,00,****DISARMED****  Ready to Arm  $"


# ────────────────────────────────────────────────────────────────────────────
# Decoding (shared module)
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
        assert decode_line("%02,0500000000000000$")["partitions"] == {1: "armed_away"}

    def test_zone_bitmap(self):
        assert 1 in decode_line("%01,0100000000000000$")["open_zones"]

    def test_cid(self):
        assert decode_line("%03,113001005$")["cid"]["event"] == 130

    def test_zone_timer_dump_decoded(self):
        d = decode_line("%FF,01000500" + "0" * 120 + "$")
        assert d["type"] == "zone_timer_dump" and d["zone_timers"] == {1: 1, 2: 5}

    def test_unparseable_line_flagged(self):
        d = decode_line("total garbage no dollar")
        assert d["parsed"] is False and "did not parse" in d["note"]

    def test_recognised_but_unparsed_counts_as_unparsed(self):
        d = decode_line("%00,01,ZZZZ,00,00,Ready$")
        assert d["type"] == "recognised_but_unparsed" and d["parsed"] is False


# ────────────────────────────────────────────────────────────────────────────
# SAFETY — read-only gate + CRLF-injection guard (tool)
# ────────────────────────────────────────────────────────────────────────────

class TestReadOnlySafety:
    def test_allowlist_is_only_keepalive_and_dump(self):
        assert _READONLY_COMMANDS == frozenset({encode_keepalive(), encode_dump_zone_timers()})

    def test_no_keypress_in_allowlist(self):
        assert encode_keypress(1, "1") not in _READONLY_COMMANDS
        for cmd in encode_disarm("1234", 1):
            assert cmd not in _READONLY_COMMANDS

    def test_send_readonly_rejects_keypress(self):
        cap = Capture("192.168.1.50", 4025, "pw", True, False)
        with pytest.raises(RuntimeError):
            cap._send_readonly(encode_keypress(1, "5"))
        with pytest.raises(RuntimeError):
            cap._send_readonly("^03,1,1$\r\n")

    def test_send_readonly_accepts_allowlisted(self):
        cap = Capture("192.168.1.50", 4025, "pw", True, False)
        sent = []
        cap.sock = type("S", (), {"sendall": lambda _self, b: sent.append(b)})()
        cap._send_readonly(encode_keepalive())
        cap._send_readonly(encode_dump_zone_timers())
        assert sent == [b"^00,$\r\n", b"^02,$\r\n"]

    def test_tool_and_plugin_never_construct_a_keypress(self):
        for mod in (capture_tpi, tpi_capture):
            src = Path(mod.__file__).read_text(encoding="utf-8")
            for forbidden in ("encode_keypress", "encode_keystroke", "encode_disarm",
                              "encode_arm", "encode_bypass", "send_keypresses"):
                assert forbidden not in src, f"{mod.__name__} references {forbidden}"
        assert Path(capture_tpi.__file__).read_text(encoding="utf-8").count("sendall(") <= 2

    def test_password_crlf_injection_rejected(self):
        assert password_is_safe("mypass\r\n^03,1,1$") is False
        assert password_is_safe("has$dollar") is False
        assert password_is_safe("has^caret") is False
        assert password_is_safe("") is False

    def test_password_normal_accepted(self):
        assert password_is_safe("user") is True
        assert password_is_safe("S3cret-Pass_1") is True


# ────────────────────────────────────────────────────────────────────────────
# Redaction (shared module)
# ────────────────────────────────────────────────────────────────────────────

class TestRedaction:
    def test_mask_codes(self):
        assert mask_codes("disarmed with 4471") == "disarmed with ####"
        assert mask_codes("opened zone 01") == "opened zone 01"      # short numbers kept

    def test_mask_keypad_raw_keeps_header(self):
        raw = mask_keypad_raw("%00,01,1008,00,00,ENTER CODE 4471$")
        assert raw.startswith("%00,01,1008,00,00,") and "4471" not in raw

    def test_display_code_is_masked(self):
        d = decode_line("%00,01,1008,00,00,ENTER CODE 4471$")
        assert "4471" not in d["display"] and "4471" not in d["raw"]

    def test_verdict_flags_undecoded_line_with_digit_run(self):
        bundle = {"records": [{"kind": "frame", "type": "other",
                               "raw": "^ZZ,ACCT 4471$", "payload": "ACCT 4471"}]}
        assert sensitive_records(bundle)

    def test_verdict_ignores_hex_payload_of_decoded_frames(self):
        recs = [decode_line("%FF," + "0100050000000000" * 8 + "$"),
                decode_line("%02,0500000000000000$")]
        assert sensitive_records({"records": recs}) == []

    def test_host_is_redacted_in_bundle(self):
        b = make_bundle([], {}, 0, 1.0, 4025)
        assert b["host"] == "<redacted>"

    def test_password_never_in_bundle(self):
        recs = [dict(kind="frame", **decode_line(REAL_KEYPAD))]
        assert "sup3rpass" not in json.dumps(make_bundle(recs, {}, 0, 1.0, 4025))


# ────────────────────────────────────────────────────────────────────────────
# Output — write fallback, state timeline
# ────────────────────────────────────────────────────────────────────────────

class TestOutput:
    def test_write_fallback_on_bad_path(self, tmp_path):
        blocker = tmp_path / "afile"
        blocker.write_text("x")
        bad = str(blocker / "sub" / "out.json")
        written = write_bundle(make_bundle([], {}, 0, 1.0, 4025), bad)
        assert Path(written).exists() and written != bad

    def test_write_creates_missing_parent(self, tmp_path):
        target = str(tmp_path / "newdir" / "capture.json")
        written = write_bundle(make_bundle([], {}, 0, 1.0, 4025), target)
        assert written == target and Path(target).exists()

    def test_state_timeline_dedups_consecutive_states(self):
        recs = [
            {"type": "keypad_update", "derived_state": "exit_delay", "t": 1.5, "display": "", "beep": "3 beeps"},
            {"type": "keypad_update", "derived_state": "exit_delay", "t": 2.0, "display": "", "beep": "3 beeps"},
            {"type": "keypad_update", "derived_state": "armed_away", "t": 8.0, "display": "", "beep": "off"},
        ]
        assert [s["state"] for s in build_state_timeline(recs)] == ["exit_delay", "armed_away"]
