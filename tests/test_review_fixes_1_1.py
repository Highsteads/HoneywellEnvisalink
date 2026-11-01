#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_review_fixes_1_1.py
# Description: Regression tests for the 1.1.0 fixes from the 1.0 code review:
#              sleep/wake reconnect, armed-flag "disarmed" event, silent-panel
#              watch, 4-digit codes, start-up seeding, frame-error logging and
#              immediate pref saves. No live Indigo or alarm access.
# Author:      CliveS & Claude Opus 5.5
# Date:        01-11-2026
# Version:     1.0

import socket
import threading
import time
import types
from unittest.mock import MagicMock

import pytest

from test_plugin import _bare_plugin, _PluginBase
import plugin
import honeywell_protocol as hp
import envisalink_client as ec


# Real-hardware-shaped %00 frames (flags per honeywell_protocol FLAG_*)
ARMED_AWAY   = "%00,01,0C0C,08,00,ARMED ***AWAY***                $"
IN_ALARM     = "%00,01,000F,08,00,ALARM 08 LIVING ROOM MOTION     $"
ALARM_MEMORY = "%00,01,000A,08,00,ALARM 08 LIVING ROOM MOTION     $"   # disarmed, memory lit
TROUBLE      = "%00,01,0208,08,00,CHECK 103 LOW BATTERY           $"   # disarmed, trouble lit
READY        = "%00,01,1C08,08,00,****DISARMED****  Ready to Arm  $"
FIRE_ALARM   = "%00,01,2008,08,00,FIRE 12 KITCHEN                 $"   # fire while disarmed


def _plugin_with_partition():
    p = _bare_plugin()
    p.partition_devs = {1: MagicMock()}
    fired = []
    p._fire_event = fired.append
    return p, fired


def _feed(p, *lines):
    for line in lines:
        p._on_frame(hp.parse_frame(line))


# ────────────────────────────────────────────────────────────────────────────
# Finding 1 — sleep / wake
# ────────────────────────────────────────────────────────────────────────────

class TestSleepWake:
    def _plugin(self):
        p = _bare_plugin()
        p.host, p.password = "192.168.1.50", "user"
        p.started = []
        p._start_client = lambda: p.started.append(True)
        return p

    def test_indigo_calls_the_camelcase_names(self):
        # The Indigo 2025.2 plugin reference documents only prepareToSleep/wakeUp.
        assert callable(getattr(plugin.Plugin, "prepareToSleep"))
        assert callable(getattr(plugin.Plugin, "wakeUp"))
        assert "wakeUp" in plugin.Plugin.__dict__ and "prepareToSleep" in plugin.Plugin.__dict__

    def test_wake_reconnects_when_base_has_no_wakeup(self):
        p = self._plugin()
        assert not hasattr(_PluginBase, "wakeUp")
        p.wakeUp()
        assert p.started == [True]

    def test_wake_reconnects_even_when_base_wakeup_raises(self, monkeypatch):
        def boom(self):
            raise RuntimeError("base failed")
        monkeypatch.setattr(_PluginBase, "wakeUp", boom, raising=False)
        p = self._plugin()
        p.wakeUp()
        assert p.started == [True]
        assert any("base failed" in str(c) for c in p.logger.error.call_args_list)

    def test_wake_calls_base_before_reconnecting(self, monkeypatch):
        order = []
        monkeypatch.setattr(_PluginBase, "wakeUp", lambda self: order.append("base"), raising=False)
        p = self._plugin()
        p._start_client = lambda: order.append("client")
        p.wakeUp()
        assert order == ["base", "client"]

    def test_wake_without_config_stays_disconnected(self):
        p = self._plugin()
        p.password = ""
        p.wakeUp()
        assert p.started == []

    def test_sleep_stops_client_and_calls_base(self, monkeypatch):
        calls = []
        monkeypatch.setattr(_PluginBase, "prepareToSleep", lambda self: calls.append("base"), raising=False)
        p = self._plugin()
        client = MagicMock()
        p.client = client
        p.prepareToSleep()
        client.stop.assert_called_once()
        assert p.client is None and calls == ["base"]

    def test_sleep_survives_base_raising(self, monkeypatch):
        def boom(self):
            raise RuntimeError("base sleep failed")
        monkeypatch.setattr(_PluginBase, "prepareToSleep", boom, raising=False)
        p = self._plugin()
        p.client = MagicMock()
        p.prepareToSleep()            # must not raise
        assert p.client is None


# ────────────────────────────────────────────────────────────────────────────
# Finding 2 — "disarmed" follows the armed flags
# ────────────────────────────────────────────────────────────────────────────

class TestDisarmedFollowsArmedFlags:
    def test_disarm_after_alarm_fires_disarmed(self):
        p, fired = _plugin_with_partition()
        _feed(p, READY, ARMED_AWAY, IN_ALARM, ALARM_MEMORY)
        assert fired == ["armed_away", "alarm_triggered", "disarmed"]

    def test_alarm_memory_stays_a_separate_state(self):
        p, _fired = _plugin_with_partition()
        _feed(p, READY, ARMED_AWAY, IN_ALARM, ALARM_MEMORY)
        states = p.partition_devs[1].updateStatesOnServer.call_args[0][0]
        assert {"key": "state", "value": "alarm_memory"} in states

    def test_disarm_with_trouble_showing_fires_disarmed(self):
        p, fired = _plugin_with_partition()
        _feed(p, READY, ARMED_AWAY, TROUBLE)
        assert fired == ["armed_away", "disarmed"]
        states = p.partition_devs[1].updateStatesOnServer.call_args[0][0]
        assert {"key": "state", "value": "trouble"} in states

    def test_one_disarm_fires_once_across_both_paths(self):
        p, fired = _plugin_with_partition()
        _feed(p, READY, ARMED_AWAY)
        _feed(p, ALARM_MEMORY, ALARM_MEMORY, "%02,0100000000000000$", READY, READY)
        assert fired.count("disarmed") == 1

    def test_partition_status_path_then_keypad_does_not_double_fire(self):
        p, fired = _plugin_with_partition()
        _feed(p, READY, ARMED_AWAY, "%02,0100000000000000$", READY)
        assert fired == ["armed_away", "disarmed"]

    def test_exit_delay_and_alarm_memory_while_armed_do_not_fire_disarmed(self):
        p, fired = _plugin_with_partition()
        _feed(p, READY, ARMED_AWAY,
              "%00,01,0C0C,08,00,ARMED ***AWAY***You may exit now$",
              "%00,01,000E,08,00,ALARM 08 LIVING ROOM MOTION     $")   # armed + memory
        assert "disarmed" not in fired

    def test_fire_alarm_while_disarmed_can_fire_again(self):
        # The alarm latch is separate, so a second alarm is not swallowed.
        p, fired = _plugin_with_partition()
        _feed(p, READY, FIRE_ALARM, READY, FIRE_ALARM)
        assert fired == ["alarm_triggered", "alarm_triggered"]


# ────────────────────────────────────────────────────────────────────────────
# Finding 7 — first reading after a restart seeds silently
# ────────────────────────────────────────────────────────────────────────────

class TestStartupSeeding:
    @pytest.mark.parametrize("line", [READY, ARMED_AWAY, TROUBLE, ALARM_MEMORY])
    def test_first_reading_fires_nothing(self, line):
        p, fired = _plugin_with_partition()
        _feed(p, line, line)
        assert fired == []

    def test_alarm_in_progress_at_startup_still_fires(self):
        p, fired = _plugin_with_partition()
        _feed(p, IN_ALARM)
        assert fired == ["alarm_triggered"]

    def test_partition_status_first_reading_fires_nothing(self):
        p, fired = _plugin_with_partition()
        _feed(p, "%02,0500000000000000$")
        assert fired == []


# ────────────────────────────────────────────────────────────────────────────
# Finding 3 — silent panel
# ────────────────────────────────────────────────────────────────────────────

class TestPanelSilentPlugin:
    def test_silent_marks_devices_logs_and_fires_once(self):
        p, fired = _plugin_with_partition()
        p.zone_devs = {3: MagicMock()}
        p._on_panel_silent(True)
        p._on_panel_silent(True)      # e.g. still silent after a reconnect
        assert fired == ["panel_silent"]
        p.partition_devs[1].setErrorStateOnServer.assert_called_with("panel silent")
        p.zone_devs[3].setErrorStateOnServer.assert_called_with("panel silent")
        assert p.logger.warning.call_count == 1

    def test_recovery_logs_and_fires_once(self):
        p, fired = _plugin_with_partition()
        p._on_panel_silent(True)
        p._on_panel_silent(False)
        p._on_panel_silent(False)
        assert fired == ["panel_silent", "panel_restored"]
        assert any("resumed" in str(c) for c in p.logger.info.call_args_list)

    def test_recovery_without_silence_is_ignored(self):
        p, fired = _plugin_with_partition()
        p._on_panel_silent(False)
        assert fired == []

    def test_events_are_declared(self):
        import xml.etree.ElementTree as ET
        root = ET.parse(f"{plugin._os.path.dirname(plugin.__file__)}/Events.xml").getroot()
        ids = {e.get("id") for e in root}
        assert {"panel_silent", "panel_restored"} <= ids


def _evl_server(send_status_after=None):
    """A local fake Envisalink: logs in, answers ^00 keepalives, and (optionally)
    starts sending %00 keypad updates after send_status_after seconds."""
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def run():
        conn, _ = srv.accept()
        conn.sendall(b"Login:\r\n")
        f = conn.makefile("rb")
        f.readline()
        conn.sendall(b"OK\r\n")
        started = time.monotonic()
        conn.settimeout(0.1)
        while True:
            try:
                line = f.readline()
                if line.startswith(b"^00"):
                    conn.sendall(b"^00,00$\r\n")
            except (socket.timeout, OSError):
                pass
            if send_status_after is not None and time.monotonic() - started >= send_status_after:
                try:
                    conn.sendall((READY + "\r\n").encode())
                except OSError:
                    return
                time.sleep(0.2)

    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1]


class TestPanelSilentClient:
    def test_keepalive_only_evl_reports_silence_then_recovery(self, monkeypatch):
        monkeypatch.setattr(ec, "KEEPALIVE_INTERVAL_S", 0.3)
        port = _evl_server(send_status_after=2.0)
        reports = []
        c = ec.EnvisalinkClient("127.0.0.1", "user", on_frame=lambda f: None, port=port,
                                on_panel_silent=reports.append, panel_silent_s=1.0)
        c.start()
        try:
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline and reports != [True, False]:
                time.sleep(0.1)
        finally:
            c.stop()
        assert reports == [True, False]
        assert c.get_stats()["last_panel_status"] is not None

    def test_zero_disables_the_watch(self, monkeypatch):
        monkeypatch.setattr(ec, "KEEPALIVE_INTERVAL_S", 0.3)
        port = _evl_server()
        reports = []
        c = ec.EnvisalinkClient("127.0.0.1", "user", on_frame=lambda f: None, port=port,
                                on_panel_silent=reports.append, panel_silent_s=0)
        c.start()
        time.sleep(1.5)
        c.stop()
        assert reports == []


# ────────────────────────────────────────────────────────────────────────────
# Finding 4 — exactly four-digit codes
# ────────────────────────────────────────────────────────────────────────────

class TestFourDigitCodes:
    @pytest.mark.parametrize("code,ok", [("1234", True), (" 1234 ", True), ("123456", False),
                                         ("12345", False), ("123", False), ("12a4", False)])
    def test_valid_user_code(self, code, ok):
        assert plugin.Plugin._valid_user_code(code) is ok

    def test_dialog_refuses_six_digits(self):
        p = _bare_plugin()
        ok, _vals, errs = p.validateActionConfigUi({"user_code": "123456"}, "disarm", 0)
        assert ok is False and "four-digit" in errs["user_code"]

    def test_saved_six_digit_code_is_never_sent(self):
        p = _bare_plugin()
        p.test_mode = False
        p.client = MagicMock()
        p.client.is_connected.return_value = True
        assert p.action_disarm(types.SimpleNamespace(props={"user_code": "123456"}),
                               types.SimpleNamespace(pluginProps={"partition_number": "1"})) is False
        p.client.send_keypresses.assert_not_called()


# ────────────────────────────────────────────────────────────────────────────
# Finding 10 — frame errors log full detail once
# ────────────────────────────────────────────────────────────────────────────

class TestFrameErrorLogging:
    def test_traceback_logged_once_per_code_and_type(self):
        p, _fired = _plugin_with_partition()
        p.partition_devs[1].updateStatesOnServer.side_effect = TypeError("bad state value")
        _feed(p, READY, READY, READY)
        assert p.logger.error.call_count == 1
        msg = p.logger.error.call_args[0][0]
        assert "bad state value" in msg and "Traceback" in msg


# ────────────────────────────────────────────────────────────────────────────
# Finding 13 — prefs saved straight after a toggle
# ────────────────────────────────────────────────────────────────────────────

class TestPrefsSavedAtOnce:
    def test_test_mode_toggle_saves(self):
        p = _bare_plugin()
        p.pluginPrefs = {}
        plugin.indigo.server.savePluginPrefs.reset_mock()
        p.menu_toggle_test_mode()
        plugin.indigo.server.savePluginPrefs.assert_called_once_with()
        assert p.pluginPrefs["test_mode"] is p.test_mode

    def test_save_failure_is_logged_not_raised(self):
        p = _bare_plugin()
        p.pluginPrefs = {}
        plugin.indigo.server.savePluginPrefs.side_effect = TypeError("needs an argument")
        try:
            p.menu_toggle_test_mode()
        finally:
            plugin.indigo.server.savePluginPrefs.side_effect = None
        assert any("save plugin settings" in str(c) for c in p.logger.warning.call_args_list)


class TestLatchSurvivesSleep:
    def test_disarm_during_sleep_fires_after_wake(self):
        # Indigo's default prepareToSleep/wakeUp stop and restart comm for every
        # device; the latch must survive that, so a change while asleep is reported.
        p, fired = _plugin_with_partition()
        dev = p.partition_devs[1]
        p.pluginId = "com.clives.indigoplugin.honeywell-envisalink"   # stub base sets none
        dev.id, dev.deviceTypeId, dev.pluginId = 101, "partition", p.pluginId
        dev.pluginProps = {"partition_number": "1"}
        _feed(p, READY, ARMED_AWAY)
        p.deviceStopComm(dev)
        p.deviceStartComm(dev)
        _feed(p, READY)
        assert fired == ["armed_away", "disarmed"]
