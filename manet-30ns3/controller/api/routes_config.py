"""配置路由：GET/PUT /api/config — 查看与暂存仿真参数。

内部实现委托 ParamStore，保持对外 REST 接口不变。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from controller.api.state import get_session
from controller.orchestrator import SimConfig

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config() -> dict[str, Any]:
    """获取当前全部参数快照（static + dynamic，camelCase JSON）。"""
    sess = get_session()
    if sess.param_store is not None:
        return sess.param_store.get_all()
    # fallback: 直接返回 SimConfig dump（兼容 ParamStore 未初始化时）
    return sess.config.model_dump(by_alias=True)


@router.put("")
async def put_config(cfg: SimConfig) -> dict[str, Any]:
    """写入新配置并持久化到文件。运行中也可保存（作为下次启动用）。

    内部通过 ParamStore.set() 逐个字段写入，触发持久化和变更广播。
    """
    sess = get_session()
    store = sess.param_store
    if store is not None:
        data = cfg.model_dump(by_alias=True)
        results = store.batch_set(data, source="rest")
        ok = all(r.get("ok") for r in results)
        return {"ok": ok, "results": results}

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
