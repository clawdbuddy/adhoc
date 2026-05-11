"""NS-3.47 + cppyy 配置组合自动化扫描脚本（子进程隔离版）。

遍历 PHY / MAC / WiFi 标准 / QoS / TapBridge 模式 / 传播模型 / 节点数 等维度，
找出不触发 Txop segfault 的可行配置组合。

运行方式（在 controller 容器内）：
    docker exec controller python3 /app/controller/orchestrator/sim_runner_test_matrix.py
"""
import csv
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RESULTS_CSV = "/results/test_matrix_results.csv"
TIMEOUT_SEC = 15

# 测试变量矩阵
PHYS = ["yans", "spectrum"]
MAC_MODES = ["adhoc", "mesh"]
STANDARDS = ["80211n-2.4GHz", "80211n-5GHz", "80211ac", "80211ax-2.4GHz", "80211ax-5GHz"]
QOS_VALUES = [True, False]
TAP_MODES = ["UseLocal", "UseBridge"]
PROPAGATIONS = ["LogDistance", "Friis", "Range"]
N_NODES_LIST = [2, 5]

# 子进程测试脚本模板（单测一个配置）
_CHILD_SCRIPT = '''
import os
import struct
import socket
import sys
import time

sys.path.insert(0, "/app")
from controller.orchestrator.sim_runner import _CppyyNsWrapper

PHY = "{phy}"
MAC_MODE = "{mac_mode}"
STANDARD = "{standard}"
QOS = {qos}
TAP_MODE = "{tap_mode}"
PROPAGATION = "{propagation}"
N_NODES = {n_nodes}
RESULT_FILE = "{result_file}"


def _import_ns():
    from ns import ns
    return _CppyyNsWrapper(ns)


def standard_enum(ns, label):
    mapping = {{
        "80211n-2.4GHz": ns.WIFI_STANDARD_80211n,
        "80211n-5GHz": ns.WIFI_STANDARD_80211n,
        "80211ac": ns.WIFI_STANDARD_80211ac,
        "80211ax-2.4GHz": ns.WIFI_STANDARD_80211ax,
        "80211ax-5GHz": ns.WIFI_STANDARD_80211ax,
    }}
    return mapping.get(label, ns.WIFI_STANDARD_80211n)


def setup_tap_devices(n):
    for i in range(n):
        name = f"mesh-tap-test{{i}}"
        os.system(f"ip tuntap add mode tap {{name}} 2>/dev/null")
        os.system(f"ip link set {{name}} up 2>/dev/null")


def cleanup_tap_devices(n):
    for i in range(n):
        os.system(f"ip link del mesh-tap-test{{i}} 2>/dev/null")


def send_frame_via_raw(ifname):
    try:
        s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0806))
        s.bind((ifname, 0))
        frame = bytes([
            0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF,
            0x02, 0x00, 0x00, 0x00, 0x00, 0x01,
            0x08, 0x06,
            0x00, 0x01, 0x08, 0x00, 0x06, 0x04, 0x00, 0x01,
            0x02, 0x00, 0x00, 0x00, 0x00, 0x01,
            0x0A, 0x01, 0x01, 0x01,
            0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
            0x0A, 0x01, 0x01, 0x02,
        ])
        s.send(frame)
        s.close()
        return True
    except Exception:
        return False


def run_test():
    ns = _import_ns()
    start = time.time()
    # 先清理可能残留的 tap 设备
    cleanup_tap_devices(N_NODES)
    try:
        # 使用 RealtimeSimulatorImpl（与 sim_runner.py 一致）
        ns.GlobalValue.Bind(
            "SimulatorImplementationType",
            ns.StringValue("ns3::RealtimeSimulatorImpl"),
        )
        ns.GlobalValue.Bind("ChecksumEnabled", ns.BooleanValue(True))

        nodes = ns.NodeContainer()
        nodes.Create(N_NODES)

        if PHY == "spectrum":
            phy_helper = ns.SpectrumWifiPhyHelper()
            ch_helper = ns.MultiModelSpectrumChannel()
            if PROPAGATION == "LogDistance":
                loss = ns.propagation.CreateObject["ns3::LogDistancePropagationLossModel"]()
            elif PROPAGATION == "Friis":
                loss = ns.propagation.CreateObject["ns3::FriisPropagationLossModel"]()
            else:
                loss = ns.propagation.CreateObject["ns3::RangePropagationLossModel"]()
                loss.SetAttribute("MaxRange", ns.DoubleValue(1000.0))
            ch_helper.AddPropagationLossModel(loss)
            delay = ns.propagation.CreateObject["ns3::ConstantSpeedPropagationDelayModel"]()
            ch_helper.SetPropagationDelayModel(delay)
            phy_helper.SetChannel(ch_helper)
        else:
            phy_helper = ns.YansWifiPhyHelper()
            ch_helper = ns.YansWifiChannelHelper()
            if PROPAGATION == "LogDistance":
                ch_helper.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel")
                ch_helper.AddPropagationLoss("ns3::LogDistancePropagationLossModel", "Exponent", ns.DoubleValue(3.0))
            elif PROPAGATION == "Friis":
                ch_helper.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel")
                ch_helper.AddPropagationLoss("ns3::FriisPropagationLossModel")
            else:
                ch_helper.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel")
                ch_helper.AddPropagationLoss("ns3::RangePropagationLossModel", "MaxRange", ns.DoubleValue(1000.0))
            phy_helper.SetChannel(ch_helper.Create())

        wifi = ns.WifiHelper()
        wifi.SetStandard(standard_enum(ns, STANDARD))
        wifi.SetRemoteStationManager(
            "ns3::ConstantRateWifiManager",
            "DataMode", ns.StringValue("ErpOfdmRate54Mbps"),
            "ControlMode", ns.StringValue("ErpOfdmRate54Mbps"),
        )

        if MAC_MODE == "mesh":
            mesh_helper = ns.MeshHelper.Default()
            mesh_helper.SetStackInstaller("ns3::Dot11sStack")
            mesh_helper.SetMacType("RandomStart", ns.TimeValue(ns.Seconds(0.1)))
            mesh_helper.SetNumberOfInterfaces(1)
            devices = mesh_helper.Install(phy_helper, nodes)
        else:
            mac = ns.WifiMacHelper()
            if QOS:
                mac.SetType("ns3::AdhocWifiMac", "QosSupported", ns.BooleanValue(True))
            else:
                mac.SetType("ns3::AdhocWifiMac", "QosSupported", ns.BooleanValue(False))
            devices = wifi.Install(phy_helper, mac, nodes)

        mob = ns.MobilityHelper()
        mob.SetPositionAllocator("ns3::GridPositionAllocator")
        mob.SetMobilityModel("ns3::ConstantPositionMobilityModel")
        mob.Install(nodes)

        stack = ns.InternetStackHelper()
        stack.Install(nodes)

        ipv4 = ns.Ipv4AddressHelper()
        ipv4.SetBase(ns.Ipv4Address("10.1.1.0"), ns.Ipv4Mask("255.255.255.0"))
        ipv4.Assign(devices)

        setup_tap_devices(N_NODES)
        tb = ns.TapBridgeHelper()
        tb.SetAttribute("Mode", ns.StringValue(TAP_MODE))
        for i in range(N_NODES):
            tb.SetAttribute("DeviceName", ns.StringValue(f"mesh-tap-test{{i}}"))
            tb.Install(nodes.Get(i), devices.Get(i))

        if N_NODES > 0:
            send_frame_via_raw("mesh-tap-test0")

        ns.Simulator.Stop(ns.Seconds(2.0))
        ns.Simulator.Run()

        wall_time = time.time() - start
        return "PASS", f"Run completed in {{wall_time:.2f}}s", wall_time
    except Exception as e:
        wall_time = time.time() - start
        exc_str = str(e)
        if "segmentation" in exc_str.lower() or "segfault" in exc_str.lower():
            return "SEGFAULT", exc_str, wall_time
        return "OTHER", exc_str, wall_time
    finally:
        try:
            ns.Simulator.Destroy()
        except Exception:
            pass
        cleanup_tap_devices(N_NODES)


result, detail, wall_time = run_test()
with open(RESULT_FILE, "w") as f:
    f.write(f"{{result}}\\t{{detail}}\\t{{wall_time}}\\n")
'''


def run_single_test_isolated(phy, mac_mode, standard, qos, tap_mode, propagation, n_nodes):
    """在子进程中运行单组配置测试，返回 (result, detail, wall_time)。"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        result_file = f.name + ".result"
        f.write(
            _CHILD_SCRIPT.format(
                phy=phy,
                mac_mode=mac_mode,
                standard=standard,
                qos=qos,
                tap_mode=tap_mode,
                propagation=propagation,
                n_nodes=n_nodes,
                result_file=result_file,
            )
        )
        child_script = f.name

    start = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, child_script],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SEC,
        )
        wall_time = time.time() - start

        if proc.returncode != 0:
            # 子进程非正常退出（segfault / abort 等）
            stderr = proc.stderr or ""
            if "segmentation" in stderr.lower() or "segfault" in stderr.lower() or proc.returncode == -11:
                return "SEGFAULT", f"segfault (rc={proc.returncode})", wall_time
            return "OTHER", f"rc={proc.returncode} stderr={stderr[:200]}", wall_time

        if os.path.exists(result_file):
            with open(result_file, "r") as rf:
                line = rf.read().strip()
            parts = line.split("\t")
            if len(parts) == 3:
                return parts[0], parts[1], float(parts[2])

        return "OTHER", "no result file from child", wall_time
    except subprocess.TimeoutExpired:
        wall_time = time.time() - start
        return "TIMEOUT", f"hung >{TIMEOUT_SEC}s", wall_time
    except Exception as e:
        wall_time = time.time() - start
        return "OTHER", str(e), wall_time
    finally:
        try:
            os.unlink(child_script)
        except Exception:
            pass
        try:
            if os.path.exists(result_file):
                os.unlink(result_file)
        except Exception:
            pass


def main():
    total = (
        len(PHYS)
        * len(MAC_MODES)
        * len(STANDARDS)
        * len(QOS_VALUES)
        * len(TAP_MODES)
        * len(PROPAGATIONS)
        * len(N_NODES_LIST)
    )
    print(f"Total combinations to test: {total}")
    print(f"Results will be written to: {RESULTS_CSV}")
    print("-" * 80)

    os.makedirs("/results", exist_ok=True)
    with open(RESULTS_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "phy",
                "mac_mode",
                "standard",
                "qos",
                "tap_mode",
                "propagation",
                "n_nodes",
                "result",
                "detail",
                "wall_time",
            ]
        )

        count = 0
        for phy in PHYS:
            for mac_mode in MAC_MODES:
                for standard in STANDARDS:
                    for qos in QOS_VALUES:
                        for tap_mode in TAP_MODES:
                            for propagation in PROPAGATIONS:
                                for n_nodes in N_NODES_LIST:
                                    count += 1
                                    label = f"[{count}/{total}] {phy}/{mac_mode}/{standard}/qos={qos}/{tap_mode}/{propagation}/n={n_nodes}"
                                    print(label, end=" ", flush=True)

                                    result, detail, wall_time = run_single_test_isolated(
                                        phy,
                                        mac_mode,
                                        standard,
                                        qos,
                                        tap_mode,
                                        propagation,
                                        n_nodes,
                                    )
                                    print(f"-> {result} ({wall_time:.2f}s)")
                                    writer.writerow(
                                        [
                                            phy,
                                            mac_mode,
                                            standard,
                                            qos,
                                            tap_mode,
                                            propagation,
                                            n_nodes,
                                            result,
                                            detail,
                                            f"{wall_time:.3f}",
                                        ]
                                    )
                                    f.flush()

    print("-" * 80)
    print(f"Done. Results written to {RESULTS_CSV}")

    with open(RESULTS_CSV, "r") as f:
        reader = csv.DictReader(f)
        results = list(reader)

    pass_count = sum(1 for r in results if r["result"] == "PASS")
    segfault_count = sum(1 for r in results if r["result"] == "SEGFAULT")
    timeout_count = sum(1 for r in results if r["result"] == "TIMEOUT")
    other_count = sum(1 for r in results if r["result"] == "OTHER")
    print(f"PASS: {pass_count}, SEGFAULT: {segfault_count}, TIMEOUT: {timeout_count}, OTHER: {other_count}")

    if pass_count > 0:
        print("\nPassing combinations:")
        for r in results:
            if r["result"] == "PASS":
                print(
                    f"  - {r['phy']}/{r['mac_mode']}/{r['standard']}/"
                    f"qos={r['qos']}/{r['tap_mode']}/{r['propagation']}"
                )


if __name__ == "__main__":
    main()
