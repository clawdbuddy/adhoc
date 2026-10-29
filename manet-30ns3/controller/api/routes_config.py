"""配置路由：GET/PUT /api/config — 查看与暂存仿真参数。

内部实现委托 ParamStore，保持对外 REST 接口不变。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

from controller.api.state import get_session
from controller.orchestrator import SimConfig

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config() -> dict[str, Any]:
    """获取当前静态配置快照（SimConfig 字段，camelCase JSON）。

    注意：只返回 static 参数（可用于启动仿真的配置），
    dynamic 运行时参数（positions / txPower 等）请通过 /ws/telemetry 获取。
    """
    sess = get_session()
    return sess.config.model_dump(by_alias=True)


@router.put("")
async def put_config(cfg: SimConfig) -> dict[str, Any]:
    """写入新配置并持久化到文件。运行中也可保存（作为下次启动用）。

    内部通过 ParamStore.set() 逐个字段写入，触发持久化和变更广播。
    """
    sess = get_session()
    store = sess.param_store
    if store is not None:
        # 配置保存与运行时调参分开：整份配置原子替换，避免逐字段校验失败或
        # 保存文件时意外修改正在运行的无线环境。
        return await asyncio.to_thread(store.save_config, cfg, source="rest")

    # fallback: 直接更新 SimConfig（兼容 ParamStore 未初始化时）
    from controller.orchestrator import save_config_to_file
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
