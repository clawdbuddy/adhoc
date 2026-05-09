"""Unit tests for controller/orchestrator/config.py.

Covers SimConfig validation, .conf parsing, preset loading, and load_config
precedence rules.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from controller.orchestrator.config import (
    SimConfig,
    NodeSpec,
    PRESETS,
    _coerce,
    _normalize_keys,
    load_config,
    parse_conf_file,
)


class TestCoerce:
    def test_boolean_true(self):
        assert _coerce("true") is True
        assert _coerce("True") is True

    def test_boolean_false(self):
        assert _coerce("false") is False
        assert _coerce("False") is False

    def test_int(self):
        assert _coerce("42") == 42
        assert _coerce("-7") == -7

    def test_float(self):
        assert _coerce("3.14") == 3.14
        assert _coerce("1e3") == 1000.0

    def test_string(self):
        assert _coerce("hello") == "hello"
        assert _coerce('"quoted"') == "quoted"


class TestNormalizeKeys:
    def test_snake_case_to_camel(self):
        assert _normalize_keys({"hello_world": 1}) == {"helloWorld": 1}
        assert _normalize_keys({"foo_bar_baz": 2}) == {"fooBarBaz": 2}

    def test_camel_case_passthrough(self):
        assert _normalize_keys({"helloWorld": 1}) == {"helloWorld": 1}

    def test_mixed(self):
        inp = {"snake_key": 1, "camelKey": 2}
        out = _normalize_keys(inp)
        assert out == {"snakeKey": 1, "camelKey": 2}


class TestSimConfigDefaults:
    def test_default_values(self):
        cfg = SimConfig()
        assert cfg.n_nodes == 5
        assert cfg.simulation_time == 300
        assert cfg.standard == "80211n-2.4GHz"
        assert cfg.frequency_mhz == 2412
        assert cfg.mac_mode == "mesh"
        assert cfg.routing_protocol == "aodv"

    def test_camel_case_alias(self):
        cfg = SimConfig()
        dumped = cfg.model_dump(by_alias=True)
        assert "nNodes" in dumped
        assert "simulationTime" in dumped
        assert "frequencyMhz" in dumped

    def test_merge_with(self):
        cfg = SimConfig()
        merged = cfg.merged_with({"n_nodes": 10})
        assert merged.n_nodes == 10
        # other fields untouched
        assert merged.simulation_time == 300

    def test_mac_mode_forced_to_mesh(self):
        cfg = SimConfig(mac_mode="adhoc")
        assert cfg.mac_mode == "mesh"


class TestNodeSpec:
    def test_defaults(self):
        spec = NodeSpec(id=0, ip="192.168.100.10")
        assert spec.role == "client"
        assert spec.image == "manet-node:latest"
        assert spec.user_app_mode == "exec"

    def test_camel_dump(self):
        spec = NodeSpec(id=0, ip="192.168.100.10")
        dumped = spec.model_dump(by_alias=True)
        assert "userAppMode" in dumped


class TestPresets:
    def test_all_presets_valid(self):
        for name, preset in PRESETS.items():
            assert isinstance(preset, SimConfig), f"{name} is not SimConfig"

    def test_debug_preset_values(self):
        cfg = PRESETS["debug"]
        assert cfg.n_nodes == 5
        assert cfg.simulation_time == 60
        assert cfg.pcap is False
        assert cfg.flow_monitor is False

    def test_tactical_preset_values(self):
        cfg = PRESETS["tactical"]
        assert cfg.n_nodes == 10
        assert cfg.standard == "80211a"
        assert cfg.frequency_mhz == 590


class TestParseConfFile:
    def test_simple_key_value(self, tmp_path: Path):
        path = tmp_path / "test.conf"
        path.write_text("nNodes = 8\nfrequencyMhz = 5180\n")
        result = parse_conf_file(path)
        assert result == {"nNodes": 8, "frequencyMhz": 5180}

    def test_comments_ignored(self, tmp_path: Path):
        path = tmp_path / "test.conf"
        path.write_text("// comment\nnNodes = 3  // inline\n")
        result = parse_conf_file(path)
        assert result == {"nNodes": 3}

    def test_legacy_aliases(self, tmp_path: Path):
        path = tmp_path / "test.conf"
        path.write_text("pcapTracing = true\nasciiTracing = false\n")
        result = parse_conf_file(path)
        assert result == {"pcap": True, "ascii": False}

    def test_coercion(self, tmp_path: Path):
        path = tmp_path / "test.conf"
        path.write_text('ssid = "test-net"\nenableFading = true\npathLossExponent = 3.5\n')
        result = parse_conf_file(path)
        assert result == {"ssid": "test-net", "enableFading": True, "pathLossExponent": 3.5}

    def test_empty_file(self, tmp_path: Path):
        path = tmp_path / "empty.conf"
        path.write_text("")
        result = parse_conf_file(path)
        assert result == {}


class TestLoadConfig:
    def test_defaults_only(self):
        cfg = load_config()
        assert cfg.n_nodes == 5

    def test_preset_override(self):
        cfg = load_config(preset="debug")
        assert cfg.n_nodes == 5
        assert cfg.simulation_time == 60

    def test_unknown_preset_raises(self):
        with pytest.raises(KeyError, match="unknown preset"):
            load_config(preset="nonexistent")

    def test_file_override(self, tmp_path: Path):
        path = tmp_path / "sim.conf"
        path.write_text("nNodes = 12\n")
        cfg = load_config(file_path=path)
        assert cfg.n_nodes == 12
        assert cfg.simulation_time == 300  # default

    def test_overrides_highest_priority(self, tmp_path: Path):
        path = tmp_path / "sim.conf"
        path.write_text("nNodes = 12\n")
        cfg = load_config(file_path=path, overrides={"n_nodes": 3})
        assert cfg.n_nodes == 3

    def test_preset_plus_file(self, tmp_path: Path):
        path = tmp_path / "sim.conf"
        path.write_text("frequencyMhz = 5900\n")
        cfg = load_config(preset="debug", file_path=path)
        assert cfg.n_nodes == 5  # from debug preset
        assert cfg.frequency_mhz == 5900  # from file

    def test_camel_case_overrides(self):
        cfg = load_config(overrides={"frequencyMhz": 5180})
        assert cfg.frequency_mhz == 5180

    def test_snake_case_overrides(self):
        cfg = load_config(overrides={"frequency_mhz": 5180})
        assert cfg.frequency_mhz == 5180
