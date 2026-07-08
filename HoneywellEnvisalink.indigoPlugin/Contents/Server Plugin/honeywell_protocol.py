#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    honeywell_protocol.py
# Description: Pure-Python parser/encoder for the Envisalink TPI Honeywell protocol.
#              No I/O — TCP transport lives in envisalink_client.py.
#              Pure functions for easy testing with mock data.
# Author:      Highsteads / CliveS & Claude Opus 4.8
# Date:        07-07-2026
# Version:     0.5.1-beta
#
# References used to build this:
#   - Eyez-On Envisalink TPI specification (Honeywell)
#   - pyenvisalink (Home Assistant integration library) — honeywell_client.py +
#     honeywell_envisalinkdefs.py: the authoritative field/flag/command layout.
#   - Real-hardware capture from beta tester (Vista 20P + EVL4, 07-Jul-2026):
#       %00,01,1C08,08,00,****DISARMED****  Ready to Arm  $
#       ^FF,05$
#
# ── PROTOCOL NOTES (corrected 26-06-2026 against real hardware) ───────────────
# The Honeywell Envisalink TPI is NOT the DSC TPI. Key differences that the
# first cut of this file got wrong (every real frame parsed to a checksum error,
# so frames_rx stayed 0):
#   * Frames are `<prefix><CC>,<DATA>$` terminated by a DOLLAR SIGN, with NO
#     checksum. (DSC uses a trailing 2-hex checksum; Honeywell does not.)
#   * The prefix is `%` for async panel messages and `^` for commands / command
#     responses, and it is part of the message identity (%00 keypad update is a
#     different thing from ^00 poll-response).
#   * The virtual-keypad `%00` LED/icon field is a 16-BIT bitfield, not 8-bit.
#   * Outgoing keystrokes are sent one character at a time as `^03,<part>,<char>$`
#     (PartitionKeypress). `^00` is KeepAlive, `^02` is DumpZoneTimers.

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set


# ─────────────────────────────────────────────────────────────────────────────
# TPI message codes (prefix included — identity depends on it)
# ─────────────────────────────────────────────────────────────────────────────

# Async messages FROM the panel/module (prefix '%'), plus the poll response ('^00')
TPI_KEYPAD_UPDATE   = "%00"   # virtual keypad update (partition state + LEDs + text)
TPI_ZONE_STATE      = "%01"   # zone state bitmap
TPI_PARTITION_STATE = "%02"   # partition status (all 8 partitions)
TPI_REALTIME_CID    = "%03"   # real-time Contact ID event
TPI_ZONE_TIMER_DUMP = "%FF"   # zone timer dump (response to DumpZoneTimers)
TPI_POLL_RESPONSE   = "^00"   # response to a KeepAlive

# Outgoing command codes (sent as ^CC,DATA$ — no checksum)
CMD_KEEPALIVE          = "00"
CMD_CHANGE_PARTITION   = "01"
CMD_DUMP_ZONE_TIMERS   = "02"
CMD_PARTITION_KEYPRESS = "03"

# Honeywell keystroke keys appended to the user code
KEY_DISARM  = "1"
KEY_AWAY    = "2"
KEY_STAY    = "3"
KEY_MAX     = "4"
KEY_TEST    = "5"
KEY_BYPASS  = "6"
KEY_INSTANT = "7"
KEY_CHIME   = "9"

# 16-bit virtual-keypad icon/LED bitfield (TPI %00 field 2). Bit meanings per
# pyenvisalink honeywell_envisalinkdefs.IconLED_Bitfield.
FLAG_ALARM           = 0x0001
FLAG_ALARM_IN_MEMORY = 0x0002
FLAG_ARMED_AWAY      = 0x0004
FLAG_AC_PRESENT      = 0x0008
FLAG_BYPASS          = 0x0010
FLAG_CHIME           = 0x0020
FLAG_ARMED_NO_ENTRY  = 0x0080   # armed with zero entry delay (instant / max)
FLAG_ALARM_FIRE_ZONE = 0x0100
FLAG_SYSTEM_TROUBLE  = 0x0200
FLAG_READY           = 0x1000
FLAG_FIRE            = 0x2000
FLAG_LOW_BATTERY     = 0x4000
FLAG_ARMED_STAY      = 0x8000

# Panel models we recognise (informational)
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
    UNKNOWN           = "unknown"
    READY             = "ready"
    NOT_READY         = "not_ready"
    ARMED_AWAY        = "armed_away"
    ARMED_STAY        = "armed_stay"
    ARMED_INSTANT     = "armed_instant"
    ARMED_MAX         = "armed_max"
    ENTRY_DELAY       = "entry_delay"
    EXIT_DELAY        = "exit_delay"
    EXIT_ENTRY_DELAY  = "exit_entry_delay"   # %02 reports these combined
    ALARM             = "alarm"
    ALARM_MEMORY      = "alarm_memory"
    TROUBLE           = "trouble"


class ZoneState(Enum):
    UNKNOWN  = "unknown"
    CLOSED   = "closed"   # Indigo "off"
    OPEN     = "open"     # Indigo "on" — fault / tripped


class LoginResult(Enum):
    OK           = "ok"
    FAILED       = "failed"
    TIMEOUT      = "timeout"
    DISCONNECTED = "disconnected"


# Partition status codes from a %02 message (2 hex chars each). Per
# pyenvisalink evl_Partition_Status_Codes.
PARTITION_STATUS_CODES = {
    "00": PartitionState.UNKNOWN,          # not used / doesn't exist
    "01": PartitionState.READY,
    "02": PartitionState.READY,            # ready, zones bypassed
    "03": PartitionState.NOT_READY,
    "04": PartitionState.ARMED_STAY,
    "05": PartitionState.ARMED_AWAY,
    "06": PartitionState.ARMED_MAX,
    "07": PartitionState.EXIT_ENTRY_DELAY,
    "08": PartitionState.ALARM,
    "09": PartitionState.ALARM_MEMORY,
}

BEEP_CODES = {
    0: "off", 1: "1 beep", 2: "2 beeps", 3: "3 beeps",
    4: "continuous fast", 5: "continuous slow",
}

# The RR code in a ^CC,RR command/keepalive response. 00 = accepted; the rest
# mean the Envisalink didn't process the command cleanly.
TPI_RESPONSE_CODES = {
    "00": "command accepted",
    "01": "receive buffer overrun",
    "02": "unknown command",
    "03": "syntax error",
    "04": "receive buffer overflow",
    "05": "receive state machine timeout",
}
# Codes that mean the Envisalink is struggling to keep up with our traffic —
# a cue to poll it less often (or the tester's dreaded keypad-lockout territory).
TPI_STRAIN_CODES = frozenset({"01", "04", "05"})

# Ordered (mask, name) for human-readable decoding of the 16-bit keypad field.
FLAG_NAMES = (
    (FLAG_READY,           "ready"),
    (FLAG_ARMED_AWAY,      "armed_away"),
    (FLAG_ARMED_STAY,      "armed_stay"),
    (FLAG_ARMED_NO_ENTRY,  "armed_no_entry"),
    (FLAG_ALARM,           "alarm"),
    (FLAG_ALARM_IN_MEMORY, "alarm_in_memory"),
    (FLAG_ALARM_FIRE_ZONE, "alarm_fire_zone"),
    (FLAG_AC_PRESENT,      "ac_present"),
    (FLAG_BYPASS,          "bypass"),
    (FLAG_CHIME,           "chime"),
    (FLAG_SYSTEM_TROUBLE,  "system_trouble"),
    (FLAG_FIRE,            "fire"),
    (FLAG_LOW_BATTERY,     "low_battery"),
)

_KNOWN_FLAG_MASK = 0
for _m, _n in FLAG_NAMES:
    _KNOWN_FLAG_MASK |= _m


def flag_names(bitmap: int) -> List[str]:
    """
    Human-readable names of the set bits in a 16-bit keypad flag field. Any set
    bit we don't have a name for is surfaced as unknown(0xNNNN) — that is exactly
    the kind of thing worth spotting in a real-hardware capture (e.g. the two
    'not used' bits Honeywell sets in the wild).
    """
    names = [name for mask, name in FLAG_NAMES if bitmap & mask]
    unknown = bitmap & ~_KNOWN_FLAG_MASK & 0xFFFF
    if unknown:
        names.append(f"unknown(0x{unknown:04X})")
    return names


# ─────────────────────────────────────────────────────────────────────────────
# Parsed message dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class KeypadUpdate:
    """A virtual-keypad update (%00) — the primary Honeywell state feed."""
    partition:  int          # 1-based partition number
    led_bitmap: int          # raw 16-bit LED/icon field — test with FLAG_* constants
    zone:       int          # zone referenced in the display (0 if none)
    beep_code:  int          # 0=off .. 5=continuous slow
    display_text: str        # up to 32-char display contents

    # Derived flags (from the 16-bit bitfield)
    armed_away:      bool = field(init=False)
    armed_stay:      bool = field(init=False)
    armed_no_entry:  bool = field(init=False)   # instant / max
    ready:           bool = field(init=False)
    bypass:          bool = field(init=False)
    ac_power:        bool = field(init=False)
    chime:           bool = field(init=False)
    alarm:           bool = field(init=False)
    alarm_in_memory: bool = field(init=False)
    fire:            bool = field(init=False)
    trouble:         bool = field(init=False)
    low_battery:     bool = field(init=False)

    def __post_init__(self):
        b = self.led_bitmap
        self.armed_away      = bool(b & FLAG_ARMED_AWAY)
        self.armed_stay      = bool(b & FLAG_ARMED_STAY)
        self.armed_no_entry  = bool(b & FLAG_ARMED_NO_ENTRY)
        self.ready           = bool(b & FLAG_READY)
        self.bypass          = bool(b & FLAG_BYPASS)
        self.ac_power        = bool(b & FLAG_AC_PRESENT)
        self.chime           = bool(b & FLAG_CHIME)
        self.alarm           = bool(b & FLAG_ALARM)
        self.alarm_in_memory = bool(b & FLAG_ALARM_IN_MEMORY)
        self.fire            = bool(b & (FLAG_FIRE | FLAG_ALARM_FIRE_ZONE))
        self.trouble         = bool(b & FLAG_SYSTEM_TROUBLE)
        self.low_battery     = bool(b & FLAG_LOW_BATTERY)

    @property
    def armed(self) -> bool:
        return self.armed_away or self.armed_stay or self.armed_no_entry


@dataclass
class ZoneBitmap:
    """A zone-state message (%01) — the set of zones currently open/faulted."""
    open_zones: Set[int]


@dataclass
class PartitionStateChange:
    """One partition's high-level state (decoded from a %02 message)."""
    partition: int
    state:     PartitionState


@dataclass
class RealtimeCIDEvent:
    """Real-time Contact ID event (%03). See SIA DC-05 / Ademco CID."""
    qualifier:    int   # 1=new event, 3=restore
    event_code:   int   # 3-digit CID event code (e.g. 130 = burglary)
    partition:    int
    zone_or_user: int


@dataclass
class RawFrame:
    """A raw TPI frame received from the EVL, before typed parsing."""
    code:    str     # e.g. "%00", "%01", "^00", or a login token
    payload: str     # everything after the first comma
    raw:     str     # the full original line, for debug logging


# ─────────────────────────────────────────────────────────────────────────────
# Exceptions
# ─────────────────────────────────────────────────────────────────────────────

class ProtocolError(ValueError):
    """Raised when a message cannot be parsed."""


# ─────────────────────────────────────────────────────────────────────────────
# Frame parsing — raw line → RawFrame
# ─────────────────────────────────────────────────────────────────────────────

# Login handshake tokens (no framing, no '$')
LOGIN_TOKENS = ("Login:", "OK", "FAILED", "Timed Out!")

_FRAME_RE = re.compile(r"^([%^].+)\$$")


def parse_frame(line: str) -> RawFrame:
    """
    Parse a single Honeywell TPI line into a RawFrame.

        %CC,DATA$        async message from the panel/module
        ^CC,DATA$        command / command-response
        Login: / OK / FAILED / Timed Out!    login handshake (no framing)

    where CC is the 2-char command code and the message is terminated by '$'.
    There is NO checksum (unlike the DSC TPI).
    """
    if line is None:
        raise ProtocolError("empty line")
    line = line.rstrip("\r\n")
    if not line:
        raise ProtocolError("blank line after strip")

    if line in LOGIN_TOKENS:
        return RawFrame(code=line, payload="", raw=line)

    m = _FRAME_RE.match(line)
    if not m:
        raise ProtocolError(f"unframed TPI line (no leading %/^ or trailing $): {line!r}")

    body = m.group(1)            # e.g. "%00,01,1C08,08,00,...text..."
    prefix, rest = body[0], body[1:]
    code_digits, _, payload = rest.partition(",")
    return RawFrame(code=prefix + code_digits, payload=payload, raw=line)


# ─────────────────────────────────────────────────────────────────────────────
# Typed parsing — RawFrame → typed dataclass (or None if not this type)
# ─────────────────────────────────────────────────────────────────────────────

def parse_keypad_update(frame: RawFrame) -> Optional[KeypadUpdate]:
    """
    Virtual keypad update — %00.
    Payload: partition,flags(4-hex 16-bit),zone,beep,DISPLAYTEXT
    """
    if frame.code != TPI_KEYPAD_UPDATE:
        return None
    parts = frame.payload.split(",", 4)
    if len(parts) < 5:
        # A short "%00" (e.g. a poll/keepalive echo) is not a keypad update —
        # return None so it falls through the dispatch chain harmlessly rather
        # than raising and spamming warnings.
        return None
    try:
        partition = int(parts[0])
        flags     = int(parts[1], 16)
    except ValueError as e:
        raise ProtocolError(f"keypad update partition/flags parse error: {e}") from e
    # zone and beep are informational. Some frames put non-decimal values here —
    # e.g. a real Vista sends "%00,01,0008,CA,20,Alarm Canceled" — so tolerate
    # them (default 0) rather than dropping the whole frame; the flags and display
    # text are what actually drive the partition state.
    zone = int(parts[2]) if parts[2].strip().isdigit() else 0
    beep = int(parts[3]) if parts[3].strip().isdigit() else 0
    display = parts[4][:32]
    return KeypadUpdate(partition=partition, led_bitmap=flags, zone=zone,
                        beep_code=beep, display_text=display)


def _decode_zone_bitmap(hexdata: str) -> Set[int]:
    """
    Decode a %01 zone bitmap into the set of open (faulted) zone numbers.

    The dump is a hex string processed in 4-char (16-bit) chunks; within each
    chunk the two bytes are little-endian, and the bits run low-zone-first.
    Mirrors pyenvisalink handle_zone_state_change. NB: unverified against real
    hardware for this plugin — the beta tester's panel had not yet streamed a
    %01 at capture time.
    """
    open_zones: Set[int] = set()
    zone = 1
    for i in range(0, len(hexdata) - (len(hexdata) % 4), 4):
        chunk = hexdata[i:i + 4]
        try:
            value = int(chunk[2:4] + chunk[0:2], 16)   # swap bytes → big-endian
        except ValueError:
            zone += 16
            continue
        for bit in range(16):                          # low zone first
            if value & (1 << bit):
                open_zones.add(zone)
            zone += 1
    return open_zones


def decode_zone_timer_dump(payload: str) -> dict:
    """
    Split a %FF zone-timer-dump payload into per-zone 16-bit values. Each zone is
    a 4-hex little-endian word; returns {zone_number: raw_value} for non-zero
    zones only. This preserves the STRUCTURE for analysis — the exact SEMANTICS
    of the value (seconds since fault / countdown) are not yet verified on
    hardware, so we don't interpret it here.
    """
    timers = {}
    zone = 1
    hexdata = payload.strip()
    for i in range(0, len(hexdata) - (len(hexdata) % 4), 4):
        chunk = hexdata[i:i + 4]
        try:
            value = int(chunk[2:4] + chunk[0:2], 16)   # little-endian word
        except ValueError:
            value = 0
        if value:
            timers[zone] = value
        zone += 1
    return timers


def open_zones_from_timer_dump(payload: str) -> Set[int]:
    """
    The set of zones currently OPEN according to a %FF zone-timer dump.

    Each zone is a 4-hex little-endian word. The word is best read as
    ``0xFFFF`` when the zone was just faulted, counting down as time passes since
    the last fault, so ``ticks = 0xFFFF - value`` is "how long ago it faulted".
    A zone is treated as open when ``ticks <= 3`` — i.e. faulted within the last
    few ticks. This matches pyenvisalink's ``is_zone_open_from_zonedump`` and was
    cross-checked against a real Vista 20P dump (the one open motion zone read
    exactly 3 ticks; every unused/closed zone read far higher).
    """
    open_zones: Set[int] = set()
    hexdata = payload.strip()
    zone = 1
    for i in range(0, len(hexdata) - (len(hexdata) % 4), 4):
        chunk = hexdata[i:i + 4]
        try:
            value = int(chunk[2:4] + chunk[0:2], 16)   # little-endian → int
        except ValueError:
            zone += 1
            continue
        if (0xFFFF - value) <= 3:
            open_zones.add(zone)
        zone += 1
    return open_zones


def parse_zone_state(frame: RawFrame) -> Optional[ZoneBitmap]:
    """Zone state change — %01. Payload is a hex bitmap of open zones."""
    if frame.code != TPI_ZONE_STATE:
        return None
    hexdata = frame.payload.strip()
    if not hexdata:
        raise ProtocolError(f"zone state message empty: {frame.payload!r}")
    return ZoneBitmap(open_zones=_decode_zone_bitmap(hexdata))


def parse_partition_state(frame: RawFrame) -> Optional[List[PartitionStateChange]]:
    """
    Partition state change — %02.
    Payload is 16 hex chars (8 partitions × 2), each a partition status code.
    Returns a list of PartitionStateChange for every in-use partition.
    """
    if frame.code != TPI_PARTITION_STATE:
        return None
    data = frame.payload.strip()
    changes: List[PartitionStateChange] = []
    for idx in range(0, min(len(data), 16), 2):
        code = data[idx:idx + 2]
        if len(code) < 2 or code == "00":
            continue                                    # 00 = partition not used
        state = PARTITION_STATUS_CODES.get(code.upper(), PartitionState.UNKNOWN)
        changes.append(PartitionStateChange(partition=(idx // 2) + 1, state=state))
    return changes


def parse_realtime_cid(frame: RawFrame) -> Optional[RealtimeCIDEvent]:
    """
    Real-time Contact ID event — %03.
    Payload: Q EEE PP ZZZ  (qualifier, 3-digit event, 2-digit partition,
    3-digit zone/user), optionally comma-delimited.
    """
    if frame.code != TPI_REALTIME_CID:
        return None
    fields = [f for f in frame.payload.split(",") if f != ""]
    try:
        if len(fields) >= 4:
            qualifier, event_code, partition, zone_or_user = (
                int(fields[0]), int(fields[1]), int(fields[2]), int(fields[3]))
        else:
            p = frame.payload.replace(",", "")
            if len(p) < 9:
                raise ProtocolError(f"CID event too short: {frame.payload!r}")
            qualifier    = int(p[0])
            event_code   = int(p[1:4])
            partition    = int(p[4:6])
            zone_or_user = int(p[6:9])
    except ValueError as e:
        raise ProtocolError(f"CID field parse error: {e}") from e
    return RealtimeCIDEvent(qualifier=qualifier, event_code=event_code,
                            partition=partition, zone_or_user=zone_or_user)


def derive_partition_state(ku: KeypadUpdate) -> PartitionState:
    """
    Derive a high-level partition state from a %00 keypad update. This is the
    primary state source for Honeywell (the panel streams %00 constantly). The
    16-bit LED flags decide armed/ready/alarm; the display text disambiguates
    exit vs entry delay and instant vs max vs stay.
    """
    text = ku.display_text.upper()
    if ku.alarm:
        return PartitionState.ALARM
    if ku.alarm_in_memory or "ALARM MEMORY" in text:
        return PartitionState.ALARM_MEMORY
    if "MAY EXIT NOW" in text or "EXIT NOW" in text:
        return PartitionState.EXIT_DELAY
    if "DISARM SYSTEM OR ALARM" in text or "ENTRY" in text:
        return PartitionState.ENTRY_DELAY
    if ku.armed:
        if "INSTANT" in text:
            return PartitionState.ARMED_INSTANT
        if "MAXIMUM" in text:
            return PartitionState.ARMED_MAX
        if ku.armed_stay or "STAY" in text:
            return PartitionState.ARMED_STAY
        if ku.armed_no_entry:
            return PartitionState.ARMED_INSTANT
        return PartitionState.ARMED_AWAY
    if ku.trouble:
        return PartitionState.TROUBLE
    if ku.ready:
        return PartitionState.READY
    return PartitionState.NOT_READY


# ─────────────────────────────────────────────────────────────────────────────
# Encoding — client → EVL commands (^CC,DATA$ — no checksum)
# ─────────────────────────────────────────────────────────────────────────────

def encode_command(code: str, data: str = "") -> str:
    """Frame an outgoing command: ^CC,DATA$ + CRLF. No checksum."""
    return f"^{code},{data}$\r\n"


def encode_login(password: str) -> str:
    """First message after the 'Login:' prompt — the bare password + CRLF."""
    if not password:
        raise ValueError("password is required")
    return password + "\r\n"


def encode_keepalive() -> str:
    """KeepAlive poll — ^00,$."""
    return encode_command(CMD_KEEPALIVE, "")


def encode_dump_zone_timers() -> str:
    """Request a zone-timer dump — ^02,$."""
    return encode_command(CMD_DUMP_ZONE_TIMERS, "")


def encode_keypress(partition: int, char: str) -> str:
    """One virtual keypress on a partition — ^03,<partition>,<char>$."""
    if partition < 1 or partition > 8:
        raise ValueError(f"partition out of range: {partition}")
    if len(char) != 1:
        raise ValueError(f"keypress must be a single character: {char!r}")
    return encode_command(CMD_PARTITION_KEYPRESS, f"{partition},{char}")


def encode_keystroke_sequence(keys: str, partition: int = 1) -> List[str]:
    """
    A sequence of keystrokes as individual PartitionKeypress commands. Honeywell
    sends one character per command (there is no bundled-keystroke command).
    """
    if partition < 1 or partition > 8:
        raise ValueError(f"partition out of range: {partition}")
    if not keys:
        raise ValueError("keys is required")
    return [encode_keypress(partition, c) for c in keys]


def encode_disarm(code: str, partition: int = 1) -> List[str]:
    return encode_keystroke_sequence(code + KEY_DISARM, partition)


def encode_arm_away(code: str, partition: int = 1) -> List[str]:
    return encode_keystroke_sequence(code + KEY_AWAY, partition)


def encode_arm_stay(code: str, partition: int = 1) -> List[str]:
    return encode_keystroke_sequence(code + KEY_STAY, partition)


def encode_arm_instant(code: str, partition: int = 1) -> List[str]:
    return encode_keystroke_sequence(code + KEY_INSTANT, partition)


def encode_arm_max(code: str, partition: int = 1) -> List[str]:
    return encode_keystroke_sequence(code + KEY_MAX, partition)


def encode_bypass_zone(code: str, zone: int, partition: int = 1) -> List[str]:
    if zone < 1 or zone > 250:
        raise ValueError(f"zone out of range: {zone}")
    return encode_keystroke_sequence(f"{code}{KEY_BYPASS}{zone:02d}", partition)


# ─────────────────────────────────────────────────────────────────────────────
# Secrets redaction — never log user codes
# ─────────────────────────────────────────────────────────────────────────────

# A user code goes out one digit at a time as ^03,<partition>,<digit>$. Mask the
# digit so a keypress sequence can't be reassembled from the log. (The bare login
# password is masked at source in envisalink_client._record_debug.)
_KEYPRESS_DIGIT = re.compile(r"(\^03,\d+,)(\d)")


def redact_line_for_log(line: str) -> str:
    """Replace the digit in an outgoing partition-keypress command with '*'."""
    return _KEYPRESS_DIGIT.sub(lambda m: m.group(1) + "*", line)
