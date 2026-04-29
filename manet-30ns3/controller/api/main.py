"""FastAPI application entrypoint.

Start with:
    uvicorn controller.api.main:app --host 0.0.0.0 --port 8000

Inside the controller container, this is launched by /entrypoint.sh.
The app must run with PYTHONPATH=/opt/ns3/ns-3/build/bindings/python so that
`from ns import ns` succeeds.
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from controller.api import routes_config, routes_nodes, routes_sim, ws_telemetry
from controller.api.state import get_session

log = logging.getLogger("manet.api")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("MANET controller starting up")
    try:
        yield
    finally:
        log.info("MANET controller shutting down")
        sess = get_session()
        if sess.running:
            try:
                await sess.stop()
            except Exception:  # noqa: BLE001
                log.exception("error stopping session during shutdown")


app = FastAPI(title="MANET ns-3 Controller", version="0.1.0", lifespan=lifespan)

# In production, the React build is served by the same server, so CORS is unused.
# In dev, the Vite dev server proxies /api and /ws here.
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
app.include_router(ws_telemetry.router)


@app.get("/api/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


# Serve the built React UI (production), if present. The controller image
# expects /app/dist to be populated at build time.
WEB_DIR = os.environ.get("MANET_WEB_DIR", "/app/dist")
if os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    log.info("serving React UI from %s", WEB_DIR)
else:
    log.info("no UI dir at %s; running in API-only mode", WEB_DIR)
