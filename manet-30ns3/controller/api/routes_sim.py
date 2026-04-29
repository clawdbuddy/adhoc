"""POST/GET /api/sim/* — simulator lifecycle."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from controller.api.state import Session, get_session
from controller.orchestrator import RunRequest, PRESETS

router = APIRouter(prefix="/api/sim", tags=["sim"])


@router.post("/start")
async def start_sim(req: RunRequest | None = None) -> dict[str, Any]:
    sess: Session = get_session()
    if sess.running:
        raise HTTPException(409, "simulator already running")
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
        raise HTTPException(500, f"start failed: {e!r}") from e
    return {"ok": True, "running": sess.running, "nNodes": sess.config.n_nodes}


@router.post("/stop")
async def stop_sim() -> dict[str, Any]:
    sess: Session = get_session()
    if not sess.running:
        return {"ok": True, "running": False}
    await sess.stop()
    return {"ok": True, "running": False}


@router.get("/status")
async def status() -> dict[str, Any]:
    sess: Session = get_session()
    sim = sess.sim
    return {
        "running": sess.running,
        "elapsed": sim.elapsed if sim else 0.0,
        "totalNodes": sess.config.n_nodes if sess.running else 0,
        "nodesOnline": sum(
            1 for s in sess.specs if sess.docker_mgr and sess.docker_mgr.is_running(s.id)
        ),
        "preset": None,
    }


@router.get("/presets")
async def list_presets() -> dict[str, dict[str, Any]]:
    return {k: v.model_dump(by_alias=True) for k, v in PRESETS.items()}
