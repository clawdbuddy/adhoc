"""无线配置、线程交接和 TAP 端到端统计回归。"""
from __future__ import annotations

import socket
import struct
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from controller.orchestrator.config import SimConfig
from controller.orchestrator.param_store import ParamStore
from controller.orchestrator.sim_runner import SimRunner
from controller.orchestrator.tap_telemetry import TapTelemetry


def packet(ident: int = 1) -> bytes:
    udp = struct.pack('!HHHH', 1234, 5000, 12, 0) + b'test'
    ip = struct.pack('!BBHHHBBH4s4s', 0x45, 0, 20 + len(udp), ident, 0, 64, 17, 0,
                     socket.inet_aton('192.168.100.10'), socket.inet_aton('192.168.100.11'))
    return b'\x00' * 12 + b'\x08\x00' + ip + udp


def test_tap_delivery_delay_and_duplicates():
    capture = TapTelemetry('tap-', 2)
    frame = packet()
    capture.observe(0, True, frame, 100.0)
    capture.observe(1, False, frame, 100.025)
    capture.observe(1, False, frame, 100.026)
    result = capture.snapshot()[0]
    assert (result['tx_packets'], result['rx_packets'], result['lost_packets']) == (1, 1, 0)
    assert result['avg_delay'] == pytest.approx(25)
    assert result['throughput'] > 0


def test_tap_loss_excludes_inflight_and_retransmission_matches_fifo():
    capture = TapTelemetry('tap-', 2)
    capture.observe(0, True, packet(), 100)
    capture.observe(0, True, packet(), 101)
    capture.observe(1, False, packet(), 102)
    capture.expire(105)
    assert capture.snapshot()[0]['lost_packets'] == 0
    capture.expire(111)
    assert capture.snapshot()[0]['lost_packets'] == 1


def test_tap_ignores_intermediate_nodes_and_non_ipv4():
    capture = TapTelemetry('tap-', 3)
    capture.observe(2, True, packet(), 100)
    capture.observe(0, True, b'garbage', 100)
    assert capture.snapshot() == []


def test_supported_bandwidth_and_mode_validation():
    assert SimConfig(mac_mode='adhoc').mac_mode == 'adhoc'
    assert '40, BAND_2_4GHZ' in SimRunner._channel_settings(SimConfig(channel_width_mhz=40))
    assert 'BAND_5GHZ' in SimRunner._channel_settings(SimConfig(standard='80211a', data_rate='OfdmRate6Mbps'))
    with pytest.raises(ValueError):
        SimConfig(channel_width_mhz=35)
    with pytest.raises(ValueError):
        SimConfig(standard='80211a', channel_width_mhz=40)


def test_config_save_is_atomic_and_does_not_apply_dynamic_setters():
    session = SimpleNamespace(config=SimConfig(), running=True, sim=SimpleNamespace())
    store = ParamStore(session)
    updated = SimConfig(channel_width_mhz=40)
    with patch('controller.orchestrator.param_store.save_config_to_file') as save:
        assert store.save_config(updated)['ok']
        save.assert_called_once_with(updated)
    assert session.config.channel_width_mhz == 40
    with patch('controller.orchestrator.param_store.save_config_to_file', side_effect=OSError('disk full')):
        assert not store.save_config(SimConfig())['ok']
    assert session.config.channel_width_mhz == 40


def test_command_executes_only_when_simulation_thread_drains_queue():
    runner = SimRunner(SimConfig())
    runner._running = True
    runner._thread = threading.current_thread()
    called = []
    result = []
    producer = threading.Thread(target=lambda: result.append(runner._inject_command(lambda: called.append(threading.get_ident()))))
    producer.start()
    deadline = time.monotonic() + 1
    while runner._command_queue.empty() and time.monotonic() < deadline:
        time.sleep(.001)
    assert called == []
    runner._command_queue.get_nowait()()
    producer.join(timeout=1)
    assert called == [threading.get_ident()]
    assert result == [{'applied': True}]


def test_dynamic_rejects_unsupported_frequency_and_nonfinite_values():
    runner = SimRunner(SimConfig())
    assert not runner.set_tx_power(0, float('nan'))['applied']
    assert not runner.set_node_position(0, float('inf'), 0)['applied']
    assert not runner.set_path_loss_exponent(-1)['applied']
    assert not runner.set_range_target(-1)['applied']
    assert not runner.set_frequency(2400)['applied']  # 不合法的 WiFi 中心频点
    assert not runner.set_channel_width(35)['applied']


def test_channel_centers_are_bandwidth_specific():
    cfg = SimConfig(standard='80211n-5GHz', frequency_mhz=5190, channel_width_mhz=40)
    assert SimRunner._channel_settings(cfg) == '{38, 40, BAND_5GHZ, 0}'
    cfg = SimConfig(frequency_mhz=2437, channel_width_mhz=40)
    assert SimRunner._channel_settings(cfg) == '{6, 40, BAND_2_4GHZ, 0}'


def test_worker_thread_broadcast_wakes_async_subscriber():
    import asyncio
    from controller.orchestrator.param_store import ParamChangeEvent

    async def verify():
        store = ParamStore(SimpleNamespace(config=SimConfig()))
        q = store.subscribe()
        await asyncio.to_thread(store._broadcast, ParamChangeEvent('nNodes', 8, 'static', 'test'))
        event = await asyncio.wait_for(q.get(), timeout=1)
        assert event.value == 8
        store.unsubscribe(q)
    asyncio.run(verify())
