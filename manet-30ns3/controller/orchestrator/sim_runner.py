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
    - 因此当前 3.47 路线强制使用 mac_mode="mesh"，adhoc 模式已禁用。
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

log = logging.getLogger(__name__)


def _to_ns3_address(inet_addr: Any) -> Any:
    """cppyy 绑定中 InetSocketAddress 无法隐式转换为 Address，需显式调用 ConvertTo。"""
    try:
        return inet_addr.ConvertTo()
    except Exception:  # noqa: BLE001
        return inet_addr


class _CppyyModuleProxy:
    """让 cppyy 的扁平命名空间也能支持 `ns.core.Simulator` 这种子模块写法。

    ns-3.47 cppyy 绑定中所有类都挂在 ns3 根命名空间下，但旧代码里大量出现
    `ns.wifi.WifiHelper`、`ns.aodv.AodvHelper` 等子模块写法。本代理在子模块
    命名空间找不到目标时，自动回退到扁平根命名空间，实现零改动兼容。
    """

    def __init__(self, ns):
        self._ns = ns

    def __getattr__(self, name):
        try:
            return getattr(self._ns, name)
        except AttributeError:
            # 子模块命名空间（如 ns3::aodv）没有该类，回退到扁平根命名空间
            pass
        # 如果根命名空间也没有，让原始异常抛出
        return getattr(self._ns, name)


class _CppyyNsWrapper:
    """包装 cppyy.gbl.ns3，优先返回扁平命名空间成员，缺失时回退到子模块代理。"""

    # ns-3 子模块名列表；cppyy 中这些名字同时是根命名空间属性（ns3::aodv 等），
    # 但类实际挂在根下，因此必须走代理做二次回退。
    _MODULE_NAMES = frozenset({
        "core", "network", "internet", "wifi", "mobility", "tap_bridge",
        "flow_monitor", "propagation", "spectrum", "aodv", "olsr",
        "dsdv", "dsr", "mesh", "applications",
    })

    def __init__(self, ns):
        self._ns = ns
        self._proxies: dict[str, Any] = {}

    def __getattr__(self, name):
        # 对已知子模块名一律走代理，让代理在"子模块空间 → 扁平根空间"回退；
        # 其它名字若根命名空间有直接命中则立即返回。
        if name in self._MODULE_NAMES:
            if name not in self._proxies:
                self._proxies[name] = _CppyyModuleProxy(self._ns)
            return self._proxies[name]
        if hasattr(self._ns, name):
            return getattr(self._ns, name)
        if name not in self._proxies:
            self._proxies[name] = _CppyyModuleProxy(self._ns)
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
    channel_width_mhz: int = 20
    range_target_m: float = 4000.0
    path_loss_model: str = "FreeSpace"


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
        # 实际使用的 MAC 模式;当前版本强制 mesh，此处记录实际生效值
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
            path_loss_model=str(config.path_loss_model),
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
        """实际生效的 MAC 模式;当前版本强制 mesh。"""
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
                path_loss_model=self._env_state.path_loss_model,
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

        # 1. RealtimeSimulatorImpl 是 TapBridge 在 UseLocal 模式下保持运行的前提；
        #    BestEffort 在事件队列为空时会立即返回，导致仿真线程退出。
        #    注：RealtimeSimulatorImpl 受 wall-time 约束，TAP 桥接下带宽上限约 1.5-2Mbps。
        ns.core.GlobalValue.Bind(
            "SimulatorImplementationType",
            ns.core.StringValue("ns3::RealtimeSimulatorImpl"),
        )
        ns.core.Config.Set(
            "ns3::RealtimeSimulatorImpl::SynchronizationMode",
            ns.core.StringValue("HardLimit"),
        )
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

        # 5. MAC：mac_mode="mesh" 启用 802.11s + HWMP，由 ns-3 mesh 模块在 L2
        #    层完成多跳转发。NS-3.47 + cppyy 下 adhoc 模式会触发 Txop segfault，
        #    因此强制使用 mesh 模式。
        if cfg.mac_mode != "mesh":
            log.warning(
                "mac_mode='%s' 在 NS-3.47 + cppyy 下会导致 segfault，强制切换到 mesh",
                cfg.mac_mode,
            )
        devices = self._install_mesh(ns, cfg, phy, nodes)

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

        # 13. ns-3.47 + cppyy 不支持 Simulator.Schedule 传入 Python callback，
        #     因此取消 in-sim periodic tick；FlowMonitor 统计由 _wall_pacer_loop
        #     在 wall-time 线程中懒更新。

        # 14. Run!
        # 不再预设自动停止时间；仿真持续运行直到用户手动调用 stop()。
        # simulation_time 仅作为配置参考，不再调度 Simulator.Stop()。
        #
        # NS-3.47 + cppyy 的 Simulator.Run() 会阻塞并持有 CPython GIL，导致 FastAPI
        # 的 asyncio 事件循环冻结。通过 cppyy.cppdef 编译一个释放 GIL 的 C++ 包装器，
        # 让 Run() 在 C++ 层执行时释放 GIL，使 wall-pacer 线程和 API 主循环得以运行。
        log.info("Simulator.Run() begin (manual stop mode)")
        try:
            import cppyy
            if not hasattr(cppyy.gbl, "ns3_simulator_run_release_gil"):
                cppyy.cppdef("""
                extern "C" {
                    void* PyEval_SaveThread(void);
                    void  PyEval_RestoreThread(void*);
                }
                void ns3_simulator_run_release_gil() {
                    void* save = PyEval_SaveThread();
                    try {
                        ns3::Simulator::Run();
                    } catch (...) {
                        PyEval_RestoreThread(save);
                        throw;
                    }
                    PyEval_RestoreThread(save);
                }
                """)
            cppyy.gbl.ns3_simulator_run_release_gil()
            log.info("Simulator.Run() end (GIL released)")
        except Exception as compile_err:
            log.warning(
                "GIL-releasing wrapper failed: %s. "
                "Falling back to direct Run() — API will freeze during simulation.",
                compile_err,
            )
            ns.core.Simulator.Run()
            log.info("Simulator.Run() end")

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
        # ns-3.47 中 ChannelWidth 为 INITIAL_VALUE，不能在 helper.Set() 中设置；
        # 移除以避免 NS_FATAL_ERROR。如需非默认带宽，需通过 ChannelSettings 配置。
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
        # ns-3.47 中 ChannelWidth 为 INITIAL_VALUE，不能在 helper.Set() 中设置。
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
        # ns-3.47 中 MeshHelper.SetStandard 会导致 PHY channel 配置冲突
        # (WifiPhyOperatingChannel: No unique channel found)，因此跳过。
        # 默认标准由 MeshHelper 内部决定，与物理层传播模型独立。
        # mesh_helper.SetStandard(self._wifi_standard(ns, cfg.standard))
        # RandomStart：mesh 节点上电后随机抖动（避免同时发 BCN）
        mesh_helper.SetMacType("RandomStart", ns.core.TimeValue(ns.core.Seconds(0.1)))
        # 单接口模式即可——多接口 mesh 主要用于多频段聚合，不在本场景目标内。
        mesh_helper.SetNumberOfInterfaces(1)
        # ns-3.47 默认 mesh 使用 802.11a；cfg.data_rate 中的 ErpOfdmRate* 是 802.11g
        # 专有命名，与 802.11a 不兼容，会导致 "Can't find response rate" NS_FATAL。
        # 因此跳过 SetRemoteStationManager，让 mesh 使用内置 ARF 速率控制。
        # mesh_helper.SetRemoteStationManager(
        #     "ns3::ConstantRateWifiManager",
        #     "DataMode", ns.core.StringValue(cfg.data_rate),
        #     "ControlMode", ns.core.StringValue(cfg.data_rate),
        # )
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
        """获取指定节点的 WifiPhy（mesh 模式下的 MeshPointDevice）。

        返回 (phy, error_message) 二元组。error_message 为 None 表示成功。
        """
        ns = self._ns
        if ns is None or self._wifi_devices is None:
            return None, "ns or wifi_devices not ready"

        device = self._wifi_devices.Get(node_id)

        # 方法1: 直接尝试 GetPhy
        try:
            phy = device.GetPhy()
            if phy is not None:
                return phy, None
        except (AttributeError, TypeError):
            pass

        # 方法2: 通过 GetObject 转换为 WifiNetDevice
        # ns-3.47 + cppyy：模板方法 GetObject 必须用方括号语法实例化
        try:
            wifi_dev = device.GetObject[ns.wifi.WifiNetDevice]()
            if wifi_dev is not None:
                phy = wifi_dev.GetPhy()
                if phy is not None:
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
                                    return phy, None
                    except Exception:
                        pass
                # ns-3.47 + cppyy：GetInterfaces 可能返回不可遍历对象，回退到节点设备列表
        except Exception:
            pass

        # 方法4: 直接遍历节点上所有 NetDevice，寻找 WifiNetDevice
        # MeshHelper::Install 会在节点上同时添加 MeshPointDevice 和 WifiNetDevice
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
        if node_id >= self.config.n_nodes:
            return {"applied": False, "reason": "node_id out of range"}

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
                        # ns-3.47 + cppyy：模板方法 GetObject 用方括号语法
                        mm = node.GetObject[ns.mobility.MobilityModel]()
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
                    # 2d. FlowMonitor 统计 (ns-3.47 cppyy 不支持 Simulator.Schedule
                    #     传入 Python callback，改在 wall-time 线程懒更新)
                    if self._fm is not None:
                        try:
                            self._fm.CheckForLostPackets()
                            stats = self._fm.GetFlowStats()
                            classifier = None
                            if hasattr(self._fm, "GetClassifier"):
                                classifier = self._fm.GetClassifier()
                            self._flows_runtime.clear()
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
                                self._flows_runtime[fid] = FlowRuntime(
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
                            log.warning("flow monitor poll failed: %s", e)
            except Exception as e:  # noqa: BLE001
                log.warning("wall pacer iteration failed: %s", e)
