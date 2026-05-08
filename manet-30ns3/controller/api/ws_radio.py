"""单兵电台参数配置协议 WebSocket 服务端：/ws/radio

实现 app/proto.txt (V0.2) 协议规范，支持查询类、设置类、上报类指令。
协议采用 JSON 格式，通过 WebSocket 与客户端（智慧战斗 App）交互。

映射关系（电台协议 <-> ns-3 仿真）：
- 网络模块开关     -> 仿真启动/停止
- 入网状态         -> 节点在线状态
- 功率档位         -> txPower (0值守/1低/2中/3高)
- 频率             -> frequencyMhz (225-512 MHz)
- 速率档位         -> dataRate (1=9.6kb/2=19.2kb/3=38.4kb/4=62.5kb)
- 频表号           -> channel preset
- 拓扑信息         -> nodes / neighbors
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from controller.api.state import get_session

log = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# 常量与映射表
# ---------------------------------------------------------------------------

# 功率档位 -> dBm 映射（值守/低/中/高）
POWER_MAP: dict[int, float] = {0: 20.0, 1: 25.0, 2: 30.0, 3: 33.0}
POWER_MAP_REVERSE: dict[float, int] = {v: k for k, v in POWER_MAP.items()}

# 速率档位 -> ns-3 DataRate 字符串映射
RATE_MAP: dict[int, str] = {
    1: "DsssRate1Mbps",    # 最接近 9.6kb 的 WiFi 低速率
    2: "DsssRate2Mbps",    # 19.2kb
    3: "DsssRate5_5Mbps",  # 38.4kb
    4: "DsssRate11Mbps",   # 62.5kb
}
RATE_MAP_REVERSE: dict[str, int] = {v: k for k, v in RATE_MAP.items()}

# 频表号 -> frequencyMhz 映射（225-512 MHz 范围，每表 10MHz 步进）
def _freq_table_to_mhz(freq_num: int) -> int:
    """频表号 0-20 -> 频率 MHz (225 + freq_num * 10, 上限 512)."""
    return min(512, 225 + freq_num * 10)

def _mhz_to_freq_table(mhz: int) -> int:
    """频率 MHz -> 频表号."""
    return max(0, min(20, (mhz - 225) // 10))


# ---------------------------------------------------------------------------
# 协议帧构造
# ---------------------------------------------------------------------------

def _make_response(cmd_code: int, extend: str = "", **fields: Any) -> dict[str, Any]:
    """构造协议响应帧。"""
    return {
        "data": {"cmdCode": cmd_code, "extend": extend, **fields},
        "ident": "",
        "mnemonic": 0,
        "resWord": "",
        "type": 0,
        "version": 0,
    }


# ---------------------------------------------------------------------------
# 查询类指令处理
# ---------------------------------------------------------------------------

async def _handle_query(cmd_code: int, extend: str, net_mode: int) -> dict[str, Any]:
    """处理查询类指令，返回响应帧。"""
    sess = get_session()
    store = sess.param_store

    # 1001 -> 1002: 网络模块开关状态查询
    if cmd_code == 1001:
        running = sess.running
        return _make_response(
            1002, extend,
            adhoc=1 if running else 0,
            lte=0,
            satcom=0,
            bd=0,
            **{"171A": 0},
            **{"173RAP": 0},
            **{"173PRN": 0},
            **{"173FCS": 0},
            uv=0,
            jmMode=0,
            flyMode=0,
        )

    # 1025 -> 1026: 入网状态查询
    if cmd_code == 1025:
        return _make_response(
            1026, extend,
            netMode=net_mode,
            state=1,
            status=1 if sess.running else 0,
        )

    # 1071 -> 1072: 功率查询
    if cmd_code == 1071:
        power = 2  # 默认中功率
        if store is not None:
            r = store.get("txPower")
            tx_power = r.get("value", []) if r.get("ok") else []
            dbm = tx_power[0] if tx_power else 30.0
            power = POWER_MAP_REVERSE.get(dbm, 2)
        return _make_response(1072, extend, netMode=net_mode, power=power)

    # 1049 -> 1050: 频表查询
    if cmd_code == 1049:
        freq_num = 0
        if store is not None:
            r = store.get("frequencyMhz")
            mhz = r.get("value", 2412) if r.get("ok") else 2412
            freq_num = _mhz_to_freq_table(int(mhz))
        return _make_response(1050, extend, netMode=net_mode, freqNum=freq_num)

    # 7001 -> 7002: 频率查询
    if cmd_code == 7001:
        freq = 2412
        if store is not None:
            r = store.get("frequencyMhz")
            freq = r.get("value", 2412) if r.get("ok") else 2412
        return _make_response(7002, extend, result=1, frequency=str(freq))

    # 7003 -> 7004: 速率查询
    if cmd_code == 7003:
        rate = 1
        if store is not None:
            r = store.get("dataRate")
            data_rate = r.get("value", "HtMcs7") if r.get("ok") else "HtMcs7"
            rate = RATE_MAP_REVERSE.get(data_rate, 1)
        return _make_response(7004, extend, result=1, rate=rate)

    return _make_response(cmd_code + 1, extend, state=0, result=0)


# ---------------------------------------------------------------------------
# 设置类指令处理
# ---------------------------------------------------------------------------

async def _handle_set(cmd_code: int, extend: str, payload: dict[str, Any]) -> dict[str, Any]:
    """处理设置类指令，返回响应帧。"""
    sess = get_session()
    store = sess.param_store
    net_mode = payload.get("netMode", 1)

    # 2001 -> 2002: 网络模块开关设置
    if cmd_code == 2001:
        ctrl = payload.get("ctrl", 0)
        if ctrl == 1 and not sess.running:
            # 启动仿真（使用当前配置）
            try:
                await sess.start(config=sess.config)
                return _make_response(2002, extend, netMode=net_mode, state=1)
            except Exception as e:
                log.exception("启动仿真失败")
                return _make_response(2002, extend, netMode=net_mode, state=0)
        elif ctrl == 0 and sess.running:
            try:
                await sess.stop()
                return _make_response(2002, extend, netMode=net_mode, state=1)
            except Exception:
                log.exception("停止仿真失败")
                return _make_response(2002, extend, netMode=net_mode, state=0)
        return _make_response(2002, extend, netMode=net_mode, state=1)

    # 2043 -> 2044: 功率设置
    if cmd_code == 2043:
        power = payload.get("power", 2)
        dbm = POWER_MAP.get(power, 30.0)
        if store is not None:
            try:
                # 对所有节点设置相同功率（标量会被 ParamStore 广播到所有节点）
                r = store.set("txPower", dbm, source="radio")
                return _make_response(2044, extend, netMode=net_mode,
                                      state=1 if r.get("ok") else 0)
            except Exception:
                log.exception("设置功率失败")
                return _make_response(2044, extend, netMode=net_mode, state=0)
        return _make_response(2044, extend, netMode=net_mode, state=0)

    # 2023 -> 2024: 频表设置
    if cmd_code == 2023:
        freq_num = payload.get("freqNum", 0)
        mhz = _freq_table_to_mhz(freq_num)
        if store is not None:
            try:
                r = store.set("frequencyMhz", mhz, source="radio")
                return _make_response(2024, extend, netMode=net_mode,
                                      state=1 if r.get("ok") else 0)
            except Exception:
                log.exception("设置频表失败")
                return _make_response(2024, extend, netMode=net_mode, state=0)
        return _make_response(2024, extend, netMode=net_mode, state=0)

    # 8001 -> 8002: 频率设置
    if cmd_code == 8001:
        freq = payload.get("frequency", 2412)
        try:
            mhz = int(freq)
        except (TypeError, ValueError):
            mhz = 2412
        if store is not None:
            try:
                r = store.set("frequencyMhz", mhz, source="radio")
                return _make_response(8002, extend,
                                      result=1 if r.get("ok") else 2)
            except Exception:
                log.exception("设置频率失败")
                return _make_response(8002, extend, result=2)
        return _make_response(8002, extend, result=2)

    # 8003 -> 8004: 速率设置
    if cmd_code == 8003:
        rate = payload.get("rate", 1)
        # 速率变更需要重启仿真才能生效（PHY/MAC 层绑定）
        if store is not None:
            data_rate = RATE_MAP.get(rate, "DsssRate1Mbps")
            r = store.set("dataRate", data_rate, source="radio")
            return _make_response(8004, extend,
                                  result=1 if r.get("ok") else 2)
        return _make_response(8004, extend, result=2)

    return _make_response(cmd_code + 1, extend, state=0, result=2)


# ---------------------------------------------------------------------------
# 上报类配置与主动推送任务
# ---------------------------------------------------------------------------

# 每个 /ws/radio 连接维护自己的上报配置副本
_REPORT_CFG: dict[str, Any] = {
    "5002_enabled": True,
    "5002_period": 2.0,
    "5006_enabled": True,
    "5006_period": 10.0,
}


def _get_report_cfg() -> dict[str, Any]:
    """返回当前上报配置快照。"""
    return dict(_REPORT_CFG)


def _set_report_cfg(key: str, value: Any) -> bool:
    """设置单个上报配置项。"""
    if key not in _REPORT_CFG:
        return False
    try:
        if key.endswith("_enabled"):
            _REPORT_CFG[key] = bool(value)
        elif key.endswith("_period"):
            v = float(value)
            _REPORT_CFG[key] = max(0.5, min(300.0, v))
        else:
            _REPORT_CFG[key] = value
        return True
    except Exception:
        return False


async def _push_5002(ws: WebSocket, stop_evt: asyncio.Event) -> None:
    """5002 入网/断网状态变化上报任务。"""
    prev_running: bool | None = None
    while not stop_evt.is_set():
        cfg = _get_report_cfg()
        period = cfg["5002_period"]
        try:
            await asyncio.wait_for(stop_evt.wait(), timeout=period)
        except asyncio.TimeoutError:
            pass
        if stop_evt.is_set():
            break
        if not cfg["5002_enabled"]:
            continue

        sess = get_session()
        running = sess.running
        if prev_running is None:
            prev_running = running
            continue
        if running == prev_running:
            continue
        prev_running = running
        try:
            frame = _make_response(5002, "", netMode=1, state=1 if running else 0)
            await ws.send_json(frame)
        except Exception:
            break


async def _push_5006(ws: WebSocket, stop_evt: asyncio.Event) -> None:
    """5006 在线信息上报任务。"""
    prev_online: set[str] = set()
    while not stop_evt.is_set():
        cfg = _get_report_cfg()
        period = cfg["5006_period"]
        try:
            await asyncio.wait_for(stop_evt.wait(), timeout=period)
        except asyncio.TimeoutError:
            pass
        if stop_evt.is_set():
            break
        if not cfg["5006_enabled"]:
            continue

        sess = get_session()
        if not (sess.running and sess.telemetry):
            continue
        try:
            snap = sess.telemetry.snapshot()
            nodes = snap.get("nodes", [])
            online_ips = [n["ip"] for n in nodes if n.get("status") == "online"]
            if set(online_ips) == prev_online:
                continue
            prev_online = set(online_ips)
            frame = _make_response(5006, "", netMode=1, groupMebsIP=online_ips)
            await ws.send_json(frame)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 上报配置查询/设置
# ---------------------------------------------------------------------------

async def _handle_report_query(cmd_code: int, extend: str) -> dict[str, Any]:
    """9001 -> 9002: 查询上报配置。"""
    cfg = _get_report_cfg()
    return _make_response(
        9002, extend,
        report5002Enabled=1 if cfg["5002_enabled"] else 0,
        report5002Period=int(cfg["5002_period"] * 1000),  # ms
        report5006Enabled=1 if cfg["5006_enabled"] else 0,
        report5006Period=int(cfg["5006_period"] * 1000),  # ms
    )


async def _handle_report_set(cmd_code: int, extend: str, payload: dict[str, Any]) -> dict[str, Any]:
    """9003 -> 9004: 设置上报配置。"""
    ok = True
    if "report5002Enabled" in payload:
        ok = _set_report_cfg("5002_enabled", payload["report5002Enabled"]) and ok
    if "report5002Period" in payload:
        ok = _set_report_cfg("5002_period", payload["report5002Period"] / 1000.0) and ok
    if "report5006Enabled" in payload:
        ok = _set_report_cfg("5006_enabled", payload["report5006Enabled"]) and ok
    if "report5006Period" in payload:
        ok = _set_report_cfg("5006_period", payload["report5006Period"] / 1000.0) and ok
    return _make_response(9004, extend, state=1 if ok else 0)


# ---------------------------------------------------------------------------
# WebSocket 入口
# ---------------------------------------------------------------------------

@router.websocket("/ws/radio")
async def radio_ws(ws: WebSocket) -> None:
    """单兵电台协议 WebSocket 服务端。"""
    log.info("[/ws/radio] 收到 WebSocket 连接请求")
    await ws.accept()
    log.info("电台协议客户端连接: %s", ws.client)
    stop_evt = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []

    try:
        # 启动两个独立的上报任务，各自拥有独立的周期和开关
        tasks.append(asyncio.create_task(_push_5002(ws, stop_evt), name="push-5002"))
        tasks.append(asyncio.create_task(_push_5006(ws, stop_evt), name="push-5006"))

        while True:
            raw = await ws.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json(_make_response(0, "", state=0, result=2))
                continue

            data = payload.get("data", {})
            cmd_code = data.get("cmdCode", 0)
            extend = data.get("extend", "")
            net_mode = data.get("netMode", 1)

            # 查询类 (1xxx / 7xxx / 9xxx)
            if cmd_code in (1001, 1025, 1071, 1049, 7001, 7003, 9001):
                if cmd_code == 9001:
                    resp = await _handle_report_query(cmd_code, extend)
                else:
                    resp = await _handle_query(cmd_code, extend, net_mode)
                await ws.send_json(resp)
                continue

            # 设置类 (2xxx / 8xxx / 9xxx)
            if cmd_code in (2001, 2043, 2023, 8001, 8003, 9003):
                if cmd_code == 9003:
                    resp = await _handle_report_set(cmd_code, extend, data)
                else:
                    resp = await _handle_set(cmd_code, extend, data)
                await ws.send_json(resp)
                continue

            # 未知指令
            await ws.send_json(_make_response(cmd_code + 1, extend, state=0, result=2))

    except WebSocketDisconnect:
        log.info("电台协议客户端断开")
    except Exception:
        log.exception("电台协议 WebSocket 异常")
    finally:
        stop_evt.set()
        for task in tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        try:
            await ws.close()
        except Exception:
            pass
