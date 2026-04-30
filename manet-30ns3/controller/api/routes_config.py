"""配置路由：GET/PUT /api/config — 查看与暂存仿真参数。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from controller.api.state import get_session
from controller.orchestrator import SimConfig

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config() -> dict[str, Any]:
    """获取当前仿真配置（camelCase JSON）。"""
    sess = get_session()
    return sess.config.model_dump(by_alias=True)


@router.put("")
async def put_config(cfg: SimConfig) -> dict[str, Any]:
    """写入新配置；仿真运行中时拒绝修改。"""
    sess = get_session()
    if sess.running:
        return {
            "ok": False,
            "reason": "仿真正在运行；请先停止再修改配置",
            "current": sess.config.model_dump(by_alias=True),
        }
    sess.config = cfg
    return {"ok": True, "config": sess.config.model_dump(by_alias=True)}
