"""GET/PUT /api/config — view & stage simulation parameters."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from controller.api.state import get_session
from controller.orchestrator import SimConfig

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config() -> dict[str, Any]:
    sess = get_session()
    return sess.config.model_dump(by_alias=True)


@router.put("")
async def put_config(cfg: SimConfig) -> dict[str, Any]:
    sess = get_session()
    if sess.running:
        # Don't mutate during a live run; the user must stop and restart.
        return {
            "ok": False,
            "reason": "simulator running; stop before changing config",
            "current": sess.config.model_dump(by_alias=True),
        }
    sess.config = cfg
    return {"ok": True, "config": sess.config.model_dump(by_alias=True)}
