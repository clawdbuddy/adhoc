"""UDP 二进制协议命令处理器（api_54.docx）。

将 api_54 定义的 16-bit 命令 ID 映射到 SimConfig / ParamStore 的读写操作。
所有处理器均为 async，以便在需要时调用异步的 Session API。
"""
from __future__ import annotations

import logging
import struct
from typing import Callable

from controller.api.state import get_session
from controller.orchestrator.udp_protocol import (
    UdpFrame,
    bcd1_to_int,
    bcd4_to_mhz,
    int_to_bcd1,
    int_to_bcd1 as bcd1_encode,  # alias for clarity
    mhz_to_bcd4,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 速率档位映射（api_54 BCD level → ns-3 DataRate 字符串）
# ---------------------------------------------------------------------------
RATE_LEVEL_MAP: dict[int, str] = {
    0: "HtMcs0",      # 速率自适应（fallback 到最低 MCS）
    1: "DsssRate1Mbps",   # 窄 512kbps → 最接近的 WiFi 低速率
    2: "DsssRate2Mbps",   # 窄 1Mbps
    3: "DsssRate5_5Mbps", # 窄 2Mbps
    4: "OfdmRate6Mbps",   # 宽 2Mbps
    5: "OfdmRate12Mbps",  # 宽 4Mbps
    6: "OfdmRate24Mbps",  # 宽 8Mbps
    7: "OfdmRate48Mbps",  # 宽 10Mbps
    8: "OfdmRate54Mbps",  # 宽 16Mbps
    9: "OfdmRate9Mbps",   # 窄 4Mbps
    10: "OfdmRate6Mbps",  # 2Mbps
    11: "OfdmRate12Mbps", # 4Mbps
    12: "OfdmRate18Mbps", # 5Mbps
    13: "OfdmRate24Mbps", # 8Mbps
    14: "OfdmRate36Mbps", # 10Mbps
    15: "OfdmRate48Mbps", # 宽 20Mbps
    16: "DsssRate1Mbps",  # 64k → fallback
    17: "DsssRate1Mbps",  # 512k → fallback
    18: "DsssRate2Mbps",  # 2M
}

# 反向映射：取最匹配的 level（先到先得）
RATE_STR_TO_LEVEL: dict[str, int] = {}
for _lvl, _rate in RATE_LEVEL_MAP.items():
    if _rate not in RATE_STR_TO_LEVEL:
        RATE_STR_TO_LEVEL[_rate] = _lvl

# ---------------------------------------------------------------------------
# 功率档位映射（api_54 BCD level → dBm）
# 与 ws_radio.py 的 POWER_MAP 不同：api_54 使用 0=大功率, 4=自适应
# ---------------------------------------------------------------------------
POWER_LEVEL_MAP: dict[int, float] = {
    0: 33.0,   # 大功率
    1: 25.0,   # 中功率
    2: 15.0,   # 小功率
    3: 5.0,    # 值守
    4: -1.0,   # 功率自适应（占位）
}

POWER_LEVEL_REVERSE: dict[float, int] = {v: k for k, v in POWER_LEVEL_MAP.items()}

# ---------------------------------------------------------------------------
# 工作模式映射
# ---------------------------------------------------------------------------
WORK_MODE_NAMES: dict[int, str] = {
    0: "fixed",
    1: "fh",
    2: "fcs",
    3: "fixed-encrypted",
    4: "fh-encrypted",
    5: "fcs-encrypted",
}


class UdpCommandHandler:
    """UDP 命令分发与执行器。"""

    def __init__(self) -> None:
        self._handlers: dict[int, Callable[[UdpFrame], UdpFrame]] = {
            # 静态参数设置
            0x0001: self._handle_set_0001,
            0x0002: self._handle_set_0002,
            0x0003: self._handle_set_0003,
            0x0004: self._handle_set_0004,
            0x0005: self._handle_set_0005,
            # 静态参数查询
            0x0041: self._handle_get_0041,
            0x0042: self._handle_get_0042,
            0x0043: self._handle_get_0043,
            0x0044: self._handle_get_0044,
            0x0045: self._handle_get_0045,
            # 动态参数设置
            0x0101: self._handle_set_0101,
            0x0102: self._handle_set_0102,
            # 动态参数查询
            0x0141: self._handle_get_0141,
            0x0142: self._handle_get_0142,
            # 版本查询
            0x0203: self._handle_get_0203,
            # 拓扑查询 / 上报
            0x0310: self._handle_get_0310,
        }

    # ------------------------------------------------------------------ 分发

    async def handle(self, frame: UdpFrame) -> UdpFrame | None:
        handler = self._handlers.get(frame.cmd_id)
        if handler is None:
            log.warning("未知 UDP 命令: 0x%04X", frame.cmd_id)
            return self._make_nack(frame.cmd_id)
        try:
            return handler(frame)
        except Exception:
            log.exception("UDP 命令 0x%04X 处理失败", frame.cmd_id)
            return self._make_nack(frame.cmd_id)

    # ------------------------------------------------------------------ ACK/NACK

    def _make_ack(self, cmd_id: int) -> UdpFrame:
        return UdpFrame(comm_type=1, cmd_id=0x02A0, payload=struct.pack(">H", cmd_id))

    def _make_nack(self, cmd_id: int) -> UdpFrame:
        return UdpFrame(comm_type=1, cmd_id=0x02A1, payload=struct.pack(">H", cmd_id))

    # ------------------------------------------------------------------ 静态设置

    def _handle_set_0001(self, frame: UdpFrame) -> UdpFrame:
        """设置网络规模 (nNodes)。"""
        if len(frame.payload) != 2:
            return self._make_nack(0x0001)
        val = struct.unpack(">H", frame.payload)[0]
        sess = get_session()
        result = sess.param_store.set("nNodes", val, source="udp")
        return self._make_ack(0x0001) if result.get("ok") else self._make_nack(0x0001)

    def _handle_set_0002(self, frame: UdpFrame) -> UdpFrame:
        """设置工作模式 (workMode)。"""
        if len(frame.payload) != 1:
            return self._make_nack(0x0002)
        val = frame.payload[0]
        sess = get_session()
        result = sess.param_store.set("workMode", val, source="udp")
        return self._make_ack(0x0002) if result.get("ok") else self._make_nack(0x0002)

    def _handle_set_0003(self, frame: UdpFrame) -> UdpFrame:
        """设置 MAC 地址 (nodeMacId)。"""
        if len(frame.payload) != 2:
            return self._make_nack(0x0003)
        val = struct.unpack(">H", frame.payload)[0]
        sess = get_session()
        result = sess.param_store.set("nodeMacId", val, source="udp")
        return self._make_ack(0x0003) if result.get("ok") else self._make_nack(0x0003)

    def _handle_set_0004(self, frame: UdpFrame) -> UdpFrame:
        """设置定频频率 (BCD → MHz)。"""
        if len(frame.payload) != 4:
            return self._make_nack(0x0004)
        mhz = bcd4_to_mhz(frame.payload)
        sess = get_session()
        result = sess.param_store.set("frequencyMhz", mhz, source="udp")
        return self._make_ack(0x0004) if result.get("ok") else self._make_nack(0x0004)

    def _handle_set_0005(self, frame: UdpFrame) -> UdpFrame:
        """设置跳频表号 (fhTableId)。"""
        if len(frame.payload) != 1:
            return self._make_nack(0x0005)
        val = frame.payload[0]
        sess = get_session()
        result = sess.param_store.set("fhTableId", val, source="udp")
        return self._make_ack(0x0005) if result.get("ok") else self._make_nack(0x0005)

    # ------------------------------------------------------------------ 静态查询 / 返回

    def _handle_get_0041(self, frame: UdpFrame) -> UdpFrame:
        """查询网络规模 → 0x0081。"""
        sess = get_session()
        val = int(sess.param_store.get("nNodes").get("value", 5))
        return UdpFrame(comm_type=1, cmd_id=0x0081, payload=struct.pack(">H", val))

    def _handle_get_0042(self, frame: UdpFrame) -> UdpFrame:
        """查询工作模式 → 0x0082。"""
        sess = get_session()
        val = int(sess.param_store.get("workMode").get("value", 0))
        return UdpFrame(comm_type=1, cmd_id=0x0082, payload=bytes([val]))

    def _handle_get_0043(self, frame: UdpFrame) -> UdpFrame:
        """查询 MAC 地址 → 0x0083。"""
        sess = get_session()
        val = int(sess.param_store.get("nodeMacId").get("value", 0))
        return UdpFrame(comm_type=1, cmd_id=0x0083, payload=struct.pack(">H", val))

    def _handle_get_0044(self, frame: UdpFrame) -> UdpFrame:
        """查询定频频率 → 0x0084。"""
        sess = get_session()
        mhz = float(sess.param_store.get("frequencyMhz").get("value", 2412))
        return UdpFrame(comm_type=1, cmd_id=0x0084, payload=mhz_to_bcd4(mhz))

    def _handle_get_0045(self, frame: UdpFrame) -> UdpFrame:
        """查询跳频表号 → 0x0085。"""
        sess = get_session()
        val = int(sess.param_store.get("fhTableId").get("value", 0))
        return UdpFrame(comm_type=1, cmd_id=0x0085, payload=bytes([val]))

    # ------------------------------------------------------------------ 动态设置

    def _handle_set_0101(self, frame: UdpFrame) -> UdpFrame:
        """设置传输速率 (BCD level → dataRate)。"""
        if len(frame.payload) != 1:
            return self._make_nack(0x0101)
        level = bcd1_to_int(frame.payload)
        rate_str = RATE_LEVEL_MAP.get(level, "HtMcs0")
        sess = get_session()
        result = sess.param_store.set("dataRate", rate_str, source="udp")
        return self._make_ack(0x0101) if result.get("ok") else self._make_nack(0x0101)

    def _handle_set_0102(self, frame: UdpFrame) -> UdpFrame:
        """设置发射功率 (BCD level → dBm)。"""
        if len(frame.payload) != 1:
            return self._make_nack(0x0102)
        level = bcd1_to_int(frame.payload)
        dbm = POWER_LEVEL_MAP.get(level, 33.0)
        sess = get_session()
        result = sess.param_store.set("txPower", dbm, source="udp")
        return self._make_ack(0x0102) if result.get("ok") else self._make_nack(0x0102)

    # ------------------------------------------------------------------ 动态查询 / 返回

    def _handle_get_0141(self, frame: UdpFrame) -> UdpFrame:
        """查询传输速率 → 0x0181。"""
        sess = get_session()
        data_rate = sess.param_store.get("dataRate").get("value", "HtMcs0")
        level = RATE_STR_TO_LEVEL.get(str(data_rate), 0)
        return UdpFrame(comm_type=1, cmd_id=0x0181, payload=bcd1_encode(level))

    def _handle_get_0142(self, frame: UdpFrame) -> UdpFrame:
        """查询发射功率 → 0x0182。"""
        sess = get_session()
        tx_power = sess.param_store.get("txPower").get("value", [33.0])
        dbm = tx_power[0] if isinstance(tx_power, list) else tx_power
        level = POWER_LEVEL_REVERSE.get(float(dbm), 0)
        return UdpFrame(comm_type=1, cmd_id=0x0182, payload=bcd1_encode(level))

    # ------------------------------------------------------------------ 版本

    def _handle_get_0203(self, frame: UdpFrame) -> UdpFrame:
        """版本查询 → 0x02A3。"""
        sess = get_session()
        version = str(getattr(sess.config, "software_version", "V1.00.03"))
        return UdpFrame(comm_type=1, cmd_id=0x02A3, payload=version.encode("ascii"))

    # ------------------------------------------------------------------ 拓扑

    def _handle_get_0310(self, frame: UdpFrame) -> UdpFrame:
        """自组网节点拓扑 → 0x0310。

        格式: [n(2B)][src_mac(2B)][dst_mac(2B)][link_quality(1B)] * n
        链路质量: 0xFF=未知(非邻居), 其他值=邻居质量(按距离估算)
        """
        sess = get_session()
        sim = sess.sim
        if not sim or not sess.running:
            return self._make_nack(0x0310)

        nodes = sim.snapshot_nodes()
        env = sim.snapshot_env()
        range_m = env.range_target_m

        pairs: list[bytes] = []
        for node in nodes:
            src_mac = node.id
            for neighbor_id in node.neighbors:
                dst_mac = neighbor_id
                # 链路质量：简化实现，邻居固定给 0x80（良好）
                # 未来可根据实际 SNR/RSSI 计算
                link_quality = 0x80
                pairs.append(struct.pack(">HHB", src_mac, dst_mac, link_quality))

        n = len(pairs)
        payload = struct.pack(">H", n) + b"".join(pairs)
        return UdpFrame(comm_type=1, cmd_id=0x0310, payload=payload)
