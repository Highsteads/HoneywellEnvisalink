#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_client.py
# Description: Pytest suite for envisalink_client.py — credential-redaction and
#              send-guard behaviour. No real sockets, no Indigo APIs.
# Author:      Highsteads / CliveS & Claude Opus 4.8

import sys
from pathlib import Path

PLUGIN_SRC = Path(__file__).parent.parent / "HoneywellEnvisalink.indigoPlugin" / "Contents" / "Server Plugin"
sys.path.insert(0, str(PLUGIN_SRC))

from envisalink_client import EnvisalinkClient


class FakeLogger:
    """Captures log messages so tests can assert on what would be written."""
    def __init__(self):
        self.messages = []
    def _rec(self, level, msg):
        self.messages.append((level, msg))
    def info(self, msg):    self._rec("info", msg)
    def warning(self, msg): self._rec("warning", msg)
    def error(self, msg):   self._rec("error", msg)
    def debug(self, msg):   self._rec("debug", msg)

    def all_text(self):
        return "\n".join(m for _lvl, m in self.messages)


SECRET = "sup3rSecretPass"


def make_client(**kw):
    log = FakeLogger()
    client = EnvisalinkClient(
        host="192.168.1.50",
        password=SECRET,
        on_frame=lambda f: None,
        logger=log,
        debug_protocol=True,   # so _record_debug also writes to the (fake) log
        **kw,
    )
    return client, log


# ────────────────────────────────────────────────────────────────────────────
# Credential redaction — the password must never reach the ring buffer or log
# ────────────────────────────────────────────────────────────────────────────

class TestCredentialRedaction:
    def test_login_marker_recorded_not_password(self):
        # The recv-loop login branch records a fixed marker, never the password.
        client, log = make_client()
        client._record_debug("TX", "<login: ****>")
        buf = client.get_debug_log()
        assert any("<login: ****>" in line for _ts, _d, line in buf)
        assert SECRET not in log.all_text()

    def test_bare_tx_line_is_blanked(self):
        # Defence-in-depth: even if a bare (non-^) line were ever passed as TX,
        # _record_debug must blank it — it can only be the login password.
        client, log = make_client()
        client._record_debug("TX", SECRET + "\r\n")
        buf = client.get_debug_log()
        for _ts, _d, line in buf:
            assert SECRET not in line
        assert SECRET not in log.all_text()

    def test_tx_keystroke_code_redacted(self):
        client, log = make_client()
        client._record_debug("TX", "^00,11234A57")
        buf = client.get_debug_log()
        joined = "\n".join(line for _ts, _d, line in buf)
        assert "1234" not in joined
        assert "****" in joined

    def test_rx_frame_recorded(self):
        client, _log = make_client()
        client._record_debug("RX", "%00,1,02,000,00,Ready")
        buf = client.get_debug_log()
        assert any(line.startswith("%00,1,02") for _ts, _d, line in buf)

    def test_debug_log_never_contains_password_after_login_record(self):
        # End-to-end of the recorder: simulate exactly what the login branch does.
        client, log = make_client()
        client._record_debug("TX", "<login: ****>")   # what the code now records
        client._record_debug("RX", "OK")
        assert SECRET not in log.all_text()
        assert all(SECRET not in line for _ts, _d, line in client.get_debug_log())


# ────────────────────────────────────────────────────────────────────────────
# send_raw guard — drops safely when not connected, and redacts the dropped line
# ────────────────────────────────────────────────────────────────────────────

class TestSendRawGuard:
    def test_send_dropped_when_not_connected(self):
        client, _log = make_client()
        # Never started → not connected, no socket
        assert client.send_raw("^00,11234A57\r\n") is False

    def test_dropped_send_log_redacts_user_code(self):
        client, log = make_client()
        client.send_raw("^00,11234A57\r\n")
        text = log.all_text()
        assert "send dropped" in text
        assert "1234" not in text   # the user code must not leak into the warning


# ────────────────────────────────────────────────────────────────────────────
# Auth-failed flag — initial state
# ────────────────────────────────────────────────────────────────────────────

class TestAuthFailedFlag:
    def test_auth_failed_defaults_false(self):
        client, _log = make_client()
        assert client._auth_failed is False
