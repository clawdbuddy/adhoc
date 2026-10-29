"""ns-3 Python 仿真运行器 —— scratch/manet-30nodes.cc 的移植版（NS-3.47 + cppyy 专用）。

线程模型：
    ns-3 仿真器在独立守护线程中启动；FastAPI 在主 asyncio 循环中运行。
    仿真线程拥有 ns-3 全局状态。

NS-3.47 + cppyy 已知限制与可行配置：
    - AdhocWifiMac + TapBridge + RealtimeSimulatorImpl 会触发上游 segfault
      （Txop::Queue / Txop::StartAccessAfterEvent），本文件无法规避。
    - MeshPointDevice（802.11s/HWMP）+ TapBridge + RealtimeSimulatorImpl 工作正常。
    - 容器 eth0 的 MAC 必须与 ns-3 mesh 设备的 MAC 一致（由 netns.mesh_mac 生成），
      否则 802.11s 会把容器视为"桥接客户端"而无法正确转发单播帧。
    - AdHoc + TAP 不安全组合显式拒绝；AdHoc + onoff 可用于内部基准。
"""
from __future__ import annotations

import json
import logging
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .config import SimConfig
from pathlib import Path
from .tap_telemetry import TapTelemetry

log = logging.getLogger(__name__)


def _to_ns3_address(inet_addr: Any) -> Any:
    """cppyy 绑定中 InetSocketAddress 无法隐式转换为 Address，需显式调用 ConvertTo。"""
    try:
        return inet_addr.ConvertTo()
    except Exception:  # noqa: BLE001
        return inet_addr


class _ModuleProxy:
    """代理已知子模块名，回退到 cppyy 根命名空间。

    对已知的 ns-3 子模块名（如 wifi, mobility），cppyy 同时暴露为根属性。
    若子模块路径未命中，代理回退到扁平根命名空间查找。
    """

    def __init__(self, ns):
        self._ns = ns

    def __getattr__(self, name):
        try:
            return getattr(self._ns, name)
        except AttributeError:
            pass
        return getattr(self._ns, name)


class _CppyyNsWrapper:
    """包装 cppyy.gbl.ns3，配合 ns-3.47 cppyy 扁平命名空间实现子模块写法兼容。

    ns-3.47 cppyy 绑定中所有类都挂在 ns3 根命名空间下，但旧代码里大量出现
    `ns.wifi.WifiHelper`、`ns.aodv.AodvHelper` 等子模块写法。已知子模块名
    (core, wifi, mobility 等) 走根命名空间二次回退；未知属性直接透传给底层。
    """

    # ns-3 子模块名列表；cppyy 中这些名字同时是根命名空间属性（ns3::aodv 等），
    # 但类实际挂在根下，因此必须做二次回退。
    _MODULE_NAMES = frozenset({
        "core", "network", "internet", "wifi", "mobility", "tap_bridge",
        "flow_monitor", "propagation", "spectrum", "aodv", "olsr",
        "dsdv", "dsr", "mesh", "applications",
    })

    def __init__(self, ns):
        self._ns = ns
        self._proxies: dict[str, Any] = {}

    def __getattr__(self, name):
        if name in self._MODULE_NAMES:
            if name not in self._proxies:
                self._proxies[name] = _ModuleProxy(self._ns)
            return self._proxies[name]
        if name not in self._proxies:
            try:
                val = getattr(self._ns, name)
            except AttributeError:
                raise AttributeError(f"ns3 has no attribute '{name}'") from None
            self._proxies[name] = val
        return self._proxies[name]


def _import_ns():
    """惰性导入 ns-3 cppyy 绑定；将 ImportError 推迟到仿真真正启动时。

    NS-3.47 使用 cppyy 作为唯一 Python 绑定后端。`from ns import ns`
    拿到 cppyy 暴露的统一 C++ 命名空间对象，所有类挂在扁平 ns3 根命名空间下。
    用 _CppyyNsWrapper 包装后，代码里的 `ns.core.Simulator`、`ns.wifi.WifiHelper`
    等子模块写法无需改动。
    """
    from ns import ns  # noqa: WPS433
    return _CppyyNsWrapper(ns)


@dataclass
class NodeRuntime:
    """单个 ns-3 节点的实时快照。"""
    id: int
    x: float = 0.0
    y: float = 0.0
    rx_packets: int = 0
    tx_packets: int = 0
    neighbors: list[int] = field(default_factory=list)


@dataclass
class FlowRuntime:
    """单条流量的实时快照。"""
    flow_id: int
    source: str
    destination: str
    tx_packets: int = 0
    rx_packets: int = 0
    lost_packets: int = 0
    avg_delay: float = 0.0
    throughput: float = 0.0


@dataclass
class EnvState:
    """动态控制后的当前生效环境参数快照。"""
    tx_power: list[float] = field(default_factory=list)
    rx_sensitivity: list[float] = field(default_factory=list)
    positions: list[dict[str, float]] = field(default_factory=list)
    path_loss_exponent: float = 2.0
    frequency_mhz: int = 590
    phy_frequency_mhz: float = 0.0
    channel_width_mhz: int = 20
    range_target_m: float = 4000.0
    path_loss_model: str = "FreeSpace"


class SimRunner:
    """封装一次 ns-3 仿真生命周期。"""

    def __init__(self, config: SimConfig, node_ips: dict[str, int] | None = None):
        self.config = config
        self._node_ips = node_ips
        self._thread: Optional[threading.Thread] = None
        self._wall_pacer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._nodes_runtime: dict[int, NodeRuntime] = {}
        self._flows_runtime: dict[int, FlowRuntime] = {}
        self._ns: Any = None
        self._fm: Any = None
        self._fm_helper: Any = None
        self._classifier: Any = None
        self._bridge: Any = None
        # cppyy 的 std::function 转换只持有 callable 的弱引用。
        self._tick_callback = self._simulation_tick
        self._tap_telemetry: TapTelemetry | None = None
        self._ready = threading.Event()
        self._sim_elapsed = 0.0
        self._running = False
        self._start_time: float | None = None
        self._error: str | None = None
        # 动态控制：线程安全命令队列(maxsize 防无界增长) + ns-3 对象引用
        self._command_queue: queue.Queue = queue.Queue(maxsize=500)
        self._nodes_container: Any = None
        self._wifi_devices: Any = None
        self._spectrum_channel: Any = None
        self._propagation_loss_model: Any = None
        self._range_model: Any = None
        self._phy_model_type: str = ""
        # 实际安装的 MAC 模式。
        self._mac_mode_actual: str = ""
        # 运行时增删节点所需 helper（仅在 _build_and_run 完成后有效）
        self._phy_helper: Any = None
        self._wifi_helper: Any = None
        self._mac_helper: Any = None
        self._mesh_helper: Any = None
        self._internet_stack: Any = None
        self._ipv4_helper: Any = None
        self._tap_bridge_helper: Any = None
        # 当前活跃节点集合（remove 后元素被移除,但 ns-3 NodeContainer 不会缩容）
        self._active_node_ids: set[int] = set()
        # PHY 缓存：node_id → phy，避免动态命令时的四级回退。
        # 缓存生命周期绑定到单次仿真；节点增删时须调用 _invalidate_phy_cache()。
        self._phy_cache: dict[int, Any] = {}
        # 动态参数当前值（供遥测回传前端）
        self._env_state = EnvState(
            tx_power=[float(config.tx_power_start)] * config.n_nodes,
            rx_sensitivity=[float(config.rx_sensitivity)] * config.n_nodes,
            positions=[{"x": 0.0, "y": 0.0, "z": 0.0} for _ in range(config.n_nodes)],
            path_loss_exponent=float(config.path_loss_exponent),
            frequency_mhz=int(config.frequency_mhz),
            channel_width_mhz=int(config.channel_width_mhz),
            range_target_m=float(config.range_target_m),
            path_loss_model=str(config.path_loss_model),
        )

    # ---------------------------------------------------- public lifecycle
    def start(self) -> None:
        if self._running:
            raise RuntimeError("simulator already running")
        self._stop_event.clear()
        self._ready.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="ns3-sim", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=30.0):
            self._stop_event.set()
            raise RuntimeError("simulator initialization timed out")
        if self._error:
            raise RuntimeError(f"simulator failed to start: {self._error}")

    def stop(self, timeout: float = 5.0) -> None:
        # Stop 本身也必须由仿真线程执行，tick 消费该事件。
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise RuntimeError("仿真线程尚未停止，不能拆除网络设备")
        self._phy_cache.clear()

    @property
    def running(self) -> bool:
        return self._running and (self._thread is not None and self._thread.is_alive())

    @property
    def capture_drops(self) -> int:
        return self._tap_telemetry.capture_drops if self._tap_telemetry else 0

    @property
    def elapsed(self) -> float:
        if self._start_time is None:
            return 0.0
        return self._sim_elapsed

    @property
    def mac_mode_actual(self) -> str:
        """实际安装的 MAC 模式。"""
        return self._mac_mode_actual

    # ------------------------------------------------- public snapshots
    def snapshot_nodes(self) -> list[NodeRuntime]:
        with self._lock:
            return [NodeRuntime(**n.__dict__) for n in self._nodes_runtime.values()]

    def snapshot_flows(self) -> list[FlowRuntime]:
        with self._lock:
            return [FlowRuntime(**f.__dict__) for f in self._flows_runtime.values()]

    def snapshot_env(self) -> EnvState:
        with self._lock:
            return EnvState(
                tx_power=list(self._env_state.tx_power),
                rx_sensitivity=list(self._env_state.rx_sensitivity),
                positions=[dict(p) for p in self._env_state.positions],
                path_loss_exponent=self._env_state.path_loss_exponent,
                frequency_mhz=self._env_state.frequency_mhz,
                phy_frequency_mhz=self._env_state.phy_frequency_mhz,
                channel_width_mhz=self._env_state.channel_width_mhz,
                range_target_m=self._env_state.range_target_m,
                path_loss_model=self._env_state.path_loss_model,
            )

    def find_path(self, src_id: int, dst_id: int) -> list[int] | None:
        """基于实际 Mesh peer 图做 BFS,返回 src→dst 的最少跳数路径。

        返回的列表首元素 = src_id,末元素 = dst_id;若不连通返回 None。
        与 ns-3 实际 HWMP/AODV 路由可能不一致——这里只反映"几何上谁能听到谁"的拓扑层结果,
        但与 mesh L2 多跳能否成功有强相关性,适合给前端做拓扑可视化。
        """
        with self._lock:
            if src_id == dst_id:
                return [src_id]
            if src_id not in self._nodes_runtime or dst_id not in self._nodes_runtime:
                return None
            # BFS
            visited = {src_id}
            parent: dict[int, int] = {}
            queue_bfs = [src_id]
            found = False
            while queue_bfs:
                cur = queue_bfs.pop(0)
                if cur == dst_id:
                    found = True
                    break
                cur_node = self._nodes_runtime.get(cur)
                if not cur_node:
                    continue
                for nb in cur_node.neighbors:
                    if nb in visited:
                        continue
                    visited.add(nb)
                    parent[nb] = cur
                    if nb == dst_id:
                        found = True
                        queue_bfs = []
                        break
                    queue_bfs.append(nb)
            if not found:
                return None
            # 回溯
            path = [dst_id]
            while path[-1] != src_id:
                p = parent.get(path[-1])
                if p is None:
                    return None
                path.append(p)
            path.reverse()
            return path

    # =================================================================== private
    def _run(self) -> None:
        try:
            ns = _import_ns()
            self._ns = ns
            self._build_and_run(ns)
        except Exception as e:  # noqa: BLE001
            self._error = repr(e)
            log.exception("ns-3 sim crashed")
        finally:
            try:
                if self._ns is not None:
                    self._sim_elapsed = self._ns.core.Simulator.Now().GetSeconds()
                    self._ns.core.Simulator.Destroy()
            except Exception:  # noqa: BLE001, S110
                pass
            if self._tap_telemetry is not None:
                self._tap_telemetry.close()
            self._bridge = None
            self._running = False
            self._ready.set()

    # --------------------------------------------------- ns-3 build steps
    def _build_and_run(self, ns: Any) -> None:
        cfg = self.config
        if cfg.mac_mode == "adhoc" and cfg.traffic_mode == "tap":
            raise ValueError("当前 cppyy 绑定不支持安全运行 AdHoc + TAP；请使用 Mesh 或 AdHoc onoff 模式")

        # RealtimeSimulatorImpl 与真实 TAP 对时；周期 tick 保证事件队列持续运行。
        ns.core.GlobalValue.Bind(
            "SimulatorImplementationType",
            ns.core.StringValue("ns3::RealtimeSimulatorImpl"),
        )
        ns.core.Config.SetDefault(
            "ns3::RealtimeSimulatorImpl::SynchronizationMode",
            # cppyy 首次调用会 JIT；HardLimit 会因一次编译抖动直接 abort。
            ns.core.StringValue("BestEffort"),
        )
        ns.core.GlobalValue.Bind("ChecksumEnabled", ns.core.BooleanValue(True))
        ns.network.Mac48Address.ResetAllocationIndex()
        ns.core.RngSeedManager.SetSeed(cfg.seed)
        ns.core.RngSeedManager.SetRun(cfg.run)

        # 2. Nodes
        nodes = ns.network.NodeContainer()
        nodes.Create(cfg.n_nodes)
        log.info("created %d ns-3 nodes", cfg.n_nodes)

        # 3. Channel + PHY
        # phy_model="spectrum" 启用 SpectrumWifiPhy + MultiModelSpectrumChannel；
        # phy_model="yans" 维持原 Yans 路径（向后兼容）。两者都通过 Friis 把传播
        # 损耗钉死在 cfg.frequency_mhz，保证 4 km LOS 物理预算与 UHF 一致。
        if cfg.phy_model == "spectrum":
            phy, spec_chan, loss = self._build_spectrum_phy(ns, cfg)
            self._spectrum_channel = spec_chan
            self._propagation_loss_model = loss
            self._phy_model_type = "spectrum"
        else:
            phy, loss, range_loss = self._build_yans_phy(ns, cfg)
            self._propagation_loss_model = loss
            self._range_model = range_loss
            self._phy_model_type = "yans"
        phy.Set("TxPowerStart", ns.core.DoubleValue(cfg.tx_power_start))
        phy.Set("TxPowerEnd", ns.core.DoubleValue(cfg.tx_power_end))
        phy.Set("TxPowerLevels", ns.core.UintegerValue(cfg.tx_power_levels))
        phy.Set("RxSensitivity", ns.core.DoubleValue(cfg.rx_sensitivity))
        phy.Set("CcaEdThreshold", ns.core.DoubleValue(cfg.cca_threshold))
        phy.Set("TxGain", ns.core.DoubleValue(cfg.antenna_gain))
        phy.Set("RxGain", ns.core.DoubleValue(cfg.antenna_gain))

        # 4. Wifi standard + rate control
        wifi = ns.wifi.WifiHelper()
        wifi.SetStandard(self._wifi_standard(ns, cfg.standard))
        self._apply_rate_control(ns, wifi, cfg)

        # 5. 将标准、速率配置应用到实际安装设备的 helper。
        if cfg.mac_mode == "mesh":
            devices = self._install_mesh(ns, cfg, phy, nodes)
        else:
            # 保留显式模式；禁止将不安全组合静默转换成另一种实验。
            if cfg.traffic_mode == "tap":
                raise ValueError("当前 cppyy 绑定的 AdHoc + TapBridge 存在上游崩溃风险；请使用 Mesh 或 AdHoc onoff 模式")
            mac = ns.wifi.WifiMacHelper()
            mac.SetType("ns3::AdhocWifiMac", "Ssid", ns.wifi.SsidValue(ns.wifi.Ssid(cfg.ssid)))
            devices = wifi.Install(phy, mac, nodes)
            self._mac_mode_actual = "adhoc"

        # 6. Mobility
        self._install_mobility(ns, cfg, nodes)

        # 7. Internet stack + routing
        self._install_routing(ns, cfg, nodes)

        # 保存 ns-3 对象引用供动态控制使用
        self._nodes_container = nodes
        self._wifi_devices = devices
        self._configure_devices(ns, cfg, nodes)

        # 8. IP addresses (192.168.100.10 + i, /24)
        ipv4 = ns.internet.Ipv4AddressHelper()
        ipv4.SetBase(
            ns.network.Ipv4Address("192.168.100.0"),
            ns.network.Ipv4Mask("255.255.255.0"),
            ns.network.Ipv4Address("0.0.0.10"),
        )
        if cfg.no_ip_node_indices:
            filtered = ns.network.NetDeviceContainer()
            for i in range(cfg.n_nodes):
                if i not in cfg.no_ip_node_indices:
                    filtered.Add(devices.Get(i))
            if filtered.GetN() > 0:
                ipv4.Assign(filtered)
        else:
            ipv4.Assign(devices)

        # 9. TapBridge or OnOff internal traffic
        if cfg.traffic_mode == "tap":
            tb_helper = ns.tap_bridge.TapBridgeHelper()
            tb_helper.SetAttribute("Mode", ns.core.StringValue(cfg.tap_mode))
            for i in range(cfg.n_nodes):
                tap_name = f"{cfg.tap_prefix}{i}"
                tb_helper.SetAttribute("DeviceName", ns.core.StringValue(tap_name))
                tb_helper.Install(nodes.Get(i), devices.Get(i))
                log.info("TapBridge node-%d ↔ %s", i, tap_name)

        else:
            # onoff mode: ns-3 internal traffic for baseline throughput test
            sink_addr = _to_ns3_address(
                ns.network.InetSocketAddress(
                    ns.network.Ipv4Address("192.168.100.10"), cfg.onoff_sink_port
                )
            )
            packet_sink_helper = ns.applications.PacketSinkHelper(
                "ns3::UdpSocketFactory", sink_addr
            )
            sink_app = packet_sink_helper.Install(nodes.Get(0))
            sink_app.Start(ns.core.Seconds(0.0))

            onoff_addr = _to_ns3_address(
                ns.network.InetSocketAddress(
                    ns.network.Ipv4Address("192.168.100.10"), cfg.onoff_sink_port
                )
            )
            onoff_helper = ns.applications.OnOffHelper(
                "ns3::UdpSocketFactory", onoff_addr
            )
            onoff_helper.SetAttribute(
                "DataRate", ns.network.DataRateValue(ns.network.DataRate(cfg.onoff_data_rate))
            )
            onoff_helper.SetAttribute(
                "PacketSize", ns.core.UintegerValue(cfg.onoff_packet_size)
            )
            if cfg.onoff_max_bytes > 0:
                onoff_helper.SetAttribute(
                    "MaxBytes", ns.core.UintegerValue(cfg.onoff_max_bytes)
                )
            # install on last node as sender
            sender_node = nodes.Get(cfg.n_nodes - 1)
            onoff_app = onoff_helper.Install(sender_node)
            onoff_app.Start(ns.core.Seconds(cfg.onoff_start_time))
            log.info(
                "OnOff traffic: node-%d → node-0 @ %s, pkt=%dB, port=%d",
                cfg.n_nodes - 1, cfg.onoff_data_rate, cfg.onoff_packet_size, cfg.onoff_sink_port
            )

        # 9b. Host-manet-nodes use the mesh peer MAC for the remote VXLAN,
        # so no proxy entries are needed — the 802.11s mesh treats the
        # remote container as a local mesh peer.

        # 10. FlowMonitor
        if cfg.flow_monitor and cfg.traffic_mode != "tap":
            fm_helper = ns.flow_monitor.FlowMonitorHelper()
            self._fm_helper = fm_helper
            self._fm = fm_helper.InstallAll()
            self._classifier = fm_helper.GetClassifier()

        # 11. Tracing
        if cfg.pcap:
            phy.EnablePcap(cfg.pcap_prefix, devices, True)
        if cfg.ascii:
            ascii_helper = ns.network.AsciiTraceHelper()
            phy.EnableAsciiAll(ascii_helper.CreateFileStream(f"{cfg.pcap_prefix}.tr"))

        # 12. Initial node-runtime snapshot (positions filled below by the poller)
        with self._lock:
            for i in range(cfg.n_nodes):
                self._nodes_runtime[i] = NodeRuntime(id=i)

        # C++ 定时器解决 cppyy 无法直接向 Schedule 传入 Python callback 的问题。
        # 所有 ns-3 读写（含遥测）均在 Run 所在线程完成。
        import cppyy
        import sysconfig
        cppyy.add_include_path(sysconfig.get_paths()["include"])
        cppyy.include(str(Path(__file__).with_name("sim_runtime.h")))
        self._bridge = cppyy.gbl.manet.Runtime(self._tick_callback)
        if cfg.traffic_mode == "tap" and cfg.flow_monitor:
            self._tap_telemetry = TapTelemetry(cfg.tap_prefix, cfg.n_nodes, ip_to_id=self._node_ips)
            self._tap_telemetry.open()
        ns.core.Simulator.Stop(ns.core.Seconds(cfg.simulation_time))
        self._start_time = time.time()
        self._running = True
        self._bridge.Start()
        self._ready.set()
        self._bridge.Run()

    @staticmethod
    def _channel_settings(cfg: SimConfig) -> str:
        """带宽与频段一起配置，UHF 用合法 WiFi 代理频道计算调制。"""
        band = "BAND_2_4GHZ" if "2.4GHz" in cfg.standard else "BAND_5GHZ"
        width = cfg.channel_width_mhz
        channel = 0
        if band == "BAND_2_4GHZ":
            candidate = (cfg.frequency_mhz - 2407) / 5
            if candidate.is_integer() and candidate in (range(1, 14) if width == 20 else range(3, 12)):
                channel = int(candidate)
        else:
            candidate = (cfg.frequency_mhz - 5000) / 5
            legal = {
                20: {36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 149, 153, 157, 161, 165},
                40: {38, 46, 54, 62, 102, 110, 118, 126, 134, 142, 151, 159},
                80: {42, 58, 106, 122, 138, 155},
                160: {50, 114},
            }
            if candidate.is_integer() and candidate in legal[width]:
                channel = int(candidate)
        return f"{{{channel}, {width}, {band}, 0}}"

    def _configure_devices(self, ns: Any, cfg: SimConfig, nodes: Any) -> None:
        """将 MAC 与竞争窗口设置接入实际安装的 WiFi 接口。"""
        for i in range(nodes.GetN()):
            node = nodes.Get(i)
            for j in range(node.GetNDevices()):
                wifi = node.GetDevice(j).GetObject[ns.wifi.WifiNetDevice]()
                if not wifi:
                    continue
                phy = wifi.GetPhy()
                phy.SetAttribute("ChannelSettings", ns.core.StringValue(self._channel_settings(cfg)))
                if i == 0:
                    self._env_state.phy_frequency_mhz = float(phy.GetFrequency())
                manager = wifi.GetRemoteStationManager()
                manager.SetAttribute("RtsCtsThreshold", ns.core.UintegerValue(cfg.rts_cts_threshold))
                manager.SetAttribute("FragmentationThreshold", ns.core.UintegerValue(cfg.fragmentation_threshold))
                if cfg.non_unicast_mode:
                    manager.SetAttribute("NonUnicastMode", ns.core.StringValue(cfg.data_rate))
                mac = wifi.GetMac()
                txop = mac.GetTxop()
                if txop:
                    txop.SetMinCw(cfg.cw_min)
                    txop.SetMaxCw(cfg.cw_max)
                if mac.GetQosSupported():
                    for tid in (0, 1, 4, 6):
                        qos = mac.GetQosTxop(tid)
                        if qos:
                            qos.SetMinCw(cfg.cw_min)
                            qos.SetMaxCw(cfg.cw_max)

    # -------------------------------------------------- channel / propagation
    def _build_yans_phy(self, ns: Any, cfg: SimConfig) -> tuple[Any, Any | None, Any | None]:
        """YansWifiChannel + YansWifiPhyHelper（旧路径，向后兼容）。

        返回 (phy_helper, path_loss_model, range_model) 三元组，供动态控制保存引用。
        """
        ch = ns.wifi.YansWifiChannelHelper()
        if cfg.propagation_delay == "ConstantSpeed":
            ch.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel")
        else:
            ch.SetPropagationDelay("ns3::RandomPropagationDelayModel")
        channel = ch.Create()

        # 主路径损耗模型
        loss = self._make_path_loss_object(ns, cfg)
        if loss is not None:
            channel.SetPropagationLossModel(loss)

        # 建立模型链（Yans 使用 SetNext 链式连接）
        last_model = loss

        # 衰落模型
        if cfg.enable_fading:
            fading = self._make_fading_model(ns, cfg)
            if fading is not None:
                if last_model is not None:
                    last_model.SetNext(fading)
                    last_model = fading
                else:
                    channel.SetPropagationLossModel(fading)
                    last_model = fading

        # 障碍物/地形模型（阴影 + 穿透）
        if cfg.enable_obstacles:
            shadowing = self._make_shadowing_model(ns, cfg)
            if shadowing is not None:
                if last_model is not None:
                    last_model.SetNext(shadowing)
                    last_model = shadowing
                else:
                    channel.SetPropagationLossModel(shadowing)
                    last_model = shadowing

            obstacle = self._make_obstacle_model(ns, cfg)
            if obstacle is not None:
                if last_model is not None:
                    last_model.SetNext(obstacle)
                    last_model = obstacle
                else:
                    channel.SetPropagationLossModel(obstacle)
                    last_model = obstacle

        # 叠加 Range 硬截断（Yans 路径）
        range_loss = None
        if cfg.range_target_m > 0:
            range_loss = ns.propagation.CreateObject["ns3::RangePropagationLossModel"]()
            range_loss.SetAttribute("MaxRange", ns.core.DoubleValue(cfg.range_target_m))
            if last_model is not None:
                last_model.SetNext(range_loss)
            else:
                channel.SetPropagationLossModel(range_loss)

        phy = ns.wifi.YansWifiPhyHelper()
        phy.SetChannel(channel)
        initial_channel = "{100, 20, BAND_5GHZ, 0}" if cfg.mac_mode == "mesh" else self._channel_settings(cfg)
        phy.Set("ChannelSettings", ns.core.StringValue(initial_channel))
        # MeshHelper 安装时内部切换到频道 100，目标信道在安装完成后设置。
        return phy, loss, range_loss

    def _build_spectrum_phy(self, ns: Any, cfg: SimConfig) -> tuple[Any, Any, Any | None]:
        """SpectrumWifiPhy + MultiModelSpectrumChannel。

        Friis 路径损耗的 Frequency 属性被钉到 cfg.frequency_mhz（默认 590 MHz），
        使距离-衰减曲线与 UHF 物理一致；ns-3 内部 802.11a 5 GHz 的频道号只是
        载波/调制配置，不影响传播预算。

        返回 (phy_helper, spectrum_channel, path_loss_model) 三元组，供动态控制保存引用。
        """
        # ns-3.47 + cppyy：Object 派生类必须用 CreateObject，直接构造会得到
        # tid=ns3::Object 的空壳对象，SetAttribute 会触发 NS_FATAL_ERROR。
        spec_chan = ns.spectrum.CreateObject["ns3::MultiModelSpectrumChannel"]()

        # 路径损耗：FreeSpace 走 Friis（带 frequency_mhz）；其余走 LogDistance/Two-Ray/...
        loss = self._make_path_loss_object(ns, cfg)
        if loss is not None:
            spec_chan.AddPropagationLossModel(loss)

        # 衰落模型（Spectrum 路径使用叠加）
        if cfg.enable_fading:
            fading = self._make_fading_model(ns, cfg)
            if fading is not None:
                spec_chan.AddPropagationLossModel(fading)

        # 障碍物/地形模型（阴影 + 穿透）
        if cfg.enable_obstacles:
            shadowing = self._make_shadowing_model(ns, cfg)
            if shadowing is not None:
                spec_chan.AddPropagationLossModel(shadowing)

            obstacle = self._make_obstacle_model(ns, cfg)
            if obstacle is not None:
                spec_chan.AddPropagationLossModel(obstacle)

        # 叠加 Range 硬截断：无论主模型是什么，都按 range_target_m 做最大距离限制。
        if cfg.range_target_m > 0:
            range_loss = ns.propagation.CreateObject["ns3::RangePropagationLossModel"]()
            range_loss.SetAttribute("MaxRange", ns.core.DoubleValue(cfg.range_target_m))
            spec_chan.AddPropagationLossModel(range_loss)
            self._range_model = range_loss
        else:
            self._range_model = None

        # 传播延迟模型
        if cfg.propagation_delay == "ConstantSpeed":
            delay = ns.propagation.CreateObject["ns3::ConstantSpeedPropagationDelayModel"]()
        else:
            delay = ns.propagation.CreateObject["ns3::RandomPropagationDelayModel"]()
        spec_chan.SetPropagationDelayModel(delay)

        phy = ns.wifi.SpectrumWifiPhyHelper()
        phy.SetChannel(spec_chan)
        initial_channel = "{100, 20, BAND_5GHZ, 0}" if cfg.mac_mode == "mesh" else self._channel_settings(cfg)
        phy.Set("ChannelSettings", ns.core.StringValue(initial_channel))
        # 目标频段在安装完成后应用；UHF 使用合法的 WiFi 代理载波。
        log.info(
            "SpectrumWifiPhy: 中心频率 %.0f MHz / 带宽 %d MHz / 视距目标 %.0f m",
            cfg.frequency_mhz, cfg.channel_width_mhz, cfg.range_target_m,
        )
        return phy, spec_chan, loss

    @staticmethod
    def _make_path_loss_object(ns: Any, cfg: SimConfig) -> Any | None:
        pl = cfg.path_loss_model
        freq_hz = float(cfg.frequency_mhz) * 1e6
        if pl == "FreeSpace":
            m = ns.propagation.CreateObject["ns3::FriisPropagationLossModel"]()
            m.SetAttribute("Frequency", ns.core.DoubleValue(freq_hz))
            m.SetAttribute("MinLoss", ns.core.DoubleValue(0.0))
            return m
        if pl == "LogDistance":
            m = ns.propagation.CreateObject["ns3::LogDistancePropagationLossModel"]()
            m.SetAttribute("Exponent", ns.core.DoubleValue(cfg.path_loss_exponent))
            m.SetAttribute("ReferenceLoss", ns.core.DoubleValue(cfg.path_loss_ref_loss))
            m.SetAttribute("ReferenceDistance", ns.core.DoubleValue(cfg.path_loss_ref_distance))
            return m
        if pl == "TwoRayGround":
            m = ns.propagation.CreateObject["ns3::TwoRayGroundPropagationLossModel"]()
            m.SetAttribute("Frequency", ns.core.DoubleValue(freq_hz))
            return m
        if pl == "ThreeLogDistance":
            return ns.propagation.CreateObject["ns3::ThreeLogDistancePropagationLossModel"]()
        if pl == "Cost231":
            return ns.propagation.CreateObject["ns3::Cost231PropagationLossModel"]()
        if pl == "Range":
            m = ns.propagation.CreateObject["ns3::RangePropagationLossModel"]()
            m.SetAttribute("MaxRange", ns.core.DoubleValue(cfg.range_target_m))
            return m
        return None

    # ---- fading / shadowing / obstacle helpers ------------------------------
    @staticmethod
    def _make_fading_model(ns: Any, cfg: SimConfig) -> Any | None:
        """创建小尺度衰落模型（Nakagami / Jakes / Rayleigh / Rician）。"""
        fm = cfg.fading_model
        if fm == "Nakagami":
            nak = ns.propagation.CreateObject["ns3::NakagamiPropagationLossModel"]()
            nak.SetAttribute("m0", ns.core.DoubleValue(cfg.nakagami_m0))
            nak.SetAttribute("m1", ns.core.DoubleValue(cfg.nakagami_m1))
            nak.SetAttribute("m2", ns.core.DoubleValue(cfg.nakagami_m2))
            nak.SetAttribute("Distance1", ns.core.DoubleValue(cfg.nakagami_d1))
            nak.SetAttribute("Distance2", ns.core.DoubleValue(cfg.nakagami_d2))
            return nak
        if fm == "Jakes":
            return ns.propagation.CreateObject["ns3::JakesPropagationLossModel"]()
        if fm == "Rayleigh":
            # Rayleigh 是 Nakagami 的准确特列（m=1）
            nak = ns.propagation.CreateObject["ns3::NakagamiPropagationLossModel"]()
            nak.SetAttribute("m0", ns.core.DoubleValue(1.0))
            nak.SetAttribute("m1", ns.core.DoubleValue(1.0))
            nak.SetAttribute("m2", ns.core.DoubleValue(1.0))
            nak.SetAttribute("Distance1", ns.core.DoubleValue(cfg.nakagami_d1))
            nak.SetAttribute("Distance2", ns.core.DoubleValue(cfg.nakagami_d2))
            log.info("Rayleigh fading (Nakagami m=1)")
            return nak
        if fm == "Rician":
            # Rician 用 Nakagami 近似：m = (K+1)^2 / (2K+1)
            k_linear = 10.0 ** (cfg.rician_k / 10.0)
            m_equiv = (k_linear + 1.0) ** 2 / (2.0 * k_linear + 1.0)
            m_equiv = min(m_equiv, 100.0)  # 上限避免数值问题
            nak = ns.propagation.CreateObject["ns3::NakagamiPropagationLossModel"]()
            nak.SetAttribute("m0", ns.core.DoubleValue(m_equiv))
            nak.SetAttribute("m1", ns.core.DoubleValue(m_equiv))
            nak.SetAttribute("m2", ns.core.DoubleValue(m_equiv))
            nak.SetAttribute("Distance1", ns.core.DoubleValue(cfg.nakagami_d1))
            nak.SetAttribute("Distance2", ns.core.DoubleValue(cfg.nakagami_d2))
            log.info("Rician fading (K=%.1f dB, Nakagami equiv m=%.2f)", cfg.rician_k, m_equiv)
            return nak
        return None

    @staticmethod
    def _make_shadowing_model(ns: Any, cfg: SimConfig) -> Any | None:
        """创建对数正态阴影模型（RandomPropagationLossModel + NormalRandomVariable）。"""
        if cfg.obstacle_shadowing_sigma <= 0:
            return None
        shadow = ns.propagation.CreateObject["ns3::RandomPropagationLossModel"]()
        normal = ns.core.CreateObject["ns3::NormalRandomVariable"]()
        normal.SetAttribute("Mean", ns.core.DoubleValue(0.0))
        normal.SetAttribute("Variance", ns.core.DoubleValue(1.0))
        # NormalRandomVariable 默认产生 N(0,1)；sigma 在 DoCalcRxPower 时乘上去
        shadow.SetAttribute("Variable", ns.core.PointerValue(normal))
        log.info("Log-normal shadowing: sigma=%.1f dB", cfg.obstacle_shadowing_sigma)
        return shadow

    def _make_obstacle_model(self, ns: Any, cfg: SimConfig) -> Any | None:
        """创建障碍物 NLOS 穿透损耗模型（含几何检测）。"""
        if not cfg.enable_obstacles or cfg.obstacle_penetration_loss <= 0:
            return None

        try:
            obstacles = json.loads(cfg.obstacles_json)
        except json.JSONDecodeError:
            obstacles = []

        if not obstacles:
            # 无具体障碍物配置，使用固定穿透损耗
            obs = ns.propagation.CreateObject["ns3::RandomPropagationLossModel"]()
            constant = ns.core.CreateObject["ns3::ConstantRandomVariable"]()
            constant.SetAttribute("Constant", ns.core.DoubleValue(cfg.obstacle_penetration_loss))
            obs.SetAttribute("Variable", ns.core.PointerValue(constant))
            log.info("Fixed obstacle penetration loss: %.1f dB", cfg.obstacle_penetration_loss)
            return obs

        # 有具体障碍物配置，使用自定义 C++ 模型
        self._register_obstacle_cppyy(ns)
        import cppyy

        raw = cppyy.gbl.ns3.CreateRawObstacleLossModel()
        for obs in obstacles:
            raw.AddObstacle(
                float(obs.get("x", 0)), float(obs.get("y", 0)),
                float(obs.get("w", 10)), float(obs.get("h", 10)),
                float(obs.get("loss", cfg.obstacle_penetration_loss)),
            )
        log.info("Rectangular obstacles: %d configured", len(obstacles))
        return raw

    @staticmethod
    def _register_obstacle_cppyy(ns: Any) -> None:
        """通过 cppyy 注册矩形障碍物传播损耗模型（仅首次调用编译）。"""
        import cppyy

        if hasattr(cppyy.gbl.ns3, "CreateRawObstacleLossModel"):
            return
        cppyy.cppdef("""
        #include <cmath>

        namespace ns3 {

        class RectObstacleLossModel : public PropagationLossModel {
        public:
            RectObstacleLossModel() : m_count(0) {}

            void AddObstacle(double cx, double cy, double w, double h, double loss) {
                if (m_count >= 20) return;
                m_cx[m_count] = cx;
                m_cy[m_count] = cy;
                m_w[m_count] = w;
                m_h[m_count] = h;
                m_loss[m_count] = loss;
                m_count++;
            }

            bool LineIntersectsRect(double x1, double y1, double x2, double y2,
                                    double cx, double cy, double w, double h) const {
                double minX = cx - w / 2.0;
                double maxX = cx + w / 2.0;
                double minY = cy - h / 2.0;
                double maxY = cy + h / 2.0;

                double dx = x2 - x1;
                double dy = y2 - y1;
                double p[4] = {-dx, dx, -dy, dy};
                double q[4] = {x1 - minX, maxX - x1, y1 - minY, maxY - y1};

                double u1 = 0.0, u2 = 1.0;
                for (int i = 0; i < 4; i++) {
                    if (p[i] == 0.0) {
                        if (q[i] < 0.0) return false;
                    } else {
                        double t = q[i] / p[i];
                        if (p[i] < 0.0) {
                            if (t > u1) u1 = t;
                        } else {
                            if (t < u2) u2 = t;
                        }
                    }
                }
                return u1 <= u2;
            }

            double DoCalcRxPower(double txPowerDbm, Ptr<MobilityModel> a,
                                 Ptr<MobilityModel> b) const override {
                if (m_count == 0) return txPowerDbm;

                Vector posA = a->GetPosition();
                Vector posB = b->GetPosition();

                double totalLoss = 0.0;
                for (int i = 0; i < m_count; i++) {
                    if (LineIntersectsRect(posA.x, posA.y, posB.x, posB.y,
                                          m_cx[i], m_cy[i], m_w[i], m_h[i])) {
                        totalLoss += m_loss[i];
                    }
                }
                return txPowerDbm - totalLoss;
            }

            int64_t DoAssignStreams(int64_t stream) override { return 0; }

        private:
            double m_cx[20], m_cy[20], m_w[20], m_h[20], m_loss[20];
            int m_count;
        };

        RectObstacleLossModel* CreateRawObstacleLossModel() {
            return new RectObstacleLossModel();
        }

        } // namespace ns3
        """)

    # -------------------------------------------------------------- mesh MAC
    def _install_mesh(self, ns: Any, cfg: SimConfig, phy: Any, nodes: Any) -> Any:
        """802.11s mesh + HWMP routing：L2 多跳由 ns-3 mesh 模块原地完成。

        TapBridge UseBridge 仍可使用——整张 mesh 在容器视角下表现为单一 L2
        广播域，距离超出单跳 LOS 的节点之间的报文由 HWMP 路径选择算法自动
        通过中间节点中继。不再需要在容器内运行额外的路由 daemon。
        """
        mesh_helper = ns.mesh.MeshHelper.Default()
        # cppyy 中 hasattr 对模板/重载方法不可靠，改用 try/except 探测
        try:
            _ = mesh_helper.Install
        except AttributeError:
            raise RuntimeError(
                "MeshHelper.Install 不可用;NS-3.47 + cppyy 强制使用 mesh 模式，"
                "请确认编译时启用了 mesh 模块 (--enable-modules=mesh)"
            ) from None

        mesh_helper.SetStackInstaller("ns3::Dot11sStack")
        mesh_helper.SetStandard(self._wifi_standard(ns, cfg.standard))
        mesh_helper.SetSpreadInterfaceChannels(ns.mesh.MeshHelper.ZERO_CHANNEL)
        mesh_helper.SetMacType(
            "RandomStart", ns.core.TimeValue(ns.core.Seconds(0.1)),
            "BeaconInterval", ns.core.TimeValue(ns.core.MilliSeconds(cfg.beacon_interval)),
        )
        mesh_helper.SetNumberOfInterfaces(1)
        self._apply_rate_control(ns, mesh_helper, cfg)
        devices = mesh_helper.Install(phy, nodes)
        # ns-3 MeshPointDevice 默认使用 Mac48Address::Allocate() 顺序分配 MAC；
        # 容器 eth0 由 netns.mesh_mac() 设为 00:00:00:00:00:{i+1}。
        # 两者必须一致，否则 802.11s 会把容器流量视为"桥接客户端"，导致广播帧
        # 不被泛洪、单播帧无法转发。若宿主机上有其他 ns-3 进程消耗了 MAC
        # 分配器，地址会偏移——此时需杀死残留进程后重启控制器。
        self._mac_mode_actual = "mesh"
        log.info(
            "Mesh (802.11s/HWMP) installed on %d 节点，data_rate=%s",
            cfg.n_nodes, cfg.data_rate,
        )
        return devices

    # ---------------------------------------------- wifi standard + rate ctrl
    @staticmethod
    def _wifi_standard(ns: Any, label: str) -> Any:
        return {
            "80211a": ns.wifi.WIFI_STANDARD_80211a,
            "80211n-2.4GHz": ns.wifi.WIFI_STANDARD_80211n,
            "80211n-5GHz": ns.wifi.WIFI_STANDARD_80211n,
            "80211ac": ns.wifi.WIFI_STANDARD_80211ac,
            "80211ax-2.4GHz": ns.wifi.WIFI_STANDARD_80211ax,
            "80211ax-5GHz": ns.wifi.WIFI_STANDARD_80211ax,
        }.get(label, ns.wifi.WIFI_STANDARD_80211n)

    @staticmethod
    def _apply_rate_control(ns: Any, wifi: Any, cfg: SimConfig) -> None:
        rc = cfg.rate_control
        if rc == "Constant":
            wifi.SetRemoteStationManager(
                "ns3::ConstantRateWifiManager",
                "DataMode", ns.core.StringValue(cfg.data_rate),
                "ControlMode", ns.core.StringValue("OfdmRate6Mbps" if "5GHz" in cfg.standard or cfg.standard in {"80211a", "80211ac"} else "ErpOfdmRate6Mbps"),
            )
        elif rc == "Arf":
            # Fix for the C++ Arf bug: use proper ns-3 attribute types,
            # no UintegerValue + std::string concatenation.
            wifi.SetRemoteStationManager(
                "ns3::ArfWifiManager",
                "TimerThreshold", ns.core.UintegerValue(15),
                "SuccessThreshold", ns.core.UintegerValue(10),
            )
        elif rc == "Aarf":
            wifi.SetRemoteStationManager("ns3::AarfWifiManager")
        elif rc == "Onoe":
            wifi.SetRemoteStationManager("ns3::OnoeWifiManager")
        elif rc == "Minstrel":
            wifi.SetRemoteStationManager("ns3::MinstrelHtWifiManager" if cfg.standard != "80211a" else "ns3::MinstrelWifiManager")
        else:
            wifi.SetRemoteStationManager("ns3::ArfWifiManager")

    # -------------------------------------------------------------- mobility
    @staticmethod
    def _install_mobility(ns: Any, cfg: SimConfig, nodes: Any) -> None:
        mob = ns.mobility.MobilityHelper()
        # Position allocator: uniform in the configured area.
        pos = ns.mobility.CreateObject["ns3::RandomBoxPositionAllocator"]()
        x_var = ns.core.CreateObject["ns3::UniformRandomVariable"]()
        x_var.SetAttribute("Min", ns.core.DoubleValue(cfg.mobility_min_x))
        x_var.SetAttribute("Max", ns.core.DoubleValue(cfg.mobility_max_x))
        y_var = ns.core.CreateObject["ns3::UniformRandomVariable"]()
        y_var.SetAttribute("Min", ns.core.DoubleValue(cfg.mobility_min_y))
        y_var.SetAttribute("Max", ns.core.DoubleValue(cfg.mobility_max_y))
        z_var = ns.core.CreateObject["ns3::ConstantRandomVariable"]()
        z_var.SetAttribute("Constant", ns.core.DoubleValue(0.0))
        pos.SetX(x_var)
        pos.SetY(y_var)
        pos.SetZ(z_var)
        mob.SetPositionAllocator(pos)

        m = cfg.mobility_model
        if m == "random-walk":
            mob.SetMobilityModel(
                "ns3::RandomWalk2dMobilityModel",
                "Mode", ns.core.StringValue(cfg.rw_mode),
                "Time", ns.core.StringValue(f"{cfg.rw_time}s"),
                "Distance", ns.core.DoubleValue(cfg.rw_distance),
                "Bounds",
                ns.mobility.RectangleValue(
                    ns.mobility.Rectangle(cfg.mobility_min_x, cfg.mobility_max_x,
                                          cfg.mobility_min_y, cfg.mobility_max_y),
                ),
                "Speed",
                ns.core.StringValue(
                    f"ns3::UniformRandomVariable[Min={cfg.rw_min_speed}|Max={cfg.rw_max_speed}]",
                ),
            )
        elif m == "gauss-markov":
            mob.SetMobilityModel(
                "ns3::GaussMarkovMobilityModel",
                "Bounds",
                ns.mobility.BoxValue(ns.mobility.Box(cfg.mobility_min_x, cfg.mobility_max_x,
                                                     cfg.mobility_min_y, cfg.mobility_max_y,
                                                     0.0, 0.0)),
                "Alpha", ns.core.DoubleValue(cfg.gm_alpha),
            )
        elif m == "grid":
            mob.SetMobilityModel("ns3::ConstantPositionMobilityModel")
        else:  # constant
            mob.SetMobilityModel("ns3::ConstantPositionMobilityModel")

        mob.Install(nodes)

        if m == "grid":
            for i in range(nodes.GetN()):
                node = nodes.Get(i)
                mm = node.GetObject[ns.mobility.MobilityModel]()
                row = i // cfg.grid_width
                col = i % cfg.grid_width
                if cfg.grid_layout == "ColumnFirst":
                    row = i % cfg.grid_width
                    col = i // cfg.grid_width
                x = cfg.grid_min_x + col * cfg.grid_delta_x
                y = cfg.grid_min_y + row * cfg.grid_delta_y
                if mm:
                    mm.SetPosition(ns.core.Vector(x, y, 0.0))

    # -------------------------------------------------------------- routing
    @staticmethod
    def _install_routing(ns: Any, cfg: SimConfig, nodes: Any) -> None:
        no_ip_set = set(cfg.no_ip_node_indices or [])
        stack = ns.internet.InternetStackHelper()
        proto = cfg.routing_protocol
        if proto == "aodv":
            aodv = ns.aodv.AodvHelper()
            aodv.Set("HelloInterval", ns.core.TimeValue(ns.core.Seconds(cfg.aodv_hello_interval)))
            aodv.Set("RreqRetries", ns.core.UintegerValue(cfg.aodv_rreq_retries))
            aodv.Set("ActiveRouteTimeout",
                     ns.core.TimeValue(ns.core.Seconds(cfg.aodv_active_route_timeout)))
            aodv.Set("DeletePeriod",
                     ns.core.TimeValue(ns.core.Seconds(cfg.aodv_delete_period)))
            aodv.Set("NetDiameter", ns.core.UintegerValue(cfg.aodv_net_diameter))
            aodv.Set("EnableHello", ns.core.BooleanValue(cfg.aodv_enable_hello))
            stack.SetRoutingHelper(aodv)
        elif proto == "olsr":
            olsr = ns.olsr.OlsrHelper()
            olsr.Set("HelloInterval", ns.core.TimeValue(ns.core.Seconds(cfg.olsr_hello_interval)))
            olsr.Set("TcInterval", ns.core.TimeValue(ns.core.Seconds(cfg.olsr_tc_interval)))
            olsr.Set("Willingness", ns.core.UintegerValue(cfg.olsr_willingness))
            stack.SetRoutingHelper(olsr)
        elif proto == "dsdv":
            dsdv = ns.dsdv.DsdvHelper()
            dsdv.Set("PeriodicUpdateInterval",
                     ns.core.TimeValue(ns.core.Seconds(cfg.dsdv_periodic_update_interval)))
            dsdv.Set("SettlingTime",
                     ns.core.TimeValue(ns.core.Seconds(cfg.dsdv_settling_time)))
            stack.SetRoutingHelper(dsdv)
        elif proto == "dsr":
            if not no_ip_set:
                stack.Install(nodes)
                dsr_helper = ns.dsr.DsrHelper()
                dsr_main = ns.dsr.DsrMainHelper()
                dsr_main.Install(dsr_helper, nodes)
                return
        # else "none": IP stack with default static routing only

        # Install stack per-node, skipping no-ip nodes
        for i in range(nodes.GetN()):
            if i in no_ip_set:
                continue
            stack.Install(nodes.Get(i))

    # ------------------------------------------------- dynamic control
    def _inject_command(self, fn: Callable[[], None]) -> dict[str, Any]:
        """将命令闭包放入队列，同步等待执行结果返回。

        命令由 C++ Runtime 在 ns-3 仿真线程中执行。
        最多等待 5 秒；超时返回失败。
        """
        if not self.running:
            return {"applied": False, "reason": "simulator is not running"}
        result: dict[str, Any] = {}
        cancelled = threading.Event()
        done_event = threading.Event()

        def _wrapped():
            if cancelled.is_set():
                return
            try:
                fn()
                result["ok"] = True
            except Exception as e:
                result["ok"] = False
                result["error"] = f"{type(e).__name__}: {e}"
            finally:
                done_event.set()

        try:
            self._command_queue.put_nowait(_wrapped)
        except queue.Full:
            return {"applied": False, "reason": "command queue is full"}

        if not done_event.wait(timeout=5.0):
            cancelled.set()
            return {"applied": False, "reason": "command execution timeout (simulation thread not responding)"}

        if not result.get("ok"):
            return {"applied": False, "reason": result.get("error", "unknown execution error")}

        return {"applied": True}

    def _get_node_phy(self, node_id: int) -> tuple[Any, str | None]:
        """获取指定节点的 WifiPhy（mesh 模式下的 MeshPointDevice）。

        首次成功后会缓存结果，避免后续动态命令时的重复四级回退。
        返回 (phy, error_message) 二元组。error_message 为 None 表示成功。
        """
        # 1. 查缓存
        cached = self._phy_cache.get(node_id)
        if cached is not None:
            return cached, None

        ns = self._ns
        if ns is None or self._wifi_devices is None:
            return None, "ns or wifi_devices not ready"

        device = self._wifi_devices.Get(node_id)

        # 方法1: 直接尝试 GetPhy
        try:
            phy = device.GetPhy()
            if phy is not None:
                self._phy_cache[node_id] = phy
                return phy, None
        except (AttributeError, TypeError):
            pass

        # 方法2: 通过 GetObject 转换为 WifiNetDevice
        try:
            wifi_dev = device.GetObject[ns.wifi.WifiNetDevice]()
            if wifi_dev is not None:
                phy = wifi_dev.GetPhy()
                if phy is not None:
                    self._phy_cache[node_id] = phy
                    return phy, None
        except Exception:
            pass

        # 方法3: MeshPointDevice - 获取第一个底层接口
        try:
            mesh_dev = device.GetObject[ns.mesh.MeshPointDevice]()
            if mesh_dev is not None:
                if hasattr(mesh_dev, "GetInterfaces"):
                    try:
                        interfaces = mesh_dev.GetInterfaces()
                        if interfaces.GetN() > 0:
                            iface = interfaces.Get(0)
                            wifi_dev = iface.GetObject[ns.wifi.WifiNetDevice]()
                            if wifi_dev is not None:
                                phy = wifi_dev.GetPhy()
                                if phy is not None:
                                    self._phy_cache[node_id] = phy
                                    return phy, None
                    except Exception:
                        pass
        except Exception:
            pass

        # 方法4: 直接遍历节点上所有 NetDevice，寻找 WifiNetDevice
        try:
            if self._nodes_container is not None:
                node = self._nodes_container.Get(node_id)
                n_devs = node.GetNDevices()
                for i in range(n_devs):
                    dev = node.GetDevice(i)
                    try:
                        wifi_dev = dev.GetObject[ns.wifi.WifiNetDevice]()
                        if wifi_dev is not None:
                            phy = wifi_dev.GetPhy()
                            if phy is not None:
                                self._phy_cache[node_id] = phy
                                return phy, None
                    except Exception:
                        pass
        except Exception:
            pass

        dev_name = ""
        try:
            dev_name = str(device.GetInstanceTypeId().GetName())
        except Exception:
            pass
        return None, f"unable to get PHY from device (type: {dev_name or 'unknown'})"

    def set_node_position(self, node_id: int, x: float, y: float, z: float = 0.0) -> dict[str, Any]:
        """将节点位置跃迁到指定坐标（线程安全）。

        仅调用现有 MobilityModel 的 SetPosition，不替换对象，
        避免与 Simulator::Run() 线程发生 race。
        """
        if node_id < 0 or node_id >= self.config.n_nodes:
            return {"applied": False, "reason": "node_id out of range"}

        if not all(math.isfinite(v) for v in (x, y, z)):
            return {"applied": False, "reason": "position must be finite"}

        def _do():
            ns = self._ns
            if ns is None or self._nodes_container is None:
                raise RuntimeError("ns or nodes_container not ready")
            node = self._nodes_container.Get(node_id)
            mm = node.GetObject[ns.mobility.MobilityModel]()
            if not mm:
                raise RuntimeError("mobility model not found on node")
            mm.SetPosition(ns.core.Vector(x, y, z))
            with self._lock:
                self._env_state.positions[node_id] = {"x": float(x), "y": float(y), "z": float(z)}
                nr = self._nodes_runtime.setdefault(node_id, NodeRuntime(id=node_id))
                nr.x = float(x)
                nr.y = float(y)
            log.info("node-%d position set to (%.1f, %.1f, %.1f)", node_id, x, y, z)

        return self._inject_command(_do)

    def set_tx_power(self, node_id: int, dbm: float) -> dict[str, Any]:
        """修改指定节点的发射功率（线程安全）。"""
        if node_id < 0 or node_id >= self.config.n_nodes:
            return {"applied": False, "reason": "node_id out of range"}

        if not math.isfinite(dbm) or not -200 <= dbm <= 100:
            return {"applied": False, "reason": "invalid dBm value"}

        def _do():
            ns = self._ns
            if ns is None or self._wifi_devices is None:
                raise RuntimeError("ns or wifi_devices not ready")

            phy, err = self._get_node_phy(node_id)
            if err:
                raise RuntimeError(err)

            phy.SetAttribute("TxPowerStart", ns.core.DoubleValue(dbm))
            phy.SetAttribute("TxPowerEnd", ns.core.DoubleValue(dbm))
            with self._lock:
                self._env_state.tx_power[node_id] = float(dbm)
            log.info("node-%d tx power set to %.1f dBm", node_id, dbm)

        return self._inject_command(_do)

    def set_rx_sensitivity(self, node_id: int, dbm: float) -> dict[str, Any]:
        """修改指定节点的接收灵敏度（线程安全）。"""
        if node_id < 0 or node_id >= self.config.n_nodes:
            return {"applied": False, "reason": "node_id out of range"}

        if not math.isfinite(dbm) or not -200 <= dbm <= 100:
            return {"applied": False, "reason": "invalid dBm value"}

        def _do():
            ns = self._ns
            if ns is None or self._wifi_devices is None:
                raise RuntimeError("ns or wifi_devices not ready")

            phy, err = self._get_node_phy(node_id)
            if err:
                raise RuntimeError(err)

            phy.SetAttribute("RxSensitivity", ns.core.DoubleValue(dbm))
            with self._lock:
                self._env_state.rx_sensitivity[node_id] = float(dbm)
            log.info("node-%d rx sensitivity set to %.1f dBm", node_id, dbm)

        return self._inject_command(_do)

    def set_path_loss_exponent(self, exponent: float) -> dict[str, Any]:
        """修改全局路径损耗指数（仅 LogDistance 模型，线程安全）。

        必须先校验 propagation_loss_model 是否为 LogDistance：其它模型(如 Friis)
        没有 Exponent 属性,SetAttribute 会触发 ns-3 NS_FATAL_ERROR → std::terminate,
        Python try/except 无法捕获,uvicorn 会被 docker 重启。
        """
        if not math.isfinite(exponent) or exponent <= 0:
            return {"applied": False, "reason": "exponent must be positive and finite"}
        model = self._propagation_loss_model
        if model is None:
            return {"applied": False, "reason": "propagation loss model not ready"}
        model_name = self.config.path_loss_model
        if model_name != "LogDistance":
            return {"applied": False, "reason": f"current model is {model_name}, not LogDistance"}

        def _do():
            self._propagation_loss_model.SetAttribute(
                "Exponent", self._ns.core.DoubleValue(exponent)
            )
            with self._lock:
                self._env_state.path_loss_exponent = float(exponent)
            log.info("path loss exponent set to %.2f", exponent)

        return self._inject_command(_do)

    def set_frequency(self, mhz: int) -> dict[str, Any]:
        """WiFi 频点同步 PHY；UHF 仅改变损耗预算，保留明确的代理载波。"""
        if mhz <= 0:
            return {"applied": False, "reason": "frequency must be positive"}
        with self._lock:
            width = self._env_state.channel_width_mhz
        standard = self.config.standard
        uhf = mhz < 1000
        if not uhf:
            if 2400 <= mhz <= 2500:
                if standard in {"80211a", "80211ac"}:
                    return {"applied": False, "reason": f"{standard} does not support 2.4 GHz"}
                standard = "80211ax-2.4GHz" if "80211ax" in standard else "80211n-2.4GHz"
            elif 4900 <= mhz <= 5900:
                if standard not in {"80211a", "80211ac"}:
                    standard = "80211ax-5GHz" if "80211ax" in standard else "80211n-5GHz"
            else:
                return {"applied": False, "reason": "not a supported WiFi frequency or UHF budget"}
        try:
            cfg = self.config.merged_with({"frequencyMhz": mhz, "channelWidthMhz": width, "standard": standard})
        except ValueError as exc:
            return {"applied": False, "reason": str(exc)}
        settings = self._channel_settings(cfg)
        if not uhf and settings.startswith("{0,"):
            return {"applied": False, "reason": "frequency is not a legal channel center for the current bandwidth"}
        adjusts_loss = self.config.path_loss_model in {"FreeSpace", "TwoRayGround"}
        if uhf and not adjusts_loss:
            return {"applied": False, "reason": "UHF budget requires FreeSpace or TwoRayGround"}

        def _do() -> None:
            if not uhf:
                for i in range(cfg.n_nodes):
                    phy, error = self._get_node_phy(i)
                    if error:
                        raise RuntimeError(error)
                    phy.SetAttribute("ChannelSettings", self._ns.core.StringValue(settings))
                    if self.config.rate_control == "Constant":
                        manager = phy.GetDevice().GetRemoteStationManager()
                        control = "ErpOfdmRate6Mbps" if "2.4GHz" in standard else "OfdmRate6Mbps"
                        manager.SetAttribute("ControlMode", self._ns.core.StringValue(control))
            if adjusts_loss:
                self._propagation_loss_model.SetAttribute("Frequency", self._ns.core.DoubleValue(float(mhz) * 1e6))
            with self._lock:
                self._env_state.frequency_mhz = mhz
        result = self._inject_command(_do)
        if result.get("applied") and uhf:
            result["note"] = "UHF propagation budget only; PHY uses a WiFi proxy carrier"
        return result

    def set_channel_width(self, mhz: int) -> dict[str, Any]:
        """通过可写的 ChannelSettings 在仿真线程切换信道宽度。"""
        try:
            with self._lock:
                frequency = self._env_state.frequency_mhz
            standard = self.config.standard
            if "80211n" in standard or "80211ax" in standard:
                standard = standard.split("-")[0] + ("-5GHz" if frequency >= 4900 else "-2.4GHz")
            cfg = self.config.merged_with({"channelWidthMhz": mhz, "frequencyMhz": frequency, "standard": standard})
        except ValueError as exc:
            return {"applied": False, "reason": str(exc)}

        def _do() -> None:
            for i in range(cfg.n_nodes):
                phy, error = self._get_node_phy(i)
                if error:
                    raise RuntimeError(error)
                phy.SetAttribute("ChannelSettings", self._ns.core.StringValue(self._channel_settings(cfg)))
            with self._lock:
                self._env_state.channel_width_mhz = mhz
        return self._inject_command(_do)

    def set_range_target(self, meters: float) -> dict[str, Any]:
        """修改全局最大通信距离（线程安全）。

        优先调整叠加的 Range 模型（所有主模型都叠加了 Range 截断）；
        若叠加模型不存在，回退到直接调整主传播损耗模型（仅 Range 模型本身支持）。
        """
        if not math.isfinite(meters) or meters <= 0:
            return {"applied": False, "reason": "range must be positive and finite"}
        # 1. 优先使用叠加的 Range 模型（所有场景都可用）
        range_model = self._range_model
        if range_model is not None:
            def _do():
                range_model.SetAttribute("MaxRange", self._ns.core.DoubleValue(meters))
                with self._lock:
                    self._env_state.range_target_m = float(meters)
                log.info("range target (overlay) set to %.0f m", meters)
            return self._inject_command(_do)

        # 2. 回退：直接调整主传播损耗模型（仅当主模型本身就是 Range 时有效）
        model = self._propagation_loss_model
        if model is None:
            return {"applied": False, "reason": "propagation loss model not ready"}
        model_name = self.config.path_loss_model
        if model_name != "Range":
            return {"applied": False, "reason": f"current model is {model_name}, not Range"}

        def _do():
            self._propagation_loss_model.SetAttribute(
                "MaxRange", self._ns.core.DoubleValue(meters)
            )
            with self._lock:
                self._env_state.range_target_m = float(meters)
            log.info("range target set to %.0f m", meters)

        return self._inject_command(_do)

    def _simulation_tick(self) -> None:
        """仅由 C++ Runtime 在仿真线程调用，API 只能读复制后的快照。"""
        ns = self._ns
        self._sim_elapsed = ns.core.Simulator.Now().GetSeconds()
        if self._stop_event.is_set():
            ns.core.Simulator.Stop()
            return
        try:
            # 1. 排空命令队列
            while not self._command_queue.empty():
                try:
                    cmd = self._command_queue.get_nowait()
                    cmd()
                except Exception as e:  # noqa: BLE001
                    log.warning("dynamic command failed: %s", e)
            phy, _ = self._get_node_phy(0)
            if phy is not None:
                with self._lock:
                    self._env_state.phy_frequency_mhz = float(phy.GetFrequency())
            # 2. 刷新位置快照 + 邻居（在锁内，快速操作）
            with self._lock:
                n_nodes = self.config.n_nodes
                # 2a. 位置
                for i in range(n_nodes):
                    node = self._nodes_container.Get(i)
                    # ns-3.47 + cppyy：模板方法 GetObject 用方括号语法
                    mm = node.GetObject[ns.mobility.MobilityModel]()
                    if mm:
                        pos = mm.GetPosition()
                        nr = self._nodes_runtime.setdefault(i, NodeRuntime(id=i))
                        nr.x = float(pos.x)
                        nr.y = float(pos.y)
                        self._env_state.positions[i] = {"x": float(pos.x), "y": float(pos.y), "z": float(pos.z)}
                # 实际已建立的 Mesh peer 链路；AdHoc 无 peer 协议，不伪造连接。
                for i in range(n_nodes):
                    self._nodes_runtime[i].neighbors = list(self._bridge.Neighbors(self._wifi_devices, i))
            # 2c. tap 接口 RX/TX(真实容器流量,FlowMonitor 看不到) —— 文件 I/O 在锁外
            tap_prefix = self.config.tap_prefix
            with self._lock:
                node_ids = list(self._nodes_runtime.keys())
            for i in node_ids:
                try:
                    with open(f"/sys/class/net/{tap_prefix}{i}/statistics/rx_packets") as fh:
                        rx = int(fh.read().strip())
                    with open(f"/sys/class/net/{tap_prefix}{i}/statistics/tx_packets") as fh:
                        tx = int(fh.read().strip())
                    with self._lock:
                        nr = self._nodes_runtime.get(i)
                        if nr:
                            nr.rx_packets = rx
                            nr.tx_packets = tx
                except Exception:  # noqa: BLE001
                    pass
            # 2d. 在仿真线程读取 TAP 采集器或内部 IP 流的 FlowMonitor。
            if self._tap_telemetry is not None:
                self._tap_telemetry.poll()
                with self._lock:
                    self._flows_runtime = {f["flow_id"]: FlowRuntime(**f) for f in self._tap_telemetry.snapshot()}
            if self._fm is not None and self.config.traffic_mode != "tap":
                try:
                    self._fm.CheckForLostPackets()
                    stats = self._fm.GetFlowStats()
                    classifier = self._classifier
                    # 在锁外构建新数据，锁内仅做交换
                    flows_batch: dict[int, FlowRuntime] = {}
                    seen: set[int] = set()
                    for fid, st in stats:
                        seen.add(fid)
                        source, destination = "", ""
                        if classifier:
                            ft = classifier.FindFlow(fid)
                            source = str(ft.sourceAddress)
                            destination = str(ft.destinationAddress)
                        elapsed = max(
                            (st.timeLastRxPacket.GetSeconds()
                             - st.timeFirstTxPacket.GetSeconds()),
                            1e-3,  # 最小 1ms 避免溢出
                        )
                        throughput_mbps = (st.rxBytes * 8.0) / elapsed / 1e6
                        avg_delay = (st.delaySum.GetSeconds() / st.rxPackets) \
                            if st.rxPackets else 0.0
                        flows_batch[fid] = FlowRuntime(
                            flow_id=fid,
                            source=source,
                            destination=destination,
                            tx_packets=st.txPackets,
                            rx_packets=st.rxPackets,
                            lost_packets=st.lostPackets,
                            avg_delay=avg_delay * 1000.0,
                            throughput=throughput_mbps,
                        )
                    # 增量合并到共享存储
                    with self._lock:
                        for fid, fr in flows_batch.items():
                            existing = self._flows_runtime.get(fid)
                            if existing is not None:
                                existing.source = fr.source
                                existing.destination = fr.destination
                                existing.tx_packets = fr.tx_packets
                                existing.rx_packets = fr.rx_packets
                                existing.lost_packets = fr.lost_packets
                                existing.avg_delay = fr.avg_delay
                                existing.throughput = fr.throughput
                            else:
                                self._flows_runtime[fid] = fr
                        # 删除已不存在的流
                        for dead_fid in list(self._flows_runtime):
                            if dead_fid not in seen:
                                del self._flows_runtime[dead_fid]
                except Exception as e:  # noqa: BLE001
                    log.warning("flow monitor poll failed: %s", e)
        except Exception as e:  # noqa: BLE001
            log.warning("simulation tick failed: %s", e)
