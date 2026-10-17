"""Regression cases found during the 1.0 review. No live Indigo or alarm access."""
import json
import os
import types
from unittest.mock import MagicMock

import pytest
from test_plugin import _bare_plugin
import honeywell_protocol as hp
import envisalink_client as ec
import tpi_capture as cap


@pytest.mark.parametrize('payload', ['', 'G000', '000', '00000', '0000ZZZZ'])
@pytest.mark.parametrize('decoder', [hp.open_zones_from_timer_dump, hp.decode_zone_timer_dump,
                                     lambda p: hp.parse_zone_state(hp.parse_frame(f'%01,{p}$'))])
def test_bad_zone_data_is_rejected(payload, decoder):
    with pytest.raises(hp.ProtocolError):
        decoder(payload)


def test_short_zone_reports_leave_uncovered_zones_alone():
    p = _bare_plugin()
    p.zone_devs = {1: MagicMock(), 32: MagicMock()}
    p._on_frame(hp.parse_frame('%01,0100$'))
    p.zone_devs[1].updateStatesOnServer.assert_called()
    p.zone_devs[32].updateStatesOnServer.assert_not_called()
    p.zone_last_change.clear()
    p._on_frame(hp.parse_frame('%FF,FFFF$'))
    p.zone_devs[32].updateStatesOnServer.assert_not_called()


def test_bad_zone_frame_does_not_close_open_zones():
    p = _bare_plugin()
    p.zone_devs = {1: MagicMock()}
    for line in ('%01,GGGG$', '%FF,GGGG$', '%FF,$'):
        p._on_frame(hp.parse_frame(line))
    p.zone_devs[1].updateStatesOnServer.assert_not_called()


@pytest.mark.parametrize('partition', ['bad', None, '', '0', '9'])
def test_invalid_saved_partition_never_sends_to_partition_one(partition):
    p = _bare_plugin()
    p.test_mode = False
    p.client = MagicMock()
    p.client.is_connected.return_value = True
    for method in ('action_disarm', 'action_arm_away', 'action_arm_stay',
                   'action_arm_instant', 'action_arm_max', 'action_bypass_zone'):
        getattr(p, method)(types.SimpleNamespace(props={'user_code': '1234', 'zone_number': '2'}),
                           types.SimpleNamespace(pluginProps={'partition_number': partition}))
    p.client.send_keypresses.assert_not_called()


@pytest.mark.parametrize('code', [None, 1234, '１２３４', '12345', ''])
def test_invalid_codes_refused_without_exception(code):
    p = _bare_plugin()
    assert p._user_code_from(types.SimpleNamespace(props={'user_code': code})) == ''


def test_fire_sets_alarm_boolean_as_well_as_primary_state():
    p = _bare_plugin()
    dev = MagicMock()
    p.partition_devs = {1: dev}
    p._handle_keypad_update(hp.KeypadUpdate(1, hp.FLAG_FIRE, 0, 0, 'FIRE'))
    states = {s['key']: s['value'] for s in dev.updateStatesOnServer.call_args.args[0]}
    assert states['state'] == 'alarm' and states['alarm'] is True


def test_max_without_display_is_still_max():
    ku = hp.KeypadUpdate(1, hp.FLAG_ARMED_AWAY | hp.FLAG_ARMED_NO_ENTRY, 0, 0, '')
    assert hp.derive_partition_state(ku) == hp.PartitionState.ARMED_MAX


def test_disconnect_marks_readings_stale_until_fresh_data():
    p = _bare_plugin()
    panel, part, zone = MagicMock(), MagicMock(), MagicMock()
    p.panel_dev, p.partition_devs, p.zone_devs = panel, {1: part}, {1: zone}
    p._on_disconnect('test')
    part.setErrorStateOnServer.assert_called_once()
    zone.setErrorStateOnServer.assert_called_once()
    p._on_login(hp.LoginResult.OK)
    assert part.setErrorStateOnServer.call_count == 1
    assert zone.setErrorStateOnServer.call_count == 1


@pytest.mark.parametrize('password', ['a\r\n^03,1,1$', 'a$b', 'a^b', 'é', ''])
def test_login_rejects_wire_delimiters_without_echoing_value(password):
    with pytest.raises(ValueError) as exc:
        hp.encode_login(password)
    if password:
        assert password not in str(exc.value)


def test_stop_immediately_reports_disconnected():
    c = ec.EnvisalinkClient('localhost', 'user', lambda _: None)
    c._connected = True
    c.stop()
    assert c.is_connected() is False


def test_interrupted_keypress_sequence_reports_failure():
    c = ec.EnvisalinkClient('localhost', 'user', lambda _: None)
    c.send_raw = MagicMock(return_value=True)
    c._stop_evt.set()
    assert c.send_keypresses(['a', 'b']) is False
    c.send_raw.assert_not_called()


def test_keypresses_never_resume_on_a_replacement_connection():
    c = ec.EnvisalinkClient('localhost', 'user', lambda _: None)
    c._sock, c._connected = object(), True
    def send(_, **kwargs):
        c._sock = object()
        return True
    c.send_raw = MagicMock(side_effect=send)
    assert c.send_keypresses(['a', 'b']) is False
    assert c.send_raw.call_count == 1


def test_busy_receive_stream_still_polls(monkeypatch):
    c = ec.EnvisalinkClient('localhost', 'user', lambda _: None, zone_poll_interval_s=5)
    tick = [0]
    class Sock:
        def settimeout(self, _): pass
        def recv(self, _):
            tick[0] += 1
            if tick[0] == 1: return b'OK\r\n'
            if tick[0] > 25: return b''
            return b'%00,01,1008,00,00,Ready$\r\n'
        def close(self): pass
    monkeypatch.setattr(ec.socket, 'create_connection', lambda *a, **k: Sock())
    monkeypatch.setattr(ec.time, 'monotonic', lambda: tick[0])
    c.send_raw = MagicMock(return_value=True)
    c._connect_and_run()
    sent = [x.args[0] for x in c.send_raw.call_args_list]
    assert hp.encode_keepalive() in sent
    assert sent.count(hp.encode_dump_zone_timers()) >= 4


def test_receive_exception_always_closes_socket(monkeypatch):
    c = ec.EnvisalinkClient('localhost', 'user', lambda _: None)
    sock = MagicMock()
    sock.recv.side_effect = RuntimeError('test failure')
    monkeypatch.setattr(ec.socket, 'create_connection', lambda *a, **k: sock)
    with pytest.raises(RuntimeError): c._connect_and_run()
    sock.close.assert_called_once()
    assert c._sock is None and not c.is_connected()


def test_diagnostic_ring_masks_codes_in_keypad_text():
    c = ec.EnvisalinkClient('localhost', 'user', lambda _: None)
    c._record_debug('RX', '%00,01,1008,00,00,Code 7654$')
    assert '7654' not in json.dumps(c.get_debug_log())


def test_capture_timeline_keeps_partitions_separate():
    records = [{'type': 'keypad_update', 'partition': p, 'derived_state': 'ready'} for p in (1, 2, 1)]
    timeline = cap.build_state_timeline(records)
    assert [r['partition'] for r in timeline] == [1, 2]


def test_bundle_writer_does_not_follow_existing_symlink(tmp_path):
    victim = tmp_path / 'keep'
    victim.write_text('original')
    out = tmp_path / 'link.json'
    out.symlink_to(victim)
    written = cap.write_bundle({'test': 1}, str(out))
    assert victim.read_text() == 'original'
    assert json.loads(open(written).read()) == {'test': 1}
    assert os.stat(written).st_mode & 0o777 == 0o600
    if str(tmp_path) not in written: os.unlink(written)


def test_duplicate_zone_cannot_steal_or_remove_live_route():
    p = _bare_plugin()
    p.pluginId = 'com.clives.indigoplugin.honeywell-envisalink'
    first = MagicMock(id=10, pluginId=p.pluginId, deviceTypeId='zone', pluginProps={'zone_number': '1'})
    second = MagicMock(id=11, pluginId=p.pluginId, deviceTypeId='zone', pluginProps={'zone_number': '1'})
    p.deviceStartComm(first)
    p.deviceStartComm(second)
    assert p.zone_devs[1] is first
    second.setErrorStateOnServer.assert_called_with('duplicate number')
    p.deviceStopComm(second)
    assert p.zone_devs[1] is first


def test_late_panel_gets_current_connection_without_reconnect():
    p = _bare_plugin()
    p.pluginId = 'com.clives.indigoplugin.honeywell-envisalink'
    p.client = MagicMock()
    p.client.is_connected.return_value = True
    panel = MagicMock(id=10, pluginId=p.pluginId, deviceTypeId='panel')
    p.deviceStartComm(panel)
    panel.updateStateOnServer.assert_called_with('connected', value=True)


def test_repeated_manual_status_requests_do_not_flood_panel():
    p = _bare_plugin()
    p.client = MagicMock()
    p.client.is_connected.return_value = True
    for _ in range(20): p._request_zone_refresh()
    assert p.client.send_raw.call_count == 1


def test_keypress_sequences_cannot_interleave(monkeypatch):
    import threading
    c = ec.EnvisalinkClient('localhost', 'user', lambda _: None)
    c._sock, c._connected = object(), True
    entered, release = threading.Event(), threading.Event()
    sent = []
    def send(cmd, **kwargs):
        sent.append(cmd)
        if cmd == 'a':
            entered.set()
            assert release.wait(2)
        return True
    c.send_raw = send
    monkeypatch.setattr(ec, 'KEYPRESS_GAP_S', 0)
    a = threading.Thread(target=c.send_keypresses, args=(['a', 'b'],))
    b = threading.Thread(target=c.send_keypresses, args=(['x', 'y'],))
    a.start()
    assert entered.wait(2)
    b.start()
    release.set()
    a.join(2)
    b.join(2)
    assert sent == ['a', 'b', 'x', 'y']


def test_local_tcp_connection_drives_plugin_and_sends_only_when_enabled():
    """Run real client, framing, state handlers and actions against loopback only."""
    import socket
    import threading
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(3)
    done = threading.Event()
    received, failures = [], []
    p = _bare_plugin()
    p.panel_dev = MagicMock()
    p.partition_devs = {1: MagicMock()}
    p.zone_devs = {1: MagicMock()}
    def server():
        try:
            conn, _ = listener.accept()
            with conn:
                conn.settimeout(3)
                conn.sendall(b'Login:\r\n')
                buf = b''
                while b'\r\n' not in buf: buf += conn.recv(1024)
                password, buf = buf.split(b'\r\n', 1)
                assert password == b'user'
                conn.sendall(b'OK\r\n%00,01,1008,00,00,Ready$\r\n%01,0100$\r\n')
                while len([r for r in received if r.startswith('^03,')]) < 5:
                    chunk = conn.recv(1024)
                    if not chunk: break
                    buf += chunk
                    while b'\r\n' in buf:
                        line, buf = buf.split(b'\r\n', 1)
                        received.append(line.decode())
                done.set()
        except Exception as exc:
            failures.append(exc)
            done.set()
        finally: listener.close()
    worker = threading.Thread(target=server, daemon=True)
    worker.start()
    update = threading.Event()
    p.partition_devs[1].updateStatesOnServer.side_effect = lambda *_a, **_k: update.set()
    p.client = ec.EnvisalinkClient('127.0.0.1', 'user', p._on_frame,
                                  on_login=p._on_login, on_disconnect=p._on_disconnect,
                                  logger=p.logger, port=listener.getsockname()[1])
    p.client.start()
    try:
        assert update.wait(3), 'did not receive a real TCP keypad frame'
        action = types.SimpleNamespace(props={'user_code': '1234'})
        dev = types.SimpleNamespace(pluginProps={'partition_number': '1'})
        assert p.action_arm_stay(action, dev) is False
        assert not any(r.startswith('^03,') for r in received)
        p.test_mode = False
        assert p.action_arm_stay(action, dev) is True
        assert done.wait(3)
        assert not failures
        assert [r for r in received if r.startswith('^03,')] == [f'^03,1,{n}$' for n in '12343']
        p.zone_devs[1].updateStatesOnServer.assert_called()
        assert '1234' not in json.dumps(p.client.get_debug_log())
    finally:
        p.client.stop()
        worker.join(3)
    assert not p.client.is_connected()
    assert not p.client._thread.is_alive()


def test_reconnect_always_requests_initial_zone_dump():
    p = _bare_plugin()
    p.client = MagicMock()
    p.client.is_connected.return_value = True
    p._request_zone_refresh()
    p.client.send_raw.reset_mock()
    p._on_login(hp.LoginResult.OK)
    p.client.send_raw.assert_called_once_with(hp.encode_dump_zone_timers())
