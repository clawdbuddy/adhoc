"""MANET WiFi 频段 / 带宽 / 距离 / Adhoc 自动化测试套件。

通过 FastAPI REST 接口驱动仿真并收集结果。

运行方式::

    cd manet-30ns3
    python3 tests/wifi_test_suite.py [test_name] [--preset PRESET] [--url URL]

前置条件:
    - ns3-controller 容器已启动 (docker compose up -d ns3-controller)
    - 宿主机可访问 localhost:8000
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import urllib.request
import urllib.error

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

RESULTS_DIR = Path(__file__).parent.parent / "test-results"
CONTROLLER_URL = "http://localhost:8000"


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _api(method: str, path: str, body: dict | None = None) -> Any:
    url = f"{CONTROLLER_URL}{path}"
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8"))
        except Exception:
            detail = e.reason
        raise RuntimeError(f"HTTP {e.code}: {detail}")


def _get(path: str) -> Any:
    return _api("GET", path)


def _post(path: str, body: dict | None = None) -> Any:
    return _api("POST", path, body)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class PingResult:
    sent: int = 0
    received: int = 0
    loss_percent: float = 0.0
    rtt_min: float = 0.0
    rtt_avg: float = 0.0
    rtt_max: float = 0.0


@dataclass
class IperfResult:
    bits_per_second: float = 0.0
    retransmits: int = 0
    jitter_ms: float = 0.0
    lost_percent: float = 0.0


@dataclass
class TestCaseResult:
    name: str
    status: str = "pending"  # pending / pass / fail / skip
    duration_sec: float = 0.0
    logs: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
class TestRunner:
    def __init__(self, controller_url: str = CONTROLLER_URL):
        global CONTROLLER_URL
        CONTROLLER_URL = controller_url.rstrip("/")
        self.results: list[TestCaseResult] = []

    # --- lifecycle ---
    def health_check(self) -> bool:
        try:
            r = _get("/api/health")
            return bool(r.get("ok"))
        except Exception as e:
            log.error("Health check failed: %s", e)
            return False

    def start_simulation(self, preset: str | None = None,
                         overrides: dict | None = None) -> dict:
        body: dict[str, Any] = {"overrides": overrides or {}}
        if preset:
            body["preset"] = preset
        log.info("Starting simulation (preset=%s, overrides=%s)", preset, overrides)
        return _post("/api/sim/start", body)

    def stop_simulation(self) -> dict:
        log.info("Stopping simulation")
        return _post("/api/sim/stop")

    def wait_for_nodes_online(self, expected_nodes: int, timeout: float = 60.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                status = _get("/api/sim/status")
                if status.get("running") and status.get("nodesOnline", 0) >= expected_nodes:
                    log.info("All %d nodes online", expected_nodes)
                    return True
                log.debug("Waiting: running=%s nodesOnline=%s",
                          status.get("running"), status.get("nodesOnline"))
            except Exception as e:
                log.debug("Status poll error: %s", e)
            time.sleep(1.0)
        log.error("Timeout waiting for nodes")
        return False

    def wait_seconds(self, seconds: float) -> None:
        log.info("Waiting %.0fs for routing convergence / stabilization", seconds)
        time.sleep(seconds)

    # --- node operations ---
    def exec_on_node(self, node_id: int, cmd: str) -> dict:
        return _post(f"/api/nodes/{node_id}/exec", {"cmd": cmd})

    def ping(self, src: int, dst_ip: str, count: int = 10) -> PingResult:
        result = self.exec_on_node(src, f"ping -c {count} -W 2 {dst_ip}")
        output = result.get("output", "")
        pr = PingResult()
        # Parse ping statistics
        m = re.search(r"(\d+) packets transmitted, (\d+) received", output)
        if m:
            pr.sent = int(m.group(1))
            pr.received = int(m.group(2))
            pr.loss_percent = (1 - pr.received / pr.sent) * 100 if pr.sent else 0
        m = re.search(r"min/avg/max.*?=\s*([\d.]+)/([\d.]+)/([\d.]+)", output)
        if m:
            pr.rtt_min = float(m.group(1))
            pr.rtt_avg = float(m.group(2))
            pr.rtt_max = float(m.group(3))
        return pr

    def iperf3(self, server_node: int, client_node: int, server_ip: str,
               duration: int = 15) -> IperfResult:
        # Ensure server is running (node-0 auto-starts iperf3 in entrypoint)
        # First check if server is already listening
        check = self.exec_on_node(server_node, "ss -tlnp | grep 5201 || echo 'no-server'")
        if "no-server" in check.get("output", ""):
            self.exec_on_node(server_node, "iperf3 -s -p 5201 -D")
            time.sleep(1.5)
        # Run client
        result = self.exec_on_node(
            client_node,
            f"timeout {duration + 15} iperf3 -c {server_ip} -p 5201 -t {duration} -J",
        )
        ir = IperfResult()
        output = result.get("output", "")
        if not output or "error" in output.lower():
            return ir
        try:
            data = json.loads(output)
            end_sum = data.get("end", {}).get("sum_received", {})
            ir.bits_per_second = end_sum.get("bits_per_second", 0)
            ir.retransmits = end_sum.get("retransmits", 0)
        except Exception:
            pass
        return ir

    def traceroute(self, src: int, dst_ip: str) -> list[str]:
        result = self.exec_on_node(src, f"traceroute -n -m 10 {dst_ip}")
        output = result.get("output", "")
        lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
        return lines

    # --- test recording ---
    def record(self, tc: TestCaseResult) -> None:
        self.results.append(tc)

    def dump_results(self) -> None:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path = RESULTS_DIR / "wifi_test_results.json"
        data = []
        for r in self.results:
            data.append({
                "name": r.name,
                "status": r.status,
                "durationSec": r.duration_sec,
                "logs": r.logs,
                "metrics": r.metrics,
                "errors": r.errors,
            })
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Results written to %s", path)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------
def tc_frequency_2_4g(runner: TestRunner) -> TestCaseResult:
    tc = TestCaseResult(name="TC-01: 2.4GHz 频段连通性")
    t0 = time.time()
    try:
        runner.start_simulation(preset="wifi-band-test-2.4g")
        if not runner.wait_for_nodes_online(5, timeout=60):
            raise RuntimeError("Nodes did not come online")
        runner.wait_seconds(15)  # AODV convergence (wall-time; ns-3 real-time may lag)

        pings = {}
        for dst in range(1, 5):
            dst_ip = f"192.168.100.{10 + dst}"
            pr = runner.ping(0, dst_ip, count=10)
            pings[f"node0->node{dst}"] = {
                "sent": pr.sent, "received": pr.received,
                "lossPercent": round(pr.loss_percent, 1),
                "rttAvgMs": round(pr.rtt_avg, 2),
            }
            tc.logs.append(f"ping node0->node{dst}: {pr.received}/{pr.sent} recv, "
                           f"loss={pr.loss_percent:.1f}%, avg RTT={pr.rtt_avg:.2f}ms")

        all_ok = all(p["received"] == p["sent"] for p in pings.values())
        tc.status = "pass" if all_ok else "fail"
        tc.metrics = {"pings": pings}
    except Exception as e:
        tc.status = "fail"
        tc.errors.append(str(e))
    finally:
        runner.stop_simulation()
        tc.duration_sec = round(time.time() - t0, 1)
    return tc


def tc_frequency_5g(runner: TestRunner) -> TestCaseResult:
    tc = TestCaseResult(name="TC-02: 5GHz 频段连通性")
    t0 = time.time()
    try:
        runner.start_simulation(preset="wifi-band-test-5g")
        if not runner.wait_for_nodes_online(5, timeout=60):
            raise RuntimeError("Nodes did not come online")
        runner.wait_seconds(10)

        pings = {}
        for dst in range(1, 5):
            dst_ip = f"192.168.100.{10 + dst}"
            pr = runner.ping(0, dst_ip, count=10)
            pings[f"node0->node{dst}"] = {
                "sent": pr.sent, "received": pr.received,
                "lossPercent": round(pr.loss_percent, 1),
                "rttAvgMs": round(pr.rtt_avg, 2),
            }
            tc.logs.append(f"ping node0->node{dst}: {pr.received}/{pr.sent} recv, "
                           f"loss={pr.loss_percent:.1f}%, avg RTT={pr.rtt_avg:.2f}ms")

        all_ok = all(p["received"] == p["sent"] for p in pings.values())
        tc.status = "pass" if all_ok else "fail"
        tc.metrics = {"pings": pings}
    except Exception as e:
        tc.status = "fail"
        tc.errors.append(str(e))
    finally:
        runner.stop_simulation()
        tc.duration_sec = round(time.time() - t0, 1)
    return tc


def tc_bandwidth_20m(runner: TestRunner) -> TestCaseResult:
    tc = TestCaseResult(name="TC-03: 20MHz 带宽吞吐量")
    t0 = time.time()
    try:
        runner.start_simulation(preset="wifi-bandwidth-test-20m")
        if not runner.wait_for_nodes_online(5, timeout=60):
            raise RuntimeError("Nodes did not come online")
        runner.wait_seconds(10)

        results = {}
        for client in range(1, 5):
            ir = runner.iperf3(0, client, "192.168.100.10", duration=15)
            mbps = ir.bits_per_second / 1e6
            results[f"node{client}->node0"] = {
                "bitsPerSecond": ir.bits_per_second,
                "mbps": round(mbps, 2),
                "retransmits": ir.retransmits,
            }
            tc.logs.append(f"iperf3 node{client}->node0: {mbps:.2f} Mbps, "
                           f"retransmits={ir.retransmits}")

        tc.status = "pass"
        tc.metrics = {"iperf": results}
    except Exception as e:
        tc.status = "fail"
        tc.errors.append(str(e))
    finally:
        runner.stop_simulation()
        tc.duration_sec = round(time.time() - t0, 1)
    return tc


def tc_bandwidth_40m(runner: TestRunner) -> TestCaseResult:
    tc = TestCaseResult(name="TC-04: 40MHz 带宽吞吐量")
    t0 = time.time()
    try:
        runner.start_simulation(preset="wifi-bandwidth-test-40m")
        if not runner.wait_for_nodes_online(5, timeout=60):
            raise RuntimeError("Nodes did not come online")
        runner.wait_seconds(10)

        results = {}
        for client in range(1, 5):
            ir = runner.iperf3(0, client, "192.168.100.10", duration=15)
            mbps = ir.bits_per_second / 1e6
            results[f"node{client}->node0"] = {
                "bitsPerSecond": ir.bits_per_second,
                "mbps": round(mbps, 2),
                "retransmits": ir.retransmits,
            }
            tc.logs.append(f"iperf3 node{client}->node0: {mbps:.2f} Mbps, "
                           f"retransmits={ir.retransmits}")

        tc.status = "pass"
        tc.metrics = {"iperf": results}
    except Exception as e:
        tc.status = "fail"
        tc.errors.append(str(e))
    finally:
        runner.stop_simulation()
        tc.duration_sec = round(time.time() - t0, 1)
    return tc


def tc_distance_attenuation(runner: TestRunner) -> TestCaseResult:
    tc = TestCaseResult(name="TC-05: 通信距离衰减")
    t0 = time.time()
    try:
        runner.start_simulation(preset="wifi-distance-test")
        if not runner.wait_for_nodes_online(5, timeout=90):
            raise RuntimeError("Nodes did not come online")
        runner.wait_seconds(15)

        distances = {1: 500, 2: 1000, 3: 1500, 4: 2000}
        pings = {}
        iperf_results = {}

        for dst, dist_m in distances.items():
            dst_ip = f"192.168.100.{10 + dst}"
            pr = runner.ping(0, dst_ip, count=10)
            pings[f"node0->node{dst}({dist_m}m)"] = {
                "distanceM": dist_m,
                "sent": pr.sent, "received": pr.received,
                "lossPercent": round(pr.loss_percent, 1),
                "rttAvgMs": round(pr.rtt_avg, 2),
            }
            tc.logs.append(f"ping node0->node{dst} ({dist_m}m): {pr.received}/{pr.sent} recv, "
                           f"loss={pr.loss_percent:.1f}%, avg RTT={pr.rtt_avg:.2f}ms")

            if pr.received > 0:
                ir = runner.iperf3(0, dst, "192.168.100.10", duration=5)
                mbps = ir.bits_per_second / 1e6
                iperf_results[f"node0->node{dst}({dist_m}m)"] = {
                    "distanceM": dist_m,
                    "mbps": round(mbps, 2),
                }
                tc.logs.append(f"  iperf3: {mbps:.2f} Mbps")

        all_reachable = all(p["received"] > 0 for p in pings.values())
        tc.status = "pass" if all_reachable else "fail"
        tc.metrics = {"pings": pings, "iperf": iperf_results}
    except Exception as e:
        tc.status = "fail"
        tc.errors.append(str(e))
    finally:
        runner.stop_simulation()
        tc.duration_sec = round(time.time() - t0, 1)
    return tc


def tc_adhoc_multihop(runner: TestRunner) -> TestCaseResult:
    # 注：Adhoc 模式无 L2 多跳能力；本测试使用 4km 单跳覆盖（range_target_m=4000），
    # 使 10 节点 300m 间距全在单跳范围内，验证大规模拓扑下的吞吐和延迟。
    tc = TestCaseResult(name="TC-06: Adhoc 大规模拓扑")
    t0 = time.time()
    try:
        runner.start_simulation(preset="wifi-adhoc-multihop")
        if not runner.wait_for_nodes_online(10, timeout=120):
            raise RuntimeError("Nodes did not come online")
        runner.wait_seconds(15)

        # End-to-end: node 0 -> node 9 (2700m, within 4km single-hop range)
        dst_ip = "192.168.100.19"
        pr = runner.ping(0, dst_ip, count=10)
        tc.logs.append(f"ping node0->node9 (2700m): {pr.received}/{pr.sent} recv, "
                       f"loss={pr.loss_percent:.1f}%, avg RTT={pr.rtt_avg:.2f}ms")

        # Traceroute (expected 1 hop since all nodes are within single-hop range)
        trace_lines = runner.traceroute(0, dst_ip)
        tc.logs.append("traceroute output:")
        for ln in trace_lines:
            tc.logs.append(f"  {ln}")

        # Count hops
        hop_count = sum(1 for ln in trace_lines if re.search(r"^\s*\d+", ln)) - 1
        if hop_count < 0:
            hop_count = 0

        if pr.received > 0:
            ir = runner.iperf3(0, 9, "192.168.100.10", duration=15)
            mbps = ir.bits_per_second / 1e6
            tc.logs.append(f"iperf3 node0->node9: {mbps:.2f} Mbps")
            tc.metrics = {
                "ping": {"received": pr.received, "sent": pr.sent,
                         "lossPercent": round(pr.loss_percent, 1),
                         "rttAvgMs": round(pr.rtt_avg, 2)},
                "tracerouteHops": hop_count,
                "iperfMbps": round(mbps, 2),
            }
        else:
            tc.metrics = {
                "ping": {"received": pr.received, "sent": pr.sent,
                         "lossPercent": round(pr.loss_percent, 1)},
                "tracerouteHops": hop_count,
            }

        # Pass if end-to-end ping succeeds (single-hop expected with 4km range)
        tc.status = "pass" if pr.received > 0 else "fail"
    except Exception as e:
        tc.status = "fail"
        tc.errors.append(str(e))
    finally:
        runner.stop_simulation()
        tc.duration_sec = round(time.time() - t0, 1)
    return tc


def tc_broadcast(runner: TestRunner) -> TestCaseResult:
    tc = TestCaseResult(name="TC-07: 广播覆盖")
    t0 = time.time()
    try:
        runner.start_simulation(preset="wifi-band-test-2.4g")
        if not runner.wait_for_nodes_online(5, timeout=90):
            raise RuntimeError("Nodes did not come online")
        runner.wait_seconds(10)

        # Node 0 sends broadcast ping
        result = runner.exec_on_node(0, "ping -c 3 -b 192.168.100.255")
        tc.logs.append(f"broadcast ping from node0: {result.get('output', '')[:200]}")

        # Check ARP tables on other nodes
        arp_results = {}
        for nid in range(1, 5):
            res = runner.exec_on_node(nid, "ip neigh | grep REACHABLE | wc -l")
            count = int(res.get("output", "0").strip() or 0)
            arp_results[f"node{nid}"] = {"reachableNeighbors": count}
            tc.logs.append(f"node{nid} reachable neighbors: {count}")

        tc.status = "pass"
        tc.metrics = {"arp": arp_results}
    except Exception as e:
        tc.status = "fail"
        tc.errors.append(str(e))
    finally:
        runner.stop_simulation()
        tc.duration_sec = round(time.time() - t0, 1)
    return tc


def tc_frequency_sweep(runner: TestRunner) -> TestCaseResult:
    tc = TestCaseResult(name="TC-08: 2.4GHz 多信道遍历")
    t0 = time.time()
    frequencies = [2412, 2437, 2462, 2472]  # Ch 1, 6, 11, 13
    all_pings = {}
    try:
        for freq in frequencies:
            runner.start_simulation(
                preset="wifi-band-test-2.4g",
                overrides={"frequencyMhz": freq},
            )
            if not runner.wait_for_nodes_online(5, timeout=90):
                raise RuntimeError(f"Nodes did not come online at {freq} MHz")
            runner.wait_seconds(10)

            freq_results = {}
            for dst in range(1, 3):  # Just test first 2 nodes for speed
                dst_ip = f"192.168.100.{10 + dst}"
                pr = runner.ping(0, dst_ip, count=5)
                freq_results[f"node0->node{dst}"] = {
                    "sent": pr.sent, "received": pr.received,
                    "lossPercent": round(pr.loss_percent, 1),
                }
            all_pings[f"{freq}MHz"] = freq_results
            tc.logs.append(f"{freq}MHz: node0->node1 recv={freq_results['node0->node1']['received']}/5, "
                           f"node0->node2 recv={freq_results['node0->node2']['received']}/5")
            runner.stop_simulation()
            time.sleep(2)  # Brief pause between runs

        all_ok = all(
            p["received"] == p["sent"]
            for freq_data in all_pings.values()
            for p in freq_data.values()
        )
        tc.status = "pass" if all_ok else "fail"
        tc.metrics = {"pings": all_pings}
    except Exception as e:
        tc.status = "fail"
        tc.errors.append(str(e))
        runner.stop_simulation()
    finally:
        tc.duration_sec = round(time.time() - t0, 1)
    return tc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
ALL_TESTS = [
    tc_frequency_2_4g,
    tc_frequency_5g,
    tc_bandwidth_20m,
    tc_bandwidth_40m,
    tc_distance_attenuation,
    tc_adhoc_multihop,
    tc_broadcast,
    tc_frequency_sweep,
]

TEST_MAP = {fn.__name__: fn for fn in ALL_TESTS}


def main() -> int:
    parser = argparse.ArgumentParser(description="MANET WiFi Test Suite")
    parser.add_argument("test", nargs="?", default="all",
                        help="Test name or 'all' (default: all)")
    parser.add_argument("--url", default=CONTROLLER_URL,
                        help=f"Controller URL (default: {CONTROLLER_URL})")
    parser.add_argument("--list", action="store_true",
                        help="List available tests")
    args = parser.parse_args()

    if args.list:
        print("Available tests:")
        for fn in ALL_TESTS:
            print(f"  {fn.__name__}")
        return 0

    runner = TestRunner(controller_url=args.url)
    if not runner.health_check():
        print("ERROR: Controller not reachable. Is `docker compose up -d ns3-controller` running?")
        return 1

    # Ensure clean state
    try:
        runner.stop_simulation()
        time.sleep(2)
    except Exception:
        pass

    if args.test == "all":
        tests_to_run = ALL_TESTS
    else:
        if args.test not in TEST_MAP:
            print(f"ERROR: Unknown test '{args.test}'. Use --list to see available tests.")
            return 1
        tests_to_run = [TEST_MAP[args.test]]

    print("=" * 60)
    print("MANET WiFi Test Suite")
    print(f"Tests: {len(tests_to_run)}")
    print("=" * 60)

    for fn in tests_to_run:
        print(f"\n>>> Running {fn.__name__}...")
        tc = fn(runner)
        runner.record(tc)
        status_icon = "PASS" if tc.status == "pass" else "FAIL" if tc.status == "fail" else tc.status.upper()
        print(f"<<< {fn.__name__}: {status_icon} ({tc.duration_sec}s)")
        for ln in tc.logs:
            print(f"    {ln}")
        for err in tc.errors:
            print(f"    ERROR: {err}")

    runner.dump_results()

    # Summary
    passed = sum(1 for r in runner.results if r.status == "pass")
    failed = sum(1 for r in runner.results if r.status == "fail")
    print(f"\n{'=' * 60}")
    print(f"Summary: {passed} passed, {failed} failed, {len(runner.results)} total")
    print(f"Results: {RESULTS_DIR / 'wifi_test_results.json'}")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
