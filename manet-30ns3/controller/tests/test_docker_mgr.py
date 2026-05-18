"""Unit tests for controller/orchestrator/docker_mgr.py.

Docker SDK calls are patched with mocks so these run anywhere.
Real Docker/netns operations require a privileged Linux environment
and are covered by E2E tests (TC-E2E-*).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from controller.orchestrator.docker_mgr import DockerMgr, RuntimeNode, CONTAINER_PREFIX
from controller.orchestrator.config import NodeSpec, SimConfig


@pytest.fixture
def mock_docker_client():
    return MagicMock()


@pytest.fixture
def docker_mgr(mock_docker_client):
    return DockerMgr(client=mock_docker_client)


@pytest.fixture
def sample_spec():
    return NodeSpec(id=0, ip="192.168.100.10", role="client")


@pytest.fixture
def sample_config():
    return SimConfig(n_nodes=5)


def _make_runtime_node(node_id: int = 0, container_id: str = "c123") -> RuntimeNode:
    return RuntimeNode(
        spec=NodeSpec(id=node_id, ip=f"192.168.100.{10+node_id}"),
        container_id=container_id,
        pid=12345,
        name=f"manet-node-{node_id}",
    )


class TestRuntimeNode:
    def test_runtime_node_fields(self):
        rn = RuntimeNode(
            spec=NodeSpec(id=1, ip="192.168.100.11"),
            container_id="abc123",
            pid=12345,
            name="manet-node-1",
        )
        assert rn.spec.id == 1
        assert rn.container_id == "abc123"
        assert rn.pid == 12345


class TestDockerMgrInit:
    def test_uses_provided_client(self, mock_docker_client):
        mgr = DockerMgr(client=mock_docker_client)
        assert mgr.client is mock_docker_client

    def test_empty_nodes_on_init(self, docker_mgr):
        assert docker_mgr._nodes == {}

    def test_status_cache_empty_on_init(self, docker_mgr):
        assert docker_mgr._status_cache == {}


class TestIsRunning:
    def test_returns_true_for_running_container(self, docker_mgr, mock_docker_client):
        docker_mgr._nodes[0] = _make_runtime_node(0, "container-0")
        mock_container = MagicMock()
        mock_container.status = "running"
        mock_docker_client.containers.get.return_value = mock_container

        assert docker_mgr.is_running(0) is True
        mock_docker_client.containers.get.assert_called_once_with("container-0")

    def test_returns_false_for_missing_container(self, docker_mgr, mock_docker_client):
        docker_mgr._nodes[99] = _make_runtime_node(99, "container-99")
        from docker.errors import NotFound
        mock_docker_client.containers.get.side_effect = NotFound("not found")
        assert docker_mgr.is_running(99) is False

    def test_returns_false_for_stopped_container(self, docker_mgr, mock_docker_client):
        docker_mgr._nodes[0] = _make_runtime_node(0, "container-0")
        mock_container = MagicMock()
        mock_container.status = "exited"
        mock_docker_client.containers.get.return_value = mock_container
        assert docker_mgr.is_running(0) is False

    def test_returns_false_for_unknown_node_id(self, docker_mgr, mock_docker_client):
        # Never touches Docker API when node not tracked
        assert docker_mgr.is_running(999) is False
        mock_docker_client.containers.get.assert_not_called()

    def test_cache_hit_avoids_docker_api(self, docker_mgr, mock_docker_client):
        docker_mgr._nodes[0] = _make_runtime_node(0, "container-0")
        # Pre-populate cache to simulate recent status check
        docker_mgr._status_cache[0] = True

        result = docker_mgr.is_running(0)
        assert result is True
        # No Docker API calls when cache is populated
        mock_docker_client.containers.get.assert_not_called()


class TestStartOneValidation:
    """start_one requires privileged netns operations; these are E2E tests.

    The image-pull logic (ImageNotFound → pull) is tested below by patching
    all netns operations.
    """

    @pytest.mark.skip(reason="requires --privileged; covered by TC-E2E-001")
    def test_raises_when_image_tag_is_host_manet_latest(self):
        pass

    @pytest.mark.skip(reason="requires --privileged; covered by TC-E2E-001")
    def test_raises_when_image_tag_is_host_manet_latest_netns_needed(self):
        pass

    def test_image_pull_on_not_found(self, docker_mgr, mock_docker_client):
        """Images not present locally are automatically pulled."""
        spec = NodeSpec(id=0, ip="192.168.100.10")
        config = SimConfig()
        from docker.errors import ImageNotFound
        mock_docker_client.images.get.side_effect = ImageNotFound("not found")
        mock_docker_client.images.pull.return_value = MagicMock()

        with patch.object(docker_mgr, "_kill_stale"):
            with patch("controller.orchestrator.docker_mgr.netns.ensure_node_bridge"):
                with patch("controller.orchestrator.docker_mgr.netns.move_to_netns"):
                    with patch("controller.orchestrator.docker_mgr.netns.create_veth"):
                        with patch(
                            "controller.orchestrator.docker_mgr.netns.create_tap"
                        ):
                            with patch(
                                "controller.orchestrator.docker_mgr.netns.DEFAULT_BRIDGE_IP",
                                "192.168.100.1",
                            ):
                                mock_container = MagicMock()
                                mock_container.attrs = {"State": {"Pid": 12345}}
                                mock_docker_client.containers.run.return_value = (
                                    mock_container
                                )

                                docker_mgr.start_one(spec, config)

        mock_docker_client.images.pull.assert_called_once_with(
            "manet-node:latest"
        )


class TestContainerNaming:
    def test_container_name_prefix(self):
        assert CONTAINER_PREFIX == "manet-node-"

    def test_node_spec_default_image(self, sample_spec):
        assert sample_spec.image == "manet-node:latest"