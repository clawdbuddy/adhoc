"""节点操作路由：GET/POST /api/nodes、/api/flows、/api/logs。"""
from __future__ import annotations

import asyncio
import logging
import re
import shlex
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from controller.api.state import get_session

log = logging.getLogger(__name__)

router = APIRouter(tags=["nodes"])

# 允许在节点内执行的命令白名单。
# 只包含网络诊断与基础查看类工具，禁止任何可能逃逸容器或破坏系统的命令。
_ALLOWED_CMDS = frozenset([
    "ping", "ping6",
    "iperf3", "iperf",
    "ip", "ss", "netstat", "route", "arp",
    "traceroute", "traceroute6", "tracepath", "tracepath6", "mtr",
    "tcpdump",
    "echo", "cat", "head", "tail", "grep", "wc", "sort", "uniq",
    "ls", "ps", "top", "df", "du", "free", "uname", "hostname", "id", "whoami",
    "wget", "curl", "nc", "nslookup", "dig", "host",
    "sh", "bash",  # 允许显式 shell，但受下方 shell_meta 检查限制
])

# 危险的 shell 元字符 — 一旦出现在字符串命令中即拒绝
_SHELL_META_RE = re.compile(r"[;|&`$(){}<>\r\n]")


def _validate_cmd(cmd: str | list[str]) -> None:
    """校验命令是否在白名单内，且不含注入字符。

     Raises:
        HTTPException(400): 命令被禁止或包含非法字符。
    """
    if isinstance(cmd, str):
        if _SHELL_META_RE.search(cmd):
            raise HTTPException(400, "命令包含非法字符")
        # 取第一个词作为命令名
        try:
            parts = shlex.split(cmd)
        except ValueError as e:
            raise HTTPException(400, f"命令解析失败: {e}") from e
        if not parts:
            raise HTTPException(400, "空命令")
        name = parts[0]
    else:
        if not cmd:
            raise HTTPException(400, "空命令")
        name = cmd[0]
        # 拒绝 list 形式的 shell -c 注入：sh -c / bash -c 可绕过元字符过滤
        if name in ("sh", "bash") and "-c" in cmd:
            raise HTTPException(400, "不允许通过 sh -c 执行命令")

    if name not in _ALLOWED_CMDS:
        raise HTTPException(400, f"命令 '{name}' 不在白名单内")


class ExecBody(BaseModel):
    """节点内执行命令的请求体。"""
    cmd: str | list[str]

    @field_validator("cmd", mode="after")
    @classmethod
    def _check_cmd(cls, v: str | list[str]) -> str | list[str]:
        _validate_cmd(v)
        return v


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
    """在指定节点容器内执行命令。支持本地和远端节点。"""
    sess = get_session()
    if not sess.docker_mgr and not sess.remote_mgrs and not sess.host_mgrs:
        raise HTTPException(409, "没有正在运行的仿真")

    # 查找节点所属主机
    spec = next((s for s in sess.specs if s.id == node_id), None)
    if spec is None:
        raise HTTPException(404, f"节点 {node_id} 不存在")

    if spec.host == "local":
        if not sess.docker_mgr:
            raise HTTPException(409, "本地 Docker 管理器不可用")
        try:
            rc, out = await asyncio.to_thread(sess.docker_mgr.exec_in, node_id, body.cmd)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
    elif spec.host_type == "host-manet":
        mgr = sess.host_mgrs.get(spec.host)
        if mgr is None:
            raise HTTPException(409, f"远端主机 {spec.host} 未连接")
        try:
            rc, out = await asyncio.to_thread(mgr.exec_in, node_id, body.cmd)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
    else:
        mgr = sess.remote_mgrs.get(spec.host)
        if mgr is None:
            raise HTTPException(409, f"远端主机 {spec.host} 未连接")
        try:
            rc, out = await asyncio.to_thread(mgr.exec_in, node_id, body.cmd)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
    return {"exitCode": rc, "output": out}


@router.get("/api/logs")
async def get_logs(node: int, tail: int = 200) -> dict[str, Any]:
    """获取指定节点容器的日志。支持本地和远端节点。"""
    sess = get_session()
    if not sess.docker_mgr and not sess.remote_mgrs and not sess.host_mgrs:
        raise HTTPException(409, "没有正在运行的仿真")

    spec = next((s for s in sess.specs if s.id == node), None)
    if spec is None:
        raise HTTPException(404, f"节点 {node} 不存在")

    if spec.host == "local":
        if not sess.docker_mgr:
            raise HTTPException(409, "本地 Docker 管理器不可用")
        try:
            text = await asyncio.to_thread(sess.docker_mgr.logs, node, tail=tail)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
    elif spec.host_type == "host-manet":
        mgr = sess.host_mgrs.get(spec.host)
        if mgr is None:
            raise HTTPException(409, f"远端主机 {spec.host} 未连接")
        try:
            text = await asyncio.to_thread(mgr.logs, node, tail=tail)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
    else:
        mgr = sess.remote_mgrs.get(spec.host)
        if mgr is None:
            raise HTTPException(409, f"远端主机 {spec.host} 未连接")
        try:
            text = await asyncio.to_thread(mgr.logs, node, tail=tail)
        except KeyError as e:
            raise HTTPException(404, str(e)) from e
    return {"node": node, "tail": tail, "logs": text}
