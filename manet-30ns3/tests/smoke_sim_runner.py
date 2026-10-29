"""真实 ns-3 冒烟：内部流量、队列调参、带宽切换与自然停止。

在主项目目录执行：PYTHONPATH=. python3 tests/smoke_sim_runner.py
不需要 Docker，不操作宿主网桥或 TAP；需要可用的 cppyy/ns-3 安装。
"""
from __future__ import annotations

import time
from controller.orchestrator.config import SimConfig
from controller.orchestrator.sim_runner import SimRunner
runner = SimRunner(SimConfig(n_nodes=2, traffic_mode='onoff', mobility_model='grid', grid_delta_x=20, routing_protocol='none', simulation_time=6, pcap=False, flow_monitor=True))
runner.start()
assert runner.running
assert runner.set_tx_power(0, 20)['applied']
assert runner.set_channel_width(40)['applied']
assert runner.set_node_position(1, 20, 10)['applied']
deadline = time.monotonic() + 20
while runner.running and time.monotonic() < deadline:
    time.sleep(.2)
print('env', runner.snapshot_env(), flush=True)
print('flows', runner.snapshot_flows(), flush=True)
assert not runner.running, 'simulationTime failed to stop the simulation'
assert any(f.source and f.destination and f.rx_packets > 0 for f in runner.snapshot_flows()), 'no received flow statistics'
runner.stop()
print('NS3_RUNNER_SMOKE_OK', flush=True)
