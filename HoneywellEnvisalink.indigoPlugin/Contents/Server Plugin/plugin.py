#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: HoneywellEnvisalink — Indigo plugin connecting Honeywell Vista
#              alarm panels to Indigo via Envisalink network modules (EVL3/EVL4).
# Author:      Highsteads / CliveS & Claude Opus 4.8
# Date:        07-07-2026
# Version:     0.4.1-beta
# Plugin ID:   com.clives.indigoplugin.honeywell-envisalink

import os as _os
import sys as _sys
_sys.path.insert(0, _os.getcwd())

import indigo
import json
import logging
import threading
import time
from datetime import datetime

import tpi_capture

from honeywell_protocol import (
    KeypadUpdate, ZoneBitmap, RealtimeCIDEvent,
    PartitionState, LoginResult,
    parse_keypad_update, parse_zone_state, parse_partition_state, parse_realtime_cid,
    derive_partition_state,
    encode_disarm, encode_arm_away, encode_arm_stay, encode_arm_instant,
    encode_arm_max, encode_bypass_zone, encode_dump_zone_timers,
)
from envisalink_client import EnvisalinkClient

# Optional: startup banner — bundled with the plugin
try:
    from plugin_utils import log_startup_banner
except ImportError:
    log_startup_banner = None

# Optional: IndigoSecrets pattern
_sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
try:
    from IndigoSecrets import ENVISALINK_PASSWORD
except ImportError:
    ENVISALINK_PASSWORD = ""

PLUGIN_VERSION = "0.4.1-beta"
PLUGIN_ID = "com.clives.indigoplugin.honeywell-envisalink"

DEFAULT_PORT = 4025


def _as_bool(value, default=False):
    """Coerce a pluginPrefs/valuesDict value to a real bool.

    Indigo checkbox fields normally round-trip as Python bools, but a value that
    has ever been serialised as the string "true"/"false" (or is blank) would be
    truthy/ambiguous under a bare `if value:`. This normalises both forms.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "on"):
            return True
        if v in ("false", "0", "no", "off", ""):
            return False
    return bool(value)


def _as_port(value, default=DEFAULT_PORT):
    """Coerce a port pref to a valid int, falling back safely on blank/bad input."""
    try:
        port = int(str(value).strip())
    except (ValueError, TypeError, AttributeError):
        return default
    return port if 1 <= port <= 65535 else default


class Plugin(indigo.PluginBase):

    def __init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs):
        indigo.PluginBase.__init__(self, pluginId, pluginDisplayName, pluginVersion, pluginPrefs)

        # Lifted from PluginConfig. Coerce defensively — a textfield cleared in the
        # config dialog comes back as "" (not the .get default), so int("") would
        # raise ValueError here in __init__ and abort the whole plugin.
        self.host = pluginPrefs.get("host", "")
        self.port = _as_port(pluginPrefs.get("port", DEFAULT_PORT))
        # Password: IndigoSecrets > PluginConfig > error
        self.password = ENVISALINK_PASSWORD or pluginPrefs.get("password", "")
        # SAFETY: test_mode prevents real arm/disarm commands from leaving Indigo.
        # Defaults TRUE so a fresh install can't accidentally do something destructive.
        self.test_mode = _as_bool(pluginPrefs.get("test_mode", True), default=True)
        self.debug_protocol = _as_bool(pluginPrefs.get("debug_protocol", False))
        self.debug_logging = _as_bool(pluginPrefs.get("debug_logging", False))

        self.debug = self.debug_logging   # Indigo's base class uses self.debug

        # Tracked Indigo devices, keyed by their internal device ID
        self.panel_dev = None
        self.partition_devs = {}   # partition_number → indigo.device
        self.zone_devs = {}        # zone_number → indigo.device
        self.partition_last_event = {}   # partition → last fired event id (de-spam)

        # Triggers registered by users for our custom events
        self.event_triggers = {}

        # EVL client (created on startup)
        self.client = None

        # Protocol capture (menu-driven, read-only) — None unless a capture is running
        self._capture = None
        self._capture_timer = None

        # Startup banner moved to showPluginInfo on demand (revised 25-May-2026 per Jay).

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def startup(self):
        self.logger.info("startup")
        if not self.host:
            # Not an ERROR — just the expected state of a fresh install.
            # Logged at INFO so it doesn't show as red in the event log.
            self.logger.info(
                "Waiting for configuration — open Plugins → HoneywellEnvisalink → Configure "
                "to set your Envisalink host and password."
            )
            return
        if not self.password:
            self.logger.info(
                "Waiting for EVL password — either define ENVISALINK_PASSWORD in IndigoSecrets.py "
                "or enter it in Plugins → HoneywellEnvisalink → Configure."
            )
            return
        self._start_client()

    def shutdown(self):
        self.logger.info("shutdown")
        if self._capture_timer:
            self._capture_timer.cancel()
            self._capture_timer = None
        self._capture = None
        if self.client:
            self.client.stop()
            self.client = None

    # ── Mac sleep / wake — close TCP socket to EVL cleanly on sleep so the
    # ── board doesn't hold our previous session, then reconnect on wake.
    # ── Mirrors startup() guards so a blank-config state doesn't loop-retry.
    def prepare_to_sleep(self):
        self.logger.info("Mac going to sleep — disconnecting from Envisalink")
        if self.client:
            self.client.stop()
            self.client = None
        super().prepare_to_sleep()
    prepareToSleep = prepare_to_sleep

    def wake_up(self):
        self.logger.info("Mac woke — reconnecting to Envisalink")
        super().wake_up()
        if self.host and self.password:
            self._start_client()
        else:
            self.logger.info(
                "EVL not configured — staying disconnected. Open Plugins → "
                "HoneywellEnvisalink → Configure to set host/password."
            )
    wakeUp = wake_up

    def _start_client(self):
        if self.client:
            self.client.stop()
        self.client = EnvisalinkClient(
            host=self.host,
            password=self.password,
            on_frame=self._on_frame,
            on_login=self._on_login,
            on_disconnect=self._on_disconnect,
            logger=self.logger,
            port=self.port,
            debug_protocol=self.debug_protocol,
            on_raw_line=self._on_raw_line,
        )
        self.client.start()
        self.logger.info(f"started EVL client → {self.host}:{self.port}")

    def validatePrefsConfigUi(self, valuesDict):
        errs = indigo.Dict()
        port = (valuesDict.get("port") or "").strip()
        if port:
            try:
                p = int(port)
                if not (1 <= p <= 65535):
                    raise ValueError
            except (ValueError, TypeError):
                errs["port"] = "Port must be a whole number between 1 and 65535 (default 4025)."
        if errs:
            return (False, valuesDict, errs)
        return (True, valuesDict)

    def closedPrefsConfigUi(self, valuesDict, userCancelled):
        if userCancelled:
            return
        # Pick up changes (coerce defensively — see __init__)
        self.host = valuesDict.get("host", "")
        self.port = _as_port(valuesDict.get("port", DEFAULT_PORT))
        self.password = ENVISALINK_PASSWORD or valuesDict.get("password", "")
        self.test_mode = _as_bool(valuesDict.get("test_mode", True), default=True)
        self.debug_protocol = _as_bool(valuesDict.get("debug_protocol", False))
        self.debug_logging = _as_bool(valuesDict.get("debug_logging", False))
        self.debug = self.debug_logging

        # Guard: same checks as startup() — don't kick off a connection loop
        # that can only fail. Stop any existing client so a previously-good
        # config that was then blanked doesn't keep retrying in the background.
        if not self.host:
            self.logger.error("No EVL host configured — connection not started.")
            if self.client:
                self.client.stop()
                self.client = None
            return
        if not self.password:
            self.logger.error(
                "No EVL password set — connection not started. "
                "Either define ENVISALINK_PASSWORD in IndigoSecrets.py or "
                "enter it in Plugins → HoneywellEnvisalink → Configure."
            )
            if self.client:
                self.client.stop()
                self.client = None
            return

        self.logger.info("config saved — restarting EVL client")
        self._start_client()

    # ── Device lifecycle ──────────────────────────────────────────────────

    def deviceStartComm(self, dev):
        super().deviceStartComm(dev)
        # Loop guard — we own all device types from this plugin
        if dev.pluginId != self.pluginId:
            return
        if dev.deviceTypeId == "panel":
            self.panel_dev = dev
        elif dev.deviceTypeId == "partition":
            try:
                pnum = int(dev.pluginProps.get("partition_number", "1"))
                self.partition_devs[pnum] = dev
            except ValueError:
                self.logger.error(f"{dev.name}: invalid partition_number, skipping")
        elif dev.deviceTypeId == "zone":
            try:
                znum = int(dev.pluginProps.get("zone_number", "0"))
                if znum:
                    self.zone_devs[znum] = dev
            except ValueError:
                self.logger.error(f"{dev.name}: invalid zone_number, skipping")

    def deviceStopComm(self, dev):
        if dev.deviceTypeId == "panel":
            self.panel_dev = None
        elif dev.deviceTypeId == "partition":
            try:
                pnum = int(dev.pluginProps.get("partition_number", "1"))
            except (ValueError, TypeError):
                return
            self.partition_devs.pop(pnum, None)
            self.partition_last_event.pop(pnum, None)
        elif dev.deviceTypeId == "zone":
            try:
                znum = int(dev.pluginProps.get("zone_number", "0"))
            except (ValueError, TypeError):
                return
            self.zone_devs.pop(znum, None)

    @staticmethod
    def didDeviceCommPropertyChange(oldDevice, newDevice):
        """Restart comm only when identity-defining props change.

        partition_number and zone_number define which physical
        partition/zone the Indigo device tracks. model and evl_model
        affect the panel command set / Envisalink dialect. Any change here
        invalidates the panel/partition/zone routing maps.
        """
        keys = ("model", "evl_model", "partition_number", "zone_number")
        return any(oldDevice.pluginProps.get(k) != newDevice.pluginProps.get(k) for k in keys)

    # ── Trigger registration (for custom Events.xml events) ───────────────

    def triggerStartProcessing(self, trigger):
        self.event_triggers[trigger.id] = trigger

    def triggerStopProcessing(self, trigger):
        self.event_triggers.pop(trigger.id, None)

    def _fire_event(self, event_id):
        # indigo.trigger.execute carries no payload, so per-partition context
        # cannot ride on the event itself — trigger scripts that need to know
        # which partition fired should read the partition device's state.
        for trig in self.event_triggers.values():
            if trig.pluginTypeId == event_id:
                indigo.trigger.execute(trig)

    # Map a high-level partition state to the custom event it should fire.
    _PARTITION_EVENTS = {
        PartitionState.ALARM:         "alarm_triggered",
        PartitionState.ARMED_AWAY:    "armed_away",
        PartitionState.ARMED_STAY:    "armed_stay",
        PartitionState.ARMED_INSTANT: "armed_instant",
        PartitionState.ARMED_MAX:     "armed_max",
        PartitionState.READY:         "disarmed",
        PartitionState.NOT_READY:     "disarmed",
    }

    def _emit_partition_events(self, partition, state):
        """Fire the custom event for a partition state, but only when the resolved
        event CHANGES. This means the '02' partition path and the keypad-derived
        path don't double-fire, repeated frames of the same state don't spam
        triggers, and a partition that only ever sends keypad updates (some EVL
        firmware) still gets armed/disarmed/alarm events."""
        evt = self._PARTITION_EVENTS.get(state)
        if evt and self.partition_last_event.get(partition) != evt:
            self.partition_last_event[partition] = evt
            self._fire_event(evt)

    # ── Frame dispatch ─────────────────────────────────────────────────────

    def _on_login(self, result: LoginResult):
        if result == LoginResult.OK:
            self.logger.info("EVL login OK")
            if self.panel_dev:
                self.panel_dev.updateStateOnServer("connected", value=True)
            # Request a zone-timer dump so we know the initial state of everything
            if self.client:
                self.client.send_raw(encode_dump_zone_timers())
        else:
            self.logger.error(f"EVL login result: {result.value}")
            if self.panel_dev:
                self.panel_dev.updateStateOnServer("connected", value=False)

    def _on_disconnect(self, reason: str):
        self.logger.warning(f"EVL disconnected: {reason}")
        if self.panel_dev:
            self.panel_dev.updateStateOnServer("connected", value=False)
        self._fire_event("evl_disconnected")

    def _on_frame(self, frame):
        # Dispatch based on TPI code
        try:
            ku = parse_keypad_update(frame)
            if ku:
                self._handle_keypad_update(ku)
                return
            zb = parse_zone_state(frame)
            if zb:
                self._handle_zone_bitmap(zb)
                return
            changes = parse_partition_state(frame)
            if changes:
                self._handle_partition_state(changes)
                return
            cid = parse_realtime_cid(frame)
            if cid:
                self._handle_cid_event(cid)
                return
        except Exception as e:
            self.logger.warning(f"frame handler error: {e}  frame={frame.raw!r}")

    def _handle_keypad_update(self, ku: KeypadUpdate):
        dev = self.partition_devs.get(ku.partition)
        if not dev:
            if self.debug:
                self.logger.debug(f"keypad update for unknown partition {ku.partition}")
            return
        derived = derive_partition_state(ku)
        dev.updateStatesOnServer([
            {"key": "display",       "value": ku.display_text.strip()},
            {"key": "armed",         "value": ku.armed},
            {"key": "ready",         "value": ku.ready},
            {"key": "trouble",       "value": ku.trouble},
            {"key": "bypass",        "value": ku.bypass},
            {"key": "acPower",       "value": ku.ac_power},
            {"key": "chime",         "value": ku.chime},
            {"key": "alarm",         "value": ku.alarm},
            {"key": "state",         "value": derived.value},
            {"key": "ledBitmap",     "value": f"0x{ku.led_bitmap:04X}"},
            {"key": "beepCode",      "value": ku.beep_code},
        ])
        self._emit_partition_events(ku.partition, derived)

    def _handle_zone_bitmap(self, zb: ZoneBitmap):
        # A %01 message is a bitmap of ALL open zones — update every tracked zone
        # (a zone not in the set is closed).
        for znum, dev in self.zone_devs.items():
            is_open = znum in zb.open_zones
            dev.updateStatesOnServer([
                {"key": "onOffState", "value": is_open},
                {"key": "zoneState", "value": "open" if is_open else "closed"},
            ])

    def _handle_partition_state(self, changes):
        # A %02 message carries the status of every partition at once.
        for psc in changes:
            # Don't let an unrecognised %02 status code (e.g. real panels emit
            # '0A' while arming instant, which isn't in the documented table)
            # clobber the good state derived from the %00 keypad stream.
            if psc.state == PartitionState.UNKNOWN:
                continue
            dev = self.partition_devs.get(psc.partition)
            if not dev:
                continue
            dev.updateStateOnServer("state", value=psc.state.value)
            self._emit_partition_events(psc.partition, psc.state)

    def _handle_cid_event(self, cid: RealtimeCIDEvent):
        self.logger.info(
            f"CID event: qualifier={cid.qualifier} code={cid.event_code:03d} "
            f"partition={cid.partition} zone_or_user={cid.zone_or_user}"
        )
        if self.panel_dev:
            self.panel_dev.updateStateOnServer(
                "lastCid",
                value=f"{cid.qualifier}{cid.event_code:03d}/P{cid.partition}/{cid.zone_or_user}"
            )

    # ── Protocol capture (read-only, menu-driven) ─────────────────────────

    def _on_raw_line(self, text):
        """Called by the client for EVERY received line (parseable or not) — records
        it while a capture is running. Read-only: this only observes inbound data."""
        cap = self._capture
        if cap is None:
            return
        try:
            dec = tpi_capture.decode_line(text)
        except Exception:
            return
        rec = {"t": round(time.time() - cap["start"], 3),
               "ts": datetime.now().isoformat(timespec="milliseconds"),
               "kind": "frame", **dec}
        cap["records"].append(rec)
        code = dec.get("code", "unparsed")
        cap["counts"][code] = cap["counts"].get(code, 0) + 1
        if not dec.get("parsed", False):
            cap["unparsed"] += 1

    def menu_capture_data(self, valuesDict=None, typeId=None):
        """Start a timed, read-only protocol capture and write a shareable file."""
        if not (self.client and self.client.is_connected()):
            self.logger.error("Capture: not connected to the Envisalink — configure and connect first.")
            return
        if self._capture is not None:
            self.logger.warning("A protocol capture is already running — please wait for it to finish.")
            return
        try:
            minutes = int((valuesDict or {}).get("duration_min", "3"))
        except (ValueError, TypeError):
            minutes = 3
        minutes = max(1, min(minutes, 10))
        self._capture = {"records": [], "counts": {}, "unparsed": 0, "start": time.time()}
        # Read-only nudge for a zone-timer dump so we get some zone data too.
        try:
            self.client.send_raw(encode_dump_zone_timers())
        except Exception:
            pass
        self.logger.info(f"── Protocol capture STARTED for {minutes} minute(s). On your keypad, please:")
        for i, step in enumerate(tpi_capture.CAPTURE_STEPS, 1):
            self.logger.info(f"     {i}. {step}")
        self.logger.info("   Recording now — you'll see the panel states update in the log as you go.")
        self._capture_timer = threading.Timer(minutes * 60, self._finish_capture)
        self._capture_timer.daemon = True
        self._capture_timer.start()

    def _finish_capture(self):
        cap = self._capture
        self._capture = None
        self._capture_timer = None
        if cap is None:
            return
        duration_s = round(time.time() - cap["start"], 3)
        bundle = tpi_capture.make_bundle(cap["records"], cap["counts"], cap["unparsed"],
                                         duration_s, self.port, source="menu")
        path = f"/tmp/honeywell_tpi_capture_{int(time.time())}.json"
        written = tpi_capture.write_bundle(bundle, path)
        sensitive = tpi_capture.sensitive_records(bundle)
        indigo.server.log("─" * 60)
        indigo.server.log(f"Protocol capture COMPLETE — {bundle['record_count']} records over {duration_s:.0f}s")
        indigo.server.log(f"  Written to: {written}")
        indigo.server.log(f"  Message types seen: {bundle['message_code_counts']}")
        if sensitive:
            indigo.server.log(
                f"  REVIEW BEFORE SHARING — {len(sensitive)} record(s) contain 4-8 digit runs; "
                "open the file and check them before posting.", level=logging.WARNING)
        else:
            indigo.server.log("  Safe to share — no password and no code-like digits. Attach this JSON to a forum reply.")
        indigo.server.log("─" * 60)

    # ── Actions (Actions.xml callbacks) ───────────────────────────────────

    def _gate_command(self, action_label: str) -> bool:
        """Block destructive commands when test_mode is on."""
        if self.test_mode:
            self.logger.warning(
                f"TEST MODE: '{action_label}' suppressed. "
                f"Disable test_mode in plugin config to send real commands."
            )
            return False
        if not (self.client and self.client.is_connected()):
            self.logger.error(f"{action_label} dropped — EVL not connected")
            return False
        return True

    def _user_code_from(self, action) -> str:
        """
        User code is taken from the action's props (NEVER stored at plugin level).
        Returns "" if missing — caller must check and refuse.
        """
        code = (action.props or {}).get("user_code", "").strip()
        if not code or not code.isdigit() or len(code) not in (4, 6):
            return ""
        return code

    def _partition_from(self, dev) -> int:
        try:
            return int(dev.pluginProps.get("partition_number", "1"))
        except ValueError:
            return 1

    def action_disarm(self, action, dev):
        if not self._gate_command("disarm"): return
        code = self._user_code_from(action)
        if not code:
            self.logger.error("disarm: invalid or missing user_code (must be 4-6 digits)")
            return
        self.client.send_keypresses(encode_disarm(code, self._partition_from(dev)))

    def action_arm_away(self, action, dev):
        if not self._gate_command("arm_away"): return
        code = self._user_code_from(action)
        if not code:
            self.logger.error("arm_away: invalid or missing user_code")
            return
        self.client.send_keypresses(encode_arm_away(code, self._partition_from(dev)))

    def action_arm_stay(self, action, dev):
        if not self._gate_command("arm_stay"): return
        code = self._user_code_from(action)
        if not code:
            self.logger.error("arm_stay: invalid or missing user_code")
            return
        self.client.send_keypresses(encode_arm_stay(code, self._partition_from(dev)))

    def action_arm_instant(self, action, dev):
        if not self._gate_command("arm_instant"): return
        code = self._user_code_from(action)
        if not code:
            self.logger.error("arm_instant: invalid or missing user_code")
            return
        self.client.send_keypresses(encode_arm_instant(code, self._partition_from(dev)))

    def action_arm_max(self, action, dev):
        if not self._gate_command("arm_max"): return
        code = self._user_code_from(action)
        if not code:
            self.logger.error("arm_max: invalid or missing user_code")
            return
        self.client.send_keypresses(encode_arm_max(code, self._partition_from(dev)))

    def action_bypass_zone(self, action, dev):
        if not self._gate_command("bypass_zone"): return
        code = self._user_code_from(action)
        if not code:
            self.logger.error("bypass_zone: invalid or missing user_code")
            return
        try:
            zone = int((action.props or {}).get("zone_number", "0"))
        except (ValueError, TypeError):
            self.logger.error("bypass_zone: invalid zone_number")
            return
        self.client.send_keypresses(encode_bypass_zone(code, zone, self._partition_from(dev)))

    # ── Sensor action (zone devices are type="sensor") ─────────────────────

    def actionControlSensor(self, action, dev):
        """Zones are receive-only. Declaring type="sensor" obliges this handler —
        without it Indigo logs 'plugin does not define method actionControlSensor'
        and drops the action. The only meaningful action is a status request."""
        if action.sensorAction == indigo.kSensorAction.RequestStatus:
            if self.client and self.client.is_connected():
                self.client.send_raw(encode_dump_zone_timers())
                self.logger.info(f"{dev.name}: status requested — polled zone-timer dump")
            else:
                self.logger.warning(f"{dev.name}: status request ignored — EVL not connected")
        else:
            self.logger.warning(f"{dev.name}: unsupported sensor action {action.sensorAction}")

    # ── Menu items ─────────────────────────────────────────────────────────

    def showPluginInfo(self, valuesDict=None, typeId=None):
        extras = [
            ("Release:",   "BETA — untested on real hardware, report issues to CliveS on Indigo forum"),
            ("EVL host:",  self.host or "(not configured)"),
            ("Test mode:", "ON (commands suppressed)" if self.test_mode else "OFF (commands LIVE)"),
        ]
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion, extras=extras)
        else:
            indigo.server.log(f"{self.pluginDisplayName} v{self.pluginVersion}")

    def menu_test_connection(self, valuesDict=None, typeId=None):
        """Connect, log in, fetch a zone-timer dump, then report."""
        if not self.client:
            self.logger.error("no client running — check config")
            return
        stats = self.client.get_stats()
        indigo.server.log("─" * 60)
        indigo.server.log("HoneywellEnvisalink — connection test")
        indigo.server.log("─" * 60)
        for k, v in stats.items():
            indigo.server.log(f"  {k:18s} {v}")
        indigo.server.log("─" * 60)
        if stats["connected"]:
            indigo.server.log("Requesting zone-timer dump…")
            self.client.send_raw(encode_dump_zone_timers())
        else:
            indigo.server.log("Not connected — check host, port, password, and that EVL is reachable.")

    def menu_dump_recent_traffic(self, valuesDict=None, typeId=None):
        """Dump the last N lines of raw TPI traffic to the Indigo event log."""
        if not self.client:
            self.logger.error("no client running")
            return
        log_lines = self.client.get_debug_log()
        if not log_lines:
            indigo.server.log("No traffic recorded yet.")
            return
        indigo.server.log("─" * 60)
        indigo.server.log(f"HoneywellEnvisalink — last {len(log_lines)} raw TPI lines")
        indigo.server.log("─" * 60)
        for ts, direction, line in log_lines:
            t = time.strftime("%H:%M:%S", time.localtime(ts))
            indigo.server.log(f"  {t}  {direction}  {line}")
        indigo.server.log("─" * 60)

    def menu_save_diagnostic_bundle(self, valuesDict=None, typeId=None):
        """
        Save a diagnostic bundle to /tmp for sending to the plugin author.
        Contains: stats, recent traffic, plugin version, configured host/port
        (NOT the password, NOT user codes).
        """
        if not self.client:
            self.logger.error("no client running")
            return
        bundle = {
            "plugin_version": PLUGIN_VERSION,
            "plugin_id": PLUGIN_ID,
            "host": self.host,
            "port": self.port,
            "test_mode": self.test_mode,
            "debug_protocol": self.debug_protocol,
            "stats": self.client.get_stats(),
            "recent_traffic": [
                {"ts": ts, "dir": d, "line": line}
                for ts, d, line in self.client.get_debug_log()
            ],
            "partition_devices": list(self.partition_devs.keys()),
            "zone_devices": sorted(self.zone_devs.keys()),
        }
        path = f"/tmp/honeywell_envisalink_diag_{int(time.time())}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, default=str)
        try:
            _os.chmod(path, 0o600)   # owner-only — it's in world-readable /tmp
        except OSError:
            pass
        indigo.server.log(f"Diagnostic bundle written to {path}")
        # Safe by construction: the password is never in the dict, and the recent
        # traffic is redacted at source (login send + user codes masked before the
        # ring buffer ever sees them).
        indigo.server.log("Safe to share — contains no password and no user codes.")
        indigo.server.log("Send via the Indigo forum (thread reply or DM 'CliveS').")

    def menu_toggle_debug_protocol(self, valuesDict=None, typeId=None):
        self.debug_protocol = not self.debug_protocol
        if self.client:
            self.client.set_debug_protocol(self.debug_protocol)
        self.pluginPrefs["debug_protocol"] = self.debug_protocol
        indigo.server.log(
            f"Protocol debug logging now {'ON' if self.debug_protocol else 'OFF'}"
        )

    def menu_toggle_test_mode(self, valuesDict=None, typeId=None):
        self.test_mode = not self.test_mode
        self.pluginPrefs["test_mode"] = self.test_mode
        warn = "" if self.test_mode else " — COMMANDS NOW LIVE, can arm/disarm panel!"
        # NB: indigo.server.warningLogLevel does NOT exist (verified live) — passing
        # it raised AttributeError on exactly the commands-live branch. Use the
        # documented logging level int instead.
        indigo.server.log(f"Test mode now {'ON (safe)' if self.test_mode else 'OFF'}{warn}",
                          level=logging.WARNING if not self.test_mode else None)
