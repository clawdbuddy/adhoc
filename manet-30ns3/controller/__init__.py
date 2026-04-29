"""MANET controller package.

Layout:
    orchestrator/   ns-3 simulation engine + container/network plumbing
    api/            FastAPI application (REST + WebSocket telemetry)

This package is launched inside the ns3-controller Docker image; it expects
ns-3 Python bindings at $PYTHONPATH=/opt/ns3/ns-3/build/bindings/python and
host network access (network_mode=host, --privileged) to drive the bridge,
veth pairs, TAPs, and child node containers.
"""
__all__ = ["orchestrator", "api"]
