#!/bin/bash
# MANET 控制器物理主机安装脚本
# 用法：bash setup-controller.sh
#
# 要求：
#   - Ubuntu 20.04/22.04（x86_64）
#   - conda（miniconda 或 anaconda）已安装并可用
#   - 当前用户在 docker 组（用于管理节点容器）
#   - root 权限（用于安装系统包和修改网络）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTROLLER_DIR="${SCRIPT_DIR}/controller"
WEB_DIR="${SCRIPT_DIR}/web-manager/dist"

log() { echo "[setup] $*"; }
error() { echo "[setup] ERROR: $*" >&2; exit 1; }

# ------------------------------------------------------------------ 0. 检查
log "检查系统环境..."

if [[ "$EUID" -ne 0 ]]; then
    error "请使用 sudo 或以 root 身份运行本脚本"
fi

if [[ "$(uname -s)" != "Linux" ]]; then
    error "本脚本仅支持 Linux"
fi

if ! command -v conda &>/dev/null; then
    error "未找到 conda。请先安装 miniconda: https://docs.conda.io/en/latest/miniconda.html"
fi

# ------------------------------------------------------------------ 1. 安装系统依赖
log "安装系统依赖（apt）..."
apt-get update
apt-get install -y \
    iproute2 net-tools iputils-ping bridge-utils \
    tcpdump iw wireless-tools socat nmap \
    libboost-all-dev libgsl-dev libpcap-dev \
    libsqlite3-dev sqlite3 libxml2-dev \
    curl wget \
    docker.io

# 确保 docker 服务运行
systemctl enable docker --now 2>/dev/null || true

# ------------------------------------------------------------------ 2. 创建 conda 环境
ENV_NAME="manet-controller"
log "创建 conda 环境: ${ENV_NAME} ..."

if conda env list | grep -q "^${ENV_NAME} "; then
    log "环境 ${ENV_NAME} 已存在，跳过创建"
else
    conda env create -f "${SCRIPT_DIR}/environment.yml"
fi

# 激活环境
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "${ENV_NAME}"

# ------------------------------------------------------------------ 3. 验证 ns-3 绑定
log "验证 ns-3 Python 绑定..."
python3 -c "
from ns import ns
_ = ns.core.Simulator
_ = ns.wifi.WifiHelper
_ = ns.tap_bridge.TapBridgeHelper
_ = ns.mesh.MeshHelper
_ = ns.spectrum.MultiModelSpectrumChannel
print('ns-3 OK: version', ns.core.NS3_VERSION)
"

# ------------------------------------------------------------------ 4. 验证控制器导入
log "验证控制器包..."
export PYTHONPATH="${CONTROLLER_DIR}:${PYTHONPATH:-}"
python3 -c "from controller.api.main import app; print('FastAPI app OK')"

# ------------------------------------------------------------------ 5. 安装 systemd 服务（可选）
read -r -p "是否安装 systemd 服务以便开机自启？ [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    cat > /etc/systemd/system/manet-controller.service <<EOF
[Unit]
Description=MANET ns-3 Controller
After=docker.service network.target

[Service]
Type=simple
User=root
WorkingDirectory=${SCRIPT_DIR}
Environment=MANET_WEB_DIR=${WEB_DIR}
Environment=PYTHONPATH=${CONTROLLER_DIR}
Environment=PATH=$(conda run -n ${ENV_NAME} which python3 | xargs dirname):/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=$(conda run -n ${ENV_NAME} which python3) -m uvicorn controller.api.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable manet-controller.service
    log "systemd 服务已安装。启动命令: systemctl start manet-controller"
fi

# ------------------------------------------------------------------ 6. 完成
log "安装完成！"
echo ""
echo "激活环境:  conda activate ${ENV_NAME}"
echo "手动启动:  PYTHONPATH=${CONTROLLER_DIR} MANET_WEB_DIR=${WEB_DIR} uvicorn controller.api.main:app --host 0.0.0.0 --port 8000"
echo "systemd:   systemctl start manet-controller"
