"""节点操作路由：GET/POST /api/nodes、/api/flows、/api/logs。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from controller.api.state import get_session

router = APIRouter(tags=["nodes"])


class ExecBody(BaseModel):
    """节点内执行命令的请求体。"""
    cmd: str | list[str]


@router.get("/api/nodes")
async def list_nodes() -> list[dict[str, Any]]:
    """列出所有节点的当前状态。"""
    sess = get_session()
    if not sess.telemetry:
        return []
    snap = sess.telemetry.snapshot()
    return snap["nodes"]


@router.get("/api/flows")
async def list_flows() -> list[dict[str, Any]]:
    """列出 FlowMonitor 统计的所有流量。"""
    sess = get_session()
    if not sess.telemetry:
        return []
    snap = sess.telemetry.snapshot()
    return snap["flows"]


@router.post("/api/nodes/{node_id}/exec")
async def exec_in_node(node_id: int, body: ExecBody) -> dict[str, Any]:
    """在指定节点容器内执行命令。"""
    sess = get_session()
    if not sess.docker_mgr:
        raise HTTPException(409, "没有正在运行的仿真")
    try:
        rc, out = sess.docker_mgr.exec_in(node_id, body.cmd)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"exitCode": rc, "output": out}


@router.get("/api/logs")
async def get_logs(node: int, tail: int = 200) -> dict[str, Any]:
    """获取指定节点容器的日志。"""
    sess = get_session()
    if not sess.docker_mgr:
        raise HTTPException(409, "没有正在运行的仿真")
    try:
        text = sess.docker_mgr.logs(node, tail=tail)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"node": node, "tail": tail, "logs": text}
