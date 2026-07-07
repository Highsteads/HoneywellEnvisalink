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
