#!/bin/bash
# MANET 控制器 PyInstaller 打包脚本
# 用法：bash build-controller.sh
#
# 输出：dist/manet-controller/ 目录（包含独立可执行程序 + 所有依赖）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_NAME="manet-controller"

log() { echo "[build] $*"; }
error() { echo "[build] ERROR: $*" >&2; exit 1; }

# ------------------------------------------------------------------ 0. 检查
if ! command -v conda &>/dev/null; then
    error "未找到 conda。请先运行 setup-controller.sh 或手动安装 miniconda"
fi

if [[ ! -d "${SCRIPT_DIR}/web-manager/dist" ]]; then
    error "未找到 web-manager/dist;请先 cd web-manager && npm install && npm run build"
fi

source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate "${ENV_NAME}"

# ------------------------------------------------------------------ 1. 收集 ns-3 .so 路径
log "收集 ns-3 二进制依赖..."
NS3_SO_DIR=$(python3 -c "
import ns, os
print(os.path.dirname(ns.__file__))
")
log "ns-3 包路径: ${NS3_SO_DIR}"

# ------------------------------------------------------------------ 2. PyInstaller 打包
log "开始 PyInstaller 打包..."

# --onedir: 输出为目录（更可靠，避免单文件大小限制）
# --name: 可执行文件名
# --add-data: 包含 web-manager 静态资源
# --hidden-import: 确保 ns-3 子模块被正确分析
pyinstaller \
    --onedir \
    --name manet-controller \
    --add-data "${SCRIPT_DIR}/web-manager/dist:web-manager/dist" \
    --hidden-import=ns.core \
    --hidden-import=ns.network \
    --hidden-import=ns.internet \
    --hidden-import=ns.wifi \
    --hidden-import=ns.mobility \
    --hidden-import=ns.tap_bridge \
    --hidden-import=ns.flow_monitor \
    --hidden-import=ns.propagation \
    --hidden-import=ns.spectrum \
    --hidden-import=ns.aodv \
    --hidden-import=ns.olsr \
    --hidden-import=ns.dsdv \
    --hidden-import=ns.dsr \
    --hidden-import=ns.mesh \
    --hidden-import=docker \
    --hidden-import=pyroute2 \
    --clean \
    --noconfirm \
    "${SCRIPT_DIR}/controller/__main__.py"

# ------------------------------------------------------------------ 3. 复制额外文件
log "复制项目文件到输出目录..."
cp -r "${SCRIPT_DIR}/controller" "${SCRIPT_DIR}/dist/manet-controller/_internal/" 2>/dev/null || true

# ------------------------------------------------------------------ 4. 完成
log "打包完成！"
echo ""
echo "输出目录: ${SCRIPT_DIR}/dist/manet-controller/"
echo "启动命令: ${SCRIPT_DIR}/dist/manet-controller/manet-controller"
echo ""
echo "运行前请确保："
echo "  1. Docker 服务已启动（systemctl start docker）"
echo "  2. 当前用户在 docker 组，或已配置 DOCKER_HOST"
echo "  3. 以 root 权限运行（需要创建 br-ns3 / veth / tap）"
