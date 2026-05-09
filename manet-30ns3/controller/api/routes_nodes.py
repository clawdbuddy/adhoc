"""节点操作路由：GET/POST /api/nodes、/api/flows、/api/logs。"""
from __future__ import annotations

import asyncio
import re
import shlex
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from controller.api.state import get_session

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
    """在指定节点容器内执行命令。"""
    sess = get_session()
    if not sess.docker_mgr:
        raise HTTPException(409, "没有正在运行的仿真")
    try:
        rc, out = await asyncio.to_thread(sess.docker_mgr.exec_in, node_id, body.cmd)
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
        text = await asyncio.to_thread(sess.docker_mgr.logs, node, tail=tail)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"node": node, "tail": tail, "logs": text}
