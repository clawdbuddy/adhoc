"""统一参数存储模块 —— 所有参数读写（静态配置 + 动态运行时参数）的唯一入口。

ParamStore 维护一个参数注册表，区分 static（需重启生效）和 dynamic（立即生效）参数。
- static 参数：读写 SimConfig，变更后自动持久化到 user_settings.conf
- dynamic 参数：运行时通过 SimRunner 的 setter 立即生效

参数变更时通过 asyncio.Queue 事件总线广播，供 WebSocket 实时推送。
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from controller.orchestrator.config import SimConfig, save_config_to_file

log = logging.getLogger(__name__)

ParamScope = Literal["static", "dynamic"]


@dataclass(frozen=True)
class ParamMeta:
    """参数元数据。"""
    key: str                # camelCase 对外名
    python_key: str         # snake_case 内部名
    scope: ParamScope       # static / dynamic
    per_node: bool          # 是否为 per-node 数组
    category: str           # 参数分类（用于分组展示）


@dataclass
class ParamChangeEvent:
    """参数变更事件，放入广播队列。"""
    key: str
    value: Any
    scope: ParamScope
    source: str             # 变更来源标识（"rest", "ws", "radio", "internal"）


# ---------------------------------------------------------------------------
# 参数注册表
# ---------------------------------------------------------------------------

# dynamic 参数定义（运行时可通过 SimRunner setter 修改）
DYNAMIC_PARAMS: dict[str, ParamMeta] = {
    "frequencyMhz": ParamMeta("frequencyMhz", "frequency_mhz", "dynamic", False, "phy"),
    "txPower": ParamMeta("txPower", "tx_power", "dynamic", True, "phy"),
    "rxSensitivity": ParamMeta("rxSensitivity", "rx_sensitivity", "dynamic", True, "phy"),
    "pathLossExponent": ParamMeta("pathLossExponent", "path_loss_exponent", "dynamic", False, "propagation"),
    "channelWidthMhz": ParamMeta("channelWidthMhz", "channel_width_mhz", "dynamic", False, "phy"),
    "rangeTargetM": ParamMeta("rangeTargetM", "range_target_m", "dynamic", False, "propagation"),
    "positions": ParamMeta("positions", "positions", "dynamic", True, "mobility"),
}

# static 参数通过 SimConfig 的 schema 反射生成（见 ParamStore._build_static_registry）


class ParamStore:
    """统一参数存储模块。线程安全。"""

    def __init__(self, session: Any) -> None:
        self._session = session
        self._lock = threading.RLock()
        self._subscribers: list[asyncio.Queue] = []
        self._static_registry: dict[str, ParamMeta] = {}
        self._build_static_registry()

    # ------------------------------------------------------------------ 注册表

    def _build_static_registry(self) -> None:
        """从 SimConfig schema 反射生成 static 参数注册表。

        排除已在 DYNAMIC_PARAMS 中定义的字段（它们以 dynamic 形式对外暴露）。
        """
        cfg = SimConfig()
        dynamic_python_keys = {m.python_key for m in DYNAMIC_PARAMS.values()}
        for name, field_info in SimConfig.model_fields.items():
            if name in dynamic_python_keys:
                continue
            # 计算 camelCase 对外名（与 SimConfig alias_generator 一致）
            alias = field_info.alias or name
            self._static_registry[alias] = ParamMeta(
                key=alias,
                python_key=name,
                scope="static",
                per_node=False,
                category=_guess_category(name),
            )

    def _meta(self, key: str) -> ParamMeta | None:
        """按 camelCase key 查找参数元数据。"""
        if key in DYNAMIC_PARAMS:
            return DYNAMIC_PARAMS[key]
        if key in self._static_registry:
            return self._static_registry[key]
        return None

    def _is_dynamic(self, key: str) -> bool:
        return key in DYNAMIC_PARAMS

    # ------------------------------------------------------------------ 读取

    def get(self, key: str) -> dict[str, Any]:
        """读取单个参数的当前值和元数据。"""
        meta = self._meta(key)
        if meta is None:
            return {"ok": False, "reason": f"unknown parameter: {key}"}

        with self._lock:
            value = self._get_value(meta)

        return {
            "ok": True,
            "key": key,
            "value": value,
            "scope": meta.scope,
            "perNode": meta.per_node,
            "category": meta.category,
        }

    def _get_value(self, meta: ParamMeta) -> Any:
        """按元数据读取实际值（必须在锁内调用）。"""
        sess = self._session

        if meta.scope == "dynamic" and sess.sim is not None:
            env = sess.sim.snapshot_env()
            return getattr(env, meta.python_key)

        # static 或仿真未运行：从 SimConfig 读取
        dump = sess.config.model_dump(by_alias=True)
        # SimConfig 中可能没有 camelCase 的 "txPower"，而是 "txPowerStart"
        if meta.key == "txPower":
            return [float(sess.config.tx_power_start)] * sess.config.n_nodes
        if meta.key == "rxSensitivity":
            return [float(sess.config.rx_sensitivity)] * sess.config.n_nodes
        if meta.key == "positions":
            n = sess.config.n_nodes
            return [{"x": 0.0, "y": 0.0, "z": 0.0} for _ in range(n)]
        if meta.key in dump:
            return dump[meta.key]
        # fallback: snake_case 属性
        return getattr(sess.config, meta.python_key, None)

    def get_all(self) -> dict[str, Any]:
        """返回全部参数的当前值快照（static + dynamic）。"""
        with self._lock:
            result: dict[str, Any] = {}
            # dynamic 参数
            for key in DYNAMIC_PARAMS:
                r = self.get(key)
                if r.get("ok"):
                    result[key] = r["value"]
            # static 参数
            dump = self._session.config.model_dump(by_alias=True)
            for key in self._static_registry:
                result[key] = dump.get(key)
            return result

    # ------------------------------------------------------------------ 写入

    def set(self, key: str, value: Any, source: str = "api") -> dict[str, Any]:
        """写入单个参数。自动区分 static/dynamic，触发事件广播。"""
        meta = self._meta(key)
        if meta is None:
            return {"ok": False, "reason": f"unknown parameter: {key}"}

        with self._lock:
            result = self._set_locked(meta, value, source)

        if result.get("ok"):
            self._broadcast(ParamChangeEvent(key, value, meta.scope, source))
        return result

    def batch_set(
        self, params: dict[str, Any], source: str = "api"
    ) -> list[dict[str, Any]]:
        """批量写入参数。返回每个参数的结果列表。"""
        results: list[dict[str, Any]] = []
        with self._lock:
            for key, value in params.items():
                meta = self._meta(key)
                if meta is None:
                    results.append({"ok": False, "key": key, "reason": f"unknown parameter: {key}"})
                    continue
                result = self._set_locked(meta, value, source)
                results.append({"ok": result.get("ok"), "key": key, **result})
                if result.get("ok"):
                    self._broadcast(ParamChangeEvent(key, value, meta.scope, source))
        return results

    def _set_locked(self, meta: ParamMeta, value: Any, source: str) -> dict[str, Any]:
        """实际写入逻辑（必须在锁内调用）。"""
        sess = self._session

        if meta.scope == "dynamic":
            return self._set_dynamic(meta, value)

        # static 参数：更新 SimConfig 并持久化
        try:
            overrides = {meta.key: value}
            sess.config = sess.config.merged_with(overrides)
            save_config_to_file(sess.config)
            return {"ok": True, "key": meta.key, "scope": "static"}
        except Exception as e:
            log.warning("static set failed: %s = %s: %s", meta.key, value, e)
            return {"ok": False, "key": meta.key, "reason": str(e)}

    def _set_dynamic(self, meta: ParamMeta, value: Any) -> dict[str, Any]:
        """设置 dynamic 参数，调用 SimRunner setter。"""
        sess = self._session
        if not sess.running or sess.sim is None:
            # 仿真未运行时，将 dynamic 参数回退为 static 处理（更新 SimConfig）
            # 这样前端可以在仿真停止时修改参数，下次启动时生效
            overrides = {meta.key: value}
            # 对 per-node 参数，需要映射回 SimConfig 的对应字段
            if meta.key == "txPower" and isinstance(value, (list, tuple)) and value:
                overrides = {"txPowerStart": value[0], "txPowerEnd": value[0]}
            elif meta.key == "rxSensitivity" and isinstance(value, (list, tuple)) and value:
                overrides = {"rxSensitivity": value[0]}
            elif meta.key == "frequencyMhz":
                overrides = {"frequencyMhz": value}
            elif meta.key == "pathLossExponent":
                overrides = {"pathLossExponent": value}
            elif meta.key == "channelWidthMhz":
                overrides = {"channelWidthMhz": value}
            elif meta.key == "rangeTargetM":
                overrides = {"rangeTargetM": value}
            try:
                sess.config = sess.config.merged_with(overrides)
                save_config_to_file(sess.config)
                return {
                    "ok": True, "key": meta.key, "scope": "static",
                    "note": "simulation not running, saved to config for next start",
                }
            except Exception as e:
                return {"ok": False, "key": meta.key, "reason": str(e)}

        sim = sess.sim
        key = meta.key

        try:
            if key == "positions":
                return self._set_positions(value, sim)
            if key == "txPower":
                return self._set_tx_power(value, sim)
            if key == "rxSensitivity":
                return self._set_rx_sensitivity(value, sim)
            if key == "pathLossExponent":
                r = sim.set_path_loss_exponent(float(value))
                return {"ok": r.get("applied", False), **r, "key": key}
            if key == "frequencyMhz":
                r = sim.set_frequency(int(value))
                return {"ok": r.get("applied", False), **r, "key": key}
            if key == "channelWidthMhz":
                r = sim.set_channel_width(int(value))
                return {"ok": r.get("applied", False), **r, "key": key}
            if key == "rangeTargetM":
                r = sim.set_range_target(float(value))
                return {"ok": r.get("applied", False), **r, "key": key}

            return {"ok": False, "key": key, "reason": f"unsupported dynamic parameter: {key}"}
        except Exception as e:
            log.exception("dynamic set failed: %s = %s", key, value)
            return {"ok": False, "key": key, "reason": str(e)}

    # -- per-node dynamic setters --

    def _set_positions(self, value: Any, sim: Any) -> dict[str, Any]:
        """设置节点位置。value 格式: {nodeId: {x, y, z}} 或 {nodeId: [x, y, z]}"""
        if isinstance(value, list):
            # 全量替换: [{x, y, z}, ...]
            results = []
            for i, pos in enumerate(value):
                x, y, z = self._extract_xyz(pos)
                r = sim.set_node_position(i, x, y, z)
                results.append({"nodeId": i, "ok": r.get("applied", False), **r})
            ok = all(r.get("ok") for r in results)
            return {"ok": ok, "key": "positions", "results": results}

        if isinstance(value, dict):
            # 部分更新: {nodeId: {x, y, z}}
            results = []
            for node_id_str, pos in value.items():
                node_id = int(node_id_str)
                x, y, z = self._extract_xyz(pos)
                r = sim.set_node_position(node_id, x, y, z)
                results.append({"nodeId": node_id, "ok": r.get("applied", False), **r})
            ok = all(r.get("ok") for r in results)
            return {"ok": ok, "key": "positions", "results": results}

        return {"ok": False, "key": "positions", "reason": "expected list or dict"}

    def _extract_xyz(self, pos: Any) -> tuple[float, float, float]:
        if isinstance(pos, dict):
            return float(pos.get("x", 0)), float(pos.get("y", 0)), float(pos.get("z", 0))
        if isinstance(pos, (list, tuple)):
            return float(pos[0]), float(pos[1]), float(pos[2]) if len(pos) > 2 else 0.0
        return float(pos), 0.0, 0.0

    def _set_tx_power(self, value: Any, sim: Any) -> dict[str, Any]:
        """设置发射功率。value 格式: {nodeId: dbm} 或 [dbm, ...]"""
        return self._set_per_node("txPower", value, sim.set_tx_power)

    def _set_rx_sensitivity(self, value: Any, sim: Any) -> dict[str, Any]:
        """设置接收灵敏度。value 格式: {nodeId: dbm} 或 [dbm, ...]"""
        return self._set_per_node("rxSensitivity", value, sim.set_rx_sensitivity)

    def _set_per_node(
        self, key: str, value: Any, setter: Callable[[int, float], dict[str, Any]]
    ) -> dict[str, Any]:
        if isinstance(value, (list, tuple)):
            results = []
            for i, v in enumerate(value):
                r = setter(i, float(v))
                results.append({"nodeId": i, "ok": r.get("applied", False), **r})
            ok = all(r.get("ok") for r in results)
            return {"ok": ok, "key": key, "results": results}

        if isinstance(value, dict):
            results = []
            for node_id_str, v in value.items():
                node_id = int(node_id_str)
                r = setter(node_id, float(v))
                results.append({"nodeId": node_id, "ok": r.get("applied", False), **r})
            ok = all(r.get("ok") for r in results)
            return {"ok": ok, "key": key, "results": results}

        # 标量：应用到所有节点
        n_nodes = self._session.config.n_nodes
        results = []
        for i in range(n_nodes):
            r = setter(i, float(value))
            results.append({"nodeId": i, "ok": r.get("applied", False), **r})
        ok = all(r.get("ok") for r in results)
        return {"ok": ok, "key": key, "results": results}

    # ------------------------------------------------------------------ 事件总线

    def subscribe(self) -> asyncio.Queue:
        """订阅参数变更事件。返回 asyncio.Queue，事件到达时放入队列。"""
        q: asyncio.Queue = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """取消订阅。"""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def _broadcast(self, event: ParamChangeEvent) -> None:
        """广播参数变更事件到所有订阅者。"""
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    # ------------------------------------------------------------------ 工具

    def list_params(self) -> list[dict[str, Any]]:
        """返回所有参数的元数据列表。"""
        with self._lock:
            return [
                {
                    "key": m.key,
                    "scope": m.scope,
                    "perNode": m.per_node,
                    "category": m.category,
                }
                for m in {**DYNAMIC_PARAMS, **self._static_registry}.values()
            ]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _guess_category(python_key: str) -> str:
    """根据 snake_case 字段名猜测参数分类。"""
    if python_key in ("n_nodes", "simulation_time", "seed", "run", "log_components"):
        return "general"
    if any(python_key.startswith(p) for p in ("phy_", "standard", "frequency", "channel_width", "data_rate", "tx_power", "rx_sensitivity", "cca_threshold", "antenna_gain")):
        return "phy"
    if any(python_key.startswith(p) for p in ("propagation_", "path_loss", "enable_fading", "fading_model", "nakagami", "range_target")):
        return "propagation"
    if any(python_key.startswith(p) for p in ("ssid", "bssid", "mac_mode", "rate_control", "rts_cts", "fragmentation", "non_unicast", "beacon", "cw_")):
        return "mac"
    if any(python_key.startswith(p) for p in ("routing_", "aodv_", "olsr_", "dsdv_")):
        return "routing"
    if any(python_key.startswith(p) for p in ("mobility_", "rw_", "grid_", "gm_")):
        return "mobility"
    if any(python_key.startswith(p) for p in ("pcap", "ascii", "flow_monitor", "enable_mobility", "tap_")):
        return "tracing"
    if any(python_key.startswith(p) for p in ("traffic_", "onoff_")):
        return "traffic"
    return "general"
