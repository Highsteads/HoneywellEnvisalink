#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    mock_evl_server.py
# Description: A mock Envisalink server speaking the REAL Honeywell TPI protocol
#              ($-terminated frames, no checksum, 16-bit keypad flags). Lets you
#              develop and demo the plugin against fake hardware.
# Author:      Highsteads / CliveS & Claude Opus 4.8
# Date:        26-06-2026
# Version:     0.3.0
#
# Usage:
#   python3 tools/mock_evl_server.py [--port 4025] [--password user] [--scenario default]
#
# Then point the plugin at  localhost:4025  with the password you set.
#
# Scenarios:
#   default       — plausible events: zone trips, arm, alarm, disarm
#   ready_only    — just sits showing 'Ready to Arm'
#   stress        — fires events as fast as the client will accept them

import argparse
import socket
import sys
import threading
import time
from pathlib import Path

PLUGIN_SRC = Path(__file__).parent.parent / "HoneywellEnvisalink.indigoPlugin" / "Contents" / "Server Plugin"
sys.path.insert(0, str(PLUGIN_SRC))

from honeywell_protocol import (
    FLAG_READY, FLAG_AC_PRESENT, FLAG_ARMED_AWAY, FLAG_ALARM, FLAG_BYPASS,
)


def make_line(prefix, code, data=""):
    """Real Honeywell TPI framing: <prefix><CC>,<DATA>$ + CRLF, NO checksum."""
    return f"{prefix}{code},{data}$\r\n".encode()


def keypad_update(partition, flags, zone=0, beep=0, text="Ready to Arm"):
    text = text[:32]
    return make_line("%", "00", f"{partition:02d},{flags:04X},{zone:02d},{beep:02d},{text}")


def partition_state(codes):
    """codes: list of eight 2-char partition status codes."""
    return make_line("%", "02", "".join(codes))


def cid_event(qualifier, code, partition, zone_or_user):
    return make_line("%", "03", f"{qualifier}{code:03d}{partition:02d}{zone_or_user:03d}")


READY   = FLAG_READY | FLAG_AC_PRESENT                 # 0x1008 — disarmed, ready
EXITING = FLAG_ARMED_AWAY | FLAG_AC_PRESENT            # arming, exit delay
ARMED   = FLAG_ARMED_AWAY | FLAG_AC_PRESENT            # armed away
INALARM = FLAG_ALARM | FLAG_ARMED_AWAY | FLAG_AC_PRESENT


class MockEVL:
    def __init__(self, port, password, scenario):
        self.port = port
        self.password = password
        self.scenario = scenario
        self.server_sock = None
        self.stop = threading.Event()

    def run(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("0.0.0.0", self.port))
        self.server_sock.listen(1)
        print(f"[mock_evl] listening on 0.0.0.0:{self.port}  scenario={self.scenario}")
        try:
            while not self.stop.is_set():
                client_sock, addr = self.server_sock.accept()
                print(f"[mock_evl] client connected from {addr}")
                threading.Thread(target=self.handle, args=(client_sock,), daemon=True).start()
        except KeyboardInterrupt:
            print("\n[mock_evl] shutting down")
        finally:
            self.server_sock.close()

    def handle(self, sock):
        sock.sendall(b"Login:\r\n")
        buf = b""
        sock.settimeout(10)
        try:
            while b"\r\n" not in buf:
                data = sock.recv(256)
                if not data:
                    return
                buf += data
        except socket.timeout:
            print("[mock_evl] login timeout")
            return
        line, _, _ = buf.partition(b"\r\n")
        pw = line.decode("ascii", "replace").strip()
        if pw != self.password:
            sock.sendall(b"FAILED\r\n")
            print(f"[mock_evl] bad password: {pw!r}")
            return
        sock.sendall(b"OK\r\n")
        print("[mock_evl] login OK")

        # Drain + respond to the client's outgoing commands (keepalive/dump/keypress)
        threading.Thread(target=self._reader, args=(sock,), daemon=True).start()
        try:
            self.run_scenario(sock)
        except (OSError, BrokenPipeError) as e:
            print(f"[mock_evl] client disconnected: {e}")

    def _reader(self, sock):
        sock2 = sock
        buf = b""
        try:
            sock2.settimeout(1.0)
            while not self.stop.is_set():
                try:
                    data = sock2.recv(256)
                except socket.timeout:
                    continue
                if not data:
                    return
                buf += data
                while b"\r\n" in buf:
                    line, buf = buf.split(b"\r\n", 1)
                    text = line.decode("ascii", "replace")
                    if text.startswith("^00,"):          # KeepAlive → poll response
                        sock2.sendall(make_line("^", "00", "00"))
                    elif text.startswith("^02,"):        # DumpZoneTimers → empty dump
                        sock2.sendall(make_line("%", "FF", "0" * 128))
                    elif text.startswith("^03,"):        # keypress — just ack
                        sock2.sendall(make_line("^", "03", "00"))
        except OSError:
            return

    def run_scenario(self, sock):
        if self.scenario == "stress":
            self.scenario_stress(sock)
        elif self.scenario == "ready_only":
            self.scenario_ready_only(sock)
        else:
            self.scenario_default(sock)

    def scenario_ready_only(self, sock):
        while not self.stop.is_set():
            sock.sendall(keypad_update(1, READY, text="****DISARMED****  Ready to Arm  "))
            time.sleep(10)

    def scenario_default(self, sock):
        scripts = [
            (0,  keypad_update(1, READY, text="****DISARMED****  Ready to Arm  ")),
            (5,  keypad_update(1, READY, zone=1, beep=1, text="FAULT 01 FRONT DOOR             ")),
            (3,  keypad_update(1, READY, text="****DISARMED****  Ready to Arm  ")),
            (5,  keypad_update(1, EXITING, beep=3, text="ARMED ***AWAY***  May Exit Now  ")),
            (10, partition_state(["05", "00", "00", "00", "00", "00", "00", "00"])),
            (0,  keypad_update(1, ARMED, text="ARMED ***AWAY***                ")),
            (15, cid_event(1, 130, 1, 5)),
            (0,  keypad_update(1, INALARM, zone=5, beep=4, text="ALARM 05 MOTION                 ")),
            (15, keypad_update(1, READY, text="****DISARMED****  Ready to Arm  ")),
        ]
        while not self.stop.is_set():
            for delay, msg in scripts:
                if self.stop.is_set():
                    break
                if delay:
                    time.sleep(delay)
                sock.sendall(msg)

    def scenario_stress(self, sock):
        i = 0
        while not self.stop.is_set():
            flags = READY if i % 2 == 0 else (READY | FLAG_BYPASS)
            sock.sendall(keypad_update(1, flags, text=f"Cycle {i}                        "))
            i += 1
            time.sleep(0.05)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port",     type=int, default=4025)
    ap.add_argument("--password", default="user")
    ap.add_argument("--scenario", default="default",
                    choices=["default", "ready_only", "stress"])
    args = ap.parse_args()
    MockEVL(args.port, args.password, args.scenario).run()


if __name__ == "__main__":
    main()
