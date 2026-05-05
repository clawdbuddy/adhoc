#!/usr/bin/env python3
"""
MANET 节点容器入口脚本（Python 实现）

每个容器 = 一个独立网络节点

网络隔离：
  - 容器在独立网络命名空间中运行（docker run 时指定 --net=none）。
  - 控制器在容器启动后注入 veth 对：vethns<ID> 被移入本 netns 并重命名为 eth0。
  - 宿主侧的 veth 和 tap-<ID> 接入该节点专属的独立桥 br-ns3-<ID>；
    tap-<ID> 绑定到 ns-3 TapBridge（UseLocal 模式）。
    在 UseLocal 模式下，ns-3 自行打开宿主预创建的持久 TAP 设备，
    因此所有跨节点流量都必须经过 ns-3 的 PHY/MAC 信道模型。

数据路径：
  Container -> eth0 -> vethns<ID>（宿主）-> br-ns3-<ID> -> tap-<ID> -> ns-3
                                                                       -> AdHoc/Mesh MAC
                                                                       -> WiFi PHY + 路径损耗 + 衰落
                                                                       -> 对端节点的 tap -> 对端 br-ns3-<ID> -> 对端 eth0

用户软件加载模式（USER_APP_MODE）：
  bind  - 宿主 bind-mount /opt/userapp；入口运行 ${USER_APP_CMD:-/opt/userapp/run.sh}
  image - 容器基于派生镜像启动，镜像内已烘焙 /opt/userapp/run.sh
  exec  - 容器保持空闲（可选 sshd）；后端通过 docker exec / ssh 推送二进制

必需环境变量：NODE_ID, NODE_IP
可选环境变量：NODE_ROLE（client|server|gateway）、BRIDGE_IP、USER_APP_MODE、
               USER_APP_CMD、SSH_AUTHORIZED_KEYS、SSH_ENABLE（1|0）
"""

import os
import subprocess
import sys
import time
from typing import List

NODE_ID = os.environ.get("NODE_ID", "0")
NODE_IP = os.environ.get("NODE_IP", "192.168.100.10")
BRIDGE_IP = os.environ.get("BRIDGE_IP", "192.168.100.1")
SUBNET_MASK = os.environ.get("SUBNET_MASK", "24")
NODE_ROLE = os.environ.get("NODE_ROLE", "client")
USER_APP_MODE = os.environ.get("USER_APP_MODE", "exec")
USER_APP_CMD = os.environ.get("USER_APP_CMD", "")
SSH_ENABLE = os.environ.get("SSH_ENABLE", "0")


def log(msg: str) -> None:
    print(f"[node-{NODE_ID}] {msg}", flush=True)


def run(cmd: List[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def wait_for_eth0(timeout: float = 30.0, interval: float = 0.5) -> bool:
    """等待控制器注入 eth0。"""
    end = time.time() + timeout
    while time.time() < end:
        result = run(["ip", "link", "show", "eth0"])
        if result.returncode == 0:
            return True
        time.sleep(interval)
    return False


def bring_down_extra_interfaces() -> None:
    """严格隔离：关闭除 lo 和 eth0 之外的所有接口。"""
    result = run(["ip", "-o", "link", "show"])
    for line in result.stdout.splitlines():
        # 格式: "<idx>: <name>: <flags>..."
        parts = line.split(": ", 2)
        if len(parts) < 2:
            continue
        iface = parts[1].split("@")[0].strip()
        if iface in ("lo", "eth0", ""):
            continue
        run(["ip", "link", "set", iface, "down"])


def setup_network() -> None:
    """配置 lo 和 eth0，设置默认路由。"""
    run(["ip", "link", "set", "lo", "up"])
    run(["ip", "addr", "add", "127.0.0.1/8", "dev", "lo"])

    run(["ip", "link", "set", "eth0", "down"])
    run(["ip", "addr", "flush", "dev", "eth0"])
    run(["ip", "addr", "add", f"{NODE_IP}/{SUBNET_MASK}", "dev", "eth0"])
    run(["ip", "link", "set", "eth0", "up"])

    # 默认路由经由宿主网桥（作为模拟子网的常规网关 IP；实际转发由 ns-3 路由决定）。
    # 在独立桥架构中 br-ns3-<ID> 通常不配置 IPv4 地址，因此添加默认路由可能失败；
    # 同子网通信不需要网关，失败仅影响跨子网/外网访问，不影响 MANET 节点间通信。
    route_res = run(["ip", "route", "add", "default", "via", BRIDGE_IP])
    if route_res.returncode != 0:
        log(f"默认路由设置失败（可忽略）: {route_res.stderr.strip() or '网桥无 IPv4 地址'}")

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
    """可选 sshd（仅在 exec 模式下，当操作员希望通过 ssh 推送代码时使用）。"""
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
        log("USER_APP_MODE=exec: 空闲等待后端通过 docker exec / ssh 驱动")
        while True:
            time.sleep(3600)


def main() -> None:
    log(f"启动 (role={NODE_ROLE} mode={USER_APP_MODE} ip={NODE_IP}/{SUBNET_MASK})")

    # 等待控制器注入 eth0
    if not wait_for_eth0():
        log("错误：控制器在 30 秒内未注入 eth0")
        sys.exit(1)

    bring_down_extra_interfaces()
    setup_network()
    setup_role_services()
    setup_sshd()

    result = run(["ip", "-4", "addr", "show", "eth0"])
    log(f"上线: {result.stdout.strip()}")

    dispatch_user_app()


if __name__ == "__main__":
    main()
