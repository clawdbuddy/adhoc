"""ns-3 Python simulation runner — port of scratch/manet-30nodes.cc.

Threading model:
    The ns-3 simulator is started in a dedicated daemon thread; FastAPI runs in
    the main asyncio loop. The simulator thread owns the ns-3 globals.

TapBridge mode (UseBridge): each ns-3 WifiNetDevice is L2-bridged to a host
TAP (tap-{i}). User traffic from the corresponding container traverses the
ns-3 AdHoc PHY/MAC channel model. ns-3 does NOT IP-route user payloads in
UseBridge mode — the L3 `routingProtocol` setting is installed on ns-3's
stack but only applies to packets ns-3 itself generates (control plane).
This matches the existing C++ implementation; multi-hop user-payload routing
must be done by software inside the containers.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import SimConfig

log = logging.getLogger(__name__)


def _import_ns():
    """Lazy-import ns-3 bindings; defer ImportError until the sim actually starts."""
    from ns import ns  # noqa: WPS433 — runtime guard
    return ns


@dataclass
class NodeRuntime:
    """Live snapshot of one ns-3 node."""
    id: int
    x: float = 0.0
    y: float = 0.0
    rx_packets: int = 0
    tx_packets: int = 0
    neighbors: list[int] = field(default_factory=list)


@dataclass
class FlowRuntime:
    flow_id: int
    source: str
    destination: str
    tx_packets: int = 0
    rx_packets: int = 0
    lost_packets: int = 0
    avg_delay: float = 0.0
    throughput: float = 0.0


class SimRunner:
    """Encapsulates one ns-3 simulation lifecycle."""

    def __init__(self, config: SimConfig):
        self.config = config
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._nodes_runtime: dict[int, NodeRuntime] = {}
        self._flows_runtime: dict[int, FlowRuntime] = {}
        self._ns: Any = None
        self._fm: Any = None
        self._running = False
        self._start_time: float | None = None
        self._error: str | None = None

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
        self._running = False

    @property
    def running(self) -> bool:
        return self._running and (self._thread is not None and self._thread.is_alive())

    @property
    def elapsed(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    # ------------------------------------------------- public snapshots
    def snapshot_nodes(self) -> list[NodeRuntime]:
        with self._lock:
            return [NodeRuntime(**n.__dict__) for n in self._nodes_runtime.values()]

    def snapshot_flows(self) -> list[FlowRuntime]:
        with self._lock:
            return [FlowRuntime(**f.__dict__) for f in self._flows_runtime.values()]

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

        # 1. Realtime simulator + RNG
        ns.core.GlobalValue.Bind(
            "SimulatorImplementationType",
            ns.core.StringValue("ns3::RealtimeSimulatorImpl"),
        )
        ns.core.GlobalValue.Bind("ChecksumEnabled", ns.core.BooleanValue(True))
        ns.core.RngSeedManager.SetSeed(cfg.seed)
        ns.core.RngSeedManager.SetRun(cfg.run)

        # 2. Nodes
        nodes = ns.network.NodeContainer()
        nodes.Create(cfg.n_nodes)
        log.info("created %d ns-3 nodes", cfg.n_nodes)

        # 3. Channel + PHY
        channel = self._build_channel(ns, cfg)
        phy = ns.wifi.YansWifiPhyHelper()
        phy.SetChannel(channel.Create())
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

        # 5. AdHoc MAC
        mac = ns.wifi.WifiMacHelper()
        mac.SetType(
            "ns3::AdhocWifiMac",
            "Ssid", ns.wifi.SsidValue(ns.wifi.Ssid(cfg.ssid)),
        )
        devices = wifi.Install(phy, mac, nodes)

        # 6. Mobility
        self._install_mobility(ns, cfg, nodes)

        # 7. Internet stack + routing
        self._install_routing(ns, cfg, nodes)

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
        ns.core.Simulator.Stop(ns.core.Seconds(cfg.simulation_time))
        log.info("Simulator.Run() begin (T=%.0fs)", cfg.simulation_time)
        ns.core.Simulator.Run()
        log.info("Simulator.Run() end")

    # -------------------------------------------------- channel / propagation
    def _build_channel(self, ns: Any, cfg: SimConfig) -> Any:
        ch = ns.wifi.YansWifiChannelHelper()

        # Delay
        if cfg.propagation_delay == "ConstantSpeed":
            ch.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel")
        else:
            ch.SetPropagationDelay("ns3::RandomPropagationDelayModel")

        # Path loss
        pl = cfg.path_loss_model
        if pl == "LogDistance":
            ch.AddPropagationLoss(
                "ns3::LogDistancePropagationLossModel",
                "Exponent", ns.core.DoubleValue(cfg.path_loss_exponent),
                "ReferenceLoss", ns.core.DoubleValue(cfg.path_loss_ref_loss),
                "ReferenceDistance", ns.core.DoubleValue(cfg.path_loss_ref_distance),
            )
        elif pl == "FreeSpace":
            ch.AddPropagationLoss("ns3::FriisPropagationLossModel")
        elif pl == "TwoRayGround":
            ch.AddPropagationLoss("ns3::TwoRayGroundPropagationLossModel")
        elif pl == "ThreeLogDistance":
            ch.AddPropagationLoss("ns3::ThreeLogDistancePropagationLossModel")
        elif pl == "Cost231":
            ch.AddPropagationLoss("ns3::Cost231PropagationLossModel")
        elif pl == "Range":
            ch.AddPropagationLoss(
                "ns3::RangePropagationLossModel",
                "MaxRange", ns.core.DoubleValue(250.0),
            )

        # Fading
        if cfg.enable_fading:
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

        return ch

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
                ns.core.RectangleValue(
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
                ns.core.BoxValue(ns.mobility.Box(cfg.mobility_min_x, cfg.mobility_max_x,
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

    # ------------------------------------------------- in-simulator periodic
    def _schedule_periodic(self, ns: Any, nodes: Any, period_s: float) -> None:
        """Schedule a recurring 1 Hz callback inside the simulator that
        snapshots positions and FlowMonitor counters into the runtime state."""
        runner = self

        def _tick():
            try:
                # positions
                with runner._lock:
                    for i in range(runner.config.n_nodes):
                        node = nodes.Get(i)
                        mm = node.GetObject(ns.mobility.MobilityModel.GetTypeId())
                        if mm:
                            pos = mm.GetPosition()
                            nr = runner._nodes_runtime.setdefault(i, NodeRuntime(id=i))
                            nr.x = float(pos.x)
                            nr.y = float(pos.y)
                # flows
                if runner._fm is not None:
                    runner._fm.CheckForLostPackets()
                    classifier = runner._fm.GetClassifier()
                    stats = runner._fm.GetFlowStats()
                    with runner._lock:
                        runner._flows_runtime.clear()
                        for fid, st in stats:
                            ft = classifier.FindFlow(fid)
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
                                source=str(ft.sourceAddress),
                                destination=str(ft.destinationAddress),
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
