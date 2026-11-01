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


# ════════════════════════════════════════════════════════════════════════════
# Second pass — the remaining review items
# ════════════════════════════════════════════════════════════════════════════

def _connected_plugin():
    p, fired = _plugin_with_partition()
    p.test_mode = False
    p.client = MagicMock()
    p.client.is_connected.return_value = True
    p.client.send_keypresses.return_value = True
    return p, fired


PARTITION_1 = types.SimpleNamespace(pluginProps={"partition_number": "1"})


class TestEntryDelayNeedsArmedPrompt:
    def test_disarmed_zone_named_entry_is_not_entry_delay(self):
        ku = hp.parse_keypad_update(hp.parse_frame("%00,01,0008,05,00,FAULT 05 FRONT ENTRY DOOR       $"))
        assert hp.derive_partition_state(ku) == hp.PartitionState.NOT_READY

    @pytest.mark.parametrize("text", ["DISARM SYSTEM ORALARM WILL OCCUR",   # two lines run together
                                      "DISARM SYSTEM   OR ALARM OCCURS ",   # padded variant
                                      "DISARM SYSTEM OR ALARM WILL OCCUR"])
    def test_armed_with_prompt_is_entry_delay(self, text):
        ku = hp.parse_keypad_update(hp.parse_frame(f"%00,01,0C0C,08,00,{text}$"))
        assert hp.derive_partition_state(ku) == hp.PartitionState.ENTRY_DELAY

    def test_prompt_while_disarmed_is_not_entry_delay(self):
        ku = hp.parse_keypad_update(hp.parse_frame("%00,01,0008,08,00,DISARM SYSTEM OR ALARM WILL OCCUR$"))
        assert hp.derive_partition_state(ku) != hp.PartitionState.ENTRY_DELAY


class TestBypassZoneDigits:
    def test_three_digit_encoding(self):
        keys = "".join(c.split(",")[2][0] for c in hp.encode_bypass_zone("1234", 5, 1, zone_digits=3))
        assert keys == "12346005"

    def test_two_digit_panel_refuses_zone_above_99(self):
        with pytest.raises(ValueError):
            hp.encode_bypass_zone("1234", 120, 1, zone_digits=2)

    @pytest.mark.parametrize("model,expected", [("vista128bp", "12346005"), ("vista250bp", "12346005"),
                                                ("vista20p", "1234605"), ("other", "1234605"), (None, "1234605")])
    def test_plugin_picks_digits_from_panel_model(self, model, expected):
        p, _fired = _connected_plugin()
        p.panel_dev = None if model is None else types.SimpleNamespace(pluginProps={"model": model})
        assert p.action_bypass_zone(types.SimpleNamespace(props={"user_code": "1234", "zone_number": "5"}),
                                    PARTITION_1) is True
        sent = p.client.send_keypresses.call_args[0][0]
        assert "".join(c.split(",")[2][0] for c in sent) == expected
        p._cancel_pending_commands()

    def test_zone_above_99_refused_on_two_digit_panel(self):
        p, _fired = _connected_plugin()
        p.panel_dev = types.SimpleNamespace(pluginProps={"model": "vista20p"})
        assert p.action_bypass_zone(types.SimpleNamespace(props={"user_code": "1234", "zone_number": "120"}),
                                    PARTITION_1) is False
        p.client.send_keypresses.assert_not_called()
        ok, _v, errs = p.validateActionConfigUi({"user_code": "1234", "zone_number": "120"}, "bypass_zone", 0)
        assert ok is False and "128BP" in errs["zone_number"]


class TestCommandConfirmation:
    def test_arm_confirmed_by_panel(self, monkeypatch):
        monkeypatch.setattr(plugin, "COMMAND_CONFIRM_S", 0.3)
        p, fired = _connected_plugin()
        _feed(p, READY)
        assert p.action_arm_away(types.SimpleNamespace(props={"user_code": "1234"}), PARTITION_1)
        _feed(p, ARMED_AWAY)
        time.sleep(0.5)
        assert "command_failed" not in fired
        assert any("confirmed by the panel" in str(c) for c in p.logger.info.call_args_list)

    def test_arm_not_confirmed_reports_failure(self, monkeypatch):
        monkeypatch.setattr(plugin, "COMMAND_CONFIRM_S", 0.2)
        p, fired = _connected_plugin()
        _feed(p, READY)
        p.action_arm_away(types.SimpleNamespace(props={"user_code": "1234"}), PARTITION_1)
        _feed(p, READY)                     # panel still disarmed (e.g. a zone open)
        time.sleep(0.5)
        assert fired == ["command_failed"]
        assert any("did not confirm" in str(c) for c in p.logger.error.call_args_list)

    def test_disarm_confirmed_after_alarm(self, monkeypatch):
        monkeypatch.setattr(plugin, "COMMAND_CONFIRM_S", 0.3)
        p, fired = _connected_plugin()
        _feed(p, READY, ARMED_AWAY, IN_ALARM)
        p.action_disarm(types.SimpleNamespace(props={"user_code": "1234"}), PARTITION_1)
        _feed(p, ALARM_MEMORY)
        time.sleep(0.5)
        assert "command_failed" not in fired and "disarmed" in fired

    def test_interrupted_send_cancels_the_watch(self, monkeypatch):
        monkeypatch.setattr(plugin, "COMMAND_CONFIRM_S", 0.2)
        p, fired = _connected_plugin()
        p.client.send_keypresses.return_value = False
        assert p.action_arm_stay(types.SimpleNamespace(props={"user_code": "1234"}), PARTITION_1) is False
        time.sleep(0.4)
        assert "command_failed" not in fired and p._pending_commands == {}

    def test_code_never_logged(self, monkeypatch):
        monkeypatch.setattr(plugin, "COMMAND_CONFIRM_S", 0.2)
        p, _fired = _connected_plugin()
        p.action_disarm(types.SimpleNamespace(props={"user_code": "4471"}), PARTITION_1)
        time.sleep(0.4)
        logged = " ".join(str(c) for m in (p.logger.info, p.logger.error, p.logger.warning)
                          for c in m.call_args_list)
        assert "4471" not in logged

    def test_rejected_keypress_warns_once(self):
        p, _fired = _connected_plugin()
        for _ in range(5):
            p._handle_command_response(types.SimpleNamespace(code="^03", payload="03"))
        assert p.logger.warning.call_count == 1
        assert "refused" in p.logger.warning.call_args[0][0]


class TestErrorStatesCleared:
    def _routed(self, p, dev_id=101):
        p.pluginId = "com.clives.indigoplugin.honeywell-envisalink"
        dev = MagicMock()
        dev.id, dev.deviceTypeId, dev.pluginId, dev.name = dev_id, "partition", p.pluginId, "Partition 1"
        dev.pluginProps = {"partition_number": "1"}
        p.partition_devs = {}
        p.deviceStartComm(dev)
        return dev

    def test_fresh_reading_clears_error_explicitly(self):
        p, _fired = _connected_plugin()
        dev = self._routed(p)
        dev.setErrorStateOnServer.assert_called_with("waiting for panel update")
        _feed(p, READY)
        dev.setErrorStateOnServer.assert_called_with(None)
        dev.setErrorStateOnServer.reset_mock()
        _feed(p, READY)                     # not in error any more — no repeat clear
        dev.setErrorStateOnServer.assert_not_called()

    def test_state_list_refreshed_for_new_states(self):
        p, _fired = _connected_plugin()
        dev = self._routed(p)
        dev.stateListOrDisplayStateIdChanged.assert_called_once_with()

    def test_low_battery_state_is_updated(self):
        p, _fired = _connected_plugin()
        _feed(p, "%00,01,4008,08,00,LO BAT                          $")
        states = p.partition_devs[1].updateStatesOnServer.call_args[0][0]
        assert {"key": "lowBattery", "value": True} in states

    def test_zone_dump_ignored_while_panel_silent(self):
        p, _fired = _connected_plugin()
        zone = MagicMock()
        p.zone_devs = {1: zone}
        p._on_panel_silent(True)
        _feed(p, "%FF,0000$")
        zone.updateStatesOnServer.assert_not_called()


class TestOutageEvents:
    def test_disconnected_once_per_outage_then_reconnected(self):
        p, fired = _plugin_with_partition()
        for _ in range(4):
            p._on_disconnect("loop_exited")
        p._on_login(hp.LoginResult.OK)
        p._on_disconnect("loop_exited")
        assert fired == ["evl_disconnected", "evl_reconnected", "evl_disconnected"]
        assert p.logger.warning.call_count == 2

    def test_normal_login_does_not_fire_reconnected(self):
        p, fired = _plugin_with_partition()
        p._on_login(hp.LoginResult.OK)
        assert fired == []

    def test_shutdown_marks_devices_disconnected(self):
        p, _fired = _plugin_with_partition()
        p.panel_dev = MagicMock()
        p.shutdown()
        p.panel_dev.updateStateOnServer.assert_called_with("connected", value=False)
        p.partition_devs[1].setErrorStateOnServer.assert_called_with("disconnected")


class TestDeclarations:
    def test_new_events_and_state_declared(self):
        import xml.etree.ElementTree as ET
        base = plugin._os.path.dirname(plugin.__file__)
        events = {e.get("id") for e in ET.parse(f"{base}/Events.xml").getroot()}
        assert {"evl_reconnected", "command_failed"} <= events
        states = {s.get("id") for s in ET.parse(f"{base}/Devices.xml").getroot().iter("State")}
        assert "lowBattery" in states

    def test_unused_names_removed(self):
        for name in ("ZoneState", "VISTA_MODELS", "TPI_POLL_RESPONSE"):
            assert not hasattr(hp, name)
        assert not hasattr(hp.LoginResult, "DISCONNECTED")
