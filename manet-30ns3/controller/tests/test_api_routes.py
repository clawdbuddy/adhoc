"""Integration tests for FastAPI REST routes.

Uses FastAPI's TestClient — no real network, no real Docker, no real ns-3.
Mocks the Session singleton so tests are fully isolated from state.py.

Covers: TC-API-001 through TC-API-015.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from fastapi.testclient import TestClient
from contextlib import asynccontextmanager

from controller.orchestrator.config import PRESETS


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class MockSim:
    elapsed = 45.0
    mac_mode_actual = "mesh"

    def find_path(self, src, dst):
        if src == 0 and dst == 4:
            return [0, 2, 4]
        return None


class MockSpecs:
    def __init__(self, n=5):
        self._specs = [
            MagicMock(id=i, ip=f"192.168.100.{10+i}") for i in range(n)
        ]

    def __iter__(self):
        return iter(self._specs)

    def __len__(self):
        return len(self._specs)


def make_mock_session(**overrides):
    sess = MagicMock()
    sess.running = False
    sess.config = MagicMock()
    sess.config.n_nodes = 5
    sess.config.routing_protocol = "aodv"
    sess.preset = "debug"
    sess.sim = None
    sess.specs = MockSpecs()
    sess.docker_mgr = None
    sess.host_mgrs = {}
    sess.remote_mgrs = {}
    # Use AsyncMock so the await in routes_sim.py works without hitting real code
    sess.start = AsyncMock(return_value=None)
    sess.stop = AsyncMock(return_value=None)
    for k, v in overrides.items():
        setattr(sess, k, v)
    return sess


# ---------------------------------------------------------------------------
# No-op lifespan avoids UDP port binding
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _stub_lifespan(app):
    yield


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self):
        from controller.api.main import app
        app.router.lifespan_context = _stub_lifespan
        with patch("controller.api.state.get_session", return_value=make_mock_session()):
            with TestClient(app) as client:
                response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {"ok": True}


class TestSimStart:
    """Test POST /api/sim/start endpoint.

    Mocks:
    - sess.start: prevents actual simulation startup
    - _reap_orphans: prevents netlink calls inside state.py
    - list_stale_links: prevents netlink calls inside state.py
    """

    def _start_sim(self, mock_sess):
        from controller.api.main import app
        app.router.lifespan_context = _stub_lifespan
        # Patch where the local binding is used (routes_sim.py), not just where
        # get_session is defined. This is needed because routes_sim does:
        #   "from controller.api.state import get_session"
        # which creates a local reference that must also be patched.
        with patch("controller.api.state._reap_orphans"):
            with patch("controller.api.state.list_stale_links", return_value=[]):
                with patch("controller.api.routes_sim.get_session", return_value=mock_sess):
                    with patch("controller.api.state.get_session", return_value=mock_sess):
                        with TestClient(app) as client:
                            response = client.post("/api/sim/start", json={})
        return response, mock_sess

    def test_start_sim_returns_ok(self):
        response, _ = self._start_sim(make_mock_session(running=False))
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_start_sim_already_running_returns_409(self):
        response, _ = self._start_sim(make_mock_session(running=True))
        assert response.status_code == 409

    def test_start_sim_with_unknown_preset_returns_400(self):
        from controller.api.main import app
        app.router.lifespan_context = _stub_lifespan
        sess = make_mock_session(running=False)
        sess.start.side_effect = KeyError("unknown preset")
        with patch("controller.api.state._reap_orphans"):
            with patch("controller.api.state.list_stale_links", return_value=[]):
                with patch("controller.api.state.get_session", return_value=sess):
                    with TestClient(app) as client:
                        response = client.post(
                            "/api/sim/start",
                            json={"preset": "nonexistent_preset_xyz"},
                        )
        assert response.status_code == 400

    def test_start_sim_with_valid_preset(self):
        response, _ = self._start_sim(make_mock_session(running=False))
        assert response.status_code == 200

    def test_start_sim_with_config_override(self):
        sess = make_mock_session(running=False)
        response, _ = self._start_sim(sess)
        assert response.status_code == 200


class TestSimStop:
    def test_stop_sim_returns_ok(self):
        from controller.api.main import app
        app.router.lifespan_context = _stub_lifespan
        sess = make_mock_session()
        with patch("controller.api.state._reap_orphans"):
            with patch("controller.api.state.list_stale_links", return_value=[]):
                with patch("controller.api.state.get_session", return_value=sess):
                    with TestClient(app) as client:
                        response = client.post("/api/sim/stop")
        assert response.status_code == 200
        assert response.json()["ok"] is True


class TestSimStatus:
    def test_status_returns_running_false(self):
        from controller.api.main import app
        app.router.lifespan_context = _stub_lifespan
        sess = make_mock_session(running=False)
        with patch("controller.api.routes_sim.get_session", return_value=sess):
            with patch("controller.api.state.get_session", return_value=sess):
                with TestClient(app) as client:
                    response = client.get("/api/sim/status")
        assert response.status_code == 200
        assert response.json()["running"] is False

    def test_status_returns_running_true(self):
        from controller.api.main import app
        app.router.lifespan_context = _stub_lifespan
        sess = make_mock_session(running=True, sim=MockSim())
        with patch("controller.api.routes_sim.get_session", return_value=sess):
            with patch("controller.api.state.get_session", return_value=sess):
                with TestClient(app) as client:
                    response = client.get("/api/sim/status")
        assert response.status_code == 200
        assert response.json()["running"] is True
        assert response.json()["elapsed"] == 45.0


class TestSimPresets:
    def test_presets_returns_dict(self):
        from controller.api.main import app
        app.router.lifespan_context = _stub_lifespan
        sess = make_mock_session()
        with patch("controller.api.state.get_session", return_value=sess):
            with TestClient(app) as client:
                response = client.get("/api/sim/presets")
        assert response.status_code == 200
        data = response.json()
        assert "debug" in data
        assert "default" in data
        assert "tactical" in data

    def test_all_presets_have_required_keys(self):
        from controller.api.main import app
        app.router.lifespan_context = _stub_lifespan
        sess = make_mock_session()
        with patch("controller.api.state.get_session", return_value=sess):
            with TestClient(app) as client:
                response = client.get("/api/sim/presets")
        required_keys = {"nNodes", "macMode", "routingProtocol", "simulationTime"}
        for name, preset in response.json().items():
            missing = required_keys - set(preset.keys())
            assert not missing, f"preset '{name}' missing keys: {missing}"


class TestSimPath:
    def test_path_returns_bfs_result(self):
        from controller.api.main import app
        app.router.lifespan_context = _stub_lifespan
        sess = make_mock_session(running=True, sim=MockSim())
        with patch("controller.api.routes_sim.get_session", return_value=sess):
            with patch("controller.api.state.get_session", return_value=sess):
                with TestClient(app) as client:
                    response = client.get("/api/sim/path?src=0&dst=4")
        assert response.status_code == 200
        data = response.json()
        assert data["reachable"] is True
        assert data["hops"] == 2
        assert data["path"] == [0, 2, 4]

    def test_path_no_sim_returns_409(self):
        from controller.api.main import app
        app.router.lifespan_context = _stub_lifespan
        sess = make_mock_session(running=False, sim=None)
        with patch("controller.api.routes_sim.get_session", return_value=sess):
            with patch("controller.api.state.get_session", return_value=sess):
                with TestClient(app) as client:
                    response = client.get("/api/sim/path?src=0&dst=1")
        assert response.status_code == 409

    def test_path_unreachable_returns_reachable_false(self):
        from controller.api.main import app
        app.router.lifespan_context = _stub_lifespan
        sess = make_mock_session(running=True, sim=MockSim())
        with patch("controller.api.routes_sim.get_session", return_value=sess):
            with patch("controller.api.state.get_session", return_value=sess):
                with TestClient(app) as client:
                    response = client.get("/api/sim/path?src=0&dst=99")
        assert response.status_code == 200
        data = response.json()
        assert data["reachable"] is False
        assert data["hops"] == -1

    def test_path_includes_ips(self):
        from controller.api.main import app
        app.router.lifespan_context = _stub_lifespan
        sess = make_mock_session(running=True, sim=MockSim())
        with patch("controller.api.routes_sim.get_session", return_value=sess):
            with patch("controller.api.state.get_session", return_value=sess):
                with TestClient(app) as client:
                    response = client.get("/api/sim/path?src=0&dst=4")
        data = response.json()
        assert "ips" in data
        assert len(data["ips"]) == len(data["path"])