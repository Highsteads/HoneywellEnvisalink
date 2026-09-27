#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_plugin.py
# Description: Pytest suite for plugin.py — config coercion and partition-event
#              de-spam logic. Stubs the `indigo` module so plugin.py imports
#              standalone (no live Indigo server needed).
# Author:      Highsteads / CliveS & Claude Opus 4.8

import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock

PLUGIN_SRC = Path(__file__).parent.parent / "HoneywellEnvisalink.indigoPlugin" / "Contents" / "Server Plugin"
sys.path.insert(0, str(PLUGIN_SRC))

# --- Stub the indigo module BEFORE importing plugin -------------------------
_ind = types.ModuleType("indigo")


class _PluginBase:
    def __init__(self, *a, **k):
        pass


_ind.PluginBase = _PluginBase
_ind.Dict = dict
_ind.List = list
for _attr in ("kStateImageSel", "server", "devices", "variables", "trigger",
              "kSensorAction", "kDeviceAction", "activePlugin"):
    setattr(_ind, _attr, MagicMock())
sys.modules["indigo"] = _ind

import plugin  # noqa: E402
from honeywell_protocol import PartitionState  # noqa: E402


# ────────────────────────────────────────────────────────────────────────────
# Config coercion helpers
# ────────────────────────────────────────────────────────────────────────────

class TestAsBool:
    def test_real_bools(self):
        assert plugin._as_bool(True) is True
        assert plugin._as_bool(False) is False

    def test_string_truthy(self):
        for v in ("true", "True", "1", "yes", "on", " TRUE "):
            assert plugin._as_bool(v) is True

    def test_string_falsy(self):
        # The key regression: the string "false" must NOT read as truthy.
        for v in ("false", "False", "0", "no", "off", ""):
            assert plugin._as_bool(v) is False

    def test_none_uses_default(self):
        assert plugin._as_bool(None, default=True) is True
        assert plugin._as_bool(None, default=False) is False


class TestAsPort:
    def test_valid_int_and_string(self):
        assert plugin._as_port(4025) == 4025
        assert plugin._as_port("4025") == 4025
        assert plugin._as_port(" 8080 ") == 8080

    def test_blank_falls_back(self):
        assert plugin._as_port("") == plugin.DEFAULT_PORT
        assert plugin._as_port(None) == plugin.DEFAULT_PORT

    def test_non_numeric_falls_back(self):
        assert plugin._as_port("abc") == plugin.DEFAULT_PORT

    def test_out_of_range_falls_back(self):
        assert plugin._as_port("0") == plugin.DEFAULT_PORT
        assert plugin._as_port("70000") == plugin.DEFAULT_PORT


# ────────────────────────────────────────────────────────────────────────────
# Partition-event de-spam
# ────────────────────────────────────────────────────────────────────────────

def make_plugin():
    p = plugin.Plugin("com.clives.indigoplugin.honeywell-envisalink",
                      "HoneywellEnvisalink", "0.2.0-beta", {})
    fired = []
    p._fire_event = lambda event_id: fired.append(event_id)
    return p, fired


class TestPartitionEventDedup:
    def test_fires_once_per_change(self):
        p, fired = make_plugin()
        p._emit_partition_events(1, PartitionState.ARMED_AWAY)
        p._emit_partition_events(1, PartitionState.ARMED_AWAY)   # repeat — no re-fire
        assert fired == ["armed_away"]

    def test_refires_on_transition(self):
        p, fired = make_plugin()
        p._emit_partition_events(1, PartitionState.READY)
        p._emit_partition_events(1, PartitionState.ARMED_AWAY)
        p._emit_partition_events(1, PartitionState.READY)
        assert fired == ["disarmed", "armed_away", "disarmed"]

    def test_not_ready_fires_disarmed(self):
        p, fired = make_plugin()
        p._emit_partition_events(1, PartitionState.NOT_READY)
        assert fired == ["disarmed"]

    def test_instant_and_max_fire_their_events(self):
        p, fired = make_plugin()
        p._emit_partition_events(1, PartitionState.ARMED_INSTANT)
        p._emit_partition_events(1, PartitionState.ARMED_MAX)
        assert fired == ["armed_instant", "armed_max"]

    def test_transitional_state_does_not_fire(self):
        p, fired = make_plugin()
        p._emit_partition_events(1, PartitionState.EXIT_DELAY)
        p._emit_partition_events(1, PartitionState.ENTRY_DELAY)
        assert fired == []

    def test_partitions_are_independent(self):
        p, fired = make_plugin()
        p._emit_partition_events(1, PartitionState.ARMED_AWAY)
        p._emit_partition_events(2, PartitionState.ARMED_AWAY)
        assert fired == ["armed_away", "armed_away"]


# ────────────────────────────────────────────────────────────────────────────
# Menu-driven protocol capture (read-only)
# ────────────────────────────────────────────────────────────────────────────

class TestMenuCapture:
    def _plugin(self):
        p = plugin.Plugin("com.clives.indigoplugin.honeywell-envisalink",
                          "HoneywellEnvisalink", "0.4.0-beta", {})
        p.logger = MagicMock()
        return p

    def test_on_raw_line_noop_when_not_capturing(self):
        p = self._plugin()
        assert p._capture is None
        p._on_raw_line("%00,01,1C08,08,00,Ready$")   # must not raise
        assert p._capture is None

    def test_on_raw_line_accumulates_when_capturing(self):
        p = self._plugin()
        p._capture = {"records": [], "counts": {}, "unparsed": 0, "start": time.time()}
        p._on_raw_line("%00,01,1C08,08,00,****DISARMED**** Ready$")
        p._on_raw_line("garbage no dollar")
        assert len(p._capture["records"]) == 2
        assert p._capture["unparsed"] == 1
        assert p._capture["counts"].get("%00") == 1

    def test_menu_capture_guards_when_not_connected(self):
        p = self._plugin()
        p.client = None
        p.menu_capture_data({"duration_min": "3"}, None)
        assert p._capture is None
        assert p.logger.error.called

    def test_menu_capture_guards_when_already_running(self):
        p = self._plugin()
        p.client = MagicMock()
        p.client.is_connected.return_value = True
        p._capture = {"records": [], "counts": {}, "unparsed": 0, "start": time.time()}
        p.menu_capture_data({"duration_min": "3"}, None)   # should refuse, not start a 2nd
        assert p.logger.warning.called


# ────────────────────────────────────────────────────────────────────────────
# Zone-timer poll (door-status latency fix)
# ────────────────────────────────────────────────────────────────────────────

class TestZonePoll:
    def test_as_zone_poll(self):
        assert plugin._as_zone_poll(30) == 30
        assert plugin._as_zone_poll("60") == 60
        assert plugin._as_zone_poll(0) == 0            # 0 disables
        assert plugin._as_zone_poll("0") == 0
        assert plugin._as_zone_poll(2) == plugin.MIN_ZONE_POLL_S       # clamped up
        assert plugin._as_zone_poll("abc") == plugin.DEFAULT_ZONE_POLL_S
        assert plugin._as_zone_poll("") == plugin.DEFAULT_ZONE_POLL_S

    def test_zone_dump_respects_recent_realtime_update(self):
        p = plugin.Plugin("com.clives.indigoplugin.honeywell-envisalink",
                          "HoneywellEnvisalink", "0.5.0-beta", {})
        p.logger = MagicMock()
        p.zone_poll_seconds = 30
        d4, d8 = MagicMock(), MagicMock()
        p.zone_devs = {4: d4, 8: d8}
        p.zone_last_change = {4: time.time()}          # zone 4 just changed via %01
        frame = types.SimpleNamespace(payload="0000" * 7 + "FFFF")   # zone 8 open per dump
        p._handle_zone_timer_dump(frame)
        d8.updateStatesOnServer.assert_called()        # stale zone refreshed from the dump
        d4.updateStatesOnServer.assert_not_called()    # fresh zone left to the %01 stream


class TestStrainWarning:
    def _p(self):
        p = plugin.Plugin("com.clives.indigoplugin.honeywell-envisalink",
                          "HoneywellEnvisalink", "0.5.1-beta", {})
        p.logger = MagicMock()
        p.zone_poll_seconds = 5
        p._last_strain_warn = 0.0
        return p

    def test_strain_response_warns(self):
        p = self._p()
        p._handle_command_response(types.SimpleNamespace(code="^02", payload="05"))  # timeout
        assert p.logger.warning.called

    def test_strain_warning_is_rate_limited(self):
        p = self._p()
        p._handle_command_response(types.SimpleNamespace(code="^02", payload="05"))
        p.logger.warning.reset_mock()
        p._handle_command_response(types.SimpleNamespace(code="^02", payload="04"))  # again, immediately
        assert not p.logger.warning.called                                          # rate-limited

    def test_clean_response_does_not_warn(self):
        p = self._p()
        p._handle_command_response(types.SimpleNamespace(code="^00", payload="00"))  # accepted
        assert not p.logger.warning.called


# ────────────────────────────────────────────────────────────────────────────
# Dialog validation — partition 1-8, zone 1-250, bypass zone 1-250 (0.6.0)
# ────────────────────────────────────────────────────────────────────────────

def _bare_plugin():
    p = plugin.Plugin("com.clives.indigoplugin.honeywell-envisalink",
                      "HoneywellEnvisalink", "0.6.0", {})
    p.logger = MagicMock()
    return p


class TestDeviceValidation:
    def test_partition_in_range_accepted(self):
        p = _bare_plugin()
        for v in ("1", "8", " 3 "):
            assert p.validateDeviceConfigUi({"partition_number": v}, "partition", 0)[0] is True

    def test_partition_out_of_range_refused(self):
        p = _bare_plugin()
        for v in ("0", "9", "", "abc", "1.5", None):
            ok, _vals, errs = p.validateDeviceConfigUi({"partition_number": v}, "partition", 0)
            assert ok is False
            assert "1 to 8" in errs["partition_number"]

    def test_zone_left_at_zero_refused(self):
        p = _bare_plugin()
        ok, _vals, errs = p.validateDeviceConfigUi({"zone_number": "0"}, "zone", 0)
        assert ok is False
        assert "1 to 250" in errs["zone_number"]

    def test_zone_range(self):
        p = _bare_plugin()
        assert p.validateDeviceConfigUi({"zone_number": "1"}, "zone", 0)[0] is True
        assert p.validateDeviceConfigUi({"zone_number": "250"}, "zone", 0)[0] is True
        assert p.validateDeviceConfigUi({"zone_number": "251"}, "zone", 0)[0] is False
        assert p.validateDeviceConfigUi({"zone_number": ""}, "zone", 0)[0] is False

    def test_panel_has_nothing_to_check(self):
        p = _bare_plugin()
        assert p.validateDeviceConfigUi({"model": "vista20p"}, "panel", 0)[0] is True


class TestBypassValidation:
    def test_bypass_zone_range_in_dialog(self):
        p = _bare_plugin()
        assert p.validateActionConfigUi({"zone_number": "12"}, "bypass_zone", 0)[0] is True
        for v in ("0", "251", "", "abc"):
            ok, _vals, errs = p.validateActionConfigUi({"zone_number": v}, "bypass_zone", 0)
            assert ok is False
            assert "1 to 250" in errs["zone_number"]

    def test_other_actions_not_checked_for_a_zone(self):
        p = _bare_plugin()
        assert p.validateActionConfigUi({"user_code": "1234"}, "arm_stay", 0)[0] is True

    def test_saved_bad_bypass_zone_refused_without_sending(self):
        # An action saved before the dialog checked it must log, not raise.
        p = _bare_plugin()
        p.test_mode = False
        p.client = MagicMock()
        p.client.is_connected.return_value = True
        action = types.SimpleNamespace(props={"user_code": "1234", "zone_number": "0"})
        dev = MagicMock()
        dev.pluginProps = {"partition_number": "1"}
        p.action_bypass_zone(action, dev)
        p.client.send_keypresses.assert_not_called()
        assert p.logger.error.called


# ────────────────────────────────────────────────────────────────────────────
# Banner on demand — Test connection prints it first (house rule)
# ────────────────────────────────────────────────────────────────────────────

class TestBanner:
    def _p(self, monkeypatch):
        p = _bare_plugin()
        p.pluginId = plugin.PLUGIN_ID
        p.pluginDisplayName = "HoneywellEnvisalink"
        p.pluginVersion = "9.9.9"          # what Indigo reads from Info.plist
        banner = MagicMock()
        monkeypatch.setattr(plugin, "log_startup_banner", banner)
        return p, banner

    def test_test_connection_logs_banner_with_show_info_extras(self, monkeypatch):
        p, banner = self._p(monkeypatch)
        p.showPluginInfo()
        info_call = banner.call_args
        banner.reset_mock()
        p.client = MagicMock()
        p.client.get_stats.return_value = {"connected": False}
        p.menu_test_connection()
        banner.assert_called_once()
        assert banner.call_args == info_call

    def test_banner_logged_even_with_no_client(self, monkeypatch):
        p, banner = self._p(monkeypatch)
        p.client = None
        p.menu_test_connection()
        banner.assert_called_once()

    def test_banner_uses_indigo_version_and_is_ascii(self, monkeypatch):
        p, banner = self._p(monkeypatch)
        p.showPluginInfo()
        args, kwargs = banner.call_args
        assert args[2] == "9.9.9"
        for label, value in kwargs["extras"]:
            assert (label + value).isascii()


# ────────────────────────────────────────────────────────────────────────────
# Toggle test mode — a real log level on both branches
# ────────────────────────────────────────────────────────────────────────────

class TestToggleTestModeLevel:
    def test_level_is_a_real_logging_level_both_ways(self):
        import logging
        p = _bare_plugin()
        p.pluginPrefs = {}
        p.test_mode = True
        levels = []
        for _ in range(2):             # ON -> OFF, then OFF -> ON
            plugin.indigo.server.log.reset_mock()
            p.menu_toggle_test_mode()
            levels.append(plugin.indigo.server.log.call_args.kwargs.get("level"))
        assert levels == [logging.WARNING, logging.INFO]


# ────────────────────────────────────────────────────────────────────────────
# IndigoSecrets_example.py carries every key the plugin reads, left blank
# ────────────────────────────────────────────────────────────────────────────

def test_secrets_example_covers_every_key_the_plugin_reads():
    import ast
    src = ast.parse((PLUGIN_SRC / "plugin.py").read_text(encoding="utf-8"))
    wanted = {a.name for n in ast.walk(src)
              if isinstance(n, ast.ImportFrom) and n.module == "IndigoSecrets"
              for a in n.names}
    assert wanted, "plugin.py no longer reads IndigoSecrets — update this test"
    example = PLUGIN_SRC / "IndigoSecrets_example.py"
    ns = {}
    exec(example.read_text(encoding="utf-8"), ns)
    for key in wanted:
        assert key in ns, f"{key} missing from IndigoSecrets_example.py"
        assert ns[key] == "", f"{key} must be blank in the example"
