#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    envisalink_client.py
# Description: TCP client for the Envisalink TPI socket (port 4025).
#              Handles connect, login, reconnect, line framing, and dispatching
#              parsed frames to a callback. Debug logging mode dumps every byte
#              in both directions (with user codes redacted).
# Author:      Highsteads / CliveS & Claude
# Date:        24-05-2026
# Version:     0.1.1

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
DEFAULT_CONNECT_TIMEOUT_S = 10
DEFAULT_RECV_TIMEOUT_S = 60       # EVL pings every ~30s, so 60s is a safe inactivity window
DEFAULT_RECONNECT_DELAY_S = 5
MAX_RECONNECT_DELAY_S = 60
DEBUG_RING_BUFFER_SIZE = 500      # last N raw lines kept in memory for diagnostics


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
        """Signal the background thread to exit and close the socket."""
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
            self._thread.join(timeout=5)

    def is_connected(self) -> bool:
        return self._connected

    def send_raw(self, line: str) -> bool:
        """
        Send a single raw TPI line to the EVL. Must already include the
        trailing \\r\\n and the checksum. Returns False if not connected.
        Thread-safe.
        """
        if not self._connected or not self._sock:
            self._log("warning", f"send dropped — not connected: {line!r}")
            return False
        data = line.encode("ascii", errors="replace")
        with self._send_lock:
            try:
                self._sock.sendall(data)
            except OSError as e:
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
        safe = redact_line_for_log(line.rstrip("\r\n"))
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
        sock.settimeout(DEFAULT_RECV_TIMEOUT_S)
        self._sock = sock
        self.connect_count += 1
        self.last_connect_ts = time.time()

        # Receive loop with line buffering
        buf = b""
        login_done = False
        while not self._stop_evt.is_set():
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                # No traffic for a while — EVL should be sending keepalives.
                # Treat as a soft failure and reconnect.
                self._log("warning", "recv timeout — assuming connection stale")
                break
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
                line, buf = buf.split(b"\r\n", 1)
                try:
                    text = line.decode("ascii", errors="replace")
                except Exception:
                    continue
                self._record_debug("RX", text)

                if not login_done:
                    if text == "Login:":
                        # EVL is asking for password
                        self.send_raw(encode_login(self.password))
                        continue
                    if text == "OK":
                        login_done = True
                        self._connected = True
                        self._log("info", "login OK — connection live")
                        self.on_login(LoginResult.OK)
                        continue
                    if text == "FAILED":
                        self._log("error", "login FAILED — check EVL password in plugin config")
                        self.on_login(LoginResult.FAILED)
                        return   # don't retry — wrong creds won't fix themselves
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
