"""Mutable session state shared by API routes.

A single Session lives in `app.state.session`. /api/sim/start mutates it.
We keep this small and explicit (no DI framework) — exactly one simulator
runs at a time on the host.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional

from controller.orchestrator import SimConfig, NodeSpec, PRESETS
from controller.orchestrator.config import load_config
from controller.orchestrator.docker_mgr import DockerMgr
from controller.orchestrator.netns import (
    DEFAULT_BRIDGE,
    ensure_bridge,
    teardown,
)
from controller.orchestrator.sim_runner import SimRunner
from controller.orchestrator.telemetry import Telemetry

log = logging.getLogger(__name__)


def default_node_specs(config: SimConfig) -> list[NodeSpec]:
    """Generate one spec per node when the caller didn't supply them.

    Matches start-simulation.sh role assignment: node-0 = server, node-15 = gateway,
    rest = client. IPs start at 192.168.100.10.
    """
    specs: list[NodeSpec] = []
    for i in range(config.n_nodes):
        if i == 0:
            role = "server"
        elif i == 15 and config.n_nodes > 15:
            role = "gateway"
        else:
            role = "client"
        specs.append(NodeSpec(id=i, ip=f"192.168.100.{10 + i}", role=role))
    return specs


@dataclass
class Session:
    """Process-wide singleton of the current simulation session."""

    config: SimConfig = field(default_factory=SimConfig)
    sim: Optional[SimRunner] = None
    docker_mgr: Optional[DockerMgr] = None
    telemetry: Optional[Telemetry] = None
    specs: list[NodeSpec] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ---------------------------------------------------------- lifecycle
    async def start(
        self,
        *,
        config: SimConfig | None = None,
        preset: str | None = None,
        overrides: dict | None = None,
        nodes: list[NodeSpec] | None = None,
    ) -> None:
        with self._lock:
            if self.sim and self.sim.running:
                raise RuntimeError("simulator already running")

        # Resolve config: explicit > preset > overrides > current
        if config is not None:
            cfg = config
        elif preset is not None:
            cfg = PRESETS[preset].model_copy()
        else:
            cfg = self.config
        if overrides:
            cfg = cfg.merged_with(overrides)

        specs = nodes if nodes is not None else default_node_specs(cfg)

        log.info("starting sim (n=%d preset=%s)", cfg.n_nodes, preset)

        # 1. Bridge
        ensure_bridge()

        # 2. Containers (each call also creates veth pair + tap and moves
        #    veth peer into the netns).
        docker_mgr = DockerMgr()
        try:
            docker_mgr.start_all(specs, cfg)
        except Exception:
            docker_mgr.stop_all()
            raise

        # 3. ns-3 simulator (drives all the TAPs created in step 2)
        sim = SimRunner(cfg)
        try:
            sim.start()
        except Exception:
            docker_mgr.stop_all()
            teardown(cfg.n_nodes)
            raise

        # 4. Telemetry pump
        tele = Telemetry(sim, docker_mgr, specs)
        await tele.start(period=1.0)

        with self._lock:
            self.config = cfg
            self.docker_mgr = docker_mgr
            self.sim = sim
            self.telemetry = tele
            self.specs = specs

    async def stop(self) -> None:
        with self._lock:
            sim, docker_mgr, tele, specs = self.sim, self.docker_mgr, self.telemetry, self.specs
            self.sim = self.docker_mgr = self.telemetry = None
            self.specs = []

        if tele is not None:
            await tele.stop()
        if sim is not None:
            sim.stop()
        if docker_mgr is not None:
            docker_mgr.stop_all()
        teardown(len(specs))

    # ---------------------------------------------------------- accessors
    @property
    def running(self) -> bool:
        return self.sim is not None and self.sim.running


# ----- singleton accessor used by routers -----------------------------------
_session = Session()


def get_session() -> Session:
    return _session
