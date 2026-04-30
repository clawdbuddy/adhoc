# CLAUDE.md

本文档为 Claude Code（claude.ai/code）在本仓库中工作时提供指引。

## 仓库结构

本仓库由**三个相互耦合的子项目**并列组成：

```
Kimi_Agent_MANET/
├── app/                       # Web 管理面板的 React 19 + Vite + TS 源码
└── manet-30ns3/               # NS-3 + Docker 的 MANET 仿真系统
    ├── controller/              # Python 编排层 + FastAPI 控制平面
    │   ├── orchestrator/          # config / netns / docker_mgr / sim_runner / telemetry
    │   └── api/                   # FastAPI 应用 + REST 路由 + /ws/telemetry
    ├── ns3-controller/          # 用于构建带 Python 绑定的 NS-3.45 的 Dockerfile
    │                            # 同时把 controller 包与 web 静态包打入镜像
    ├── node/                    # Dockerfile.node + node-entrypoint.sh，MANET 节点容器
    ├── web-manager/             # 预构建的静态包（由 `app/` 产出），由 FastAPI 直接托管
    └── ns3-code/                # 旧版 C++ scratch 程序（仅作参考与回归对比保留）
```

`app/` 是管理面板的**源码**。`manet-30ns3/web-manager/` 存放该 UI 的**预构建**静态包；FastAPI 把它挂到 `/`，因此同一个 `:8000` 源同时提供 API 与 SPA。修改 UI 行为时：先改 `app/`，执行 `npm run build`，然后把 `app/dist/*` 复制到 `manet-30ns3/web-manager/`，再重新构建 controller 镜像。

旧版 C++ 流水线（`ns3-code/manet-30nodes.cc` + `setup-network.sh` + `start-simulation.sh` + `web-manager-start.sh`）已被 Python 控制器**取代**。.cc 文件与 shell 脚本仍保留在磁盘上仅作历史参考，运行时实际跑的是 `controller/`。

## 常用命令

### React 应用 (`app/`)

```bash
cd app
npm install
npm run dev       # Vite 开发服务器，http://localhost:3000
npm run build     # tsc -b && vite build  → 生成 dist/
npm run lint      # eslint .
npm run preview   # 本地预览生产构建
```

- 路径别名：`@/*` → `./src/*`（在 `vite.config.ts` 与 `tsconfig.app.json` 中配置）。
- shadcn/ui 已预置（`components.json`，风格 `new-york`，基色 `slate`）；用 `npx shadcn add <name>` 添加组件，会落到 `src/components/ui/`。
- `vite.config.ts` 启用了 `kimi-plugin-inspect-react`（dev 期注入 inspect 属性）。
- Vite 开发服务器把 `/api` 反代到 `http://localhost:8000`、把 `/ws` 反代到 `ws://localhost:8000`，使 dev 模式下 UI 能直接对接本机（Linux）上运行的 FastAPI 控制器。
- 项目未配置测试框架；`lint` 与 `tsc -b` 是仅有的静态检查。

### 仿真系统 (`manet-30ns3/`)

```bash
cd manet-30ns3

# 1. 构建镜像（节点 + 控制器）。controller 构建会编译 NS-3.45 并启用
#    --enable-python-bindings；ccache 已挂载，重复构建会更快。
docker compose --profile build build node-image-builder
docker compose build ns3-controller

# 2. 拉起控制器（FastAPI 监听 :8000，network_mode: host，特权模式）。
docker compose up -d ns3-controller
curl -s localhost:8000/api/health      # → {"ok": true}

# 3. 通过 REST 接口驱动一次仿真。
curl -X POST localhost:8000/api/sim/start \
     -H 'content-type: application/json' \
     -d '{"preset":"debug"}'           # 5 节点，60 秒，无衰落
curl -s localhost:8000/api/sim/status
curl -X POST localhost:8000/api/sim/stop

# 4. 打开 UI：http://localhost:8000/（FastAPI 托管 manet-30ns3/web-manager/）。
#    或在 dev 模式下：cd app && npm run dev → http://localhost:3000
#    （Vite 反代 /api 与 /ws）。

# 5. 全部下线（控制器的 /api/sim/stop 已经会清理 bridge / veth / TAP 与节点容器；
#    若还想停掉控制器自身）：
docker compose down
```

> **注意**：控制器会通过 `pyroute2` 修改**宿主网络状态**（创建 `br-ns3`、`veth{i}`、`tap-{i}`，并把 veth 移入容器 netns），需要 `--privileged`、`network_mode: host` 以及 Docker socket 访问权限。它**只能在 Linux 下运行**，且需要内核加载 `tun` / `tap` / `bridge` 模块——**无法在本仓库所在的 macOS 主机上跑**。要实际验证，请把仓库拷贝/克隆到 x86 Ubuntu 20.04（或等价 Linux VM）上再运行。

> **UI 包**：`manet-30ns3/web-manager/` 是构建时打入控制器镜像的静态包。修改 `app/` 源码后，必须先 `cd app && npm run build`，再把 `dist/*` 复制到 `manet-30ns3/web-manager/`，**然后**才执行 `docker compose build ns3-controller`——否则正在运行的控制器会继续提供旧版本的前端。

## 架构说明

### 仿真：每节点一个容器，所有流量强制经过 ns-3

整体设计参考 `manet-30ns3/README.md`（含原始 ASCII 拓扑图）以及 `/Users/binnary/.claude/plans/melodic-puzzling-pebble.md`（产出当前 Python 实现的重设计文档）。核心是**严格的网络隔离**：

- 每个节点是一个用 `network_mode="none"` 启动的 Docker 容器（独立 netns，无 Docker bridge），容器之间无法直接相互访问。
- 对每个节点 `i`，`controller/orchestrator/netns.py`（基于 pyroute2）创建一对 `veth`：宿主端 `veth{i}` 接到 Linux bridge `br-ns3`；对端 `vethns{i}` 被移入容器的 netns 并改名为 `eth0`。
- 同时创建 `tap-{i}` 并挂到 `br-ns3`。控制器容器内，ns-3 通过 `TapBridgeHelper` 在 `UseBridge` 模式下把每个 TAP 与一个 ns-3 WifiNetDevice 绑定。默认配置下，WifiNetDevice 由 `MeshHelper`（802.11s + HWMP）创建，运行在 SpectrumWifiPhy 上、中心频率 590 MHz（覆盖 500–680 MHz UHF 频段）、Friis 路径损耗按 4 km 视距预算调好（30 dBm Tx + 3 dBi 天线 + −92 dBm 接收灵敏度，余约 15 dB）。`mac_mode="adhoc"` 可退回到 `AdhocWifiMac`。
- 结果：`manet-node-A:eth0` 发出的每一帧都会经过 `br-ns3` → `tap-A` → ns-3，由 mesh PHY/MAC 与配置好的传播模型决定它能否被任何处于半径 ~4 km 内的对端接收；超出单跳视距的目标节点由 HWMP 自动在中间节点之间多跳转发。Linux bridge 自身永远不会让节点间的流量短路——因为没有任何容器之间存在可路由的直连路径。
- 子网 `192.168.100.0/24`；节点 `i` 分配 `192.168.100.(10+i)`，bridge IP 是 `192.168.100.1`。节点 0 是 `server`，节点 15 是 `gateway`，其余是 `client`（在 `controller/api/state.py:default_node_specs` 中设置）。

多跳模型说明：默认 `mac_mode="mesh"` 时，整张 mesh 在容器视角下表现为单一 L2 广播域，多跳转发由 ns-3 mesh 模块的 HWMP 在 L2 完成，容器内部不需要再跑 batman-adv / olsrd 之类的 L2 mesh 协议。`mac_mode="adhoc"` 是历史 fallback 路径——在该模式下 `UseBridge` 仅承担单跳 L2 桥接，安装在 ns-3 IP 协议栈上的 AODV/OLSR/DSDV/DSR 只看得到 ns-3 自己的控制面流量、看不到容器载荷，因此跨多跳的容器流量必须由容器内部的软件（如 batman-adv）自己处理。

### FastAPI 控制平面 (`controller/`)

控制器镜像（`ns3-controller/Dockerfile.controller`）打包了启用 `--enable-python-bindings` 的 NS-3.45、`controller/` Python 包以及预构建的 `web-manager/` 前端。镜像启动 `uvicorn controller.api.main:app`，监听 8000 端口。

模块布局：

```
controller/
├── orchestrator/
│   ├── config.py        # Pydantic SimConfig + NodeSpec + PRESETS + load_config()
│   ├── netns.py         # ensure_bridge / create_veth / move_to_netns / create_tap / teardown
│   ├── docker_mgr.py    # DockerMgr.start_one/stop_all/exec_in/logs（docker SDK）
│   ├── sim_runner.py    # SimRunner 在守护线程里跑 ns-3；惰性 `from ns import ns`
│   └── telemetry.py     # FlowMonitor + 位置快照 → asyncio.Queue 订阅者
└── api/
    ├── main.py          # FastAPI app、CORS、lifespan，挂载 /api + /ws + StaticFiles("/")
    ├── state.py         # Session 单例，包装 start/stop 生命周期
    ├── routes_sim.py    # POST /api/sim/start|stop, GET /api/sim/status|presets
    ├── routes_nodes.py  # GET /api/nodes /api/flows, POST /api/nodes/{id}/exec, GET /api/logs
    ├── routes_config.py # GET/PUT /api/config（运行中拒绝 PUT）
    └── ws_telemetry.py  # GET /ws/telemetry（1 Hz 帧，schema 见设计文档 §8.2）
```

线程模型：FastAPI 跑在 asyncio 主循环；`SimRunner` 在守护线程里运行 `ns3::Simulator::Run`；遥测由一个 `asyncio.Task` 周期性轮询 `SimRunner` 状态，并把 JSON 帧广播给所有 WebSocket 订阅者。

### 配置：Pydantic SimConfig + REST + 兼容旧版 .conf 解析

`controller/orchestrator/config.py` 是仿真参数的唯一权威源。

- **`SimConfig`** 是 Pydantic v2 模型，使用 `alias_generator=to_camel, populate_by_name=True`。每个字段都有默认值，与 `PRESETS["default"]` 一致。线上线下交互均使用 camelCase（与 `app/src/types/config.ts` 对齐），Python 内部使用 snake_case。约 80 个字段覆盖 PHY / 传播 / MAC / 路由 / 移动 / 跟踪。
- **优先级在代码里显式实现**：`load_config(file_path, overrides, preset)` 的次序为 显式 `overrides`（REST body）> `.conf` 文件 > 选定的 `preset` > 内置默认值。这与旧版 `manet-30nodes.cc` **正好相反**——旧版让 `.conf` 反过来覆盖 CLI 参数（README 当年写错了次序）。Python 加载器是与文档一致的。
- **旧版 `.conf` 文件**由 `parse_conf_file(path)` 解析，接受 React `useSimConfig.exportConfig` 写出的 camelCase key，同时显式翻译两个旧别名 `pcapTracing → pcap` 与 `asciiTracing → ascii`（这两个 key 在原 C++ 解析器里被静默丢弃，Python 加载器予以纠正）。新增可调参数的步骤：在 `SimConfig` 增加字段、在 `sim_runner.py` 把参数串起来、（可选）更新 `PRESETS`。React UI 类型（`app/src/types/config.ts`）目前需手工保持一致；后续可考虑由 OpenAPI 自动生成 TS 类型。
- 预设 `default`、`urban`、`rural`、`debug` 定义在 `PRESETS` 中，并通过 `GET /api/sim/presets` 暴露。

### React 应用结构

- 入口：`src/main.tsx` → `src/App.tsx`。单页应用，五个 Tab（Dashboard / Configuration / Topology / Realtime / Logs）以及一个常驻侧边栏（`ControlPanel` + `LogView`）。
- 状态拆分到两个 hook：
  - `useSimConfig`（`src/hooks/useSimConfig.ts`）—— 持有 `SimConfig`、预设加载、`.conf` 导入/导出。`exportConfig` 输出 `key = value` 行，key 命名与 Python 解析器精确对齐。
  - `useSimulation`（`src/hooks/useSimulation.ts`）—— **已与 FastAPI 后端打通**。打开 `WebSocket('/ws/telemetry')` 并自动重连（3 秒），每帧到达后用其覆盖 `nodes` / `flows` / `status`。`startSimulation(config?, preset?)` → `POST /api/sim/start`；`stopSimulation()` → `POST /api/sim/stop`。已经**不再有任何 mock 数据**。
- 类型与预设集中在 `src/types/config.ts`。其中 `PRESETS`（default / urban / rural / debug）与 `controller/orchestrator/config.py:PRESETS` 对应。跟踪字段命名为 `pcap` / `ascii`（已从旧名 `pcapTracing` / `asciiTracing` 改名，与 Python 解析器保持一致）。
- 各 Section：`Dashboard.tsx`、`ConfigPanel.tsx`、`ControlPanel.tsx`、`TopologyView.tsx`（基于 Canvas）、`LogView.tsx`。shadcn 原子组件位于 `src/components/ui/`。

### 构建缓存

两个 Dockerfile（`node/Dockerfile.node`、`ns3-controller/Dockerfile.controller`）都跑在 `linux/amd64` 上、使用 `ccache`（挂载到 `/ccache`，上限 10 GB）。控制器构建是慢项（完整 NS-3.45 编译 + Python 绑定）；节点镜像很小且很快。**仓库不再支持 ARM64 / 多架构** —— Dockerfile、workflow 与脚本中已不再有 `TARGETPLATFORM` / `TARGETARCH` 之类的分支。

### 多机部署（暂未实现）

当前已落地的是**单机 MVP**。多机为已设计但延后到第二阶段：一台机器运行 ns-3 控制器，独占 `br-ns3` 与所有 TAP；其它机器只跑节点容器，其 `veth*-h` 端不接本地 bridge，而是接到一个 VXLAN 网卡，把控制器主机上的 `br-ns3` 在 L2 上扩展过来。`netns.py` 与 `docker_mgr.py` 增加 `host` 参数；ns-3 进程仍只有一个，从而保证仿真时间与 PHY 模型一致。详见设计文档 §9。

## 验证（仅 Linux）

设计文档 §11 中的端到端冒烟测试。要求 x86 Ubuntu 20.04（或等价系统），Docker ≥ 20.10，内核加载 `tun` / `bridge` / `veth`。

```bash
cd manet-30ns3

# 1. 构建
docker compose --profile build build node-image-builder
docker compose build ns3-controller
# 预期：ns3-controller 镜像内存在 /opt/ns-3.45/build/bindings/python/ns/__init__.py

# 2. 起服
docker compose up -d ns3-controller
curl -s localhost:8000/api/health     # {"ok": true}

# 3. 用 debug 预设启动一次仿真（5 节点冒烟）
curl -X POST localhost:8000/api/sim/start \
     -H 'content-type: application/json' \
     -d '{"preset":"debug"}'
ip link | grep -E 'br-ns3|tap-|veth'  # 应能看到 br-ns3、5 个 tap-{i}、5 个 veth{i}
docker ps | grep manet-node           # 应能看到 5 个节点容器

# 4. 连通性（节点 0 = 服务端 @ 192.168.100.10；节点 1 @ .11；节点 4 @ .14）
docker exec manet-node-0 ping -c 3 192.168.100.11
docker exec manet-node-0 iperf3 -c 192.168.100.14 -t 5

# 5. 遥测
#    打开 http://localhost:8000/ → React UI 应正常加载。
#    Topology 页应显示 5 个节点；iperf3 起来约 10 秒后 FlowStats 列表会更新。

# 6. 用户软件加载模式（R7）—— 重复第 3 步，分别使用三种 USER_APP_MODE：
#    通过修改 start payload 中 `nodes` 数组实现，例如：
curl -X POST localhost:8000/api/sim/start \
     -H 'content-type: application/json' \
     -d '{"preset":"debug","nodes":[{"id":0,"userAppMode":"exec"}]}'
curl -X POST localhost:8000/api/nodes/0/exec \
     -H 'content-type: application/json' \
     -d '{"cmd":"echo hi"}'
curl 'localhost:8000/api/logs?node=0&tail=20'

# 7. 拆除
curl -X POST localhost:8000/api/sim/stop
ip link | grep -E 'br-ns3|tap-|veth' || echo "clean"   # 期望输出 "clean"
```

如果第 1 步失败（pip 解析到不兼容的 wheel，或 ns-3 cmake 阶段卡在某个模块），请加 `--no-cache` 重试一次；持续失败时把 ns-3 commit 钉死再排查。设计文档 §12 列出了三类已知风险（Python 绑定稳定性、大规模 N 时 TapBridge 实时模式回压、特权控制器的攻击面）。

## 工作笔记

- 仓库根目录**不是** git 仓库。`manet-30ns3.tar.gz` 是仿真系统的一个打包（很可能是规范分发产物）。请把 `manet-30ns3/` 当作工作副本对待。
- `app/src/components/ui/` 由 shadcn 生成，**不要**手工修改原子组件，定制时优先在 `src/sections/` 中通过组合方式实现。
- `manet-30ns3/skills/webapp-building/` 是用于初始化 `app/` 的 skill 脚手架，仅供参考，不属于运行时。
- `manet-30ns3/ns3-code/manet-30nodes.cc`、`setup-network.sh`、`start-simulation.sh`、`cleanup.sh`、`web-manager-start.sh` 都是**遗留代码**——保留在树中只为参考，运行时不再使用。Python 控制器（`controller/`）才是权威实现。
- 持久化的设计文档位于 `/Users/binnary/.claude/plans/melodic-puzzling-pebble.md`，其中 §3 的需求溯源表（R1–R8）可用于事后审计。
