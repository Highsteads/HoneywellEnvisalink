#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_protocol.py
# Description: Pytest suite for honeywell_protocol.py — pure-function tests.
#              Run from repo root with:   pytest -v tests/
# Author:      Highsteads / CliveS & Claude

import sys
import pytest
from pathlib import Path

# Make the plugin's source importable
PLUGIN_SRC = Path(__file__).parent.parent / "HoneywellEnvisalink.indigoPlugin" / "Contents" / "Server Plugin"
sys.path.insert(0, str(PLUGIN_SRC))

from honeywell_protocol import (
    tpi_checksum, verify_checksum, append_checksum,
    parse_frame, parse_keypad_update, parse_zone_state, parse_partition_state,
    parse_realtime_cid, derive_partition_state,
    encode_login, encode_keystrokes, encode_disarm, encode_arm_away,
    encode_arm_stay, encode_arm_instant, encode_arm_max, encode_bypass_zone,
    encode_dump_zone_timers,
    redact_line_for_log,
    KeypadUpdate, ZoneState, PartitionState,
    LED_ARMED, LED_READY, LED_TROUBLE, LED_BYPASS, LED_AC_POWER, LED_ALARM, LED_ALARM_OCCURRED,
    ProtocolError, ChecksumError,
)


# ────────────────────────────────────────────────────────────────────────────
# Checksum tests
# ────────────────────────────────────────────────────────────────────────────

class TestChecksum:
    def test_empty_string_is_zero(self):
        assert tpi_checksum("") == "00"

    def test_single_char(self):
        # ord('A') = 65 = 0x41
        assert tpi_checksum("A") == "41"

    def test_wraps_modulo_256(self):
        # 256 'A's = 65 * 256 = 16640 → mod 256 = 0
        assert tpi_checksum("A" * 256) == "00"

    def test_known_value(self):
        # "00,1" → 0x30+0x30+0x2C+0x31 = 0xBD
        assert tpi_checksum("00,1").upper() == "BD"

    def test_verify_roundtrip(self):
        payload = "00,11234A"
        line = payload + tpi_checksum(payload)
        assert verify_checksum(line) == payload

    def test_verify_bad_checksum_raises(self):
        with pytest.raises(ChecksumError):
            verify_checksum("00,1ZZ")

    def test_append_checksum(self):
        assert append_checksum("AB") == "AB" + tpi_checksum("AB")


# ────────────────────────────────────────────────────────────────────────────
# Frame parsing
# ────────────────────────────────────────────────────────────────────────────

class TestParseFrame:
    def test_login_prompt(self):
        f = parse_frame("Login:")
        assert f.code == "Login:"

    def test_login_ok(self):
        f = parse_frame("OK")
        assert f.code == "OK"

    def test_login_failed(self):
        f = parse_frame("FAILED")
        assert f.code == "FAILED"

    def test_simple_server_frame(self):
        payload = "00,01,01,000,00,Ready                              "
        line = "%" + payload + tpi_checksum(payload)
        f = parse_frame(line)
        assert f.code == "00"
        assert f.payload.startswith("01,01,000,00,Ready")

    def test_client_frame_with_caret(self):
        payload = "00,11234A"
        line = "^" + payload + tpi_checksum(payload)
        f = parse_frame(line)
        assert f.code == "00"
        assert f.payload == "11234A"

    def test_empty_line_raises(self):
        with pytest.raises(ProtocolError):
            parse_frame("")

    def test_blank_after_strip_raises(self):
        with pytest.raises(ProtocolError):
            parse_frame("\r\n")

    def test_strips_crlf(self):
        payload = "00,1"
        line = "^" + payload + tpi_checksum(payload) + "\r\n"
        f = parse_frame(line)
        assert f.code == "00"

    def test_skip_checksum_verify(self):
        # For test fixtures that don't bother computing the checksum
        f = parse_frame("%00,1,02,000,00,ARMED                              ZZ", verify_checksums=False)
        assert f.code == "00"
        assert f.payload.startswith("1,02,000,00,ARMED")

    def test_bad_checksum_through_parse_frame_raises(self):
        # A real frame with a corrupted checksum must raise ChecksumError when
        # verification is on (the default for live traffic).
        payload = "01,007,O"
        good = "%" + payload + tpi_checksum(payload)
        bad = good[:-2] + "ZZ"   # clobber the trailing checksum
        with pytest.raises(ChecksumError):
            parse_frame(bad)


# ────────────────────────────────────────────────────────────────────────────
# Keypad update parsing
# ────────────────────────────────────────────────────────────────────────────

def make_keypad_frame(partition=1, led_hex="02", zone=0, beep=0,
                      display="Ready                            "):
    """Helper: build a properly-checksummed keypad update line for tests."""
    display = display[:32].ljust(32)
    payload = f"00,{partition},{led_hex},{zone:03d},{beep},{display}"
    return "%" + payload + tpi_checksum(payload)


class TestKeypadUpdate:
    def test_basic_ready(self):
        line = make_keypad_frame(led_hex=f"{LED_READY:02X}",
                                  display="Ready                            ")
        ku = parse_keypad_update(parse_frame(line))
        assert ku is not None
        assert ku.partition == 1
        assert ku.ready
        assert not ku.armed
        assert ku.display_text.startswith("Ready")

    def test_armed_away(self):
        line = make_keypad_frame(led_hex=f"{LED_ARMED:02X}",
                                  display="ARMED ***AWAY***                 ")
        ku = parse_keypad_update(parse_frame(line))
        assert ku.armed
        assert not ku.ready

    def test_combined_leds(self):
        bits = LED_ARMED | LED_AC_POWER | LED_BYPASS
        line = make_keypad_frame(led_hex=f"{bits:02X}",
                                  display="ARMED BYPASS                     ")
        ku = parse_keypad_update(parse_frame(line))
        assert ku.armed and ku.ac_power and ku.bypass
        assert not ku.ready

    def test_alarm_flag(self):
        line = make_keypad_frame(led_hex=f"{LED_ALARM:02X}",
                                  display="ALARM ZONE 2                     ")
        ku = parse_keypad_update(parse_frame(line))
        assert ku.alarm

    def test_returns_none_for_non_keypad_frame(self):
        # Zone-state-change frame
        payload = "01,005,O"
        line = "%" + payload + tpi_checksum(payload)
        assert parse_keypad_update(parse_frame(line)) is None

    def test_short_00_frame_returns_none(self):
        # TPI code "00" is overloaded (keypad update AND keep-alive). A short
        # "00" frame (too few fields to be a keypad update) must return None —
        # treated as an uninteresting keep-alive — NOT raise, so it doesn't spam
        # "frame handler error" warnings on real hardware.
        payload = "00,1,02"
        line = "%" + payload + tpi_checksum(payload)
        assert parse_keypad_update(parse_frame(line)) is None

    def test_bare_00_keepalive_returns_none(self):
        payload = "00,"
        line = "%" + payload + tpi_checksum(payload)
        assert parse_keypad_update(parse_frame(line)) is None

    def test_non_hex_led_raises(self):
        # A 5-field "00" frame with a non-hex LED byte is a genuinely malformed
        # keypad update and must still raise.
        payload = "00,1,ZZ,000,0,Ready"
        line = "%" + payload + tpi_checksum(payload)
        with pytest.raises(ProtocolError):
            parse_keypad_update(parse_frame(line))


# ────────────────────────────────────────────────────────────────────────────
# Zone state parsing
# ────────────────────────────────────────────────────────────────────────────

class TestZoneState:
    @pytest.mark.parametrize("char,expected", [
        ("O", ZoneState.OPEN),
        ("C", ZoneState.CLOSED),
        ("B", ZoneState.BYPASS),
        ("T", ZoneState.TROUBLE),
        ("A", ZoneState.ALARM),
        ("X", ZoneState.UNKNOWN),
    ])
    def test_states(self, char, expected):
        payload = f"01,007,{char}"
        line = "%" + payload + tpi_checksum(payload)
        zsc = parse_zone_state(parse_frame(line))
        assert zsc is not None
        assert zsc.zone == 7
        assert zsc.state == expected

    def test_three_digit_zone(self):
        payload = "01,142,O"
        line = "%" + payload + tpi_checksum(payload)
        zsc = parse_zone_state(parse_frame(line))
        assert zsc.zone == 142

    def test_high_zone_number(self):
        payload = "01,250,O"   # Vista 250BP max zone
        line = "%" + payload + tpi_checksum(payload)
        zsc = parse_zone_state(parse_frame(line))
        assert zsc.zone == 250

    def test_non_numeric_zone_raises(self):
        payload = "01,ABC,O"
        line = "%" + payload + tpi_checksum(payload)
        with pytest.raises(ProtocolError):
            parse_zone_state(parse_frame(line))


# ────────────────────────────────────────────────────────────────────────────
# Partition state parsing
# ────────────────────────────────────────────────────────────────────────────

class TestPartitionState:
    @pytest.mark.parametrize("code,expected", [
        ("READY",         PartitionState.READY),
        ("NOT_READY",     PartitionState.NOT_READY),
        ("ARMED_AWAY",    PartitionState.ARMED_AWAY),
        ("ARMED_STAY",    PartitionState.ARMED_STAY),
        ("ARMED_INSTANT", PartitionState.ARMED_INSTANT),
        ("ARMED_MAX",     PartitionState.ARMED_MAX),
        ("ENTRY_DELAY",   PartitionState.ENTRY_DELAY),
        ("EXIT_DELAY",    PartitionState.EXIT_DELAY),
        ("ALARM",         PartitionState.ALARM),
        ("TROUBLE",       PartitionState.TROUBLE),
        ("BOGUS",         PartitionState.UNKNOWN),
    ])
    def test_states(self, code, expected):
        payload = f"02,1,{code}"
        line = "%" + payload + tpi_checksum(payload)
        psc = parse_partition_state(parse_frame(line))
        assert psc.partition == 1
        assert psc.state == expected

    @pytest.mark.parametrize("partition", [1, 2, 3])
    def test_multi_partition(self, partition):
        payload = f"02,{partition},ARMED_AWAY"
        line = "%" + payload + tpi_checksum(payload)
        psc = parse_partition_state(parse_frame(line))
        assert psc.partition == partition
        assert psc.state == PartitionState.ARMED_AWAY

    def test_non_numeric_partition_raises(self):
        payload = "02,X,READY"
        line = "%" + payload + tpi_checksum(payload)
        with pytest.raises(ProtocolError):
            parse_partition_state(parse_frame(line))


# ────────────────────────────────────────────────────────────────────────────
# Derived partition state from keypad text (fallback path)
# ────────────────────────────────────────────────────────────────────────────

class TestDerivedState:
    def test_ready(self):
        ku = KeypadUpdate(1, LED_READY, 0, 0, "Ready                            ")
        assert derive_partition_state(ku) == PartitionState.READY

    def test_armed_away_default(self):
        ku = KeypadUpdate(1, LED_ARMED, 0, 0, "ARMED ***AWAY***                 ")
        assert derive_partition_state(ku) == PartitionState.ARMED_AWAY

    def test_armed_stay(self):
        ku = KeypadUpdate(1, LED_ARMED, 0, 0, "ARMED ***STAY***                 ")
        assert derive_partition_state(ku) == PartitionState.ARMED_STAY

    def test_armed_instant(self):
        ku = KeypadUpdate(1, LED_ARMED, 0, 0, "ARMED **INSTANT**                ")
        assert derive_partition_state(ku) == PartitionState.ARMED_INSTANT

    def test_exit_delay(self):
        ku = KeypadUpdate(1, LED_ARMED, 0, 1, "ARMED MAY EXIT NOW               ")
        assert derive_partition_state(ku) == PartitionState.EXIT_DELAY

    def test_alarm_overrides(self):
        ku = KeypadUpdate(1, LED_ALARM | LED_ARMED, 0, 1, "ALARM                            ")
        assert derive_partition_state(ku) == PartitionState.ALARM

    def test_armed_max(self):
        ku = KeypadUpdate(1, LED_ARMED, 0, 0, "ARMED ***MAXIMUM***              ")
        assert derive_partition_state(ku) == PartitionState.ARMED_MAX

    def test_armed_stay_not_misread_as_max(self):
        # Regression: the old code matched a bare "MAX" substring before "STAY".
        ku = KeypadUpdate(1, LED_ARMED, 0, 0, "ARMED ***STAY***                 ")
        assert derive_partition_state(ku) == PartitionState.ARMED_STAY

    def test_alarm_memory_from_led_bit(self):
        # LED_ALARM_OCCURRED (0x40) alone, no live alarm, no text — should derive
        # ALARM_MEMORY (regression: that LED bit used to be defined but never read).
        ku = KeypadUpdate(1, LED_ALARM_OCCURRED | LED_READY, 0, 0, "Ready                  ")
        assert derive_partition_state(ku) == PartitionState.ALARM_MEMORY

    def test_entry_delay(self):
        ku = KeypadUpdate(1, LED_ARMED, 0, 1, "DISARM SYSTEM OR ALARM           ")
        assert derive_partition_state(ku) == PartitionState.ENTRY_DELAY

    def test_trouble(self):
        ku = KeypadUpdate(1, LED_TROUBLE, 0, 0, "Check 03                         ")
        assert derive_partition_state(ku) == PartitionState.TROUBLE

    def test_not_ready(self):
        ku = KeypadUpdate(1, 0x00, 0, 0, "Not Ready Fault 02               ")
        assert derive_partition_state(ku) == PartitionState.NOT_READY


# ────────────────────────────────────────────────────────────────────────────
# Real-time CID
# ────────────────────────────────────────────────────────────────────────────

class TestRealtimeCID:
    def test_burglary_concatenated(self):
        # Concatenated form: Qualifier=1 (new), code=130, partition=01, zone=0007
        payload = "03,1130010007"
        line = "%" + payload + tpi_checksum(payload)
        cid = parse_realtime_cid(parse_frame(line))
        assert cid.qualifier == 1
        assert cid.event_code == 130
        assert cid.partition == 1
        assert cid.zone_or_user == 7

    def test_burglary_comma_form(self):
        # Comma-delimited firmware variant: Q,XXX,PP,ZZZZ
        payload = "03,1,130,01,0007"
        line = "%" + payload + tpi_checksum(payload)
        cid = parse_realtime_cid(parse_frame(line))
        assert cid.qualifier == 1
        assert cid.event_code == 130
        assert cid.partition == 1
        assert cid.zone_or_user == 7

    def test_comma_form_unpadded_fields(self):
        # Regression: comma-stripping + fixed slicing mis-attributed un-padded
        # fields. Positional comma-split must read them correctly.
        payload = "03,3,401,1,42"   # qualifier 3 (restore), user/installer code 401, partition 1, user 42
        line = "%" + payload + tpi_checksum(payload)
        cid = parse_realtime_cid(parse_frame(line))
        assert cid.qualifier == 3
        assert cid.event_code == 401
        assert cid.partition == 1
        assert cid.zone_or_user == 42

    def test_short_cid_raises(self):
        payload = "03,12"
        line = "%" + payload + tpi_checksum(payload)
        with pytest.raises(ProtocolError):
            parse_realtime_cid(parse_frame(line))


# ────────────────────────────────────────────────────────────────────────────
# Encoding
# ────────────────────────────────────────────────────────────────────────────

class TestEncoding:
    def test_login(self):
        assert encode_login("user") == "user\r\n"

    def test_login_empty_raises(self):
        with pytest.raises(ValueError):
            encode_login("")

    def test_keystrokes_basic(self):
        line = encode_keystrokes("1234A", partition=1)
        # Must start with ^, end with \r\n, contain a checksum
        assert line.startswith("^")
        assert line.endswith("\r\n")
        # Round-trip through parse
        f = parse_frame(line.rstrip("\r\n"))
        assert f.code == "00"
        assert f.payload == "11234A"

    def test_keystrokes_partition_out_of_range(self):
        with pytest.raises(ValueError):
            encode_keystrokes("1234A", partition=99)

    def test_arm_disarm_helpers(self):
        for fn in (encode_disarm, encode_arm_away, encode_arm_stay):
            line = fn("1234", partition=1)
            assert line.startswith("^00,1")
            assert line.endswith("\r\n")

    def test_bypass_includes_zone(self):
        line = encode_bypass_zone("1234", zone=5)
        f = parse_frame(line.rstrip("\r\n"))
        # Bypass keystrokes: code + '6' + 2-digit zone
        assert f.payload == "11234605"

    def test_bypass_out_of_range(self):
        with pytest.raises(ValueError):
            encode_bypass_zone("1234", zone=999)

    def test_arm_instant_and_max_helpers(self):
        # Instant key = '7', Max key = '4' appended to the code
        assert parse_frame(encode_arm_instant("1234", 1).rstrip("\r\n")).payload == "112347"
        assert parse_frame(encode_arm_max("1234", 1).rstrip("\r\n")).payload == "112344"

    def test_six_digit_code_encodes(self):
        f = parse_frame(encode_disarm("123456", partition=1).rstrip("\r\n"))
        assert f.payload == "11234561"   # partition 1 + code 123456 + disarm key 1

    def test_multi_partition_keystrokes(self):
        for p in (1, 2, 3):
            f = parse_frame(encode_arm_away("1234", partition=p).rstrip("\r\n"))
            assert f.payload == f"{p}12342"

    def test_dump_zone_timers(self):
        line = encode_dump_zone_timers()
        f = parse_frame(line.rstrip("\r\n"))
        assert f.code == "FF"


# ────────────────────────────────────────────────────────────────────────────
# Secrets redaction — vital: user codes must never appear in logs
# ────────────────────────────────────────────────────────────────────────────

class TestRedaction:
    def test_keystroke_code_redacted(self):
        line = "^00,11234A57"
        assert "1234" not in redact_line_for_log(line)
        assert "****" in redact_line_for_log(line)

    def test_six_digit_code_redacted(self):
        line = "^00,1987654A57"
        assert "987654" not in redact_line_for_log(line)

    def test_inbound_lines_untouched(self):
        line = "%00,01,02,000,00,Ready                            FF"
        assert redact_line_for_log(line) == line

    def test_non_code_numbers_left_alone(self):
        # Zone-timer dump has lots of digits — must not be mangled
        line = "%FF,000000000000FF"
        assert redact_line_for_log(line) == line

    def test_bypass_command_code_redacted(self):
        # ^00,P<code>6<zone> — the user code must be masked
        line = encode_bypass_zone("1234", zone=5).rstrip("\r\n")
        out = redact_line_for_log(line)
        assert "1234" not in out
        assert "****" in out

    def test_multi_partition_code_redacted(self):
        line = encode_arm_away("123456", partition=3).rstrip("\r\n")
        out = redact_line_for_log(line)
        assert "123456" not in out

    def test_bare_line_passes_through(self):
        # redact_line_for_log only masks ^00 keystroke codes; a bare login line
        # is NOT its job — that is masked at source in envisalink_client (see
        # test_client.py). Confirm it is left untouched here so the client's
        # direction-aware handling is the single source of truth.
        assert redact_line_for_log("user") == "user"
