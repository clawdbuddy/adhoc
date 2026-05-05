"""Pydantic models for the MANET simulation configuration and node specs.

Wire format is camelCase to match the React `SimConfig` TypeScript interface
in manet-30ns3/web-manager/src/types/config.ts and the .conf files in manet-30ns3/. Internal
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

# ----- supported enums (mirror manet-30ns3/web-manager/src/types/config.ts) ----------------------
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
    n_nodes: int = 6
    simulation_time: float = 300
    seed: int = 1
    run: int = 1
    log_components: str = ""

    # PHY
    # phy_model="spectrum" 启用 SpectrumWifiPhy + MultiModelSpectrumChannel；
    # 默认使用 2.4 GHz WiFi 频段（802.11g Channel 1, 2412 MHz），确保 ns-3 PHY/MAC
    # 工作在标准 WiFi 模式，避免非合法频段导致速率回退到 1 Mbps。
    # 传播损耗按 frequency_mhz 计算，4 km LOS 预算与 2.4 GHz 物理一致。
    standard: Standard = "80211g"
    phy_model: PhyModel = "spectrum"
    frequency_mhz: int = 2412
    channel_width_mhz: int = 20
    range_target_m: float = 4000.0
    data_rate: str = "ErpOfdmRate24Mbps"
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
    mac_mode: MacMode = "adhoc"
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
    tap_mode: Literal["UseBridge", "UseLocal"] = "UseLocal"
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


# ----- presets (mirror manet-30ns3/web-manager/src/types/config.ts PRESETS) ----------------------
def _preset(**overrides: Any) -> SimConfig:
    return SimConfig.model_validate(overrides)


PRESETS: dict[str, SimConfig] = {
    # 默认预设 = 用户目标场景：SpectrumWifiPhy + 802.11s mesh 多跳，
    # 中心频率 590 MHz（覆盖 500–680 MHz UHF 频段），4 km 视距，5 km × 5 km 活动区。
    "default": _preset(),

    # 城区——视距受阻、路径衰减更陡、节点密集，频段维持 UHF。
    "urban": _preset(
        nNodes=30, macMode="mesh",
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
        nNodes=30, macMode="mesh",
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

    # 战术场景——10 节点 / UHF 590 MHz / 20 MHz 信道 / 6 Mbps / 4 km 视距。
    # 适用于需要 4–8 Mbps 带宽、3–4 km 通视距离的典型战术通信场景。
    "tactical": _preset(
        nNodes=10, simulationTime=300,
        ssid="adhoc-tactical",
        standard="80211a",
        phyModel="spectrum",
        frequencyMhz=590,
        channelWidthMhz=20,
        dataRate="OfdmRate6Mbps",
        txPowerStart=30.0, txPowerEnd=30.0,
        txPowerLevels=1,
        rxSensitivity=-92.0,
        ccaThreshold=-82.0,
        antennaGain=3.0,
        pathLossModel="FreeSpace",
        pathLossExponent=2.0,
        enableFading=False,
        macMode="mesh",
        rateControl="Constant",
        rtsCtsThreshold=2200,
        mobilityModel="grid",
        mobilityMaxX=5000.0, mobilityMaxY=5000.0,
        gridMinX=100.0, gridMinY=100.0,
        gridDeltaX=1000.0, gridDeltaY=1000.0,
        gridWidth=5,
        rangeTargetM=4000.0,
        pcapPrefix="manet-tactical",
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
        # Compatibility: legacy aliases used in manet-30ns3/web-manager/src/types/config.ts.
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


# ----- persistent config file helpers ----------------------------------------

FIELD_DESCRIPTIONS: dict[str, str] = {
    # General
    "nNodes": "节点数量：仿真中同时活跃的节点总数（2-100）",
    "simulationTime": "仿真时长：单轮仿真的持续时间（秒）",
    "seed": "随机种子：控制伪随机数生成器的初始状态",
    "run": "运行编号：用于区分同一配置下的多次重复实验",
    "logComponents": "日志组件：逗号分隔的 ns-3 LogComponent 名称",
    # PHY
    "standard": "802.11 标准：决定调制方式和速率表",
    "phyModel": "PHY 模型：yans（简化）或 spectrum（频谱级仿真）",
    "frequencyMhz": "中心频率：工作频段的中心频率（MHz），范围 500–680 MHz UHF，默认 590",
    "channelWidthMhz": "信道带宽：每个信道的带宽（MHz）",
    "rangeTargetM": "目标覆盖范围：期望的单跳通信距离（米），用于链路预算",
    "dataRate": "数据速率：固定使用的 PHY 数据速率模式",
    "txPowerStart": "发射功率起始：最小发射功率（dBm）",
    "txPowerEnd": "发射功率结束：最大发射功率（dBm）",
    "txPowerLevels": "发射功率等级数：功率控制的分级数量",
    "rxSensitivity": "接收灵敏度：可解调信号的最小接收功率（dBm）",
    "ccaThreshold": "CCA 阈值：信道评估的忙碌判定门限（dBm）",
    "antennaGain": "天线增益：全向天线增益（dBi）",
    # Propagation
    "propagationDelay": "传播延迟模型：ConstantSpeed（光速）或 Random",
    "pathLossModel": "路径损耗模型：FreeSpace/LogDistance/TwoRayGround 等",
    "pathLossExponent": "路径损耗指数：LogDistance 模型中的衰减指数",
    "pathLossRefLoss": "1m 参考损耗：参考距离 1 米处的路径损耗（dB）",
    "pathLossRefDistance": "参考距离：计算参考损耗的距离（米）",
    "enableFading": "启用衰落：是否叠加小尺度衰落模型",
    "fadingModel": "衰落模型：Nakagami（默认）或 Jakes",
    "nakagamiM0": "Nakagami M0：近距离（d < D1）的衰落参数",
    "nakagamiM1": "Nakagami M1：中距离（D1 <= d < D2）的衰落参数",
    "nakagamiM2": "Nakagami M2：远距离（d >= D2）的衰落参数",
    "nakagamiD1": "Nakagami 距离 D1：M0/M1 分界的距离阈值（米）",
    "nakagamiD2": "Nakagami 距离 D2：M1/M2 分界的距离阈值（米）",
    # MAC
    "ssid": "SSID：网络标识符",
    "bssid": "BSSID：基本服务集标识符（MAC 格式）",
    "macMode": "MAC 模式：adhoc（独立基本服务集）或 mesh（802.11s）",
    "rateControl": "速率控制算法：Arf/Aarf/Onoe/Constant/Minstrel",
    "rtsCtsThreshold": "RTS/CTS 阈值：超过此字节的数据帧启用 RTS/CTS，65535=禁用",
    "fragmentationThreshold": "分片阈值：超过此字节的数据帧分片传输",
    "nonUnicastMode": "非单播模式：广播/组播使用最低数据速率",
    "beaconInterval": "信标间隔：Beacon 帧发送间隔（TU，1024us）",
    "cwMin": "最小竞争窗口：CSMA/CA 的最小退避窗口大小",
    "cwMax": "最大竞争窗口：CSMA/CA 的最大退避窗口大小",
    # Routing
    "routingProtocol": "路由协议：aodv/olsr/dsdv/dsr/none",
    "aodvHelloInterval": "AODV Hello 间隔：邻居发现广播间隔（秒）",
    "aodvRreqRetries": "AODV RREQ 重试：路由请求的最大重传次数",
    "aodvActiveRouteTimeout": "AODV 活跃路由超时：未使用路由的过期时间（秒）",
    "aodvDeletePeriod": "AODV 删除周期：路由表项的清理周期（秒）",
    "aodvNetDiameter": "AODV 网络直径：预估的网络最大跳数",
    "aodvEnableHello": "AODV 启用 Hello：是否使用 Hello 消息维护邻居关系",
    "olsrHelloInterval": "OLSR Hello 间隔：拓扑发现广播间隔（秒）",
    "olsrTcInterval": "OLSR TC 间隔：拓扑控制消息发送间隔（秒）",
    "olsrWillingness": "OLSR 意愿值：节点转发 TC 消息的意愿（0-7）",
    "dsdvPeriodicUpdateInterval": "DSDV 定期更新间隔：路由表广播间隔（秒）",
    "dsdvSettlingTime": "DSDV 稳定时间：等待路由收敛的最长时间（秒）",
    # Mobility
    "mobilityModel": "移动模型：random-walk/gauss-markov/grid/constant",
    "mobilityMinX": "区域最小 X：仿真区域的左边界（米）",
    "mobilityMaxX": "区域最大 X：仿真区域的右边界（米）",
    "mobilityMinY": "区域最小 Y：仿真区域的下边界（米）",
    "mobilityMaxY": "区域最大 Y：仿真区域的上边界（米）",
    "rwMinSpeed": "随机游走最小速度：节点最小移动速度（m/s）",
    "rwMaxSpeed": "随机游走最大速度：节点最大移动速度（m/s）",
    "rwDistance": "随机游走距离：Distance 模式下每次改变方向前移动的距离（米）",
    "rwMode": "随机游走模式：Time（按时间）或 Distance（按距离）",
    "rwTime": "随机游走时间：Time 模式下每次改变方向前的时间（秒）",
    "gridMinX": "网格起始 X：Grid 布局的左上角 X 坐标（米）",
    "gridMinY": "网格起始 Y：Grid 布局的左上角 Y 坐标（米）",
    "gridDeltaX": "网格 X 间距：Grid 布局中节点水平间距（米）",
    "gridDeltaY": "网格 Y 间距：Grid 布局中节点垂直间距（米）",
    "gridWidth": "网格每行节点数：Grid 布局每行的节点数量",
    "gridLayout": "网格布局：RowFirst（按行填充）或 ColumnFirst（按列填充）",
    "gmAlpha": "高斯-马尔可夫 Alpha：速度记忆系数（0=完全随机, 1=直线运动）",
    # Tracing
    "pcap": "PCAP 跟踪：是否生成 PCAP 抓包文件",
    "ascii": "ASCII 跟踪：是否生成 ASCII 文本跟踪文件",
    "flowMonitor": "流监控：是否启用 ns-3 FlowMonitor 端到端统计",
    "pcapPrefix": "PCAP 文件名前缀：跟踪文件的路径前缀",
    "enableMobilityTrace": "移动性跟踪：是否记录节点位置轨迹",
}

_FIELD_GROUPS: list[tuple[str, list[str]]] = [
    ("--- General ---", ["nNodes", "simulationTime", "seed", "run", "logComponents"]),
    ("--- PHY ---", [
        "standard", "phyModel", "frequencyMhz", "channelWidthMhz", "rangeTargetM",
        "dataRate", "txPowerStart", "txPowerEnd", "txPowerLevels",
        "rxSensitivity", "ccaThreshold", "antennaGain",
    ]),
    ("--- Propagation ---", [
        "propagationDelay", "pathLossModel", "pathLossExponent", "pathLossRefLoss",
        "pathLossRefDistance", "enableFading", "fadingModel",
        "nakagamiM0", "nakagamiM1", "nakagamiM2", "nakagamiD1", "nakagamiD2",
    ]),
    ("--- MAC ---", [
        "ssid", "bssid", "macMode", "rateControl", "rtsCtsThreshold",
        "fragmentationThreshold", "nonUnicastMode", "beaconInterval", "cwMin", "cwMax",
    ]),
    ("--- Routing ---", [
        "routingProtocol", "aodvHelloInterval", "aodvRreqRetries",
        "aodvActiveRouteTimeout", "aodvDeletePeriod", "aodvNetDiameter", "aodvEnableHello",
        "olsrHelloInterval", "olsrTcInterval", "olsrWillingness",
        "dsdvPeriodicUpdateInterval", "dsdvSettlingTime",
    ]),
    ("--- Mobility ---", [
        "mobilityModel", "mobilityMinX", "mobilityMaxX", "mobilityMinY", "mobilityMaxY",
        "rwMinSpeed", "rwMaxSpeed", "rwDistance", "rwMode", "rwTime",
        "gridMinX", "gridMinY", "gridDeltaX", "gridDeltaY", "gridWidth", "gridLayout",
        "gmAlpha",
    ]),
    ("--- Tracing ---", ["pcap", "ascii", "flowMonitor", "pcapPrefix", "enableMobilityTrace"]),
]

CONFIG_FILE_PATH: Path = Path("/app/config/user_settings.conf")


def save_config_to_file(cfg: SimConfig, path: str | Path | None = None) -> None:
    """将 SimConfig 序列化为带注释的 .conf 文件。

    文件格式：分组注释 + 字段注释 + key = value 行。
    使用原子写入（先写 .tmp 再 replace）避免文件损坏。
    """
    import datetime as _dt

    target = Path(path) if path else CONFIG_FILE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("// NS-3 MANET 仿真用户配置")
    lines.append(f"// 生成时间: {_dt.datetime.now().isoformat()}")
    lines.append("")

    data = cfg.model_dump(by_alias=True)

    for group_header, keys in _FIELD_GROUPS:
        lines.append(group_header)
        for key in keys:
            if key not in data:
                continue
            desc = FIELD_DESCRIPTIONS.get(key, "")
            if desc:
                lines.append(f"// {desc}")
            val = data[key]
            if isinstance(val, bool):
                lines.append(f"{key} = {'true' if val else 'false'}")
            elif isinstance(val, str):
                lines.append(f'{key} = "{val}"')
            else:
                lines.append(f"{key} = {val}")
            lines.append("")

    tmp = target.with_suffix(".tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    tmp.replace(target)


def load_user_config(path: str | Path | None = None) -> SimConfig | None:
    """从配置文件加载用户配置。文件不存在或解析失败时返回 None。"""
    target = Path(path) if path else CONFIG_FILE_PATH
    if not target.exists():
        return None
    try:
        return SimConfig.model_validate(parse_conf_file(target))
    except Exception:
        return None
