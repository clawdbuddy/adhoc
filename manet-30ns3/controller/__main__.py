#!/usr/bin/env python3
"""MANET 控制器独立运行入口。

支持两种启动模式：
  1. 直接运行：python -m controller
  2. PyInstaller 打包后的单文件/单目录可执行程序
"""
import os
import sys

def _find_project_root() -> str:
    """定位项目根目录（包含 controller/ 和 web-manager/dist/ 的目录）。"""
    # 策略 1：从可执行文件路径推断（PyInstaller 场景）
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        # PyInstaller --onedir: _internal/controller/__main__.py
        # PyInstaller --onefile: 临时目录
        for candidate in (exe_dir, os.path.dirname(exe_dir)):
            if os.path.isdir(os.path.join(candidate, 'web-manager', 'dist')):
                return candidate
        return exe_dir

    # 策略 2：从本文件路径推断（开发场景）
    this_file = os.path.abspath(__file__)
    # controller/__main__.py -> 上级目录
    return os.path.dirname(os.path.dirname(this_file))


def main() -> None:
    root = _find_project_root()
    controller_dir = os.path.join(root, 'controller')
    web_dir = os.path.join(root, 'web-manager', 'dist')

    # 确保 PYTHONPATH 包含 controller 包
    if controller_dir not in sys.path:
        sys.path.insert(0, controller_dir)

    os.environ.setdefault('MANET_WEB_DIR', web_dir)

    # 启动 uvicorn
    import uvicorn
    uvicorn.run(
        'controller.api.main:app',
        host='0.0.0.0',
        port=7000,
        reload=False,
    )


if __name__ == '__main__':
    main()
