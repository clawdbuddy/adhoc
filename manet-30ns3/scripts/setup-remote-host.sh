#!/bin/bash
# MANET 远端主机初始化脚本
# 在每台要运行节点容器的远端主机上执行一次（或每次系统重启后）
#
# Usage:
#   curl -fsSL https://.../setup-remote-host.sh | sudo bash
#   # or
#   bash scripts/setup-remote-host.sh
#
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ------------------------------------------------------------------ 0. root 检查
if [ "$EUID" -ne 0 ]; then
    log_error "请使用 root 权限运行此脚本: sudo bash $0"
    exit 1
fi

# ------------------------------------------------------------------ 1. Docker 检查/安装
if command -v docker &> /dev/null; then
    log_info "Docker 已安装: $(docker --version)"
else
    log_warn "Docker 未安装，正在安装..."
    apt-get update
    apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg lsb-release
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
        gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu \
        $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y --no-install-recommends docker-ce docker-ce-cli containerd.io
    systemctl enable docker
    systemctl start docker
    log_info "Docker 安装完成"
fi

# ------------------------------------------------------------------ 2. 内核模块
log_info "加载内核模块..."
MODULES="tun tap bridge veth vxlan"
for mod in $MODULES; do
    if ! lsmod | grep -q "^$mod "; then
        modprobe "$mod" 2>/dev/null || log_warn "无法加载模块 $mod"
    fi
done

# 持久化模块加载
echo "tun" > /etc/modules-load.d/manet.conf
echo "tap" >> /etc/modules-load.d/manet.conf
echo "bridge" >> /etc/modules-load.d/manet.conf
echo "veth" >> /etc/modules-load.d/manet.conf
echo "vxlan" >> /etc/modules-load.d/manet.conf

# ------------------------------------------------------------------ 3. sysctl
log_info "配置网络 sysctl..."
cat > /etc/sysctl.d/99-manet.conf << 'EOF'
# MANET 仿真所需
net.ipv4.ip_forward=1
net.ipv4.conf.all.forwarding=1
net.bridge.bridge-nf-call-iptables=0
net.bridge.bridge-nf-call-ip6tables=0
EOF
sysctl --system

# ------------------------------------------------------------------ 4. 防火墙
log_info "配置防火墙放行 VXLAN (UDP 4789)..."
if command -v ufw &> /dev/null; then
    ufw allow 4789/udp comment 'MANET VXLAN' || true
    log_info "UFW 已放行 UDP 4789"
elif command -v firewall-cmd &> /dev/null; then
    firewall-cmd --permanent --add-port=4789/udp || true
    firewall-cmd --reload || true
    log_info "firewalld 已放行 UDP 4789"
else
    # 兜底: iptables
    iptables -C INPUT -p udp --dport 4789 -j ACCEPT 2>/dev/null || \
        iptables -I INPUT -p udp --dport 4789 -j ACCEPT
    log_info "iptables 已放行 UDP 4789"
fi

# ------------------------------------------------------------------ 5. SSH 配置提示
log_info "检查 SSH 服务..."
if ! systemctl is-active --quiet sshd 2>/dev/null && ! systemctl is-active --quiet ssh 2>/dev/null; then
    apt-get install -y --no-install-recommends openssh-server
    systemctl enable ssh
    systemctl start ssh
fi

# ------------------------------------------------------------------ 6. 节点镜像
log_info "检查 manet-node 镜像..."
if docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "^manet-node:latest$"; then
    log_info "manet-node:latest 镜像已存在"
else
    log_warn "manet-node:latest 镜像未找到"
    log_warn "请从控制器主机复制镜像:"
    echo "    # 在控制器主机上执行:"
    echo "    docker save manet-node:latest | ssh root@$(hostname -I | awk '{print $1}') 'docker load'"
fi

# ------------------------------------------------------------------ 7. 完成
echo ""
echo "========================================"
log_info "远端主机初始化完成"
echo "========================================"
echo ""
echo "下一步:"
echo "1. 确保控制器主机的 SSH 公钥已添加到本机的 ~/.ssh/authorized_keys"
echo "   (以便控制器可以通过 SSH 免密连接到此主机)"
echo ""
echo "2. 在控制器上注册此主机:"
echo "   curl -X POST localhost:8000/api/hosts/register \\"
echo "     -H 'content-type: application/json' \\"
echo "     -d '{\"ip\":\"$(hostname -I | awk '{print $1}')\",\"ssh_user\":\"root\",\"capacity\":4}'"
echo ""
