"""配置路由：GET/PUT /api/config — 查看与暂存仿真参数。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from controller.api.state import get_session
from controller.orchestrator import SimConfig, save_config_to_file

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config() -> dict[str, Any]:
    """获取当前仿真配置（camelCase JSON）。"""
    sess = get_session()
    return sess.config.model_dump(by_alias=True)


@router.put("")
async def put_config(cfg: SimConfig) -> dict[str, Any]:
    """写入新配置并持久化到文件。运行中也可保存（作为下次启动用）。"""
    sess = get_session()
    sess.config = cfg
    try:
        save_config_to_file(cfg)
    except Exception as e:
        return {
            "ok": False,
            "reason": f"配置已更新，但写入文件失败: {e}",
            "config": sess.config.model_dump(by_alias=True),
        }
    return {"ok": True, "config": sess.config.model_dump(by_alias=True)}
