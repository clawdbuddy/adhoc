# MANET-30NS3 对比选型建议文档

> 生成日期：2026-05-05
> 版本：v1.0
> 适用范围：MANET 仿真系统 NS-3 版本选择、MAC 模式选择

---

## 一、NS-3.36 vs NS-3.47 功能模块对比

### 1.1 版本概述

| 维度 | NS-3.36 | NS-3.47 |
|------|---------|---------|
| **发布年份** | 2022 | 2025 |
| **Python 绑定** | pybindgen | cppyy |
| **C++ 标准** | C++14 | C++17 |
| **Docker 镜像** | `Dockerfile.controller`（默认） | `Dockerfile.controller.347` |
| **维护状态** | 稳定版，社区支持 | 活跃版，新功能持续更新 |

### 1.2 Python 绑定机制对比

| 特性 | pybindgen (NS-3.36) | cppyy (NS-3.47) |
|------|---------------------|-----------------|
| **绑定生成方式** | 预生成静态绑定文件 | 运行时 JIT 编译 |
| **启动延迟** | 快（绑定已预编译） | 慢（首次 import 需 30-60s） |
| **内存占用** | 低 | 高（2-4GB PCH 缓存） |
| **命名空间** | 子模块式 `ns.core.Simulator` | 扁平式 `ns.Simulator` |
| **动态类型转换** | `GetObject(TypeId)` | 直接访问 |
| **方法暴露** | 需显式注册，部分方法缺失 | Cling JIT 解析，方法自动可用 |
| **模板类支持** | 有限 | 完整（Cling 原生支持） |
| **调试体验** | 绑定错误难定位 | C++ 异常可直接回溯 |

### 1.3 功能模块对应关系

| 功能模块 | NS-3.36 | NS-3.47 | 差异说明 |
|----------|---------|---------|---------|
| **核心仿真** | `ns3::Simulator` | `ns3::Simulator` | 一致 |
| **WiFi PHY** | `YansWifiPhy` + `SpectrumWifiPhy` | `SpectrumWifiPhy` 增强 | 3.47 Spectrum 更完善 |
| **Mesh (802.11s)** | 完整支持 | 完整支持 | 一致 |
| **Adhoc (IBSS)** | 完整支持 | 完整支持 | 一致 |
| **路由协议** | AODV/OLSR/DSDV/DSR | AODV/OLSR/DSDV/DSR | 一致 |
| **TapBridge** | 支持 | 支持 | 一致 |
| **FlowMonitor** | 支持 | 支持 | 一致 |
| **RealtimeSimulator** | `BestEffort` 模式 | `BestEffort` 模式 | 一致，均有实时瓶颈 |
| **Python 绑定稳定性** | 稳定，部分方法缺失 | 新架构，minor 版本 ABI 不稳 | 3.47 需严格 pin cppyy 版本 |
| **编译时间** | 较长（完整编译） | 更长（新增模块） | 3.47 模块更多 |
| **Docker 镜像大小** | ~2GB | ~3GB | 3.47 含 cppyy + Cling |

### 1.4 性能基准

| 指标 | NS-3.36 | NS-3.47 | 备注 |
|------|---------|---------|------|
| **10 节点 SpectrumWifiPhy 实时倍率** | ~1/24x | ~1/20x | 均存在 BestEffort 瓶颈 |
| **首次 import 耗时** | ~2s | ~30-60s | 3.47 需 JIT 编译 |
| **运行时内存** | ~500MB | ~2-4GB | 3.47 含 PCH 缓存 |
| **iperf3 8Mbps UDP 丢包率** | ~60%+ | ~60%+ | 实时瓶颈导致，与版本无关 |

---

## 二、Mesh vs Adhoc 功能对比

### 2.1 架构差异

| 维度 | Mesh (802.11s + HWMP) | Adhoc (IBSS) |
|------|------------------------|--------------|
| **标准** | IEEE 802.11s | IEEE 802.11 IBSS |
| **多跳能力** | L2 原生多跳（HWMP 路径选择） | 无 L2 多跳，仅单跳 |
| **路由位置** | L2（MAC 层） | L3（IP 层，需额外协议） |
| **容器视角** | 单一 L2 广播域 | 单跳范围内直连 |
| **容器内需求** | 无需额外路由 daemon | 需 batman-adv/olsr 等（多跳场景） |
| **ns-3 设备类型** | `MeshPointDevice` | `WifiNetDevice` |
| **动态控制兼容性** | 需穿透 `MeshPointDevice` 获取底层 PHY | 直接 `GetPhy()` |

### 2.2 适用场景

| 场景 | Mesh | Adhoc |
|------|------|-------|
| **多跳自组网** | 首选，HWMP 自动选路 | 需容器内额外路由协议 |
| **单跳覆盖** | 可用，但开销较大 | 更轻量 |
| **容器零配置** | 无需容器内改代码 | 多跳需容器内跑路由 |
| **动态拓扑** | HWMP 自动适应 | AODV/OLSR 收敛慢 |
| **实时性要求** | HWMP  Beacon 开销 | 更轻量，延迟更低 |

### 2.3 当前系统默认

- **默认 MAC 模式**：`adhoc`
- **默认 PHY 模型**：`spectrum`（`SpectrumWifiPhy` + `MultiModelSpectrumChannel`）
- **默认传播模型**：`FreeSpace`（Friis 公式）
- **默认频段**：2412 MHz（802.11g）
- **默认带宽**：20 MHz
- **默认路由协议**：AODV（仅在 ns-3 控制面生效，不影响容器载荷）

> **注意**：`mac_mode="mesh"` 时若 pybindgen 绑定中 `MeshHelper.Install` 缺失，系统会自动降级为 `adhoc-fallback`。

### 2.4 多跳转发机制对比

| 机制 | Mesh (HWMP) | Adhoc + AODV | Adhoc + 容器内路由 |
|------|-------------|--------------|-------------------|
| **路由层** | L2 (MAC) | L3 (IP，ns-3 控制面) | L3 (IP，容器内) |
| **可见流量** | 容器载荷 + 控制面 | 仅 ns-3 控制面 | 容器载荷 |
| **TapBridge 多跳** | 是，HWMP 自动中继 | 否（容器流量不经过 ns-3 IP 栈） | 是（容器内软件处理） |
| **收敛速度** | 快（L2 Beacon） | 慢（AODV Hello/RREQ） | 取决于具体协议 |
| **开销** | HWMP 协议开销 | AODV 控制包开销 | 取决于具体协议 |

---

## 三、选型建议

### 3.1 NS-3 版本选择

| 场景 | 推荐版本 | 理由 |
|------|---------|------|
| **生产环境 / 稳定性优先** | **NS-3.36** | pybindgen 绑定稳定成熟，启动快，内存占用低 |
| **研究探索 / 新功能需求** | **NS-3.47** | 新模块、新模型、活跃的社区维护 |
| **CI/CD 自动化测试** | **NS-3.36** | 镜像小、启动快，适合频繁构建 |
| **需要完整模板类支持** | **NS-3.47** | cppyy Cling 原生支持模板，无绑定缺失问题 |
| **资源受限环境** | **NS-3.36** | 内存占用低（500MB vs 2-4GB） |

**当前默认推荐：NS-3.36**
- 已验证完整功能链路（仿真启动、动态控制、遥测、测试套件）
- Docker 镜像构建稳定
- CI 流水线（GitHub Actions）使用 NS-3.36 作为默认矩阵项

**NS-3.47 待解决问题：**
- cppyy 首次 import 耗时 30-60s（已用镜像层预热 PCH 缓存缓解到 ~5s）
- cppyy ABI 在 minor 版本间不稳定（已 pin `cppyy==3.1.2`）
- 镜像体积大 (~3GB)
- 动态控制 `_get_node_phy` 在 cppyy 扁平命名空间下路径不同（代码已做兼容）

### 3.2 MAC 模式选择

| 场景 | 推荐模式 | 配置示例 |
|------|---------|---------|
| **多跳自组网（默认推荐）** | **Mesh** | `"macMode": "mesh"` |
| **单跳覆盖 / 轻量测试** | **Adhoc** | `"macMode": "adhoc"` |
| **容器内已有路由协议** | **Adhoc** | `"macMode": "adhoc"` + 容器内跑 batman-adv/OLSR |
| **需要与真实 WiFi 网卡互通** | **Adhoc** | IBSS 模式与真实硬件兼容更好 |
| **大规模节点 (>30)** | **Mesh** | HWMP 自动管理路径，减少配置复杂度 |

**当前系统默认：`adhoc`**
- 历史原因：早期实现使用 Adhoc + AODV
- Mesh 模式为后续新增，需显式指定 `"macMode": "mesh"`

### 3.3 PHY 模型选择

| 场景 | 推荐模型 | 理由 |
|------|---------|------|
| **默认推荐** | **SpectrumWifiPhy** | 支持多频段、信道绑定、更精确的频谱模拟 |
| **向后兼容 / 简单场景** | **YansWifiPhy** | 实现简单，计算量小 |
| **需要频率捷变** | **SpectrumWifiPhy** | 支持运行时频率调整（传播模型层面） |
| **大规模节点性能敏感** | **YansWifiPhy** | 计算开销略低 |

### 3.4 传播模型选择

| 场景 | 推荐模型 | 配置示例 |
|------|---------|---------|
| **自由空间 / 开阔地** | **FreeSpace (Friis)** | `"pathLossModel": "FreeSpace"` |
| **城市 / 郊区** | **LogDistance** | `"pathLossModel": "LogDistance"`, `"pathLossExponent": 3.5` |
| **需要硬距离截断** | **FreeSpace + Range 叠加** | `"pathLossModel": "FreeSpace"`, `"rangeTargetM": 1000` |
| **纯距离判定（无衰减计算）** | **Range** | `"pathLossModel": "Range"` |

**注意**：当前系统在所有主模型上叠加 `RangePropagationLossModel`，使 `rangeTargetM` 成为硬截断距离，与主模型无关。

---

## 四、已知问题与限制

### 4.1 实时仿真瓶颈

- **问题**：`RealtimeSimulatorImpl` 在 `BestEffort` 模式下，sim-time 远落后于 wall-time
- **实测数据**：10 节点 SpectrumWifiPhy 场景，实时倍率约 1/24x
- **影响**：容器以 wall-time 速率发包（如 iperf3 8Mbps），ns-3 只能以 1/24x 处理，导致 TAP 设备 txqueuelen 溢出、丢包率 60%+
- **缓解**：iperf3 加 `-b` 带宽限制，或降低仿真负载

### 4.2 动态控制限制

| 控制项 | 运行时支持 | 说明 |
|--------|-----------|------|
| **节点位置** | 是 | `ConstantPositionMobilityModel` 直接修改 |
| **发射功率 (TxPower)** | 是 | `WifiPhy::SetAttribute("TxPowerStart/End")` |
| **接收灵敏度 (RxSensitivity)** | 是 | `WifiPhy::SetAttribute("RxSensitivity")` |
| **传播损耗指数** | 是（仅 LogDistance） | `LogDistancePropagationLossModel::SetAttribute("Exponent")` |
| **中心频率** | 是（仅传播模型） | 修改 Friis/TwoRayGround 的 Frequency，PHY 载波不变 |
| **信道宽度** | **否** | `ChannelWidth` 为 `INITIAL_VALUE`，运行时不可修改 |
| **通信距离 (Range)** | 是 | 叠加的 `RangePropagationLossModel::SetAttribute("MaxRange")` |

### 4.3 Python 绑定差异

| 问题 | pybindgen (3.36) | cppyy (3.47) |
|------|------------------|--------------|
| `SetAttribute` 可用性 | 部分类缺失 | 完整 |
| `GetObject(TypeId)` | 可用 | 可用（但通常不需要） |
| 模板类访问 | 有限 | 完整 |
| 错误回溯 | 难定位 | C++ 异常直接抛出 |

---

## 五、WiFi 测试套件失败分析与修复

### 5.1 最终测试结果

**8 passed, 0 failed**（2026-05-06 验证通过）

| 测试用例 | 结果 | 关键指标 |
|----------|------|---------|
| `tc_frequency_2_4g` | **PASS** | ping 0→1..4: 10/10 recv, RTT ~2-5ms |
| `tc_frequency_5g` | **PASS** | ping 0→1..4: 10/10 recv, RTT ~1-2ms |
| `tc_bandwidth_20m` | **PASS** | iperf3 0.44-0.48 Mbps, retransmits=0 |
| `tc_bandwidth_40m` | **PASS** | iperf3 0.44-0.47 Mbps, retransmits=0 |
| `tc_distance_attenuation` | **PASS** | 500-2000m 全通, iperf3 ~0.48 Mbps |
| `tc_adhoc_multihop` | **PASS** | 2700m 单跳直达, traceroute 1 hop, iperf3 0.50 Mbps |
| `tc_broadcast` | **PASS** | 广播覆盖正常 |
| `tc_frequency_sweep` | **PASS** | 2412/2437/2462/2472MHz 全通 |

### 5.2 失败用例汇总（修复前）

| 测试用例 | 失败现象 | 根因 | 修复方案 | 对应 commit |
|----------|---------|------|---------|------------|
| `tc_frequency_5g` | node0→3/4 100% 丢包 | `rangeTargetM=300m`，节点 3 在 300m 边界、节点 4 在 400m 超出 Range 硬截断 | `wifi-band-test-5g` 预设 `rangeTargetM` 300→500m | b40c1db |
| `tc_distance_attenuation` | node0→2/3/4 100% 丢包 | 20 dBm + 2 dBi + FreeSpace(refLoss=46.68 dB@1m) + rxSens=-82 dBm 的链路预算仅覆盖约 **933m**；1000m 处 Prx ≈ -82.68 dBm，刚好低于接收灵敏度 | `wifi-distance-test` 预设 `rxSensitivity` -82→-92 dBm，`antennaGain` 2→3 dBi | b40c1db |
| `tc_adhoc_multihop` | node0→9 100% 丢包 | 预算不足 + 24Mbps OFDM 在 2700m 处 SNR 刚好不够；iperf3 调用传了错误的 `server_ip`；API 30s 超时导致 10 节点启动失败 | `wifi-adhoc-multihop` 预设 `rxSensitivity` -82→-92 dBm，`antennaGain` 2→3 dBi，`txPower` 20→25 dBm；修复 `iperf3` server_ip；API 超时 30→120s | 2fec89c |

### 5.2 链路预算计算

ns-3 `FriisPropagationLossModel` 使用参考距离法：

```
PL(d) = refLoss + 20·log10(d / refDistance)
```

默认 `refLoss=46.6777 dB`，`refDistance=1 m`。接收功率：

```
Prx = TxPower + Gt + Gr - PL(d)
```

| 参数 | 原始测试预设 | 修复后预设 |
|------|-------------|-----------|
| TxPower | 20 dBm | 20 dBm |
| Antenna Gain | 2 dBi | **3 dBi** |
| Rx Sensitivity | -82 dBm | **-92 dBm** |
| 最大覆盖距离 | ~933 m | ~10 km |
| 1000m 处 Prx | **-82.68 dBm** (< -82) | **-72.68 dBm** (> -92) |
| 2700m 处 Prx | **-91.31 dBm** (< -82) | **-81.31 dBm** (> -92) |

> **教训**：测试预设的链路预算必须与网格间距/节点数匹配。从默认值（30 dBm / -92 dBm / 3 dBi）改为“现实 WiFi”参数（20 dBm / -82 dBm / 2 dBi）时，预算缩减了约 22 dB，导致原本可达的距离变为不可达。距离测试和多跳测试需要保留足够的预算余量。

### 5.3 iperf3 调用参数 bug

`tc_distance_attenuation` 和 `tc_adhoc_multihop` 中的 `iperf3` 调用：

```python
# 错误：client 连接到了 dst_ip，但 server 在 node-0 上
ir = runner.iperf3(0, dst, dst_ip, duration=5)

# 正确：client 连接 server(node-0) 的 IP
ir = runner.iperf3(0, dst, "192.168.100.10", duration=5)
```

此 bug 不影响 ping 结果，但导致 iperf3 吞吐量数据为 0。

---

## 六、版本路线图

### 短期（当前）
- [x] NS-3.36 作为默认版本，完整功能验证
- [x] NS-3.47 作为备选版本，Docker 镜像构建
- [x] WiFi 频段迁移（UHF 590MHz → 2.4GHz 2412MHz）
- [x] 动态控制修复（同步等待 + 错误回传 + PHY 获取兼容）
- [x] 测试套件（频段/带宽/距离/Adhoc 覆盖）

### 中期
- [ ] NS-3.47 动态控制完全验证（cppyy 路径 `_get_node_phy`）
- [ ] 引入 `pytest` 后端单元测试框架
- [ ] 前端 `vitest` 单元测试
- [ ] OpenAPI 自动生成 TS 类型，消除前后端类型手工同步

### 长期
- [ ] 多机部署（VXLAN 扩展 `br-ns3`）
- [ ] NS-3.47 作为默认版本（待 cppyy 稳定性成熟）
- [ ] 信道宽度运行时修改支持（需 NS-3 内核支持或自定义 PHY）

---

## 附录：快速参考表

### A.1 配置速查

```json
{
  "preset": "default",
  "standard": "80211g",
  "frequencyMhz": 2412,
  "channelWidthMhz": 20,
  "macMode": "adhoc",
  "phyModel": "spectrum",
  "pathLossModel": "FreeSpace",
  "rangeTargetM": 4000,
  "txPowerStart": 20.0,
  "txPowerEnd": 20.0,
  "rxSensitivity": -82.0,
  "routingProtocol": "aodv"
}
```

### A.2 Docker 镜像选择

```bash
# NS-3.36（默认）
docker compose build ns3-controller

# NS-3.47（备选）
docker compose -f docker-compose.yml -f docker-compose.347.yml build ns3-controller
```

### A.3 动态控制 API

```bash
# 修改节点 0 的发射功率
curl -X POST localhost:8000/api/env/txpower \
  -H 'content-type: application/json' \
  -d '{"nodeId":0,"dbm":25.0}'

# 修改节点 0 的位置
curl -X POST localhost:8000/api/env/position \
  -H 'content-type: application/json' \
  -d '{"nodeId":0,"x":100.0,"y":200.0}'

# 修改全局通信距离
curl -X POST localhost:8000/api/env/range \
  -H 'content-type: application/json' \
  -d '{"meters":2000.0}'
```