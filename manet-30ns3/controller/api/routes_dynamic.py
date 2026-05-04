"""动态环境控制路由：运行时修改仿真参数。

所有端点仅在仿真运行期间可用；仿真未运行时返回 409。
命令通过线程安全队列注入 ns-3 仿真线程执行。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from controller.api.state import get_session

router = APIRouter(tags=["dynamic"])


class TxPowerBody(BaseModel):
    nodeId: int
    dbm: float


class PositionBody(BaseModel):
    nodeId: int
    x: float
    y: float
    z: float = 0.0


class RxSensBody(BaseModel):
    nodeId: int
    dbm: float


class PathLossBody(BaseModel):
    exponent: float


class FrequencyBody(BaseModel):
    mhz: int


class ChannelWidthBody(BaseModel):
    mhz: int


class RangeBody(BaseModel):
    meters: float


def _check_running() -> None:
    sess = get_session()
    if not sess.running:
        raise HTTPException(409, "仿真未运行")
    if sess.sim is None:
        raise HTTPException(409, "仿真器未初始化")


@router.post("/api/env/txpower")
async def set_tx_power(body: TxPowerBody) -> dict[str, Any]:
    """修改指定节点的发射功率。"""
    _check_running()
    get_session().sim.set_tx_power(body.nodeId, body.dbm)
    return {"ok": True, "nodeId": body.nodeId, "dbm": body.dbm}


@router.post("/api/env/position")
async def set_position(body: PositionBody) -> dict[str, Any]:
    """将指定节点跃迁到指定坐标。"""
    _check_running()
    get_session().sim.set_node_position(body.nodeId, body.x, body.y, body.z)
    return {"ok": True, "nodeId": body.nodeId, "x": body.x, "y": body.y, "z": body.z}


@router.post("/api/env/rxsens")
async def set_rx_sensitivity(body: RxSensBody) -> dict[str, Any]:
    """修改指定节点的接收灵敏度。"""
    _check_running()
    get_session().sim.set_rx_sensitivity(body.nodeId, body.dbm)
    return {"ok": True, "nodeId": body.nodeId, "dbm": body.dbm}


@router.post("/api/env/pathloss")
async def set_path_loss_exponent(body: PathLossBody) -> dict[str, Any]:
    """修改全局路径损耗指数（仅 LogDistance 模型生效）。"""
    _check_running()
    get_session().sim.set_path_loss_exponent(body.exponent)
    return {"ok": True, "exponent": body.exponent}


@router.post("/api/env/frequency")
async def set_frequency(body: FrequencyBody) -> dict[str, Any]:
    """修改全局中心频率（MHz）。"""
    _check_running()
    get_session().sim.set_frequency(body.mhz)
    return {"ok": True, "mhz": body.mhz}


@router.post("/api/env/channelwidth")
async def set_channel_width(body: ChannelWidthBody) -> dict[str, Any]:
    """修改全局信道宽度（MHz）。"""
    _check_running()
    get_session().sim.set_channel_width(body.mhz)
    return {"ok": True, "mhz": body.mhz}


@router.post("/api/env/range")
async def set_range_target(body: RangeBody) -> dict[str, Any]:
    """修改 Range 传播模型的最大通信距离（米）。"""
    _check_running()
    get_session().sim.set_range_target(body.meters)
    return {"ok": True, "meters": body.meters}


@router.get("/api/env/capabilities")
async def get_capabilities() -> dict[str, Any]:
    """返回当前支持的动态调整能力列表。"""
    return {
        "capabilities": [
            {"id": "txpower", "name": "发射功率", "unit": "dBm", "scope": "per-node"},
            {"id": "position", "name": "节点位置", "unit": "m", "scope": "per-node"},
            {"id": "rxsens", "name": "接收灵敏度", "unit": "dBm", "scope": "per-node"},
            {"id": "pathloss", "name": "路径损耗指数", "unit": "", "scope": "global"},
            {"id": "frequency", "name": "中心频率", "unit": "MHz", "scope": "global"},
            {"id": "channelwidth", "name": "信道宽度", "unit": "MHz", "scope": "global"},
            {"id": "range", "name": "最大通信距离", "unit": "m", "scope": "global"},
        ],
    }
