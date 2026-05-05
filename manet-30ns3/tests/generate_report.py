"""将 JSON 测试结果转换为 Markdown 报告。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime

RESULTS_DIR = Path(__file__).parent.parent / "test-results"


def _load_results() -> list[dict]:
    path = RESULTS_DIR / "wifi_test_results.json"
    if not path.exists():
        print(f"ERROR: {path} not found. Run tests first.")
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def _status_icon(status: str) -> str:
    return {"pass": "PASS", "fail": "FAIL", "skip": "SKIP"}.get(status, status.upper())


def main() -> int:
    results = _load_results()
    if not results:
        print("No test results found.")
        return 1

    lines: list[str] = []
    lines.append("# MANET WiFi 频段 / 带宽 / 距离 / Adhoc 测试报告")
    lines.append("")
    lines.append(f"**生成时间**: {datetime.now().isoformat()}")
    lines.append("")

    # Summary table
    passed = sum(1 for r in results if r.get("status") == "pass")
    failed = sum(1 for r in results if r.get("status") == "fail")
    lines.append("## 汇总")
    lines.append("")
    lines.append(f"| 指标 | 数值 |")
    lines.append(f"|------|------|")
    lines.append(f"| 总测试数 | {len(results)} |")
    lines.append(f"| 通过 | {passed} |")
    lines.append(f"| 失败 | {failed} |")
    lines.append(f"| 通过率 | {passed / len(results) * 100:.1f}% |")
    lines.append("")

    # Per-test details
    for r in results:
        name = r.get("name", "Unknown")
        status = r.get("status", "unknown")
        duration = r.get("durationSec", 0)
        metrics = r.get("metrics", {})
        logs = r.get("logs", [])
        errors = r.get("errors", [])

        icon = "OK" if status == "pass" else "FAIL" if status == "fail" else status.upper()
        lines.append(f"## {name} — {icon} ({duration}s)")
        lines.append("")

        if logs:
            lines.append("**日志**:")
            for ln in logs:
                lines.append(f"- {ln}")
            lines.append("")

        if errors:
            lines.append("**错误**:")
            for err in errors:
                lines.append(f"- `{err}`")
            lines.append("")

        # Metrics tables
        pings = metrics.get("pings")
        if pings:
            lines.append("**Ping 结果**:")
            lines.append("| 链路 | 距离 | 发送 | 接收 | 丢包率 | 平均 RTT |")
            lines.append("|------|------|------|------|--------|----------|")
            for link, data in pings.items():
                dist = data.get("distanceM", "—")
                sent = data.get("sent", 0)
                recv = data.get("received", 0)
                loss = data.get("lossPercent", 0)
                rtt = data.get("rttAvgMs", 0)
                lines.append(f"| {link} | {dist} | {sent} | {recv} | {loss}% | {rtt}ms |")
            lines.append("")

        iperf = metrics.get("iperf")
        if iperf:
            lines.append("**iperf3 吞吐量**:")
            lines.append("| 链路 | 距离 | 吞吐量 (Mbps) | 重传 |")
            lines.append("|------|------|---------------|------|")
            for link, data in iperf.items():
                dist = data.get("distanceM", "—")
                mbps = data.get("mbps", 0)
                retr = data.get("retransmits", "—")
                lines.append(f"| {link} | {dist} | {mbps} | {retr} |")
            lines.append("")

        traceroute_hops = metrics.get("tracerouteHops")
        if traceroute_hops is not None:
            lines.append(f"**Traceroute 跳数**: {traceroute_hops}")
            lines.append("")

        ping_summary = metrics.get("ping")
        if ping_summary and not pings:
            recv = ping_summary.get("received", 0)
            sent = ping_summary.get("sent", 0)
            loss = ping_summary.get("lossPercent", 0)
            rtt = ping_summary.get("rttAvgMs", 0)
            lines.append(f"**Ping**: {recv}/{sent} recv, loss={loss}%, avg RTT={rtt}ms")
            lines.append("")

        iperf_mbps = metrics.get("iperfMbps")
        if iperf_mbps is not None:
            lines.append(f"**iperf3 吞吐量**: {iperf_mbps} Mbps")
            lines.append("")

        arp = metrics.get("arp")
        if arp:
            lines.append("**ARP 可达邻居数**:")
            for node, data in arp.items():
                lines.append(f"- {node}: {data.get('reachableNeighbors', 0)}")
            lines.append("")

    output_path = RESULTS_DIR / "wifi_test_report.md"
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report written to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
