"""FastAPI 应用入口。

启动方式：
    uvicorn controller.api.main:app --host 0.0.0.0 --port 8000

在控制器容器内由 /entrypoint.sh 启动。
PYTHONPATH 须包含 ns-3 Python 绑定目录（Docker：/opt/ns3/ns-3/build/bindings/python）。
导入双路径兼容：cppyy（pip install ns3）走 `from ns import ns`，
pybindgen（NS-3.36 源码编译）走 `import ns.core` 等显式子模块导入，
具体见 controller/orchestrator/sim_runner.py:_import_ns()。
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from controller.api import routes_config, routes_dynamic, routes_nodes, routes_sim, ws_telemetry
from controller.api.state import get_session

log = logging.getLogger("manet.api")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("MANET 控制器启动")
    try:
        yield
    finally:
        log.info("MANET 控制器关闭")
        sess = get_session()
        if sess.running:
            try:
                await sess.stop()
            except Exception:  # noqa: BLE001
                log.exception("关闭期间停止会话出错")


app = FastAPI(title="MANET ns-3 控制器", version="0.1.0", lifespan=lifespan)

# 生产环境中 React 构建产物由同一服务器托管，因此 CORS 实际未使用。
# 开发模式下 Vite 开发服务器将 /api 和 /ws 代理到本服务。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(routes_sim.router)
app.include_router(routes_config.router)
app.include_router(routes_nodes.router)
app.include_router(routes_dynamic.router)
app.include_router(ws_telemetry.router)


@app.get("/api/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


# 托管构建后的 React UI（生产环境）。控制器镜像要求在构建时填充 /app/dist。
WEB_DIR = os.environ.get("MANET_WEB_DIR", "/app/dist")
if os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    log.info("从 %s 提供 React UI", WEB_DIR)
else:
    log.info("%s 处无 UI 目录；以纯 API 模式运行", WEB_DIR)
