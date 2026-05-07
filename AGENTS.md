# AGENTS.md — MANET NS-3 仿真系统

本文档面向 AI 编码助手。阅读本文档后，你应该能够在本仓库中独立完成开发、调试和构建任务。

---

## 项目概览

本项目是一套**容器化 MANET（移动自组网）仿真系统**，核心能力是把每个 MANET 节点放到独立的 Docker 容器中，并强制所有节点间流量经过 NS-3 的信道模型（PHY/MAC/传播/路由）。

项目路径：`manet-30ns3/`

**关键特性：**
- 每节点一个 Docker 容器，`network_mode="none"`，通过 veth + TAP 接入 ns-3
- 支持 802.11s Mesh（HWMP L2 多跳）和 802.11 AdHoc（IBSS）两种模式
- 80+ 仿真参数可通过 REST API 或 React Web 面板实时配置
- 实时遥测：节点位置、流量统计、端到端延迟/吞吐
- 仅支持 **linux/amd64**（x86_64 Ubuntu 20.04/22.04）

---

## 仓库结构

```
adhoc/
├── manet-30ns3/                 # 主项目目录
│   ├── controller/              # Python 控制器（FastAPI + 编排器）
│   │   ├── orchestrator/        #   config / netns / docker_mgr / sim_runner / telemetry
│   │   └── api/                 #   FastAPI 应用 + REST 路由 + WebSocket
│   ├── ns3-controller/          #   控制器 Dockerfile（NS-3.36 pybindgen / 3.47 cppyy）
│   ├── node/                    #   节点 Dockerfile + node-entrypoint.py
│   ├── web-manager/             #   React 19 + Vite + TypeScript 前端
│   ├── tests/                   #   WiFi 自动化测试套件 + 报告生成器
│   ├── docs/                    #   需求方案文档（中文）
│   ├── docker-compose.yml       #   控制器 + 节点镜像构建编排
│   ├── environment.yml          #   Conda 环境定义（物理主机部署用）
│   ├── setup-controller.sh      #   物理主机安装脚本（conda + systemd）
│   ├── build-controller.sh      #   PyInstaller 打包脚本
│   ├── manet-controller.spec    #   PyInstaller spec 文件
│   └── README.md                #   面向用户的完整文档
├── docs/                        # 顶层需求方案
├── .github/workflows/build.yml  # GitHub Actions CI/CD
└── CLAUDE.md                    # 历史工作笔记（已被本文档覆盖）
```

---

## 技术栈

### 后端（控制器）

| 组件 | 版本/说明 |
|------|----------|
| Python | 3.10 |
| FastAPI | 0.110.x |
| Pydantic | v2 |
| ns-3 | 3.36（pybindgen）或 3.47（cppyy） |
| Docker SDK | 7.x |
| pyroute2 | 0.7.x（操作宿主机网络） |
| uvicorn | 0.29.x |

### 前端（Web 管理面板）

| 组件 | 版本/说明 |
|------|----------|
| React | 19.2 |
| Vite | 7.2 |
| TypeScript | ~5.9 |
| Tailwind CSS | 3.4 |
| shadcn/ui | new-york / slate |
| 路由 | react-router 7 |

### 基础设施

| 组件 | 说明 |
|------|------|
| Docker / Docker Compose | 容器编排 |
| Linux netns / veth / TAP / bridge | 网络隔离与注入 |
| GitHub Actions | CI/CD，构建镜像推送到 GHCR |

---

## 构建与运行命令

### 前端（`manet-30ns3/web-manager/`）

```bash
cd manet-30ns3/web-manager
npm install          # 安装依赖
npm run dev          # Vite 开发服务器 http://localhost:3000
npm run build        # tsc -b && vite build → 产出 dist/
npm run lint         # eslint .
npm run preview      # 本地预览生产构建
```

开发服务器代理配置（`vite.config.ts`）：
- `/api` → `http://localhost:8000`
- `/ws` → `ws://localhost:8000`

### Docker 方式运行仿真系统（推荐）

```bash
cd manet-30ns3

# 1. 构建节点镜像 + 控制器镜像
docker compose --profile build build node-image-builder
docker compose build ns3-controller

# 2. 启动控制器（FastAPI :8000，特权模式 + host 网络）
docker compose up -d ns3-controller
curl -s localhost:8000/api/health     # → {"ok": true}

# 3. 启动仿真
curl -X POST localhost:8000/api/sim/start \
     -H 'content-type: application/json' \
     -d '{"preset":"debug"}'           # 5 节点，60 秒，无衰落

# 4. 停止仿真
curl -X POST localhost:8000/api/sim/stop

# 5. 全部下线
docker compose down
```

### 物理主机部署（conda 环境）

```bash
cd manet-30ns3
sudo bash setup-controller.sh          # 安装系统依赖 + conda 环境 + systemd 服务
conda activate manet-controller
PYTHONPATH=./controller MANET_WEB_DIR=./web-manager/dist \
  python3 -m uvicorn controller.api.main:app --host 0.0.0.0 --port 8000
```

### 打包为独立可执行程序

```bash
bash build-controller.sh               # 输出 dist/manet-controller/
```

---

## 代码组织与模块划分

### 后端模块（`controller/`）

```
controller/
├── orchestrator/
│   ├── config.py          # Pydantic SimConfig + NodeSpec + PRESETS + .conf 解析
│   ├── netns.py           # Linux 网桥/veth/TAP/netns 操作（pyroute2）
│   ├── docker_mgr.py      # Docker 容器生命周期管理
│   ├── sim_runner.py      # ns-3 仿真线程（守护线程运行 Simulator::Run）
│   └── telemetry.py       # FlowMonitor + 位置快照 → WebSocket 广播
└── api/
    ├── main.py            # FastAPI 入口、CORS、静态文件挂载
    ├── state.py           # Session 单例，包装 start/stop 生命周期
    ├── routes_sim.py      # /api/sim/start|stop|status|presets
    ├── routes_nodes.py    # /api/nodes /api/flows /api/nodes/{id}/exec /api/logs
    ├── routes_config.py   # GET/PUT /api/config
    ├── routes_dynamic.py  # 运行时动态调整参数（功率/灵敏度/范围等）
    └── ws_telemetry.py    # GET /ws/telemetry（实时遥测，5 Hz）
```

**线程模型：**
- FastAPI 主循环 = asyncio
- `SimRunner` = 独立守护线程运行 `ns3::Simulator::Run`
- `Telemetry` = asyncio Task 周期性轮询状态并广播 WebSocket

### 前端模块（`web-manager/src/`）

```
src/
├── main.tsx               # 入口
├── App.tsx                # 主布局（5 个 Tab + 侧边栏）
├── types/config.ts        # SimConfig / NodeStatus / FlowStats 类型定义
├── hooks/
│   ├── useSimConfig.ts    # 配置状态管理、预设加载、.conf 导入导出
│   ├── useSimulation.ts   # 与后端 REST + WebSocket 通信
│   └── useDynamicControl.ts  # 运行时动态控制
├── sections/
│   ├── Dashboard.tsx      # 仿真概览
│   ├── ConfigPanel.tsx    # 80+ 参数配置表单
│   ├── ControlPanel.tsx   # 启停控制
│   ├── TopologyView.tsx   # Canvas 实时拓扑
│   ├── LogView.tsx        # 实时日志
│   └── DynamicControl.tsx # 动态环境调整
└── components/ui/         # shadcn/ui 原子组件（自动生成，禁止手工修改）
```

### 节点容器（`node/`）

- `Dockerfile.node`：基于 Ubuntu 20.04，安装网络工具、iperf3、sshd
- `node-entrypoint.py`：等待 eth0 注入 → 配置网络 → 按角色启动服务 → 进入用户应用模式

---

## 配置系统

配置的唯一权威源是 `controller/orchestrator/config.py:SimConfig`（Pydantic v2 模型，约 85 个字段）。

**命名约定：**
- Python 内部：snake_case
- 对外交互（REST / WebSocket / .conf 文件 / React 类型）：camelCase
- 通过 `alias_generator=to_camel` 自动转换

**配置优先级（高 → 低）：**
1. 显式 `overrides`（REST body）
2. `.conf` 文件
3. 选定的 `preset`
4. 内置默认值

**预设（PRESETS）：**
| 预设 | 场景 |
|------|------|
| `default` | 用户目标场景（adhoc） |
| `urban` | 高密度城市（mesh） |
| `rural` | 开阔野外（mesh） |
| `debug` | 5 节点冒烟测试 |
| `tactical` | 战术通信场景（UHF 590 MHz） |
| `wifi-band-test-2.4g` / `wifi-band-test-5g` | WiFi 频段基准测试 |
| `wifi-bandwidth-test-20m` / `wifi-bandwidth-test-40m` | 带宽测试 |
| `wifi-distance-test` | 距离衰减测试 |
| `wifi-adhoc-multihop` | 大规模拓扑测试 |

**重要：** React 前端类型 `web-manager/src/types/config.ts` 与后端 Pydantic 模型之间**没有自动生成机制**。新增字段时必须两边手工同步。

---

## 测试策略

### 现有测试

1. **前端静态检查**
   ```bash
   cd manet-30ns3/web-manager
   npm run lint      # ESLint
   npm run build     # tsc -b + vite build（类型检查）
   ```

2. **WiFi 自动化测试套件**（`tests/wifi_test_suite.py`）
   - 通过 REST API 驱动控制器，执行端到端测试
   - 覆盖：2.4GHz/5GHz 连通性、20MHz/40MHz 带宽、距离衰减、大规模拓扑、广播、多信道遍历
   - 输出 JSON 结果到 `test-results/wifi_test_results.json`

3. **报告生成器**（`tests/generate_report.py`）
   - 读取 JSON 结果，生成 `test-results/wifi_test_report.md`

### 测试缺失（已知问题）

- 后端无单元测试框架（pytest 未引入）
- 前端无组件/Hook 测试框架（vitest + @testing-library/react 未引入）
- 网络操作（netns.py）需要集成测试在 Linux 宿主机上运行

---

## CI/CD 与部署

### GitHub Actions（`.github/workflows/build.yml`）

流水线分为 4 个阶段：
1. **frontend**：`npm ci` → `npm run lint` → `npm run build` → 上传 dist artifact
2. **node-image**：构建 `manet-node` 镜像，推送到 GHCR
3. **controller-image**：矩阵构建 ns3-controller（3.36 + 3.47 两个版本），推送到 GHCR
4. **release**：仅在打 tag 时生成 Release Notes

镜像地址：
- `ghcr.io/{owner}/adhoc-node`
- `ghcr.io/{owner}/adhoc-controller`
- `ghcr.io/{owner}/adhoc-controller-347`

### 部署方式

| 方式 | 文件 | 适用场景 |
|------|------|----------|
| Docker Compose | `docker-compose.yml` | 开发/测试/生产首选 |
| Conda + systemd | `setup-controller.sh` | 物理主机长期运行 |
| 独立可执行程序 | `build-controller.sh` | 无 Python 环境的目标机器 |

---

## 开发规范与约定

### 代码风格

- **Python**：遵循 PEP 8，注释使用中文，类型提示完整（`from __future__ import annotations`）
- **TypeScript**： camelCase 对外接口，严格类型（`strict: true` 隐含在 `tsconfig.app.json`）
- **命名空间兼容性**：ns-3 Python 绑定有两条路线
  - cppyy（3.47）：`from ns import ns`，类在扁平命名空间
  - pybindgen（3.36）：需显式 `import ns.core` 等子模块
  - `sim_runner.py:_import_ns()` 已做双路径兼容封装

### 禁止事项

- `web-manager/src/components/ui/` 中的 shadcn/ui 原子组件**禁止手工修改**。需要定制时，在 `src/sections/` 中通过组合方式实现。
- 不要在非 Linux 环境（如 macOS）中尝试运行控制器或测试，因为涉及内核网络操作。

### 文件同步清单

当新增仿真参数时，必须同步修改以下位置：
1. `controller/orchestrator/config.py:SimConfig`（新增字段 + 默认值）
2. `controller/orchestrator/config.py:FIELD_DESCRIPTIONS`（字段中文说明）
3. `controller/orchestrator/config.py:_FIELD_GROUPS`（分组）
4. `web-manager/src/types/config.ts`（TypeScript 类型）
5. `web-manager/src/sections/ConfigPanel.tsx`（如有必要，UI 表单）
6. `controller/orchestrator/sim_runner.py`（将参数接入 ns-3）

---

## 安全与运行限制

### 运行环境限制

- **仅 Linux**：控制器需要 `pyroute2` 直接操作宿主机网络（创建/删除 bridge、veth、TAP）
- **仅 x86_64**：镜像和 ns-3 绑定均为 linux/amd64 构建
- **需要 root/特权**：`--privileged`、`network_mode: host`、Docker socket 访问
- **内核模块**：必须加载 `tun`、`tap`、`bridge`

### 网络隔离保证

- 每个节点容器 `network_mode="none"`，无 Docker 默认网桥
- 每节点独占一个 Linux bridge `br-ns3-{i}`，仅连接该节点的 veth 和 TAP
- 容器之间不存在共享 L2 广播域，跨节点流量**只能**通过 ns-3 PHY/MAC 模型转发

### 已知风险

1. **Python 绑定稳定性**：ns-3 Python 绑定在大型拓扑或长时间运行下可能出现 segfault
2. **TapBridge 实时模式回压**：大规模节点数（N > 20）时，宿主 TAP 可能产生背压
3. **特权容器攻击面**：控制器拥有完整宿主机网络权限，建议仅在可信环境运行

---

## 常用调试命令

```bash
# 检查控制器健康
curl -s localhost:8000/api/health

# 查看当前仿真状态
curl -s localhost:8000/api/sim/status | python3 -m json.tool

# 查看节点列表
curl -s localhost:8000/api/nodes | python3 -m json.tool

# 在节点 0 中执行命令
curl -X POST localhost:8000/api/nodes/0/exec \
     -H 'content-type: application/json' \
     -d '{"cmd":"ip -4 addr show eth0"}'

# 查看节点日志
curl 'localhost:8000/api/logs?node=0&tail=50'

# 检查宿主机网络接口（需 Linux）
ip link | grep -E 'br-ns3|tap-|veth'

# 查看残留容器
docker ps -a | grep manet-node

# 查看控制器日志
docker logs ns3-controller
```

---

## 延伸阅读

- `manet-30ns3/README.md` — 面向用户的完整使用手册（含架构图、参数表、故障排查）
- `docs/MANET-需求方案-v2.0.md` — 需求溯源表（R1–R8）
- `CLAUDE.md` — 历史工作笔记（部分信息可能已过时，以本文档为准）
