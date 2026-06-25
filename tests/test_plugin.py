#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_plugin.py
# Description: Pytest suite for plugin.py — config coercion and partition-event
#              de-spam logic. Stubs the `indigo` module so plugin.py imports
#              standalone (no live Indigo server needed).
# Author:      Highsteads / CliveS & Claude Opus 4.8

import sys
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
