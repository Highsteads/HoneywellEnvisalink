#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    mock_evl_server.py
# Description: A minimal mock Envisalink server speaking the Honeywell TPI
#              protocol. Lets you develop and demo the plugin against fake
#              hardware before testing on real kit. Also useful for
#              regression tests in CI.
# Author:      Highsteads / CliveS & Claude
# Date:        24-05-2026
# Version:     0.1.0
#
# Usage:
#   python3 tools/mock_evl_server.py [--port 4025] [--password user] [--scenario default]
#
# Then point the plugin at  localhost:4025  with the password you set.
#
# Scenarios:
#   default       — fires a series of plausible events: zone trips, arm, alarm
#   ready_only    — just sits showing 'Ready' for the partition
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
    tpi_checksum, LED_ARMED, LED_READY, LED_BYPASS, LED_AC_POWER, LED_ALARM,
)


def make_line(prefix, code, payload):
    body = f"{code},{payload}" if payload else code
    return f"{prefix}{body}{tpi_checksum(body)}\r\n".encode()


def keypad_update(partition, led, zone=0, beep=0, text="Ready"):
    text = text[:32].ljust(32)
    payload = f"{partition},{led:02X},{zone:03d},{beep},{text}"
    return make_line("%", "00", payload)


def zone_state(zone, state):
    return make_line("%", "01", f"{zone:03d},{state}")


def partition_state(partition, state):
    return make_line("%", "02", f"{partition},{state}")


def cid_event(qualifier, code, partition, zone_or_user):
    return make_line("%", "03", f"{qualifier}{code:03d}{partition:02d}{zone_or_user:04d}")


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
        # Wait for password
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
        print(f"[mock_evl] login OK")

        # Start sending the scenario
        try:
            self.run_scenario(sock)
        except (OSError, BrokenPipeError) as e:
            print(f"[mock_evl] client disconnected: {e}")

    def run_scenario(self, sock):
        if self.scenario == "stress":
            self.scenario_stress(sock)
        elif self.scenario == "ready_only":
            self.scenario_ready_only(sock)
        else:
            self.scenario_default(sock)

    def scenario_ready_only(self, sock):
        while not self.stop.is_set():
            sock.sendall(keypad_update(1, LED_READY | LED_AC_POWER, text="Ready                    "))
            time.sleep(30)

    def scenario_default(self, sock):
        scripts = [
            (0,    keypad_update(1, LED_READY | LED_AC_POWER, text="Ready                    ")),
            (2,    zone_state(1, "C")),
            (2,    zone_state(2, "C")),
            (5,    zone_state(1, "O")),    # front door opens
            (1,    keypad_update(1, LED_AC_POWER, zone=1, beep=1, text="Faulted 01 Front Door    ")),
            (3,    zone_state(1, "C")),    # closed again
            (1,    keypad_update(1, LED_READY | LED_AC_POWER, text="Ready                    ")),
            (5,    partition_state(1, "EXIT_DELAY")),
            (0,    keypad_update(1, LED_ARMED | LED_AC_POWER, beep=3, text="ARMED MAY EXIT NOW       ")),
            (10,   partition_state(1, "ARMED_AWAY")),
            (0,    keypad_update(1, LED_ARMED | LED_AC_POWER, text="ARMED ***AWAY***         ")),
            (15,   zone_state(5, "O")),    # motion triggers
            (0,    cid_event(1, 130, 1, 5)),
            (0,    partition_state(1, "ALARM")),
            (0,    keypad_update(1, LED_ARMED | LED_ALARM | LED_AC_POWER, zone=5,
                                 beep=10, text="ALARM ZONE 5             ")),
            (15,   partition_state(1, "READY")),
            (0,    keypad_update(1, LED_READY | LED_AC_POWER, text="Ready                    ")),
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
            zone = (i % 8) + 1
            sock.sendall(zone_state(zone, "O" if i % 2 == 0 else "C"))
            i += 1
            if i % 20 == 0:
                sock.sendall(keypad_update(1, LED_READY | LED_AC_POWER,
                                           text=f"Cycle {i}                "))
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
