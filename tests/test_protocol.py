#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_protocol.py
# Description: Pytest suite for honeywell_protocol.py — the REAL Envisalink
#              Honeywell TPI ($-terminated, no checksum, 16-bit keypad flags).
#              Anchored to real-hardware captures from the beta tester.
# Author:      Highsteads / CliveS & Claude Opus 4.8

import sys
import pytest
from pathlib import Path

PLUGIN_SRC = Path(__file__).parent.parent / "HoneywellEnvisalink.indigoPlugin" / "Contents" / "Server Plugin"
sys.path.insert(0, str(PLUGIN_SRC))

from honeywell_protocol import (
    parse_frame, parse_keypad_update, parse_zone_state, parse_partition_state,
    parse_realtime_cid, derive_partition_state,
    encode_login, encode_keepalive, encode_dump_zone_timers, encode_keypress,
    encode_keystroke_sequence, encode_disarm, encode_arm_away, encode_arm_stay,
    encode_arm_instant, encode_arm_max, encode_bypass_zone,
    redact_line_for_log, flag_names, decode_zone_timer_dump,
    ZoneBitmap, PartitionState,
    FLAG_READY, FLAG_AC_PRESENT, FLAG_ARMED_AWAY, FLAG_ARMED_STAY,
    FLAG_ARMED_NO_ENTRY, FLAG_ALARM, FLAG_ALARM_IN_MEMORY, FLAG_BYPASS,
    FLAG_CHIME, FLAG_SYSTEM_TROUBLE,
    ProtocolError,
)


# ────────────────────────────────────────────────────────────────────────────
# REAL HARDWARE CAPTURES — beta tester, Vista 20P + EVL4, 07-Jul-2026.
# These are the exact bytes that used to fail (frames_rx stayed 0). They are the
# ground truth: if these ever fail to parse, the protocol model has regressed.
# ────────────────────────────────────────────────────────────────────────────

REAL_KEYPAD_DISARMED = "%00,01,1C08,08,00,****DISARMED****  Ready to Arm  $"
REAL_CMD_RESPONSE    = "^FF,05$"


class TestRealHardwareCaptures:
    def test_real_keypad_frame_parses(self):
        f = parse_frame(REAL_KEYPAD_DISARMED)
        assert f.code == "%00"
        ku = parse_keypad_update(f)
        assert ku is not None
        assert ku.partition == 1
        assert ku.led_bitmap == 0x1C08
        # 0x1C08 = ready + ac_present (+ two vendor 'not used' bits)
        assert ku.ready is True
        assert ku.ac_power is True
        assert ku.armed is False
        assert ku.alarm is False
        assert "DISARMED" in ku.display_text
        assert derive_partition_state(ku) == PartitionState.READY

    def test_real_command_response_does_not_crash(self):
        # '^FF,05$' is a command response — every TYPED parser must return None
        # (not raise). This is the frame that spammed checksum errors before.
        f = parse_frame(REAL_CMD_RESPONSE)
        assert f.code == "^FF"
        assert parse_keypad_update(f) is None
        assert parse_zone_state(f) is None
        assert parse_partition_state(f) is None
        assert parse_realtime_cid(f) is None


# ────────────────────────────────────────────────────────────────────────────
# Frame parsing — $ terminator, NO checksum
# ────────────────────────────────────────────────────────────────────────────

class TestParseFrame:
    def test_async_message(self):
        f = parse_frame("%00,01,1008,00,00,Ready$")
        assert f.code == "%00"
        assert f.payload == "01,1008,00,00,Ready"

    def test_command_response(self):
        f = parse_frame("^00,00$")
        assert f.code == "^00"
        assert f.payload == "00"

    def test_strips_crlf(self):
        f = parse_frame("%02,0100000000000000$\r\n")
        assert f.code == "%02"
        assert f.payload == "0100000000000000"

    def test_login_tokens(self):
        for tok in ("Login:", "OK", "FAILED", "Timed Out!"):
            assert parse_frame(tok).code == tok

    def test_no_checksum_expected(self):
        # A trailing 2-char group is NOT a checksum — it's real payload.
        f = parse_frame("%00,01,1C08,08,00,Ready to Arm$")
        assert f.payload.endswith("Ready to Arm")

    def test_unframed_line_raises(self):
        with pytest.raises(ProtocolError):
            parse_frame("garbage with no dollar")

    def test_missing_terminator_raises(self):
        with pytest.raises(ProtocolError):
            parse_frame("%00,01,1008,00,00,Ready")   # no trailing $

    def test_blank_raises(self):
        with pytest.raises(ProtocolError):
            parse_frame("\r\n")


# ────────────────────────────────────────────────────────────────────────────
# Keypad update (%00) — 16-bit flag decoding
# ────────────────────────────────────────────────────────────────────────────

def keypad(flags, partition=1, zone=0, beep=0, text="Ready to Arm"):
    line = f"%00,{partition:02d},{flags:04X},{zone:02d},{beep:02d},{text}$"
    return parse_keypad_update(parse_frame(line))


class TestFlagNames:
    def test_known_flags(self):
        names = flag_names(FLAG_READY | FLAG_AC_PRESENT)
        assert "ready" in names and "ac_present" in names

    def test_real_capture_surfaces_unknown_bits(self):
        # 0x1C08 = ready + ac_present + 0x0C00 (two vendor 'not used' bits)
        names = flag_names(0x1C08)
        assert "ready" in names and "ac_present" in names
        assert "unknown(0x0C00)" in names

    def test_no_flags(self):
        assert flag_names(0x0000) == []


class TestKeypadFlags:
    def test_ready(self):
        ku = keypad(FLAG_READY | FLAG_AC_PRESENT)
        assert ku.ready and ku.ac_power and not ku.armed

    def test_armed_away(self):
        ku = keypad(FLAG_ARMED_AWAY | FLAG_AC_PRESENT, text="ARMED ***AWAY***")
        assert ku.armed_away and ku.armed and not ku.ready

    def test_armed_stay(self):
        ku = keypad(FLAG_ARMED_STAY | FLAG_AC_PRESENT, text="ARMED ***STAY***")
        assert ku.armed_stay and ku.armed

    def test_alarm(self):
        ku = keypad(FLAG_ALARM | FLAG_ARMED_AWAY, text="ALARM 05")
        assert ku.alarm

    def test_bypass_and_chime(self):
        ku = keypad(FLAG_READY | FLAG_BYPASS | FLAG_CHIME)
        assert ku.bypass and ku.chime

    def test_short_00_frame_returns_none(self):
        # An overloaded short "%00" (e.g. a poll echo) is not a keypad update.
        assert parse_keypad_update(parse_frame("%00,01$")) is None

    def test_non_hex_flags_raises(self):
        with pytest.raises(ProtocolError):
            parse_keypad_update(parse_frame("%00,01,ZZZZ,00,00,Ready$"))


# ────────────────────────────────────────────────────────────────────────────
# derive_partition_state — LED flags + display text
# ────────────────────────────────────────────────────────────────────────────

class TestDerivedState:
    def test_ready(self):
        assert derive_partition_state(keypad(FLAG_READY)) == PartitionState.READY

    def test_armed_away(self):
        ku = keypad(FLAG_ARMED_AWAY, text="ARMED ***AWAY***")
        assert derive_partition_state(ku) == PartitionState.ARMED_AWAY

    def test_armed_stay(self):
        ku = keypad(FLAG_ARMED_STAY, text="ARMED ***STAY***")
        assert derive_partition_state(ku) == PartitionState.ARMED_STAY

    def test_armed_instant_from_text(self):
        ku = keypad(FLAG_ARMED_AWAY | FLAG_ARMED_NO_ENTRY, text="ARMED ***INSTANT***")
        assert derive_partition_state(ku) == PartitionState.ARMED_INSTANT

    def test_armed_max_from_text(self):
        ku = keypad(FLAG_ARMED_AWAY | FLAG_ARMED_NO_ENTRY, text="ARMED **MAXIMUM**")
        assert derive_partition_state(ku) == PartitionState.ARMED_MAX

    def test_armed_no_entry_without_text_is_instant(self):
        ku = keypad(FLAG_ARMED_NO_ENTRY, text="ARMED")
        assert derive_partition_state(ku) == PartitionState.ARMED_INSTANT

    def test_exit_delay(self):
        ku = keypad(FLAG_ARMED_AWAY, text="ARMED ***AWAY*** May Exit Now")
        assert derive_partition_state(ku) == PartitionState.EXIT_DELAY

    def test_entry_delay(self):
        ku = keypad(FLAG_ARMED_AWAY, text="DISARM SYSTEM OR ALARM")
        assert derive_partition_state(ku) == PartitionState.ENTRY_DELAY

    def test_alarm_overrides(self):
        ku = keypad(FLAG_ALARM | FLAG_ARMED_AWAY, text="ALARM")
        assert derive_partition_state(ku) == PartitionState.ALARM

    def test_alarm_memory_from_flag(self):
        ku = keypad(FLAG_ALARM_IN_MEMORY | FLAG_READY, text="Ready")
        assert derive_partition_state(ku) == PartitionState.ALARM_MEMORY

    def test_trouble(self):
        ku = keypad(FLAG_SYSTEM_TROUBLE, text="Check 03")
        assert derive_partition_state(ku) == PartitionState.TROUBLE

    def test_not_ready(self):
        ku = keypad(0x0000, text="Not Ready Fault 02")
        assert derive_partition_state(ku) == PartitionState.NOT_READY


# ────────────────────────────────────────────────────────────────────────────
# Partition state (%02) — 8 partitions, 2 hex chars each
# ────────────────────────────────────────────────────────────────────────────

class TestPartitionState:
    def test_single_partition_ready(self):
        changes = parse_partition_state(parse_frame("%02,0100000000000000$"))
        assert len(changes) == 1
        assert changes[0].partition == 1
        assert changes[0].state == PartitionState.READY

    def test_status_code_mapping(self):
        cases = {
            "01": PartitionState.READY, "03": PartitionState.NOT_READY,
            "04": PartitionState.ARMED_STAY, "05": PartitionState.ARMED_AWAY,
            "06": PartitionState.ARMED_MAX, "07": PartitionState.EXIT_ENTRY_DELAY,
            "08": PartitionState.ALARM, "09": PartitionState.ALARM_MEMORY,
        }
        for code, expected in cases.items():
            data = code + "00" * 7
            changes = parse_partition_state(parse_frame(f"%02,{data}$"))
            assert changes[0].state == expected

    def test_multiple_partitions(self):
        # Partition 1 armed away, partition 2 ready, rest unused
        changes = parse_partition_state(parse_frame("%02,0501000000000000$"))
        assert {c.partition: c.state for c in changes} == {
            1: PartitionState.ARMED_AWAY, 2: PartitionState.READY}

    def test_all_unused_is_empty(self):
        assert parse_partition_state(parse_frame("%02,0000000000000000$")) == []


# ────────────────────────────────────────────────────────────────────────────
# Zone bitmap (%01)
# ────────────────────────────────────────────────────────────────────────────

class TestZoneTimerDump:
    def test_little_endian_words_nonzero_only(self):
        # zone1 0100->0x0001, zone2 0000->skip, zone3 3412->0x1234
        timers = decode_zone_timer_dump("010000003412")
        assert timers == {1: 1, 3: 0x1234}

    def test_all_zero_is_empty(self):
        assert decode_zone_timer_dump("0" * 128) == {}


class TestZoneBitmap:
    def test_no_zones_open(self):
        zb = parse_zone_state(parse_frame("%01,0000000000000000$"))
        assert isinstance(zb, ZoneBitmap)
        assert zb.open_zones == set()

    def test_zone_one_open(self):
        # First 16-bit chunk, byte-swapped: 0100 -> 0x0001 -> bit0 -> zone 1
        zb = parse_zone_state(parse_frame("%01,0100000000000000$"))
        assert 1 in zb.open_zones

    def test_empty_raises(self):
        with pytest.raises(ProtocolError):
            parse_zone_state(parse_frame("%01,$"))


# ────────────────────────────────────────────────────────────────────────────
# Real-time CID (%03)
# ────────────────────────────────────────────────────────────────────────────

class TestRealtimeCID:
    def test_concatenated(self):
        # Q(1) EEE(3) PP(2) ZZZ(3) = 9 chars: qual 1, event 130, partition 01, zone 005
        cid = parse_realtime_cid(parse_frame("%03,113001005$"))
        assert (cid.qualifier, cid.event_code, cid.partition, cid.zone_or_user) == (1, 130, 1, 5)

    def test_comma_form(self):
        cid = parse_realtime_cid(parse_frame("%03,1,130,01,005$"))
        assert (cid.qualifier, cid.event_code, cid.partition, cid.zone_or_user) == (1, 130, 1, 5)

    def test_short_raises(self):
        with pytest.raises(ProtocolError):
            parse_realtime_cid(parse_frame("%03,12$"))


# ────────────────────────────────────────────────────────────────────────────
# Encoding — ^CC,DATA$  (no checksum); keystrokes one char per command
# ────────────────────────────────────────────────────────────────────────────

class TestEncoding:
    def test_login(self):
        assert encode_login("user") == "user\r\n"

    def test_login_empty_raises(self):
        with pytest.raises(ValueError):
            encode_login("")

    def test_keepalive(self):
        assert encode_keepalive() == "^00,$\r\n"

    def test_dump_zone_timers(self):
        assert encode_dump_zone_timers() == "^02,$\r\n"

    def test_keypress(self):
        assert encode_keypress(1, "5") == "^03,1,5$\r\n"

    def test_keypress_bad_partition(self):
        with pytest.raises(ValueError):
            encode_keypress(9, "5")

    def test_keypress_multichar_raises(self):
        with pytest.raises(ValueError):
            encode_keypress(1, "55")

    def test_sequence_is_one_command_per_char(self):
        seq = encode_keystroke_sequence("1234", partition=2)
        assert seq == ["^03,2,1$\r\n", "^03,2,2$\r\n", "^03,2,3$\r\n", "^03,2,4$\r\n"]

    def test_disarm_appends_key_1(self):
        seq = encode_disarm("1234", partition=1)
        assert seq[-1] == "^03,1,1$\r\n"      # last keystroke is the disarm key
        assert len(seq) == 5                  # 4 code digits + 1 key

    def test_arm_helpers_append_correct_key(self):
        assert encode_arm_away("1234")[-1]    == "^03,1,2$\r\n"
        assert encode_arm_stay("1234")[-1]    == "^03,1,3$\r\n"
        assert encode_arm_max("1234")[-1]     == "^03,1,4$\r\n"
        assert encode_arm_instant("1234")[-1] == "^03,1,7$\r\n"

    def test_bypass_zone(self):
        seq = encode_bypass_zone("1234", zone=5, partition=1)
        # code(4) + bypass key '6' + zone '05' = 7 keystrokes
        assert len(seq) == 7
        assert [c[len("^03,1,")] for c in seq] == list("1234605")

    def test_bypass_out_of_range(self):
        with pytest.raises(ValueError):
            encode_bypass_zone("1234", zone=999)


# ────────────────────────────────────────────────────────────────────────────
# Redaction — the user code goes out one digit per ^03 command
# ────────────────────────────────────────────────────────────────────────────

class TestRedaction:
    def test_keypress_digit_masked(self):
        assert redact_line_for_log("^03,1,4$") == "^03,1,*$"

    def test_full_sequence_masks_every_digit(self):
        for cmd in encode_disarm("1234", partition=1):
            out = redact_line_for_log(cmd)
            # no bare digit remains in the keypress position
            assert "*" in out

    def test_inbound_not_touched(self):
        line = "%00,01,1C08,08,00,****DISARMED****  Ready to Arm  $"
        assert redact_line_for_log(line) == line

    def test_non_digit_key_left_alone(self):
        # '*' and '#' function keys are not codes — leave them visible
        assert redact_line_for_log("^03,1,#$") == "^03,1,#$"
