#!/usr/bin/env python3
"""
MANET Host Node 入口脚本（物理主机/VM 直接使用）

与容器节点 (node-entrypoint.py) 的区别：
  - 在 host netns 中运行（docker run --net=host），直接操作宿主网络栈
  - 不需要等待控制器注入 veth；自己创建 VXLAN 隧道到控制器
  - VXLAN 接口本身承载 MAC/IP，成为 MANET 网络接口

数据路径：
  Host 应用 → vxlan-{id} (MAC=00:00:00:00:00:{id+1}, IP=192.168.100.{10+id})
    → VXLAN 封装 (UDP/4789) → Controller Host
    → Controller: vxlan-{id} → mesh-br-{id} → mesh-tap-{id} → ns-3 PHY/MAC

必需环境变量：NODE_ID, NODE_IP, CONTROLLER_IP
可选环境变量：NODE_ROLE, LOCAL_IP, VNI, SSH_ENABLE, SSH_AUTHORIZED_KEYS,
               USER_APP_MODE, USER_APP_CMD
"""

import os
import subprocess
import sys
import time
from typing import List

NODE_ID = os.environ.get("NODE_ID", "0")
NODE_IP = os.environ.get("NODE_IP", "192.168.100.10")
CONTROLLER_IP = os.environ.get("CONTROLLER_IP", "")
LOCAL_IP = os.environ.get("LOCAL_IP", "")
VNI = os.environ.get("VNI", "")
SUBNET_MASK = os.environ.get("SUBNET_MASK", "24")
NODE_ROLE = os.environ.get("NODE_ROLE", "client")
USER_APP_MODE = os.environ.get("USER_APP_MODE", "exec")
USER_APP_CMD = os.environ.get("USER_APP_CMD", "")
SSH_ENABLE = os.environ.get("SSH_ENABLE", "0")

VXLAN_NAME = f"vxlan-{NODE_ID}"
VNI_DEFAULT = 100 + int(NODE_ID)


def log(msg: str) -> None:
    print(f"[host-node-{NODE_ID}] {msg}", flush=True)


def run(cmd: List[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def mesh_mac(node_id: int) -> str:
    """ns-3 MeshPointDevice 顺序分配的 MAC 地址。"""
    return f"00:00:00:00:00:{node_id + 1:02x}"


def detect_local_ip() -> str:
    """通过默认路由自动检测本机用于 VXLAN 的 IP 地址。"""
    # 先尝试 ip route
    result = run(["ip", "route", "get", "1.1.1.1"])
    if result.returncode == 0:
        parts = result.stdout.strip().split()
        for i, p in enumerate(parts):
            if p == "src" and i + 1 < len(parts):
                return parts[i + 1]
    # fallback: hostname -I
    result = run(["hostname", "-I"])
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().split()[0]
    raise RuntimeError("无法自动检测本地 IP，请通过 LOCAL_IP 环境变量指定")


def setup_vxlan() -> None:
    """创建并配置 VXLAN 接口。"""
    if not CONTROLLER_IP:
        raise RuntimeError("缺少 CONTROLLER_IP 环境变量")

    local_ip = LOCAL_IP or detect_local_ip()
    vni = int(VNI) if VNI else VNI_DEFAULT
    mac = mesh_mac(int(NODE_ID))

    log(f"创建 VXLAN: {VXLAN_NAME} (vni={vni} local={local_ip} remote={CONTROLLER_IP})")

    # 删除同名旧接口（幂等）
    run(["ip", "link", "del", VXLAN_NAME], check=False)

    # 创建 VXLAN
    run([
        "ip", "link", "add", VXLAN_NAME,
        "type", "vxlan",
        "id", str(vni),
        "remote", CONTROLLER_IP,
        "local", local_ip,
        "dstport", "4789",
    ], check=True)

    # 设置 MAC 地址（必须与 ns-3 MeshPointDevice 一致）
    run(["ip", "link", "set", VXLAN_NAME, "address", mac], check=True)

    # 配置 IP
    run(["ip", "addr", "add", f"{NODE_IP}/{SUBNET_MASK}", "dev", VXLAN_NAME], check=True)

    # 启用接口
    run(["ip", "link", "set", VXLAN_NAME, "up"], check=True)

    log(f"VXLAN 就绪: {VXLAN_NAME} mac={mac} ip={NODE_IP}/{SUBNET_MASK}")


def setup_network() -> None:
    """配置 lo 和路由。"""
    run(["ip", "link", "set", "lo", "up"])
    run(["ip", "addr", "add", "127.0.0.1/8", "dev", "lo"])

    # 确保 MANET 子网路由指向 VXLAN 接口
    run(["ip", "route", "add", "192.168.100.0/24", "dev", VXLAN_NAME], check=False)

    # 允许回应广播 ping
    run(["sysctl", "-w", "net.ipv4.icmp_echo_ignore_broadcasts=0"])


def setup_role_services() -> None:
    """根据节点角色启动服务。"""
    if NODE_ROLE == "server":
        log("role=server: 启动 iperf3 (5201) + UDP echo (5000)")
        subprocess.Popen(["iperf3", "-s", "-p", "5201", "-D"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.Popen(["socat", "UDP4-LISTEN:5000,fork", "EXEC:cat"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        run(["sysctl", "-w", "net.ipv4.ip_forward=0"])
    elif NODE_ROLE == "gateway":
        log("role=gateway: 启用 ip_forward")
        run(["sysctl", "-w", "net.ipv4.ip_forward=1"])
    else:
        run(["sysctl", "-w", "net.ipv4.ip_forward=0"])


def setup_sshd() -> None:
    """可选 sshd。"""
    if SSH_ENABLE != "1":
        return
    log("启动 sshd")
    if not os.path.exists("/etc/ssh/ssh_host_rsa_key"):
        run(["ssh-keygen", "-A"])
    authorized = os.environ.get("SSH_AUTHORIZED_KEYS", "")
    if authorized:
        os.makedirs("/root/.ssh", mode=0o700, exist_ok=True)
        with open("/root/.ssh/authorized_keys", "w") as f:
            f.write(authorized + "\n")
        os.chmod("/root/.ssh/authorized_keys", 0o600)
    subprocess.Popen(["/usr/sbin/sshd"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def dispatch_user_app() -> None:
    """根据 USER_APP_MODE 执行用户程序。"""
    if USER_APP_MODE == "bind":
        cmd = USER_APP_CMD or "/opt/userapp/run.sh"
        if os.path.isfile(cmd) and not os.access(cmd, os.X_OK):
            os.chmod(cmd, 0o755)
        if not os.path.exists(cmd):
            log(f"USER_APP_MODE=bind 但 {cmd} 不存在；进入空闲休眠")
            while True:
                time.sleep(3600)
        log(f"执行 bind 应用: {cmd}")
        os.execv(cmd, [cmd])
    elif USER_APP_MODE == "image":
        cmd = USER_APP_CMD or "/opt/userapp/run.sh"
        if not os.path.exists(cmd):
            log(f"USER_APP_MODE=image 但 {cmd} 缺失；进入空闲休眠")
            while True:
                time.sleep(3600)
        log(f"执行 image 应用: {cmd}")
        os.execv(cmd, [cmd])
    else:
        log("USER_APP_MODE=exec: 空闲等待后端通过 ssh/docker exec 驱动")
        while True:
            time.sleep(3600)


def main() -> None:
    log(f"启动 (role={NODE_ROLE} mode={USER_APP_MODE} ip={NODE_IP}/{SUBNET_MASK})")

    try:
        setup_vxlan()
    except Exception as e:
        log(f"VXLAN 设置失败: {e}")
        sys.exit(1)

    setup_network()
    setup_role_services()
    setup_sshd()

    result = run(["ip", "-4", "addr", "show", VXLAN_NAME])
    log(f"上线: {result.stdout.strip()}")

    dispatch_user_app()


if __name__ == "__main__":
    main()
