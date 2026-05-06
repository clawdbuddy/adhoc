"""ns-3 Python 仿真运行器 —— scratch/manet-30nodes.cc 的移植版。

线程模型：
    ns-3 仿真器在独立守护线程中启动；FastAPI 在主 asyncio 循环中运行。
    仿真线程拥有 ns-3 全局状态。

TapBridge 模式（UseBridge）：每个 ns-3 WifiNetDevice 在 L2 上与宿主 TAP（tap-{i}）桥接。
对应容器的用户流量经过 ns-3 的 AdHoc/Mesh PHY/MAC 信道模型。
在 UseBridge 模式下，ns-3 不对用户载荷做 IP 路由 —— L3 的 `routingProtocol` 设置
仅安装在 ns-3 协议栈上，且只作用于 ns-3 自身生成的报文（控制面）。
这与旧版 C++ 实现一致；多跳用户载荷路由必须由容器内的软件处理。
"""
from __future__ import annotations

import logging
import math
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .config import SimConfig

log = logging.getLogger(__name__)


class _CppyyModuleProxy:
    """让 cppyy 的扁平命名空间也能支持 `ns.core.Simulator` 这种子模块写法。"""

    def __init__(self, ns):
        self._ns = ns

    def __getattr__(self, name):
        return getattr(self._ns, name)


class _CppyyNsWrapper:
    """包装 cppyy.gbl.ns3，优先扁平访问，缺失时回退到子模块代理。"""

    def __init__(self, ns):
        self._ns = ns
        self._proxies: dict[str, Any] = {}

    def __getattr__(self, name):
        if hasattr(self._ns, name):
            return getattr(self._ns, name)
        if name not in self._proxies:
            self._proxies[name] = _CppyyModuleProxy(self._ns)
        return self._proxies[name]


def _import_ns():
    """惰性导入 ns-3 绑定；将 ImportError 推迟到仿真真正启动时。

    本工程有两条部署路径,Python 绑定机制不同,这里 try/except 双路径兼容:

    1) cppyy 路线（NS-3.40+ / NS-3.47 Docker 镜像）:
       `from ns import ns` 拿到 cppyy 暴露的统一 C++ 命名空间对象;
       所有类都直接挂在 ns3 命名空间下（如 ns.Simulator）。
       用 _CppyyNsWrapper 包装后，现有代码里的 `ns.core.Simulator`
       等子模块写法无需改动。
    2) pybindgen 路线（Docker 镜像内 NS-3.36 源码编译）:
       build 出来的 `ns/__init__.py` 是空文件,必须为每个用到的子模块
       显式 `import ns.X`,才会把它注入到 `ns` 包命名空间下;
       完成后 `ns.core.Simulator` 这种统一访问才不会 AttributeError。
    """
    try:
        from ns import ns  # noqa: WPS433 — cppyy 统一命名空间
        return _CppyyNsWrapper(ns)
    except ImportError:
        import ns  # noqa: WPS433
        import ns.core  # noqa: F401, WPS433
        import ns.network  # noqa: F401, WPS433
        import ns.internet  # noqa: F401, WPS433
        import ns.wifi  # noqa: F401, WPS433
        import ns.mobility  # noqa: F401, WPS433
        import ns.tap_bridge  # noqa: F401, WPS433
        import ns.flow_monitor  # noqa: F401, WPS433
        import ns.propagation  # noqa: F401, WPS433
        import ns.spectrum  # noqa: F401, WPS433
        import ns.aodv  # noqa: F401, WPS433
        import ns.olsr  # noqa: F401, WPS433
        import ns.dsdv  # noqa: F401, WPS433
        import ns.dsr  # noqa: F401, WPS433
        import ns.mesh  # noqa: F401, WPS433
        return ns


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
    channel_width_mhz: int = 20
    range_target_m: float = 4000.0


class SimRunner:
    """封装一次 ns-3 仿真生命周期。"""

    def __init__(self, config: SimConfig):
        self.config = config
        self._thread: Optional[threading.Thread] = None
        self._wall_pacer_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._nodes_runtime: dict[int, NodeRuntime] = {}
        self._flows_runtime: dict[int, FlowRuntime] = {}
        self._ns: Any = None
        self._fm: Any = None
        self._running = False
        self._start_time: float | None = None
        self._error: str | None = None
        # 动态控制：线程安全命令队列 + ns-3 对象引用
        self._command_queue: queue.Queue = queue.Queue()
        self._nodes_container: Any = None
        self._wifi_devices: Any = None
        self._spectrum_channel: Any = None
        self._propagation_loss_model: Any = None
        self._range_model: Any = None
        self._phy_model_type: str = ""
        # 实际使用的 MAC 模式;若 mesh 因 pybindgen 绑定缺失而 fallback,这里会变成 "adhoc"
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
        # 动态参数当前值（供遥测回传前端）
        self._env_state = EnvState(
            tx_power=[float(config.tx_power_start)] * config.n_nodes,
            rx_sensitivity=[float(config.rx_sensitivity)] * config.n_nodes,
            positions=[{"x": 0.0, "y": 0.0, "z": 0.0} for _ in range(config.n_nodes)],
            path_loss_exponent=float(config.path_loss_exponent),
            frequency_mhz=int(config.frequency_mhz),
            channel_width_mhz=int(config.channel_width_mhz),
            range_target_m=float(config.range_target_m),
        )

    # ---------------------------------------------------- public lifecycle
    def start(self) -> None:
        if self._running:
            raise RuntimeError("simulator already running")
        self._stop_event.clear()
        self._error = None
        self._thread = threading.Thread(target=self._run, name="ns3-sim", daemon=True)
        self._thread.start()
        # Block briefly so an immediate import error surfaces to the caller.
        self._thread.join(timeout=2.0)
        if not self._thread.is_alive() and self._error:
            raise RuntimeError(f"simulator failed to start: {self._error}")
        self._running = self._thread.is_alive()
        if self._running:
            self._start_time = time.time()
            # 启动 wall-time 触发的命令 drain + 位置快照线程,绕开 sim 时钟
            # (实测 BestEffort + 10 节点 SpectrumWifiPhy 跑到 1/24x,sim-time
            # 调度的命令落地会拖到 20s+,前端用户体验不可接受)
            self._wall_pacer_thread = threading.Thread(
                target=self._wall_pacer_loop, name="ns3-wall-pacer", daemon=True,
            )
            self._wall_pacer_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if not self._running:
            return
        try:
            ns = self._ns
            if ns is not None:
                ns.core.Simulator.Stop()  # schedules an immediate stop
        except Exception as e:  # noqa: BLE001
            log.warning("Simulator.Stop() raised: %s", e)
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        if self._wall_pacer_thread:
            self._wall_pacer_thread.join(timeout=2.0)
            self._wall_pacer_thread = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running and (self._thread is not None and self._thread.is_alive())

    @property
    def elapsed(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    @property
    def mac_mode_actual(self) -> str:
        """实际生效的 MAC 模式;若 cfg.mac_mode='mesh' 但绑定缺失,返回 'adhoc-fallback'。"""
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
                channel_width_mhz=self._env_state.channel_width_mhz,
                range_target_m=self._env_state.range_target_m,
            )

    def find_path(self, src_id: int, dst_id: int) -> list[int] | None:
        """基于当前邻居图（位置 + range_target_m）做 BFS,返回 src→dst 的最少跳数路径。

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
                    self._ns.core.Simulator.Destroy()
            except Exception:  # noqa: BLE001, S110
                pass
            self._running = False

    # --------------------------------------------------- ns-3 build steps
    def _build_and_run(self, ns: Any) -> None:
        cfg = self.config

        # 1. BestEffort simulator (非实时，CPU 全速推进，验证纯 ns-3 内部吞吐量上限)
        # 注：RealtimeSimulatorImpl 受 wall-time 约束，TAP 桥接下带宽上限约 1.5-2Mbps。
        # 切回默认 BestEffort 以验证理论带宽，但 sim-time 与 wall-time 不同步，
        # iperf3 等 wall-time 工具的统计口径会失真，需以 ns-3 FlowMonitor 为准。
        # ns.core.GlobalValue.Bind(
        #     "SimulatorImplementationType",
        #     ns.core.StringValue("ns3::RealtimeSimulatorImpl"),
        # )
        # ns.core.Config.Set(
        #     "ns3::RealtimeSimulatorImpl::SynchronizationMode",
        #     ns.core.StringValue("HardLimit"),
        # )
        ns.core.GlobalValue.Bind("ChecksumEnabled", ns.core.BooleanValue(True))
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
            phy = self._build_yans_phy(ns, cfg)
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

        # 5. MAC：mac_mode="mesh" 启用 802.11s + HWMP，由 ns-3 mesh 模块在 L2
        #    层完成多跳转发；mac_mode="adhoc" 维持原 AdhocWifiMac（无多跳，由
        #    上层路由协议或容器内软件负责）。
        if cfg.mac_mode == "mesh":
            devices = self._install_mesh(ns, cfg, phy, nodes)
        else:
            mac = ns.wifi.WifiMacHelper()
            mac.SetType(
                "ns3::AdhocWifiMac",
                "Ssid", ns.wifi.SsidValue(ns.wifi.Ssid(cfg.ssid)),
                "QosSupported", ns.core.BooleanValue(True),
            )
            devices = wifi.Install(phy, mac, nodes)
            self._mac_mode_actual = "adhoc"

        # 6. Mobility
        self._install_mobility(ns, cfg, nodes)

        # 7. Internet stack + routing
        self._install_routing(ns, cfg, nodes)

        # 保存 ns-3 对象引用供动态控制使用
        self._nodes_container = nodes
        self._wifi_devices = devices

        # 8. IP addresses (192.168.100.10 + i, /24)
        ipv4 = ns.internet.Ipv4AddressHelper()
        ipv4.SetBase(
            ns.network.Ipv4Address("192.168.100.0"),
            ns.network.Ipv4Mask("255.255.255.0"),
            ns.network.Ipv4Address("0.0.0.10"),
        )
        ipv4.Assign(devices)

        # 9. TapBridge — bind each WifiNetDevice to tap-{i} in UseBridge mode
        tb_helper = ns.tap_bridge.TapBridgeHelper()
        tb_helper.SetAttribute("Mode", ns.core.StringValue(cfg.tap_mode))
        for i in range(cfg.n_nodes):
            tap_name = f"{cfg.tap_prefix}{i}"
            tb_helper.SetAttribute("DeviceName", ns.core.StringValue(tap_name))
            tb_helper.Install(nodes.Get(i), devices.Get(i))
            log.info("TapBridge node-%d ↔ %s", i, tap_name)

        # 10. FlowMonitor
        if cfg.flow_monitor:
            fm_helper = ns.flow_monitor.FlowMonitorHelper()
            self._fm = fm_helper.InstallAll()

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

        # 13. Schedule the in-sim periodic snapshot updater (1 Hz simulator time)
        self._schedule_periodic(ns, nodes, period_s=1.0)

        # 14. Run!
        # 不再预设自动停止时间；仿真持续运行直到用户手动调用 stop()。
        # simulation_time 仅作为配置参考，不再调度 Simulator.Stop()。
        log.info("Simulator.Run() begin (manual stop mode)")
        ns.core.Simulator.Run()
        log.info("Simulator.Run() end")

    # -------------------------------------------------- channel / propagation
    def _build_yans_phy(self, ns: Any, cfg: SimConfig) -> Any:
        """YansWifiChannel + YansWifiPhyHelper（旧路径，向后兼容）。"""
        ch = ns.wifi.YansWifiChannelHelper()
        if cfg.propagation_delay == "ConstantSpeed":
            ch.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel")
        else:
            ch.SetPropagationDelay("ns3::RandomPropagationDelayModel")
        self._add_yans_path_loss(ns, ch, cfg)
        if cfg.enable_fading:
            self._add_yans_fading(ns, ch, cfg)
        # 叠加 Range 硬截断（Yans 路径）
        if cfg.range_target_m > 0:
            ch.AddPropagationLoss(
                "ns3::RangePropagationLossModel",
                "MaxRange", ns.core.DoubleValue(cfg.range_target_m),
            )
        phy = ns.wifi.YansWifiPhyHelper()
        phy.SetChannel(ch.Create())
        phy.Set("ChannelWidth", ns.core.UintegerValue(cfg.channel_width_mhz))
        return phy

    def _build_spectrum_phy(self, ns: Any, cfg: SimConfig) -> tuple[Any, Any, Any | None]:
        """SpectrumWifiPhy + MultiModelSpectrumChannel。

        Friis 路径损耗的 Frequency 属性被钉到 cfg.frequency_mhz（默认 590 MHz），
        使距离-衰减曲线与 UHF 物理一致；ns-3 内部 802.11a 5 GHz 的频道号只是
        载波/调制配置，不影响传播预算。

        返回 (phy_helper, spectrum_channel, path_loss_model) 三元组，供动态控制保存引用。
        """
        spec_chan = ns.spectrum.MultiModelSpectrumChannel()

        # 路径损耗：FreeSpace 走 Friis（带 frequency_mhz）；其余走 LogDistance/Two-Ray/...
        loss = self._make_path_loss_object(ns, cfg)
        if loss is not None:
            spec_chan.AddPropagationLossModel(loss)

        # 叠加 Range 硬截断：无论主模型是什么，都按 range_target_m 做最大距离限制。
        # 这样 FreeSpace/LogDistance 模型下也能通过 set_range_target 动态控制通信距离。
        if cfg.range_target_m > 0:
            range_loss = ns.propagation.RangePropagationLossModel()
            range_loss.SetAttribute("MaxRange", ns.core.DoubleValue(cfg.range_target_m))
            spec_chan.AddPropagationLossModel(range_loss)
            self._range_model = range_loss
        else:
            self._range_model = None

        if cfg.enable_fading and cfg.fading_model == "Nakagami":
            nak = ns.propagation.NakagamiPropagationLossModel()
            nak.SetAttribute("m0", ns.core.DoubleValue(cfg.nakagami_m0))
            nak.SetAttribute("m1", ns.core.DoubleValue(cfg.nakagami_m1))
            nak.SetAttribute("m2", ns.core.DoubleValue(cfg.nakagami_m2))
            nak.SetAttribute("Distance1", ns.core.DoubleValue(cfg.nakagami_d1))
            nak.SetAttribute("Distance2", ns.core.DoubleValue(cfg.nakagami_d2))
            spec_chan.AddPropagationLossModel(nak)

        # 传播延迟模型
        if cfg.propagation_delay == "ConstantSpeed":
            delay = ns.propagation.ConstantSpeedPropagationDelayModel()
        else:
            delay = ns.propagation.RandomPropagationDelayModel()
        spec_chan.SetPropagationDelayModel(delay)

        phy = ns.wifi.SpectrumWifiPhyHelper()
        phy.SetChannel(spec_chan)
        phy.Set("ChannelWidth", ns.core.UintegerValue(cfg.channel_width_mhz))
        # 频段表里 590 MHz 不是合法 802.11 频道，因此 SpectrumWifiPhy 内部仍按
        # 默认的 802.11a 5GHz 频道号工作；真实物理频段语义由 Friis 的 Frequency
        # 决定。Logger 里把 cfg.frequency_mhz 打出来便于审计。
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
            m = ns.propagation.FriisPropagationLossModel()
            m.SetAttribute("Frequency", ns.core.DoubleValue(freq_hz))
            m.SetAttribute("MinLoss", ns.core.DoubleValue(0.0))
            return m
        if pl == "LogDistance":
            m = ns.propagation.LogDistancePropagationLossModel()
            m.SetAttribute("Exponent", ns.core.DoubleValue(cfg.path_loss_exponent))
            m.SetAttribute("ReferenceLoss", ns.core.DoubleValue(cfg.path_loss_ref_loss))
            m.SetAttribute("ReferenceDistance", ns.core.DoubleValue(cfg.path_loss_ref_distance))
            return m
        if pl == "TwoRayGround":
            m = ns.propagation.TwoRayGroundPropagationLossModel()
            m.SetAttribute("Frequency", ns.core.DoubleValue(freq_hz))
            return m
        if pl == "ThreeLogDistance":
            return ns.propagation.ThreeLogDistancePropagationLossModel()
        if pl == "Cost231":
            return ns.propagation.Cost231PropagationLossModel()
        if pl == "Range":
            m = ns.propagation.RangePropagationLossModel()
            m.SetAttribute("MaxRange", ns.core.DoubleValue(cfg.range_target_m))
            return m
        return None

    @staticmethod
    def _add_yans_path_loss(ns: Any, ch: Any, cfg: SimConfig) -> None:
        pl = cfg.path_loss_model
        freq_hz = float(cfg.frequency_mhz) * 1e6
        if pl == "LogDistance":
            ch.AddPropagationLoss(
                "ns3::LogDistancePropagationLossModel",
                "Exponent", ns.core.DoubleValue(cfg.path_loss_exponent),
                "ReferenceLoss", ns.core.DoubleValue(cfg.path_loss_ref_loss),
                "ReferenceDistance", ns.core.DoubleValue(cfg.path_loss_ref_distance),
            )
        elif pl == "FreeSpace":
            ch.AddPropagationLoss(
                "ns3::FriisPropagationLossModel",
                "Frequency", ns.core.DoubleValue(freq_hz),
                "MinLoss", ns.core.DoubleValue(0.0),
            )
        elif pl == "TwoRayGround":
            ch.AddPropagationLoss(
                "ns3::TwoRayGroundPropagationLossModel",
                "Frequency", ns.core.DoubleValue(freq_hz),
            )
        elif pl == "ThreeLogDistance":
            ch.AddPropagationLoss("ns3::ThreeLogDistancePropagationLossModel")
        elif pl == "Cost231":
            ch.AddPropagationLoss("ns3::Cost231PropagationLossModel")
        elif pl == "Range":
            ch.AddPropagationLoss(
                "ns3::RangePropagationLossModel",
                "MaxRange", ns.core.DoubleValue(cfg.range_target_m),
            )

    @staticmethod
    def _add_yans_fading(ns: Any, ch: Any, cfg: SimConfig) -> None:
        if cfg.fading_model == "Nakagami":
            ch.AddPropagationLoss(
                "ns3::NakagamiPropagationLossModel",
                "m0", ns.core.DoubleValue(cfg.nakagami_m0),
                "m1", ns.core.DoubleValue(cfg.nakagami_m1),
                "m2", ns.core.DoubleValue(cfg.nakagami_m2),
                "Distance1", ns.core.DoubleValue(cfg.nakagami_d1),
                "Distance2", ns.core.DoubleValue(cfg.nakagami_d2),
            )
        elif cfg.fading_model == "Jakes":
            ch.AddPropagationLoss("ns3::JakesPropagationLossModel")

    # -------------------------------------------------------------- mesh MAC
    def _install_mesh(self, ns: Any, cfg: SimConfig, phy: Any, nodes: Any) -> Any:
        """802.11s mesh + HWMP routing：L2 多跳由 ns-3 mesh 模块原地完成。

        TapBridge UseBridge 仍可使用——整张 mesh 在容器视角下表现为单一 L2
        广播域，距离超出单跳 LOS 的节点之间的报文由 HWMP 路径选择算法自动
        通过中间节点中继。不再需要在容器内运行额外的路由 daemon。

        回退：pybindgen 绑定中 MeshHelper.Install 可能缺失，此时降级为 adhoc。
        """
        mesh_helper = ns.mesh.MeshHelper.Default()
        if not hasattr(mesh_helper, "Install"):
            log.warning(
                "MeshHelper.Install 在 pybindgen 绑定中缺失,降级为 adhoc(L2 多跳由 ns-3 mesh 转发的语义将丢失,跨多跳的容器流量需要容器内额外路由协议)"
            )
            self._mac_mode_actual = "adhoc-fallback"
            mac = ns.wifi.WifiMacHelper()
            mac.SetType(
                "ns3::AdhocWifiMac",
                "Ssid", ns.wifi.SsidValue(ns.wifi.Ssid(cfg.ssid)),
            )
            return ns.wifi.WifiHelper().Install(phy, mac, nodes)

        mesh_helper.SetStackInstaller("ns3::Dot11sStack")
        mesh_helper.SetStandard(self._wifi_standard(ns, cfg.standard))
        # RandomStart：mesh 节点上电后随机抖动（避免同时发 BCN）
        mesh_helper.SetMacType("RandomStart", ns.core.TimeValue(ns.core.Seconds(0.1)))
        # 单接口模式即可——多接口 mesh 主要用于多频段聚合，不在本场景目标内。
        mesh_helper.SetNumberOfInterfaces(1)
        mesh_helper.SetRemoteStationManager(
            "ns3::ConstantRateWifiManager",
            "DataMode", ns.core.StringValue(cfg.data_rate),
            "ControlMode", ns.core.StringValue(cfg.data_rate),
        )
        devices = mesh_helper.Install(phy, nodes)
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
            "80211b": ns.wifi.WIFI_STANDARD_80211b,
            "80211a": ns.wifi.WIFI_STANDARD_80211a,
            "80211g": ns.wifi.WIFI_STANDARD_80211g,
            "80211n-2.4GHz": ns.wifi.WIFI_STANDARD_80211n,
            "80211n-5GHz": ns.wifi.WIFI_STANDARD_80211n,
            "80211ac": ns.wifi.WIFI_STANDARD_80211ac,
            "80211ax-2.4GHz": ns.wifi.WIFI_STANDARD_80211ax,
            "80211ax-5GHz": ns.wifi.WIFI_STANDARD_80211ax,
        }.get(label, ns.wifi.WIFI_STANDARD_80211g)

    @staticmethod
    def _apply_rate_control(ns: Any, wifi: Any, cfg: SimConfig) -> None:
        rc = cfg.rate_control
        if rc == "Constant":
            wifi.SetRemoteStationManager(
                "ns3::ConstantRateWifiManager",
                "DataMode", ns.core.StringValue(cfg.data_rate),
                "ControlMode", ns.core.StringValue(cfg.data_rate),
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
            wifi.SetRemoteStationManager("ns3::MinstrelWifiManager")
        else:
            wifi.SetRemoteStationManager("ns3::ArfWifiManager")

    # -------------------------------------------------------------- mobility
    @staticmethod
    def _install_mobility(ns: Any, cfg: SimConfig, nodes: Any) -> None:
        mob = ns.mobility.MobilityHelper()
        # Position allocator: uniform in the configured area.
        pos = ns.mobility.RandomBoxPositionAllocator()
        x_var = ns.core.UniformRandomVariable()
        x_var.SetAttribute("Min", ns.core.DoubleValue(cfg.mobility_min_x))
        x_var.SetAttribute("Max", ns.core.DoubleValue(cfg.mobility_max_x))
        y_var = ns.core.UniformRandomVariable()
        y_var.SetAttribute("Min", ns.core.DoubleValue(cfg.mobility_min_y))
        y_var.SetAttribute("Max", ns.core.DoubleValue(cfg.mobility_max_y))
        z_var = ns.core.ConstantRandomVariable()
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
            grid_alloc = ns.mobility.GridPositionAllocator()
            grid_alloc.SetMinX(cfg.grid_min_x)
            grid_alloc.SetMinY(cfg.grid_min_y)
            grid_alloc.SetDeltaX(cfg.grid_delta_x)
            grid_alloc.SetDeltaY(cfg.grid_delta_y)
            grid_alloc.SetN(cfg.grid_width)
            mob.SetPositionAllocator(grid_alloc)
            mob.SetMobilityModel("ns3::ConstantPositionMobilityModel")
        else:  # constant
            mob.SetMobilityModel("ns3::ConstantPositionMobilityModel")

        mob.Install(nodes)

    # -------------------------------------------------------------- routing
    @staticmethod
    def _install_routing(ns: Any, cfg: SimConfig, nodes: Any) -> None:
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
            # DSR requires a separate dsrMain.Install; follow that pattern strictly.
            stack.Install(nodes)
            dsr_helper = ns.dsr.DsrHelper()
            dsr_main = ns.dsr.DsrMainHelper()
            dsr_main.Install(dsr_helper, nodes)
            return  # stack already installed
        # else "none": IP stack with default static routing only

        stack.Install(nodes)

    # ------------------------------------------------- dynamic control
    def _inject_command(self, fn: Callable[[], None]) -> dict[str, Any]:
        """将命令闭包放入队列，同步等待执行结果返回。

        命令由 _wall_pacer_loop 在 wall-time 线程中执行。
        最多等待 5 秒；超时返回失败。
        """
        result: dict[str, Any] = {}
        done_event = threading.Event()

        def _wrapped():
            try:
                fn()
                result["ok"] = True
            except Exception as e:
                result["ok"] = False
                result["error"] = f"{type(e).__name__}: {e}"
            finally:
                done_event.set()

        self._command_queue.put(_wrapped)

        if not done_event.wait(timeout=5.0):
            return {"applied": False, "reason": "command execution timeout (wall pacer not responding)"}

        if not result.get("ok"):
            return {"applied": False, "reason": result.get("error", "unknown execution error")}

        return {"applied": True}

    def _get_node_phy(self, node_id: int) -> tuple[Any, str | None]:
        """获取指定节点的 WifiPhy，处理 adhoc 和 mesh 两种模式。

        返回 (phy, error_message) 二元组。error_message 为 None 表示成功。
        """
        ns = self._ns
        if ns is None or self._wifi_devices is None:
            return None, "ns or wifi_devices not ready"

        device = self._wifi_devices.Get(node_id)

        # 方法1: 直接尝试 GetPhy (adhoc 模式下 device 可能是 WifiNetDevice)
        try:
            phy = device.GetPhy()
            if phy is not None:
                return phy, None
        except (AttributeError, TypeError):
            pass

        # 方法2: 通过 GetObject 转换为 WifiNetDevice
        try:
            type_id = ns.wifi.WifiNetDevice.GetTypeId()
            wifi_dev = device.GetObject(type_id)
            if wifi_dev is not None:
                phy = wifi_dev.GetPhy()
                if phy is not None:
                    return phy, None
        except Exception:
            pass

        # 方法3: MeshPointDevice - 获取第一个底层接口
        try:
            type_id = ns.mesh.MeshPointDevice.GetTypeId()
            mesh_dev = device.GetObject(type_id)
            if mesh_dev is not None:
                if hasattr(mesh_dev, "GetInterfaces"):
                    interfaces = mesh_dev.GetInterfaces()
                    if interfaces.GetN() > 0:
                        iface = interfaces.Get(0)
                        wifi_dev = iface.GetObject(ns.wifi.WifiNetDevice.GetTypeId())
                        if wifi_dev is not None:
                            phy = wifi_dev.GetPhy()
                            if phy is not None:
                                return phy, None
                return None, "MeshPointDevice has no WifiNetDevice interfaces"
        except Exception:
            pass

        dev_name = ""
        try:
            dev_name = str(device.GetInstanceTypeId().GetName())
        except Exception:
            pass
        return None, f"unable to get PHY from device (type: {dev_name or 'unknown'})"

    def set_node_position(self, node_id: int, x: float, y: float, z: float = 0.0) -> dict[str, Any]:
        """将节点位置跃迁到指定坐标（线程安全）。"""
        if node_id >= self.config.n_nodes:
            return {"applied": False, "reason": "node_id out of range"}

        def _do():
            ns = self._ns
            if ns is None or self._nodes_container is None:
                raise RuntimeError("ns or nodes_container not ready")
            node = self._nodes_container.Get(node_id)
            mm = node.GetObject(ns.mobility.MobilityModel.GetTypeId())
            if not mm:
                raise RuntimeError("mobility model not found on node")
            mm.SetPosition(ns.core.Vector(x, y, z))
            with self._lock:
                self._env_state.positions[node_id] = {"x": float(x), "y": float(y), "z": float(z)}
                # 同步更新 _nodes_runtime，避免 snapshot_nodes() 与 snapshot_env() 在
                # _wall_pacer_loop 下一周期（100ms）前出现位置不一致。
                nr = self._nodes_runtime.setdefault(node_id, NodeRuntime(id=node_id))
                nr.x = float(x)
                nr.y = float(y)
            log.info("node-%d position set to (%.1f, %.1f, %.1f)", node_id, x, y, z)

        return self._inject_command(_do)

    def set_tx_power(self, node_id: int, dbm: float) -> dict[str, Any]:
        """修改指定节点的发射功率（线程安全）。"""
        if node_id >= self.config.n_nodes:
            return {"applied": False, "reason": "node_id out of range"}

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
        if node_id >= self.config.n_nodes:
            return {"applied": False, "reason": "node_id out of range"}

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
        model = self._propagation_loss_model
        if model is None:
            return {"applied": False, "reason": "propagation loss model not ready"}
        model_name = str(model.GetInstanceTypeId().GetName())
        if "LogDistance" not in model_name:
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
        """修改全局中心频率（线程安全）。

        SpectrumWifiPhy 的 Frequency 属性是 INITIAL_VALUE 类型,运行时不可设置;
        YansWifiPhy 同理。因此本方法只在 Friis/TwoRayGround 路径损耗模型上调整
        Frequency(那是真正参与传播预算计算的字段),PHY 端的载波/调制保持不动。
        """
        model = self._propagation_loss_model
        if model is None:
            return {"applied": False, "reason": "propagation loss model not ready"}
        model_name = str(model.GetInstanceTypeId().GetName())
        if "Friis" not in model_name and "TwoRay" not in model_name:
            return {"applied": False, "reason": f"current model {model_name} does not support frequency adjustment"}

        def _do():
            ns = self._ns
            freq_hz = float(mhz) * 1e6
            self._propagation_loss_model.SetAttribute(
                "Frequency", ns.core.DoubleValue(freq_hz)
            )
            with self._lock:
                self._env_state.frequency_mhz = int(mhz)
            log.info(
                "propagation-loss frequency set to %d MHz (%.0f Hz); PHY 载波保持不动,如需重置 802.11 频道请重启仿真",
                mhz, freq_hz,
            )

        return self._inject_command(_do)

    def set_channel_width(self, mhz: int) -> dict[str, Any]:
        """修改全局信道宽度（线程安全）。

        SpectrumWifiPhy 与 YansWifiPhy 的 ChannelWidth 都不允许运行时设置(都是
        INITIAL_VALUE)。本方法只 warning,提示用户重启仿真才能生效;直接调
        SetAttribute 会 NS_FATAL_ERROR 把 uvicorn 杀掉。
        """
        return {"applied": False, "reason": "channel width requires simulator restart"}

    def set_range_target(self, meters: float) -> dict[str, Any]:
        """修改全局最大通信距离（线程安全）。

        优先调整叠加的 Range 模型（所有主模型都叠加了 Range 截断）；
        若叠加模型不存在，回退到直接调整主传播损耗模型（仅 Range 模型本身支持）。
        """
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
        model_name = str(model.GetInstanceTypeId().GetName())
        if "Range" not in model_name:
            return {"applied": False, "reason": f"current model is {model_name}, not Range"}

        def _do():
            self._propagation_loss_model.SetAttribute(
                "MaxRange", self._ns.core.DoubleValue(meters)
            )
            with self._lock:
                self._env_state.range_target_m = float(meters)
            log.info("range target set to %.0f m", meters)

        return self._inject_command(_do)

    # ------------------------------------------------- in-simulator periodic
    def _schedule_periodic(self, ns: Any, nodes: Any, period_s: float) -> None:
        """在仿真器内调度周期性回调,刷新 FlowMonitor 计数器。

        位置快照与命令队列由 `_wall_pacer_loop` 在 wall-time 100ms 周期执行,
        因为实时仿真器在重负载时 ns-3 sim_t 远落后于 wall_t (实测 1/24x),
        若把这些放在 sim-time tick 里,前端拖拽 → 落地的延迟可达 20s+。
        """
        runner = self

        def _tick():
            try:
                if runner._fm is not None:
                    runner._fm.CheckForLostPackets()
                    stats = runner._fm.GetFlowStats()
                    # pybindgen/cppyy 绑定中 GetClassifier 可能缺失，跳过源/目的解析
                    classifier = None
                    if hasattr(runner._fm, "GetClassifier"):
                        classifier = runner._fm.GetClassifier()
                    with runner._lock:
                        runner._flows_runtime.clear()
                        for fid, st in stats:
                            source, destination = "", ""
                            if classifier:
                                ft = classifier.FindFlow(fid)
                                source = str(ft.sourceAddress)
                                destination = str(ft.destinationAddress)
                            elapsed = max(
                                (st.timeLastRxPacket.GetSeconds()
                                 - st.timeFirstTxPacket.GetSeconds()),
                                1e-9,
                            )
                            throughput_mbps = (st.rxBytes * 8.0) / elapsed / 1e6
                            avg_delay = (st.delaySum.GetSeconds() / st.rxPackets) \
                                if st.rxPackets else 0.0
                            runner._flows_runtime[fid] = FlowRuntime(
                                flow_id=fid,
                                source=source,
                                destination=destination,
                                tx_packets=st.txPackets,
                                rx_packets=st.rxPackets,
                                lost_packets=st.lostPackets,
                                avg_delay=avg_delay,
                                throughput=throughput_mbps,
                            )
            except Exception as e:  # noqa: BLE001
                log.warning("periodic tick failed: %s", e)
            finally:
                if not runner._stop_event.is_set():
                    ns.core.Simulator.Schedule(ns.core.Seconds(period_s), _tick)

        ns.core.Simulator.Schedule(ns.core.Seconds(period_s), _tick)

    def _wall_pacer_loop(self) -> None:
        """wall-time 100ms 周期：drain 命令队列 + 刷新节点位置快照。

        独立于 ns-3 sim 时钟,避免 sim 实时倍率 (BestEffort 下重负载会跌到 1/20x)
        把命令落地与位置回读拖到 20s+。

        thread-safety 注记:
        - `mm.SetPosition` / `mm.GetPosition` 在 ConstantPositionMobilityModel 下是
          单一字段读写,且 CPython GIL 下 Python 调用绑定时序列化执行,与 ns-3 主循环
          的 C++ 段并发只在 m_position 上读写——x86 对齐写是原子的,最坏情况是
          下一帧出现一次撕裂,可接受。
        - 对 RandomWalk/GaussMarkov 等带内部 schedule 的模型,从外部线程改 position
          仍存在风险;tactical 用 grid (ConstantPosition) 路径已规避。
        """
        while not self._stop_event.is_set():
            time.sleep(0.1)
            ns = self._ns
            if not self._running or ns is None or self._nodes_container is None:
                continue
            try:
                # 1. 排空命令队列
                while not self._command_queue.empty():
                    try:
                        cmd = self._command_queue.get_nowait()
                        cmd()
                    except Exception as e:  # noqa: BLE001
                        log.warning("dynamic command failed: %s", e)
                # 2. 刷新位置快照 + 邻居 + tap 接口计数器
                with self._lock:
                    n_nodes = self.config.n_nodes
                    tap_prefix = self.config.tap_prefix
                    # 必须用 _env_state.range_target_m（动态控制可能已修改），
                    # 不能用 self.config.range_target_m（启动时的静态快照）。
                    max_range = self._env_state.range_target_m
                    # 2a. 位置
                    for i in range(n_nodes):
                        node = self._nodes_container.Get(i)
                        mm = node.GetObject(ns.mobility.MobilityModel.GetTypeId())
                        if mm:
                            pos = mm.GetPosition()
                            nr = self._nodes_runtime.setdefault(i, NodeRuntime(id=i))
                            nr.x = float(pos.x)
                            nr.y = float(pos.y)
                            self._env_state.positions[i] = {"x": float(pos.x), "y": float(pos.y), "z": float(pos.z)}
                    # 2b. 邻居(按距离 + range_target_m 判定)
                    for i in range(n_nodes):
                        ni = self._nodes_runtime.get(i)
                        if not ni:
                            continue
                        neighbors = []
                        for j in range(n_nodes):
                            if i == j:
                                continue
                            nj = self._nodes_runtime.get(j)
                            if not nj:
                                continue
                            if math.hypot(ni.x - nj.x, ni.y - nj.y) <= max_range:
                                neighbors.append(j)
                        ni.neighbors = neighbors
                    # 2c. tap 接口 RX/TX(真实容器流量,FlowMonitor 看不到)
                    for i in range(n_nodes):
                        nr = self._nodes_runtime.get(i)
                        if not nr:
                            continue
                        try:
                            with open(f"/sys/class/net/{tap_prefix}{i}/statistics/rx_packets") as fh:
                                nr.rx_packets = int(fh.read().strip())
                            with open(f"/sys/class/net/{tap_prefix}{i}/statistics/tx_packets") as fh:
                                nr.tx_packets = int(fh.read().strip())
                        except Exception:  # noqa: BLE001
                            pass
            except Exception as e:  # noqa: BLE001
                log.warning("wall pacer iteration failed: %s", e)
