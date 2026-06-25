#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    honeywell_protocol.py
# Description: Pure-Python parser/encoder for the Envisalink TPI Honeywell protocol.
#              No I/O — TCP transport lives in envisalink_client.py.
#              Pure functions for easy testing with mock data.
# Author:      Highsteads / CliveS & Claude Opus 4.8
# Date:        25-06-2026
# Version:     0.2.0-beta
#
# References used to build this:
#   - Eyez-On Envisalink TPI specification (Honeywell)
#   - pyenvisalink (Home Assistant integration library)
#   - Indigo AD2USB plugin (same panel protocol over USB instead of network)
#   - Indigo DSC plugin (same Envisalink, different panel protocol — used for
#     overall plugin structure reference)
#
# Coverage goals:
#   - All Vista panels supported by Envisalink (15P, 20P, 21iP, 128BP, 250BP)
#   - EVL3 and EVL4 hardware
#   - 1-3 partitions
#   - Up to 250 zones (per Vista 250BP max)
#
# Compatibility notes are inline as we encounter model-specific quirks.

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# Envisalink TPI command codes (server → client and client → server)
TPI_LOGIN              = "005"   # Login interaction
TPI_KEYPAD_UPDATE      = "00"    # Virtual keypad update (Honeywell)
TPI_ZONE_STATE_CHANGE  = "01"    # Zone state change
TPI_PARTITION_STATE    = "02"    # Partition state change
TPI_REALTIME_CID_EVENT = "03"    # Real-time Contact ID event
TPI_ZONE_TIMER_DUMP    = "FF"    # Zone timer dump (response to poll)
TPI_KEEP_ALIVE         = "00"    # Keep-alive (EVL → client periodic)
TPI_COMMAND_RESPONSE   = "%"     # Command echo / acknowledgement prefix

# Honeywell keystroke commands appended to user code:
KEY_DISARM         = "1"
KEY_AWAY           = "2"
KEY_STAY           = "3"
KEY_INSTANT        = "7"
KEY_MAX            = "4"
KEY_TEST           = "5"
KEY_BYPASS         = "6"
KEY_CHIME          = "9"

# LED bit positions in keypad update messages
LED_ARMED          = 0x01
LED_READY          = 0x02
LED_TROUBLE        = 0x04
LED_BYPASS         = 0x08
LED_AC_POWER       = 0x10
LED_CHIME          = 0x20
LED_ALARM_OCCURRED = 0x40
LED_ALARM          = 0x80

# Panel models we recognise from keypad update text
VISTA_MODELS = (
    "VISTA-15",   "VISTA-15P",
    "VISTA-20",   "VISTA-20P",  "VISTA-21IP",
    "VISTA-128",  "VISTA-128BP",
    "VISTA-250",  "VISTA-250BP",
)


# ─────────────────────────────────────────────────────────────────────────────
# Enumerations
# ─────────────────────────────────────────────────────────────────────────────

class PartitionState(Enum):
    UNKNOWN          = "unknown"
    READY            = "ready"
    NOT_READY        = "not_ready"
    ARMED_AWAY       = "armed_away"
    ARMED_STAY       = "armed_stay"
    ARMED_INSTANT    = "armed_instant"
    ARMED_MAX        = "armed_max"
    ENTRY_DELAY      = "entry_delay"
    EXIT_DELAY       = "exit_delay"
    ALARM            = "alarm"
    ALARM_MEMORY     = "alarm_memory"
    TROUBLE          = "trouble"


class ZoneState(Enum):
    UNKNOWN  = "unknown"
    CLOSED   = "closed"   # Indigo "off"
    OPEN     = "open"     # Indigo "on" — fault / tripped
    BYPASS   = "bypass"
    TROUBLE  = "trouble"
    ALARM    = "alarm"


class LoginResult(Enum):
    OK           = "ok"
    FAILED       = "failed"
    TIMEOUT      = "timeout"
    DISCONNECTED = "disconnected"


# ─────────────────────────────────────────────────────────────────────────────
# Parsed message dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class KeypadUpdate:
    """
    Mirrors a physical Vista keypad: 16x2 LCD, beeps, LED state.
    Sent asynchronously by EVL whenever the panel display would change.
    """
    partition: int          # 1-based partition number
    led_bitmap: int         # raw LED byte — use LED_* constants to test bits
    zone: int               # zone number referenced in the display (0 if none)
    beep_code: int          # 0=none, 1=continuous, 2..N=N short beeps, etc.
    display_text: str       # 32-char display contents

    # Derived
    armed:          bool = field(init=False)
    ready:          bool = field(init=False)
    trouble:        bool = field(init=False)
    bypass:         bool = field(init=False)
    ac_power:       bool = field(init=False)
    chime:          bool = field(init=False)
    alarm:          bool = field(init=False)
    alarm_occurred: bool = field(init=False)   # 0x40 — alarm in memory (occurred, now cleared)

    def __post_init__(self):
        self.armed          = bool(self.led_bitmap & LED_ARMED)
        self.ready          = bool(self.led_bitmap & LED_READY)
        self.trouble        = bool(self.led_bitmap & LED_TROUBLE)
        self.bypass         = bool(self.led_bitmap & LED_BYPASS)
        self.ac_power       = bool(self.led_bitmap & LED_AC_POWER)
        self.chime          = bool(self.led_bitmap & LED_CHIME)
        self.alarm          = bool(self.led_bitmap & LED_ALARM)
        self.alarm_occurred = bool(self.led_bitmap & LED_ALARM_OCCURRED)


@dataclass
class ZoneStateChange:
    """Zone went from one state to another (open/closed/bypass/alarm/trouble)."""
    zone:  int
    state: ZoneState


@dataclass
class PartitionStateChange:
    """Partition entered a new high-level state."""
    partition: int
    state:     PartitionState


@dataclass
class RealtimeCIDEvent:
    """
    Real-time Contact ID event — the raw alarm-monitoring format.
    See SIA DC-05 / Ademco CID spec for code meanings.
    """
    qualifier:    int   # 1=new event, 3=restore
    event_code:   int   # 3-digit CID event code (e.g. 130 = burglary)
    partition:    int
    zone_or_user: int


@dataclass
class RawFrame:
    """A raw TPI frame received from the EVL, before parsing into a typed message."""
    code:    str     # e.g. "00", "01", "FF"
    payload: str     # everything after the comma, before the terminator
    raw:     str     # the full original line for debug logging


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────

class ProtocolError(ValueError):
    """Raised when a message cannot be parsed."""


class ChecksumError(ProtocolError):
    """Raised when an incoming message has a bad TPI checksum."""


# ─────────────────────────────────────────────────────────────────────────────
# Checksum helpers
# ─────────────────────────────────────────────────────────────────────────────

def tpi_checksum(payload: str) -> str:
    """
    TPI checksum: sum of ASCII values mod 256, expressed as two uppercase hex digits.
    Applies to everything in the message except the trailing CRLF.
    """
    total = 0
    for c in payload:
        total = (total + ord(c)) & 0xFF
    return f"{total:02X}"


def verify_checksum(line: str) -> str:
    """
    Strip and verify the trailing 2-char checksum from a TPI line.
    Returns the payload without the checksum. Raises ChecksumError on mismatch.
    """
    if len(line) < 3:
        raise ProtocolError(f"line too short for checksum: {line!r}")
    body, sup_chk = line[:-2], line[-2:]
    actual = tpi_checksum(body)
    if actual.upper() != sup_chk.upper():
        raise ChecksumError(f"checksum mismatch: expected {actual}, got {sup_chk}")
    return body


def append_checksum(payload: str) -> str:
    """Append the TPI checksum to a payload (no trailing CRLF added)."""
    return payload + tpi_checksum(payload)


# ─────────────────────────────────────────────────────────────────────────────
# Frame parsing — raw line → RawFrame
# ─────────────────────────────────────────────────────────────────────────────

def parse_frame(line: str, verify_checksums: bool = True) -> RawFrame:
    """
    Parse a single TPI line into a RawFrame. Lines look like:

        ^cc,payloadCC\r\n          (client → server, '^' prefix)
        %cc,payloadCC\r\n          (server → client async, '%' prefix)
        cc,payloadCC\r\n           (some server messages lack the prefix)
        Login:                     (login prompt — special case)
        OK / FAILED                (login result — special case)

    where cc is the 2-char command code and CC is the 2-char checksum.

    If verify_checksums is False (useful for tests with hand-typed fixtures),
    the checksum is stripped but not validated.
    """
    if not line:
        raise ProtocolError("empty line")
    line = line.rstrip("\r\n")
    if not line:
        raise ProtocolError("blank line after strip")

    # Special: non-checksum login prompts
    if line in ("Login:", "OK", "FAILED"):
        return RawFrame(code=line, payload="", raw=line)

    # Strip leading prefix if present
    prefix = ""
    if line[0] in ("^", "%"):
        prefix, line = line[0], line[1:]

    if verify_checksums:
        body = verify_checksum(line)
    else:
        # Strip the assumed 2 trailing chars without verifying
        body = line[:-2] if len(line) > 2 else line

    if "," not in body:
        # Some short responses have no comma — treat whole body as code
        return RawFrame(code=body, payload="", raw=prefix + line)

    code, _, payload = body.partition(",")
    return RawFrame(code=code, payload=payload, raw=prefix + line)


# ─────────────────────────────────────────────────────────────────────────────
# Typed parsing — RawFrame → typed dataclass (or None if not interesting)
# ─────────────────────────────────────────────────────────────────────────────

def parse_keypad_update(frame: RawFrame) -> Optional[KeypadUpdate]:
    """
    Honeywell keypad update — TPI code "00".
    Payload format (typical):
        PP,LL,ZZ,BB,DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD
    where:
        PP = partition (decimal)
        LL = LED bitmap (hex byte)
        ZZ = zone reference (decimal)
        BB = beep code (decimal)
        D… = 32-character display text
    """
    if frame.code != TPI_KEYPAD_UPDATE:
        return None
    parts = frame.payload.split(",", 4)
    if len(parts) < 5:
        # TPI code "00" is overloaded: a full keypad update has 5 fields, but the
        # EVL also sends short "00" keep-alive frames. Return None (not interesting)
        # rather than raising so a keep-alive falls through the dispatch chain
        # quietly instead of spamming "frame handler error" warnings on real kit.
        return None
    try:
        partition = int(parts[0])
        led       = int(parts[1], 16)
        zone      = int(parts[2])
        beep      = int(parts[3])
    except ValueError as e:
        raise ProtocolError(f"keypad update field parse error: {e}") from e
    display = parts[4][:32].ljust(32)
    return KeypadUpdate(partition=partition, led_bitmap=led, zone=zone,
                        beep_code=beep, display_text=display)


def parse_zone_state(frame: RawFrame) -> Optional[ZoneStateChange]:
    """
    Zone state change — TPI code "01".
    Payload: ZZZ,S where ZZZ is 3-digit zone and S is single-char state code.
    """
    if frame.code != TPI_ZONE_STATE_CHANGE:
        return None
    parts = frame.payload.split(",", 1)
    if len(parts) != 2:
        raise ProtocolError(f"zone state change malformed: {frame.payload!r}")
    try:
        zone = int(parts[0])
    except ValueError as e:
        raise ProtocolError(f"bad zone number: {e}") from e
    state_char = parts[1].strip().upper()[:1]
    state_map = {
        "C": ZoneState.CLOSED,
        "O": ZoneState.OPEN,
        "B": ZoneState.BYPASS,
        "T": ZoneState.TROUBLE,
        "A": ZoneState.ALARM,
    }
    return ZoneStateChange(zone=zone, state=state_map.get(state_char, ZoneState.UNKNOWN))


def parse_partition_state(frame: RawFrame) -> Optional[PartitionStateChange]:
    """
    Partition state change — TPI code "02".
    Payload: P,STATE where STATE is one of the panel state codes.
    """
    if frame.code != TPI_PARTITION_STATE:
        return None
    parts = frame.payload.split(",", 1)
    if len(parts) != 2:
        raise ProtocolError(f"partition state malformed: {frame.payload!r}")
    try:
        partition = int(parts[0])
    except ValueError as e:
        raise ProtocolError(f"bad partition number: {e}") from e
    state_code = parts[1].strip().upper()
    state_map = {
        "READY":         PartitionState.READY,
        "NOT_READY":     PartitionState.NOT_READY,
        "ARMED_AWAY":    PartitionState.ARMED_AWAY,
        "ARMED_STAY":    PartitionState.ARMED_STAY,
        "ARMED_INSTANT": PartitionState.ARMED_INSTANT,
        "ARMED_MAX":     PartitionState.ARMED_MAX,
        "ENTRY_DELAY":   PartitionState.ENTRY_DELAY,
        "EXIT_DELAY":    PartitionState.EXIT_DELAY,
        "ALARM":         PartitionState.ALARM,
        "ALARM_MEMORY":  PartitionState.ALARM_MEMORY,
        "TROUBLE":       PartitionState.TROUBLE,
    }
    return PartitionStateChange(
        partition=partition,
        state=state_map.get(state_code, PartitionState.UNKNOWN),
    )


def parse_realtime_cid(frame: RawFrame) -> Optional[RealtimeCIDEvent]:
    """
    Real-time Contact ID event — TPI code "03".
    Payload: QXXXPPZZZZ or Q,XXX,PP,ZZZZ depending on EVL firmware.
    """
    if frame.code != TPI_REALTIME_CID_EVENT:
        return None
    # Two firmware variants: a comma-delimited form (Q,XXX,PP,ZZZZ) and a
    # concatenated form (QXXXPPZZZZ). For the comma form, split positionally —
    # comma-stripping then fixed-offset slicing mis-attributes partition/zone
    # whenever a field is not exactly the documented width (e.g. a 1-digit
    # partition or 3-digit user shifts every later slice).
    fields = [f for f in frame.payload.split(",") if f != ""]
    try:
        if len(fields) >= 4:
            qualifier    = int(fields[0])
            event_code   = int(fields[1])
            partition    = int(fields[2])
            zone_or_user = int(fields[3])
        else:
            p = frame.payload.replace(",", "")
            if len(p) < 9:
                raise ProtocolError(f"CID event too short: {frame.payload!r}")
            qualifier    = int(p[0])
            event_code   = int(p[1:4])
            partition    = int(p[4:6])
            zone_or_user = int(p[6:10]) if len(p) >= 10 else int(p[6:9])
    except ValueError as e:
        raise ProtocolError(f"CID field parse error: {e}") from e
    return RealtimeCIDEvent(
        qualifier=qualifier, event_code=event_code,
        partition=partition, zone_or_user=zone_or_user,
    )


def derive_partition_state(ku: KeypadUpdate) -> PartitionState:
    """
    Derive a high-level partition state from a keypad update — useful as a
    fallback when the EVL doesn't push a separate "02" partition state message
    (some firmware versions only push keypad updates).
    """
    text = ku.display_text.upper()
    if ku.alarm:
        return PartitionState.ALARM
    if ku.alarm_occurred or "ALARM MEMORY" in text:
        return PartitionState.ALARM_MEMORY
    if "MAY EXIT NOW" in text or "EXIT NOW" in text:
        return PartitionState.EXIT_DELAY
    if "DISARM SYSTEM OR ALARM" in text or "ENTRY" in text:
        return PartitionState.ENTRY_DELAY
    if ku.armed:
        # Order matters, but each token is now unambiguous: "INSTANT", "MAXIMUM"
        # and "STAY" never appear as substrings of one another. (The old bare
        # "MAX" test could in principle match other text — dropped.)
        if "INSTANT" in text:
            return PartitionState.ARMED_INSTANT
        if "MAXIMUM" in text:
            return PartitionState.ARMED_MAX
        if "STAY" in text:
            return PartitionState.ARMED_STAY
        return PartitionState.ARMED_AWAY
    if ku.trouble:
        return PartitionState.TROUBLE
    if ku.ready:
        return PartitionState.READY
    return PartitionState.NOT_READY


# ─────────────────────────────────────────────────────────────────────────────
# Encoding — client → EVL commands
# ─────────────────────────────────────────────────────────────────────────────

def encode_login(password: str) -> str:
    """First message sent after EVL prompts 'Login:'. Just the password + CRLF."""
    if not password:
        raise ValueError("password is required")
    return password + "\r\n"


def encode_keystrokes(keys: str, partition: int = 1) -> str:
    """
    Send raw keystrokes to the panel as if typed on a keypad.
    Format: ^00,PKEYS where P is the partition byte and KEYS the keys.

    Example: arm partition 1 away with code 1234:
        encode_keystrokes("12342", partition=1)
    """
    if partition < 1 or partition > 8:
        raise ValueError(f"partition out of range: {partition}")
    if not keys:
        raise ValueError("keys is required")
    payload = f"00,{partition}{keys}"
    return "^" + append_checksum(payload) + "\r\n"


def encode_dump_zone_timers() -> str:
    """Request a one-shot dump of all zone last-seen timers (TPI 'FF')."""
    payload = "FF,00"
    return "^" + append_checksum(payload) + "\r\n"


def encode_disarm(code: str, partition: int = 1) -> str:
    return encode_keystrokes(code + KEY_DISARM, partition)


def encode_arm_away(code: str, partition: int = 1) -> str:
    return encode_keystrokes(code + KEY_AWAY, partition)


def encode_arm_stay(code: str, partition: int = 1) -> str:
    return encode_keystrokes(code + KEY_STAY, partition)


def encode_arm_instant(code: str, partition: int = 1) -> str:
    return encode_keystrokes(code + KEY_INSTANT, partition)


def encode_arm_max(code: str, partition: int = 1) -> str:
    return encode_keystrokes(code + KEY_MAX, partition)


def encode_bypass_zone(code: str, zone: int, partition: int = 1) -> str:
    if zone < 1 or zone > 250:
        raise ValueError(f"zone out of range: {zone}")
    keys = f"{code}{KEY_BYPASS}{zone:02d}"
    return encode_keystrokes(keys, partition)


# ─────────────────────────────────────────────────────────────────────────────
# Secrets redaction — never log user codes
# ─────────────────────────────────────────────────────────────────────────────

# Matches the user-code digits in an outgoing keystroke command (^00,P<code>…).
# The digit run is greedy and deliberately wide (3-8) so we over-mask rather than
# under-mask if the code length ever changes. NB this only covers keystroke
# commands — a bare login password is masked at source in envisalink_client.py
# (the recv-loop login branch), never recorded through this path.
_CODE_PATTERN = re.compile(r"(\^00,\d)(\d{3,8})")

def redact_line_for_log(line: str) -> str:
    """
    Replace user codes in outgoing keystroke commands with '****'.
    Inbound lines are left unchanged.
    """
    return _CODE_PATTERN.sub(lambda m: m.group(1) + "****", line)
