"""远端主机管理 API。

提供主机的注册、查询、注销接口。注册信息持久化到 JSON 文件，
控制器重启后自动恢复。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from controller.orchestrator.config import HostRegisterRequest

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hosts", tags=["hosts"])

REGISTRY_PATH: Path = Path("/app/config/host_registry.json")

# 进程级内存存储：{host_ip: HostRegisterRequest}
_registry: dict[str, HostRegisterRequest] = {}


def _load_registry() -> None:
    """从 JSON 文件加载主机注册表。"""
    if not REGISTRY_PATH.exists():
        return
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        for item in data:
            req = HostRegisterRequest(**item)
            _registry[req.ip] = req
        if _registry:
            log.info("已从 %s 恢复 %d 台主机", REGISTRY_PATH, len(_registry))
    except Exception as e:
        log.warning("加载主机注册表失败: %s", e)


def _save_registry() -> None:
    """将主机注册表持久化到 JSON 文件。"""
    data = [
        {
            "ip": h.ip,
            "ssh_user": h.ssh_user,
            "ssh_key": h.ssh_key,
            "capacity": h.capacity,
            "labels": h.labels,
        }
        for h in _registry.values()
    ]
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# 模块导入时自动恢复
_load_registry()


@router.post("/register")
async def register_host(req: HostRegisterRequest) -> dict[str, Any]:
    """注册远端主机。

    同一 IP 重复注册会覆盖旧记录。
    """
    _registry[req.ip] = req
    _save_registry()
    log.info("注册远端主机 %s (user=%s capacity=%d)", req.ip, req.ssh_user, req.capacity)
    return {
        "ok": True,
        "ip": req.ip,
        "ssh_user": req.ssh_user,
        "capacity": req.capacity,
    }


@router.get("")
async def list_hosts() -> list[dict[str, Any]]:
    """列出所有已注册的远端主机。"""
    return [
        {
            "ip": h.ip,
            "ssh_user": h.ssh_user,
            "capacity": h.capacity,
            "labels": h.labels,
        }
        for h in _registry.values()
    ]


@router.put("/{host_ip}")
async def update_host(host_ip: str, req: HostRegisterRequest) -> dict[str, Any]:
    """更新远端主机的 SSH 凭据、容量等信息。

    调用时必须与现有 host_ip 一致（或使用 URL 中的 IP）。
    """
    if host_ip not in _registry:
        raise HTTPException(404, f"主机 {host_ip} 未注册")
    updated = req.model_copy(update={"ip": host_ip})
    _registry[host_ip] = updated
    _save_registry()
    log.info("更新远端主机 %s (user=%s capacity=%d)", host_ip, updated.ssh_user, updated.capacity)
    return {
        "ok": True,
        "ip": host_ip,
        "ssh_user": updated.ssh_user,
        "capacity": updated.capacity,
    }


@router.delete("/{host_ip}")
async def deregister_host(host_ip: str) -> dict[str, Any]:
    """注销远端主机。"""
    if host_ip not in _registry:
        raise HTTPException(404, f"主机 {host_ip} 未注册")
    del _registry[host_ip]
    _save_registry()
    log.info("注销远端主机 %s", host_ip)
    return {"ok": True, "ip": host_ip}


@router.get("/{host_ip}")
async def get_host(host_ip: str) -> dict[str, Any]:
    """获取单个远端主机的注册信息。"""
    h = _registry.get(host_ip)
    if h is None:
        raise HTTPException(404, f"主机 {host_ip} 未注册")
    return {
        "ip": h.ip,
        "ssh_user": h.ssh_user,
        "capacity": h.capacity,
        "labels": h.labels,
    }


def get_host_registry() -> dict[str, HostRegisterRequest]:
    """返回内部注册表（供 state.py 启动仿真时查询主机凭据）。"""
    return dict(_registry)
