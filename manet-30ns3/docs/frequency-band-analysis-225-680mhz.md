# MANET 仿真系统频段分析：225–680 MHz UHF 频段

**分析日期**: 2026-05-08  
**标签**: v1.0  
**分析范围**: PHY 层参数、链路预算、带宽与距离可达性

---

## 1. 频段特性概述

225–680 MHz 属于 **UHF（特高频）频段**，是战术 military 通信的核心频段：

| 参数 | 2.4 GHz (WiFi) | 590 MHz (UHF) | 225 MHz (UHF 低端) |
|------|----------------|---------------|-------------------|
| 波长 λ | 12.5 cm | 50.8 cm | 1.33 m |
| 自由空间损耗 @1km | 100.0 dB | 87.9 dB | 79.5 dB |
| 绕射能力 | 弱（视距为主） | 中等 | 强（可绕射小障碍物） |
| 典型天线尺寸 (λ/2 偶极子) | 6.3 cm | 25.4 cm | 66.7 cm |
| 可用带宽（regulatory） | 80 MHz (2.4G) / 500 MHz (5G) | 通常 1–25 MHz | 通常 < 1 MHz |

**关键结论**：UHF 频段的路径损耗比 2.4 GHz 低 **12–20 dB**，这意味着在同等发射功率下，UHF 的通信距离可以远 **4–10 倍**。

---

## 2. 当前代码中的 UHF 支持

### 2.1 预设配置

`controller/orchestrator/config.py` 中定义了 `tactical` 和 `rural` 两个 UHF 预设：

```python
"tactical": _preset(
    standard="80211n-5GHz",      # ⚠️ 注意：标准仍绑定 802.11n
    phyModel="yans",
    frequencyMhz=590,            # UHF 中心频率
    channelWidthMhz=20,
    dataRate="HtMcs7",
    txPowerStart=30.0,           # 1 W
    rxSensitivity=-92.0,
    antennaGain=3.0,
    pathLossModel="FreeSpace",
    rangeTargetM=4000.0,         # 4 km 视距目标
)

"rural": _preset(
    standard="80211n-5GHz",
    phyModel="yans",
    frequencyMhz=590,
    txPowerStart=33.0,           # 2 W
    rxSensitivity=-95.0,
    antennaGain=3.0,
    pathLossModel="FreeSpace",
    rangeTargetM=4000.0,
)
```

### 2.2 电台协议映射

`controller/api/ws_radio.py` 支持频表号 0–20，映射到 225–512 MHz：

```python
def _freq_table_to_mhz(freq_num: int) -> int:
    return min(512, 225 + freq_num * 10)   # 10 MHz 步进
```

**覆盖范围**: 225, 235, 245, ..., 512 MHz（共 29 个频点）。  
**上限 512 MHz**: 未覆盖 512–680 MHz 的上半段 UHF。

### 2.3 动态频率调整

`sim_runner.py:set_frequency()` 支持运行时修改频率：

- 仅调整 **Friis/TwoRayGround 路径损耗模型** 的 `Frequency` 属性
- PHY 层的 802.11 载波/调制配置**保持不动**
- 这意味着传播预算按 UHF 计算，但 PHY 的调制/编码参数仍按 5 GHz 802.11a/n 工作

---

## 3. 链路预算分析

### 3.1 计算公式

自由空间路径损耗（Friis）：

```
PL(dB) = 32.45 + 20·log10(d[km]) + 20·log10(f[MHz])
```

接收功率：

```
Pr = Pt + Gt + Gr - PL
```

链路余量：

```
Margin = Pr - RxSensitivity
```

### 3.2 tactical preset (590 MHz) 预算

| 参数 | 值 |
|------|-----|
| 发射功率 Pt | 30 dBm (1 W) |
| 发射天线增益 Gt | 3 dBi |
| 接收天线增益 Gr | 3 dBi |
| 接收灵敏度 | -92 dBm |
| 距离 d | 4 km |
| 频率 f | 590 MHz |

计算：

```
PL @ 4km = 32.45 + 20·log10(4) + 20·log10(590)
         = 32.45 + 12.04 + 55.42
         = 99.91 dB

Pr = 30 + 3 + 3 - 99.91 = -63.91 dBm
Margin = -63.91 - (-92) = 28.09 dB ✅
```

**最大理论距离**（余量=0）：

```
d_max = 4 km × 10^(28.09/20) = 4 × 25.4 = 101.6 km (FreeSpace)
```

### 3.3 rural preset (590 MHz, 更高功率) 预算

| 参数 | 值 |
|------|-----|
| 发射功率 | 33 dBm (2 W) |
| 接收灵敏度 | -95 dBm |

计算：

```
Pr = 33 + 3 + 3 - 99.91 = -60.91 dBm
Margin = -60.91 - (-95) = 34.09 dB ✅
d_max = 4 × 10^(34.09/20) = 4 × 50.1 = 200.4 km (FreeSpace)
```

### 3.4 不同频段对比 @ 4km

| 频段 | 频率 | PL @ 4km | Pr (tactical) | Margin | 相对距离 |
|------|------|----------|---------------|--------|----------|
| UHF 低端 | 225 MHz | 91.5 dB | -55.5 dBm | 36.5 dB | 1.0× (基准) |
| UHF 中段 | 590 MHz | 99.9 dB | -63.9 dBm | 28.1 dB | 0.42× |
| WiFi 2.4G | 2412 MHz | 112.1 dB | -76.1 dBm | 15.9 dB | 0.16× |
| WiFi 5G | 5180 MHz | 118.7 dB | -82.7 dBm | 9.3 dB | 0.10× |

**结论**: 在同等功率配置下，590 MHz UHF 的通信距离约为 2.4 GHz WiFi 的 **2.6 倍**，为 5 GHz WiFi 的 **4.2 倍**。

---

## 4. 带宽分析

### 4.1 测试实测结果

测试中使用的均为 **2.4/5 GHz WiFi 预设**（未使用 UHF 预设）：

| 测试 | 信道带宽 | 频率 | 实测吞吐量 | 备注 |
|------|----------|------|-----------|------|
| TC-03 | 20 MHz | 2437 MHz | 16.88–19.85 Mbps | 无重传 |
| TC-04 | 40 MHz | 2437 MHz | 13.60–18.39 Mbps | ⚠️ 未提升 |

### 4.2 40MHz 未提升的分析

TC-04 中 40 MHz 带宽的吞吐量与 20 MHz 相当甚至更低（node4 仅 13.60 Mbps），可能原因：

1. **YansWifiPhy 不支持 40MHz 动态切换**: 代码注释明确说明 `ChannelWidth` 是 `INITIAL_VALUE`，运行时不可修改
2. **预设仅覆盖 20MHz 配置**: `wifi-bandwidth-test-40m` 预设设置了 `channelWidthMhz=40`，但 PHY 层实际可能仍按 20 MHz 工作
3. **ns-3.47 的已知限制**: 802.11n 40 MHz 模式需要 HT40+/- 频道配对支持，单信道 40 MHz 配置可能回退到 20 MHz

### 4.3 UHF 频段的带宽现实性

| 指标 | 实际战术电台 | 当前仿真配置 | 差距 |
|------|-------------|-------------|------|
| 典型信道带宽 | 25 kHz – 1.25 MHz | 20 MHz | **800× 过大** |
| 典型数据速率 | 64 kbps – 2 Mbps | 17–20 Mbps (实测) | **10× 过大** |
| 频谱效率 | 2–4 bps/Hz | 0.85–1 bps/Hz | 合理（仿真偏低） |

**关键问题**: 当前仿真使用 **20 MHz 信道带宽** 在 UHF 频段运行，这在物理上是不现实的：

- 225–680 MHz 整个频段宽度仅 **455 MHz**，一个 20 MHz 信道就占用了 4.4% 的频谱
- 实际战术通信在 UHF 通常使用 **25/50 kHz 窄带**（如 HAVE QUICK、SINCGARS）
- 如果按比例缩放，UHF 窄带（50 kHz）的理论速率约为 20 MHz 的 1/400，即 **~50 kbps**

**建议**: 如需仿真真实 UHF 战术通信，应：
1. 使用 `channelWidthMhz=1` 或更低（ns-3 的 SpectrumWifiPhy 支持任意带宽）
2. 使用更低阶调制（如 BPSK/QPSK 替代 64-QAM HT-MCS7）
3. 相应调整 `dataRate` 为低速率模式

---

## 5. 距离可达性分析

### 5.1 测试中的距离表现

| 测试 | 配置 | 距离 | 结果 |
|------|------|------|------|
| TC-05 | 2.4GHz, FreeSpace, 200m 视距 | 500–2000m | ✅ 全可达 |
| TC-06 | 2.4GHz, Grid 300m 间距, 200m 视距 | 2700m (node0→node9) | ❌ ping 100% 丢包 |

### 5.2 TC-06 失败根因分析

TC-06 使用 `wifi-adhoc-multihop` 预设：

```python
"wifi-adhoc-multihop": _preset(
    nNodes=10,
    standard="80211g",           # 802.11g 仅支持 2.4 GHz
    frequencyMhz=2412,
    macMode="adhoc",             # AdhocWifiMac (IBSS)
    rangeTargetM=200.0,          # ⚠️ 视距仅 200m
    gridDeltaX=300.0,            # 节点间距 300m
)
```

**问题**: `rangeTargetM=200.0` 意味着单跳覆盖仅 200m，而 node0→node9 的距离为 2700m，需要 **14 跳**中继。但：

- `macMode="adhoc"` 使用 IBSS，L2 无多跳能力
- 容器内的 Linux 网络栈看到的是一个 L2 广播域，超出 200m 的单跳直接被 Range 模型丢弃
- traceroute 能到达是因为 ICMP TTL-expired 由中间节点的 **ns-3 IP 协议栈**生成，走 ns-3 内部路由（AODV/OLSR），不经过 Linux 容器的数据面

**这是设计预期行为，不是 Bug**：Adhoc 模式需要容器内部运行 batman-adv/OLSRd 等 L3 路由协议才能实现多跳。

### 5.3 UHF 频段距离可达性

若使用 `tactical` 预设（590 MHz, rangeTargetM=4000m）：

| 链路 | 距离 | 链路余量 | 是否可达 |
|------|------|----------|----------|
| node0→node1 | 1000m | 40 dB | ✅ |
| node0→node5 | 2236m | 33 dB | ✅ |
| node0→node9 | 2828m | 31 dB | ✅ |
| 4km 边缘 | 4000m | 28 dB | ✅ |

**结论**: 在 UHF 590 MHz、FreeSpace 模型、4km 视距目标配置下， tactical preset 的 10 节点 Grid（5×2，间距 1000m）拓扑中 **所有节点均在单跳覆盖范围内**，无需多跳中继。

---

## 6. 综合评估

### 6.1 是否达到带宽要求

| 要求来源 | 目标带宽 | 仿真能力 | 达标状态 |
|----------|----------|----------|----------|
| `tactical` preset 注释 | 4–8 Mbps | 17–20 Mbps (20MHz @ 2.4G) | ✅ 超额达标 |
| 真实 UHF 战术电台 | 64 kbps – 2 Mbps | 未实测 UHF 窄带 | ⚠️ 配置不匹配 |

**判定**: 如果使用 20 MHz 带宽配置，仿真吞吐量远超 tactical 场景的带宽需求。但 20 MHz 在 UHF 频段不现实，如需真实战术仿真，需切换到窄带配置（< 1 MHz）。

### 6.2 是否达到距离要求

| 要求来源 | 目标距离 | 理论计算 | 实测验证 | 达标状态 |
|----------|----------|----------|----------|----------|
| `tactical` preset | 4 km 视距 | 28 dB 余量 @ 590 MHz | 未测试 UHF | ⚠️ 理论达标，未实测 |
| `rural` preset | 4 km 视距 | 34 dB 余量 @ 590 MHz | 未测试 UHF | ⚠️ 理论达标，未实测 |
| TC-05 (2.4G) | 2 km | 实测全可达 | 2000m 0% 丢包 | ✅ 达标 |
| TC-06 (2.4G) | 2.7km | range=200m 导致失败 | ping 100% 丢包 | ❌ 配置问题 |

**判定**: 
- UHF 频段（590 MHz）在 4km 视距下链路余量充足（28–34 dB），**理论上完全可达**
- 现有测试 **全部使用 2.4/5 GHz**，未覆盖 225–680 MHz 频段的实测验证
- TC-06 的失败是 **Adhoc 模式 + 200m 视距截断** 的设计预期行为，不是距离能力问题

### 6.3 频段覆盖完整性

| 频段范围 | 代码支持 | 预设覆盖 | 测试覆盖 | 电台协议 |
|----------|----------|----------|----------|----------|
| 225–512 MHz | ✅ (frequencyMhz) | ✅ (tactical/rural) | ❌ (无 UHF 测试) | ✅ (频表号 0–20) |
| 512–680 MHz | ✅ (frequencyMhz) | ❌ (频表号上限 512) | ❌ | ❌ |

** gaps **:
1. **512–680 MHz 未覆盖**: 电台协议的频表号上限为 512 MHz，无法配置 590 MHz 以上的 UHF 频点
2. **无 UHF 实测**: 8 个网络测试用例全部使用 2.4/5 GHz，未验证 UHF 频段性能
3. **带宽不匹配**: 20 MHz 信道在 UHF 不现实，但代码未提供窄带（< 1 MHz）预设

---

## 7. 建议与改进

### 7.1 短期（立即可做）

1. **补充 UHF 测试用例**: 在 `tests/wifi_test_suite.py` 中增加：
   - `tc_tactical_uhf_connectivity`: 使用 `tactical` preset (590 MHz) 验证 10 节点连通性
   - `tc_tactical_uhf_throughput`: 验证 590 MHz 下吞吐量
   - `tc_tactical_uhf_range`: 验证 4km 边缘节点可达性

2. **修复频表号上限**: `ws_radio.py` 中 `_freq_table_to_mhz()` 当前上限 512 MHz，应扩展至 680 MHz：
   ```python
   def _freq_table_to_mhz(freq_num: int) -> int:
       return min(680, 225 + freq_num * 10)   # 扩展上限至 680
   ```

### 7.2 中期（下一版本）

1. **增加窄带预设**: 添加 `tactical-narrowband` 预设：
   ```python
   "tactical-narrowband": _preset(
       frequencyMhz=590,
       channelWidthMhz=1,          # 1 MHz 窄带
       dataRate="DsssRate1Mbps",   # 低速率
       standard="80211b",          # DSSS 模式更适合窄带
   )
   ```

2. **PHY 层一致性改进**: 当 `frequencyMhz < 1000` 时，自动选择 `SpectrumWifiPhy` 并禁用 802.11 频道号绑定，避免调制参数与频段物理不匹配。

### 7.3 长期

1. **引入真实战术波形模型**: 使用 ns-3 的 `WaveformGenerator` 替代 802.11 PHY，模拟真实的 UHF 战术通信波形（如 DAMA、TDMA）。
2. **地形/障碍物模型**: 引入 `ITU-R P.1546` 或 `Longley-Rice` 传播模型，替代理想化的 FreeSpace，更真实地反映 UHF 在非视距场景下的表现。

---

## 附录：链路预算速查表

### FreeSpace @ 590 MHz

| 距离 | 路径损耗 | Pr (tactical 30dBm) | Pr (rural 33dBm) |
|------|----------|---------------------|------------------|
| 100 m | 68.0 dB | -32.0 dBm | -29.0 dBm |
| 500 m | 81.9 dB | -45.9 dBm | -42.9 dBm |
| 1 km | 87.9 dB | -51.9 dBm | -48.9 dBm |
| 2 km | 93.9 dB | -57.9 dBm | -54.9 dBm |
| 4 km | 99.9 dB | -63.9 dBm | -60.9 dBm |
| 10 km | 107.9 dB | -71.9 dBm | -68.9 dBm |
| 20 km | 113.9 dB | -77.9 dBm | -74.9 dBm |
| 50 km | 121.9 dB | -85.9 dBm | -82.9 dBm |
| 100 km | 127.9 dB | -91.9 dBm | -88.9 dBm |

*注: Pr 计算含 3dBi 收发天线增益。接收灵敏度 -92 dBm (tactical) / -95 dBm (rural)。*
