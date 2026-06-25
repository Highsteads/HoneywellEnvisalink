#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    envisalink_client.py
# Description: TCP client for the Envisalink TPI socket (port 4025).
#              Handles connect, login, reconnect, line framing, and dispatching
#              parsed frames to a callback. Debug logging mode dumps every byte
#              in both directions (with user codes redacted).
# Author:      Highsteads / CliveS & Claude Opus 4.8
# Date:        25-06-2026
# Version:     0.2.0-beta

import socket
import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable, Optional

from honeywell_protocol import (
    LoginResult, RawFrame, parse_frame, encode_login, redact_line_for_log,
)


DEFAULT_PORT = 4025
DEFAULT_CONNECT_TIMEOUT_S = 5     # connect blocks the thread (self._sock not yet set), keep it tight
RECV_SOCKET_TIMEOUT_S = 1.0       # short tick: lets the recv loop wake promptly when _stop_evt flips
STALE_CONNECTION_S = 60           # EVL pings every ~30s — no traffic for 60s ⇒ treat as stale and reconnect
DEFAULT_RECONNECT_DELAY_S = 5
MAX_RECONNECT_DELAY_S = 60
DEBUG_RING_BUFFER_SIZE = 500      # last N raw lines kept in memory for diagnostics
THREAD_JOIN_TIMEOUT_S = 3         # shutdown grace period — short, so plugin host exits promptly


class EnvisalinkClient:
    """
    Persistent TCP connection to an Envisalink module speaking the Honeywell
    TPI protocol. Runs the receive loop in a background thread.

    Usage:
        client = EnvisalinkClient(
            host="192.168.1.50",
            password="user",
            on_frame=lambda f: ...,
            logger=indigo_logger,
        )
        client.start()
        ...
        client.send_raw("^00,11234A...\r\n")   # outgoing command
        ...
        client.stop()
    """

    def __init__(
        self,
        host: str,
        password: str,
        on_frame: Callable[[RawFrame], None],
        on_login: Optional[Callable[[LoginResult], None]] = None,
        on_disconnect: Optional[Callable[[str], None]] = None,
        logger=None,
        port: int = DEFAULT_PORT,
        debug_protocol: bool = False,
    ):
        self.host = host
        self.password = password
        self.port = port
        self.on_frame = on_frame
        self.on_login = on_login or (lambda r: None)
        self.on_disconnect = on_disconnect or (lambda r: None)
        self.logger = logger
        self.debug_protocol = debug_protocol

        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._connected = False
        self._auth_failed = False   # set on login FAILED — stops the reconnect loop
        self._send_lock = threading.Lock()

        # Diagnostics — ring buffer of last N (timestamp, direction, line) tuples
        self._debug_log = deque(maxlen=DEBUG_RING_BUFFER_SIZE)
        self._debug_lock = threading.Lock()

        # Stats
        self.bytes_rx = 0
        self.bytes_tx = 0
        self.frames_rx = 0
        self.frames_tx = 0
        self.connect_count = 0
        self.last_connect_ts: Optional[float] = None
        self.last_rx_ts: Optional[float] = None

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self):
        """Spawn the background connection/receive thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"EnvisalinkClient[{self.host}]", daemon=True
        )
        self._thread.start()

    def stop(self):
        """Signal the background thread to exit and close the socket.

        Defensive order: set the stop event FIRST so the recv loop's short-tick
        wakeup sees it on the next iteration even if the socket-shutdown path
        below is a no-op (e.g. self._sock is None because we're mid-connect or
        mid-reconnect-delay). The 1s recv tick plus the event-driven backoff
        wait means the thread exits within ~1s in the worst case.
        """
        self._stop_evt.set()
        sock = self._sock
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=THREAD_JOIN_TIMEOUT_S)
            if self._thread.is_alive():
                # Daemon thread will die when the process exits, but log this
                # so future shutdown-stall investigations have a breadcrumb.
                self._log("warning",
                          f"client thread still alive after {THREAD_JOIN_TIMEOUT_S}s join — "
                          "daemon will be reaped at process exit")

    def is_connected(self) -> bool:
        return self._connected

    def send_raw(self, line: str) -> bool:
        """
        Send a single raw TPI line to the EVL. Must already include the
        trailing \\r\\n and the checksum. Returns False if not connected.
        Thread-safe.
        """
        # Capture the socket reference locally: stop()/the recv loop can set
        # self._sock to None between this guard and the sendall, which would
        # otherwise raise AttributeError on None.
        sock = self._sock
        if not self._connected or sock is None:
            # Redact: an action send carries the user code, which must never hit the log.
            self._log("warning", f"send dropped — not connected: {redact_line_for_log(line)!r}")
            return False
        data = line.encode("ascii", errors="replace")
        with self._send_lock:
            try:
                sock.sendall(data)
            except (OSError, AttributeError) as e:
                self._log("warning", f"send error: {e}")
                self._connected = False
                return False
            self.bytes_tx += len(data)
            self.frames_tx += 1
        self._record_debug("TX", line)
        return True

    def set_debug_protocol(self, enabled: bool):
        """Toggle verbose protocol logging at runtime."""
        self.debug_protocol = enabled
        self._log("info", f"protocol debug logging {'ENABLED' if enabled else 'disabled'}")

    def get_debug_log(self):
        """Return a copy of the recent-traffic ring buffer (list of tuples)."""
        with self._debug_lock:
            return list(self._debug_log)

    def get_stats(self) -> dict:
        return {
            "connected": self._connected,
            "host": self.host,
            "port": self.port,
            "bytes_rx": self.bytes_rx,
            "bytes_tx": self.bytes_tx,
            "frames_rx": self.frames_rx,
            "frames_tx": self.frames_tx,
            "connect_count": self.connect_count,
            "last_connect": (
                datetime.fromtimestamp(self.last_connect_ts).isoformat()
                if self.last_connect_ts else None
            ),
            "last_rx": (
                datetime.fromtimestamp(self.last_rx_ts).isoformat()
                if self.last_rx_ts else None
            ),
        }

    # ── Internal ────────────────────────────────────────────────────────────

    def _log(self, level: str, msg: str):
        if not self.logger:
            return
        fn = getattr(self.logger, level, None)
        if fn:
            fn(f"[envisalink] {msg}")

    def _record_debug(self, direction: str, line: str):
        ts = time.time()
        raw = line.rstrip("\r\n")
        # Defence-in-depth for credentials: the ONLY outbound line that is not a
        # "^" keystroke command is the bare login password. Never let it reach the
        # ring buffer (which feeds the diagnostic bundle) or the protocol log.
        if direction == "TX" and not raw.startswith("^"):
            safe = "<login: ****>"
        else:
            safe = redact_line_for_log(raw)
        with self._debug_lock:
            self._debug_log.append((ts, direction, safe))
        if self.debug_protocol:
            self._log("info", f"{direction}  {safe}")

    def _run(self):
        """Background thread: connect → login → recv loop → reconnect on failure."""
        reconnect_delay = DEFAULT_RECONNECT_DELAY_S
        while not self._stop_evt.is_set():
            try:
                self._connect_and_run()
                reconnect_delay = DEFAULT_RECONNECT_DELAY_S   # successful run resets backoff
            except Exception as e:
                self._log("warning", f"connection loop error: {e}")
            self._connected = False
            if self._auth_failed:
                # Wrong credentials won't fix themselves by retrying. The previous
                # code only `return`ed from _connect_and_run, so the outer loop here
                # reconnected and re-sent the bad password forever. Stop the loop.
                self._log("error",
                          "login FAILED — stopping reconnect. Fix the EVL password "
                          "in plugin config (or IndigoSecrets.py), then reload the plugin.")
                if not self._stop_evt.is_set():
                    self.on_disconnect("auth_failed")
                break
            # Suppress the disconnect callback when we're stopping — the plugin
            # is mid-shutdown, calling back into indigo APIs (trigger.execute,
            # device.updateStateOnServer) from this thread races the host's
            # cleanup and is the kind of thing that can stall the host exit.
            if not self._stop_evt.is_set():
                self.on_disconnect("loop_exited")
            if self._stop_evt.is_set():
                break
            self._log("info", f"reconnecting in {reconnect_delay}s")
            if self._stop_evt.wait(reconnect_delay):
                break
            reconnect_delay = min(reconnect_delay * 2, MAX_RECONNECT_DELAY_S)

    def _connect_and_run(self):
        self._log("info", f"connecting to {self.host}:{self.port}")
        sock = socket.create_connection((self.host, self.port), timeout=DEFAULT_CONNECT_TIMEOUT_S)
        sock.settimeout(RECV_SOCKET_TIMEOUT_S)
        self._sock = sock
        self.connect_count += 1
        self.last_connect_ts = time.time()
        self.last_rx_ts = time.time()  # seed so the stale-connection check has a baseline

        # Receive loop with line buffering. The socket timeout is short (1s) so
        # the loop wakes promptly when _stop_evt flips even if the socket
        # shutdown path in stop() was a no-op (e.g. self._sock not yet set
        # because we were mid-connect when stop() ran). Liveness of the
        # connection itself is tracked separately via last_rx_ts.
        buf = b""
        login_done = False
        while not self._stop_evt.is_set():
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                # Short-tick wakeup — not a connection failure. Loop back to
                # the stop-event check. Use last_rx_ts to spot a genuinely
                # stale connection (EVL pings ~every 30s).
                if time.time() - (self.last_rx_ts or 0) > STALE_CONNECTION_S:
                    self._log("warning", "no traffic for 60s — assuming connection stale")
                    break
                continue
            except OSError as e:
                self._log("warning", f"recv error: {e}")
                break

            if not chunk:
                self._log("info", "connection closed by remote")
                break

            self.bytes_rx += len(chunk)
            self.last_rx_ts = time.time()
            buf += chunk

            # TPI is line-delimited with CRLF
            while b"\r\n" in buf:
                # Re-check the stop event per line so on_login/on_frame are not
                # invoked into Indigo APIs once shutdown has been signalled —
                # mirrors the on_disconnect guard in _run().
                if self._stop_evt.is_set():
                    break
                line, buf = buf.split(b"\r\n", 1)
                try:
                    text = line.decode("ascii", errors="replace")
                except Exception:
                    continue
                self._record_debug("RX", text)

                if not login_done:
                    if text == "Login:":
                        # EVL is asking for password. Cannot use send_raw() here —
                        # that path gates on self._connected, which is only set to
                        # True AFTER the EVL replies "OK", which it can't do until
                        # we send the password. Direct sendall instead. send_raw()
                        # stays strict so action-handler sends still refuse if the
                        # connection isn't fully authenticated.
                        pwd_line = encode_login(self.password)
                        with self._send_lock:
                            try:
                                sock.sendall(pwd_line.encode("ascii", errors="replace"))
                            except OSError as e:
                                self._log("warning", f"login send failed: {e}")
                                break
                            self.bytes_tx += len(pwd_line)
                            self.frames_tx += 1
                        # NEVER record the credential — log a fixed marker only.
                        self._record_debug("TX", "<login: ****>")
                        continue
                    if text == "OK":
                        login_done = True
                        self._connected = True
                        self._auth_failed = False
                        self._log("info", "login OK — connection live")
                        self.on_login(LoginResult.OK)
                        continue
                    if text == "FAILED":
                        self._auth_failed = True   # _run() sees this and stops retrying
                        self.on_login(LoginResult.FAILED)
                        return
                    # Some EVL firmware sends a welcome banner before the prompt — ignore
                    continue

                # Normal frame
                try:
                    frame = parse_frame(text)
                except Exception as e:
                    self._log("warning", f"frame parse error: {e}  line={text!r}")
                    continue

                self.frames_rx += 1
                try:
                    self.on_frame(frame)
                except Exception as e:
                    self._log("error", f"on_frame callback raised: {e}")

        # Loop exited — clean up
        try:
            sock.close()
        except OSError:
            pass
        self._sock = None
        self._connected = False
