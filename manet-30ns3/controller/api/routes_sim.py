"""仿真生命周期路由：POST/GET /api/sim/*"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from controller.api.state import Session, get_session
from controller.orchestrator import RunRequest, PRESETS

router = APIRouter(prefix="/api/sim", tags=["sim"])


@router.post("/start")
async def start_sim(req: RunRequest | None = None) -> dict[str, Any]:
    """启动仿真。接收 RunRequest（含 config/preset/overrides/nodes）。"""
    sess: Session = get_session()
    if sess.running:
        raise HTTPException(409, "仿真已在运行")
    req = req or RunRequest()
    try:
        await sess.start(
            config=req.config,
            preset=req.preset,
            overrides=req.overrides or {},
            nodes=req.nodes,
        )
    except KeyError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"启动失败: {e!r}") from e
    return {"ok": True, "running": sess.running, "nNodes": sess.config.n_nodes}


@router.post("/stop")
async def stop_sim() -> dict[str, Any]:
    """停止仿真并清理所有资源。

    总是走 sess.stop():即使 sess.running == False(例如 ns-3 线程崩溃后),
    上一次仿真留下的 docker 容器/mesh-br/mesh-tap/mesh-veth 也会在这里被兜底清掉。
    """
    sess = get_session()
    await sess.stop()
    return {"ok": True, "running": False}


@router.get("/status")
async def status() -> dict[str, Any]:
    """获取当前仿真状态。"""
    sess = get_session()
    sim = sess.sim
    return {
        "running": sess.running,
        "elapsed": sim.elapsed if sim else 0.0,
        "totalNodes": sess.config.n_nodes if sess.running else 0,
        "nodesOnline": sum(
            1 for s in sess.specs
            if (
                (s.host == "local" and sess.docker_mgr and sess.docker_mgr.is_running(s.id))
                or (s.host != "local" and sess.remote_mgrs.get(s.host) and sess.remote_mgrs[s.host].is_running(s.id))
            )
        ),
        "preset": sess.preset,
        "macModeActual": sim.mac_mode_actual if sim else "",
    }


@router.get("/presets")
async def list_presets() -> dict[str, dict[str, Any]]:
    """列出所有可用预设及其参数。"""
    return {k: v.model_dump(by_alias=True) for k, v in PRESETS.items()}


@router.get("/path")
async def find_path(src: int, dst: int) -> dict[str, Any]:
    """基于当前邻居图的 BFS,返回 src→dst 的最少跳数路径。

    路径反映"几何上谁能听到谁"——`_nodes_runtime[i].neighbors` 由 wall_pacer
    每 100ms 根据节点位置 + range_target_m 重算。在 mesh 模式下与 HWMP
    实际选择的多跳路径强相关,可作为前端拓扑可视化的近似。
    """
    sess = get_session()
    if not sess.sim or not sess.running:
        raise HTTPException(409, "没有正在运行的仿真")
    path = sess.sim.find_path(src, dst)
    if path is None:
        return {
            "src": src, "dst": dst,
            "path": [],
            "hops": -1,
            "reachable": False,
        }
    # 把节点 ID 路径附上 IP,便于前端展示
    ip_by_id = {spec.id: spec.ip for spec in sess.specs}
    return {
        "src": src, "dst": dst,
        "path": path,
        "ips": [ip_by_id.get(nid, "") for nid in path],
        "hops": len(path) - 1,
        "reachable": True,
    }
