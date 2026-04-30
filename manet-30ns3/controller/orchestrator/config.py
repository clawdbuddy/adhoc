"""Pydantic models for the MANET simulation configuration and node specs.

Wire format is camelCase to match the React `SimConfig` TypeScript interface
in app/src/types/config.ts and the .conf files in manet-30ns3/. Internal
Python attribute names are snake_case.

Single source of truth for the parameter surface: this module. The .conf parser
in `parse_conf_file` accepts the same camelCase keys used by start-simulation.sh
and the React UI's exportConfig.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# ----- supported enums (mirror app/src/types/config.ts) ----------------------
Standard = Literal[
    "80211b", "80211a", "80211g",
    "80211n-2.4GHz", "80211n-5GHz",
    "80211ac", "80211ax-2.4GHz", "80211ax-5GHz",
]
PhyModel = Literal["yans", "spectrum"]
PathLossModel = Literal[
    "LogDistance", "FreeSpace", "TwoRayGround", "ThreeLogDistance", "Cost231", "Range",
]
FadingModel = Literal["Nakagami", "Jakes"]
PropagationDelay = Literal["ConstantSpeed", "Random"]
RateControl = Literal["Arf", "Aarf", "Onoe", "Constant", "Minstrel"]
RoutingProtocol = Literal["aodv", "olsr", "dsdv", "dsr", "none"]
MacMode = Literal["adhoc", "mesh"]
MobilityModel = Literal["random-walk", "gauss-markov", "grid", "constant"]
GridLayout = Literal["RowFirst", "ColumnFirst"]
RwMode = Literal["Time", "Distance"]
NodeRole = Literal["client", "server", "gateway"]
UserAppMode = Literal["bind", "image", "exec"]


class _CamelModel(BaseModel):
    """Base: snake_case Python attrs ↔ camelCase JSON aliases."""
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )


# ----- simulation config -----------------------------------------------------
class SimConfig(_CamelModel):
    # General
    n_nodes: int = 30
    simulation_time: float = 300
    seed: int = 1
    run: int = 1
    log_components: str = ""

    # PHY
    # phy_model="spectrum" 启用 SpectrumWifiPhy + MultiModelSpectrumChannel；
    # frequency_mhz/channel_width_mhz 主要驱动 Friis 路径损耗（590 MHz UHF + 20 MHz 带宽）。
    # 真实射频参数虽然落在 802.11a 5 GHz 内部表里，但传播损耗按 frequency_mhz 计算，
    # 4 km LOS 的距离预算与 UHF 物理一致。
    standard: Standard = "80211a"
    phy_model: PhyModel = "spectrum"
    frequency_mhz: int = 590
    channel_width_mhz: int = 20
    range_target_m: float = 4000.0
    data_rate: str = "OfdmRate6Mbps"
    tx_power_start: float = 30.0
    tx_power_end: float = 30.0
    tx_power_levels: int = 1
    rx_sensitivity: float = -92.0
    cca_threshold: float = -82.0
    antenna_gain: float = 3.0

    # Propagation
    propagation_delay: PropagationDelay = "ConstantSpeed"
    path_loss_model: PathLossModel = "FreeSpace"
    path_loss_exponent: float = 2.0
    path_loss_ref_loss: float = 46.6777
    path_loss_ref_distance: float = 1.0
    enable_fading: bool = False
    fading_model: FadingModel = "Nakagami"
    nakagami_m0: float = 1.5
    nakagami_m1: float = 1.0
    nakagami_m2: float = 0.75
    nakagami_d1: float = 50.0
    nakagami_d2: float = 100.0

    # MAC — mac_mode="mesh" 启用 802.11s + HWMP 实现 L2 多跳；
    # 此时 TapBridge UseBridge 仍可用，整张 mesh 在容器视角下是一个 L2 广播域，
    # 多跳转发由 ns-3 mesh 模块在底层完成，容器侧无需额外路由配置。
    ssid: str = "adhoc-30ns3"
    bssid: str = "00:00:00:00:AD:H0"
    mac_mode: MacMode = "mesh"
    rate_control: RateControl = "Constant"
    rts_cts_threshold: int = 2200
    fragmentation_threshold: int = 2200
    non_unicast_mode: bool = False
    beacon_interval: int = 100
    cw_min: int = 15
    cw_max: int = 1023

    # Routing
    routing_protocol: RoutingProtocol = "aodv"
    aodv_hello_interval: float = 1.0
    aodv_rreq_retries: int = 2
    aodv_active_route_timeout: float = 3.0
    aodv_delete_period: float = 5.0
    aodv_net_diameter: int = 35
    aodv_enable_hello: bool = True
    olsr_hello_interval: float = 2.0
    olsr_tc_interval: float = 5.0
    olsr_willingness: int = 7
    dsdv_periodic_update_interval: float = 15.0
    dsdv_settling_time: float = 6

    # Mobility — 默认覆盖 5000 m × 5000 m 的活动范围，配合 4 km LOS 视距。
    mobility_model: MobilityModel = "random-walk"
    mobility_min_x: float = 0.0
    mobility_max_x: float = 5000.0
    mobility_min_y: float = 0.0
    mobility_max_y: float = 5000.0
    rw_min_speed: float = 0.5
    rw_max_speed: float = 3.0
    rw_distance: float = 200.0
    rw_mode: RwMode = "Time"
    rw_time: float = 1.0
    grid_min_x: float = 100.0
    grid_min_y: float = 100.0
    grid_delta_x: float = 800.0
    grid_delta_y: float = 800.0
    grid_width: int = 6
    grid_layout: GridLayout = "RowFirst"
    gm_alpha: float = 0.85

    # Tracing — keys match .conf files (`pcap`, `ascii`); camelCase aliases
    # are `pcap` and `ascii` (single-word, no transformation).
    pcap: bool = True
    ascii: bool = False
    flow_monitor: bool = True
    pcap_prefix: str = "manet-30nodes-adhoc"
    enable_mobility_trace: bool = False

    # TapBridge
    tap_mode: Literal["UseBridge", "UseLocal"] = "UseBridge"
    tap_prefix: str = "tap-"

    # ----- helpers -----------------------------------------------------------
    def merged_with(self, partial: Mapping[str, Any]) -> "SimConfig":
        """Return a copy with `partial` overrides (accepts camelCase or snake_case)."""
        base = self.model_dump(by_alias=True)
        base.update(_normalize_keys(partial))
        return SimConfig.model_validate(base)


# ----- per-node spec ---------------------------------------------------------
class NodeSpec(_CamelModel):
    """Per-node spec carried in the orchestrator's runtime registry."""
    id: int
    ip: str
    role: NodeRole = "client"
    image: str = "manet-node:latest"
    user_app_mode: UserAppMode = "exec"
    user_app_cmd: str | None = None
    user_app_bind_path: str | None = None  # host path to bind-mount when mode=bind
    ssh_enable: bool = False
    ssh_authorized_keys: str | None = None
    host: str = "local"  # multi-host phase 2 hook; "local" = same machine as controller


class RunRequest(_CamelModel):
    """Body of POST /api/sim/start."""
    config: SimConfig | None = None
    preset: str | None = None
    overrides: dict[str, Any] = Field(default_factory=dict)
    nodes: list[NodeSpec] | None = None  # if None, generated from config.n_nodes


# ----- presets (mirror app/src/types/config.ts PRESETS) ----------------------
def _preset(**overrides: Any) -> SimConfig:
    return SimConfig.model_validate(overrides)


PRESETS: dict[str, SimConfig] = {
    # 默认预设 = 用户目标场景：SpectrumWifiPhy + 802.11s mesh 多跳，
    # 中心频率 590 MHz（覆盖 500–680 MHz UHF 频段），4 km 视距，5 km × 5 km 活动区。
    "default": _preset(),

    # 城区——视距受阻、路径衰减更陡、节点密集，频段维持 UHF。
    "urban": _preset(
        ssid="adhoc-urban",
        txPowerStart=27.0, txPowerEnd=27.0,
        rxSensitivity=-90.0, ccaThreshold=-78.0,
        pathLossModel="LogDistance", pathLossExponent=3.5,
        enableFading=True,
        nakagamiM0=1.0, nakagamiM1=0.75, nakagamiM2=0.5,
        nakagamiD1=300.0, nakagamiD2=800.0,
        rateControl="Aarf",
        rtsCtsThreshold=500, fragmentationThreshold=1000,
        mobilityMaxX=2000.0, mobilityMaxY=2000.0,
        rwMaxSpeed=2.0, rwDistance=100.0,
        gridDeltaX=300.0, gridDeltaY=300.0,
        pcapPrefix="manet-urban",
    ),

    # 旷野——开阔视距、路径衰减接近自由空间、活动区更大。
    "rural": _preset(
        ssid="adhoc-rural",
        txPowerStart=33.0, txPowerEnd=33.0,
        rxSensitivity=-95.0, ccaThreshold=-85.0,
        pathLossModel="FreeSpace",
        pathLossExponent=2.0,
        rtsCtsThreshold=65535,
        mobilityModel="grid",
        mobilityMaxX=8000.0, mobilityMaxY=8000.0,
        gridMinX=200.0, gridMinY=200.0,
        gridDeltaX=1500.0, gridDeltaY=1500.0,
        pcapPrefix="manet-rural",
    ),

    # 冒烟测试——5 节点 / 短时长 / 小活动区 / 关闭衰落 / 关闭 mesh 退回 ad-hoc。
    "debug": _preset(
        nNodes=5, simulationTime=60,
        ssid="adhoc-debug",
        macMode="adhoc",
        routingProtocol="none",
        mobilityModel="grid",
        mobilityMaxX=300.0, mobilityMaxY=300.0,
        gridMinX=10.0, gridMinY=10.0,
        gridDeltaX=50.0, gridDeltaY=50.0, gridWidth=5,
        rangeTargetM=200.0,
        ascii=True,
        pcapPrefix="manet-debug",
        enableMobilityTrace=True,
    ),
}


# ----- .conf parser ----------------------------------------------------------
_CONF_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$")


def _coerce(val: str) -> Any:
    v = val.strip().strip('"').strip("'")
    if v.lower() in ("true", "false"):
        return v.lower() == "true"
    try:
        if "." in v or "e" in v.lower():
            return float(v)
        return int(v)
    except ValueError:
        return v


def _normalize_keys(d: Mapping[str, Any]) -> dict[str, Any]:
    """Accept either snake_case or camelCase keys."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if "_" in k:
            # snake_case → camelCase alias
            head, *rest = k.split("_")
            ck = head + "".join(p.capitalize() for p in rest)
            out[ck] = v
        else:
            out[k] = v
    return out


def parse_conf_file(path: str | Path) -> dict[str, Any]:
    """Parse a key=value .conf file (// comments allowed). Returns camelCase dict."""
    out: dict[str, Any] = {}
    text = Path(path).read_text()
    for raw in text.splitlines():
        line = raw
        cmt = line.find("//")
        if cmt != -1:
            line = line[:cmt]
        line = line.strip()
        if not line:
            continue
        m = _CONF_LINE_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        # Compatibility: legacy aliases used in app/src/types/config.ts.
        if key == "pcapTracing":
            key = "pcap"
        elif key == "asciiTracing":
            key = "ascii"
        out[key] = _coerce(val)
    return out


def load_config(
    *,
    file_path: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
    preset: str | None = None,
) -> SimConfig:
    """Build SimConfig with explicit precedence: overrides > file > preset > defaults.

    Resolves the user's documented "CLI > .conf > env" expectation
    (the C++ scratch program inverted file vs CLI; this function fixes that).
    """
    if preset:
        if preset not in PRESETS:
            raise KeyError(f"unknown preset {preset!r}; available: {sorted(PRESETS)}")
        cfg = PRESETS[preset]
    else:
        cfg = SimConfig()

    if file_path:
        cfg = cfg.merged_with(parse_conf_file(file_path))

    if overrides:
        cfg = cfg.merged_with(overrides)

    return cfg
