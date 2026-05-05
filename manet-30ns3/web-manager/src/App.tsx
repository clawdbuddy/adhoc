import { useState, useCallback } from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { useSimConfig } from '@/hooks/useSimConfig';
import { useSimulation } from '@/hooks/useSimulation';
import { Dashboard } from '@/sections/Dashboard';
import { ConfigPanel } from '@/sections/ConfigPanel';
import { TopologyView } from '@/sections/TopologyView';
import { LogView } from '@/sections/LogView';
import { DynamicControl } from '@/sections/DynamicControl';
import {
  LayoutDashboard, Settings, Network, ScrollText, Zap,
  Play, Square, RotateCw, Wifi, Route,
} from 'lucide-react';
import './App.css';

// 构建时间戳：每次修改后更新，确保 Vite 内容哈希变化，避免浏览器缓存旧版本
const BUILD_TIME = '2026-05-05-0010';
void BUILD_TIME;

const NAV_ITEMS = [
  { key: 'dashboard', label: '仪表板', icon: LayoutDashboard },
  { key: 'config', label: '配置', icon: Settings },
  { key: 'dynamic', label: '动态控制', icon: Zap },
  { key: 'logs', label: '日志', icon: ScrollText },
] as const;

type PageKey = typeof NAV_ITEMS[number]['key'];

function App() {
  const {
    config, activePreset, presets, saveStatus, updateConfig,
    loadPreset, resetToDefault, exportConfig, importConfig,
  } = useSimConfig();

  const { status, nodes, flows, env, logs, startSimulation, stopSimulation, addLog } = useSimulation(config.nNodes);

  const [activePage, setActivePage] = useState<PageKey>('dashboard');

  const handleStart = () => {
    startSimulation(config);
  };

  const handleRestart = async () => {
    if (!status.running) {
      addLog('[ui] 仿真未运行，直接启动');
      handleStart();
      return;
    }
    addLog('[ui] 正在重启仿真...');
    await stopSimulation();
    await new Promise(r => setTimeout(r, 1500));
    await startSimulation(config);
    addLog('[ui] 仿真已重启');
  };

  const handleIperf3 = async () => {
    if (!status.running) {
      addLog('[ui] 仿真未运行，无法执行 iperf3');
      return;
    }
    addLog('[ui] 启动 iperf3 测试...');
    try {
      // node-0 (server 角色) 已由 node-entrypoint.py 自动启动 iperf3 server，无需再启动
      const clientNode = Math.max(1, Math.floor(Math.random() * config.nNodes));
      const res = await fetch(`/api/nodes/${clientNode}/exec`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ cmd: 'iperf3 -c 192.168.100.10 -p 5201 -t 5 -J' }),
      });
      const data = await res.json();
      addLog(`[iperf3] clientNode=${clientNode} exitCode=${data.exitCode}`);
      if (data.output) {
        try {
          const json = JSON.parse(data.output);
          const sum = json.end?.sum_received;
          if (sum) {
            addLog(`[iperf3] 带宽: ${(sum.bits_per_second / 1e6).toFixed(2)} Mbps, 传输: ${(sum.bytes / 1e6).toFixed(2)} MB`);
          } else {
            addLog(`[iperf3] ${data.output.slice(0, 150)}`);
          }
        } catch {
          addLog(`[iperf3] ${data.output.slice(0, 150)}`);
        }
      }
    } catch (e) {
      addLog(`[iperf3] 失败: ${(e as Error).message}`);
    }
  };

  const handleTraceroute = async () => {
    if (!status.running) {
      addLog('[ui] 仿真未运行');
      return;
    }
    if (nodes.length < 2) {
      addLog('[traceroute] 节点不足，无法追踪路径');
      return;
    }
    // 选择两个不同的节点;尽量挑距离较远的一对以增加多跳概率
    const liveIds = nodes.map(n => n.id);
    const srcId = liveIds[Math.floor(Math.random() * liveIds.length)];
    let dstId = liveIds[Math.floor(Math.random() * liveIds.length)];
    if (dstId === srcId) {
      dstId = liveIds[(liveIds.indexOf(srcId) + 1) % liveIds.length];
    }
    addLog(`[traceroute] 节点${srcId} → 节点${dstId} 路径分析中...`);
    try {
      // 先查 ns-3 邻居拓扑给出的多跳路径(基于 range_target_m 的几何邻居图)
      const pathRes = await fetch(`/api/sim/path?src=${srcId}&dst=${dstId}`);
      if (pathRes.ok) {
        const pdata = await pathRes.json();
        if (pdata.reachable) {
          const arrow = pdata.path.map((nid: number, i: number) => {
            const ip = pdata.ips?.[i] ?? '';
            return `节点${nid}(${ip})`;
          }).join(' → ');
          addLog(`[traceroute] mesh 路径(${pdata.hops} 跳): ${arrow}`);
        } else {
          addLog(`[traceroute] 节点${srcId} 与 节点${dstId} 在当前几何拓扑下不连通`);
        }
      } else {
        addLog(`[traceroute] /api/sim/path 失败: ${pathRes.status}`);
      }
      // 同时跑容器内 traceroute 作为补充(UseBridge 模式下 L2 mesh 多跳对 L3 透明,
      // 通常只显示最终目的地这一跳;两路输出对照能让用户看到 L3 与 mesh 的差异)
      const targetIp = `192.168.100.${10 + dstId}`;
      const res = await fetch(`/api/nodes/${srcId}/exec`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ cmd: `traceroute -n -m 5 -w 1 ${targetIp}` }),
      });
      const data = await res.json();
      if (data.exitCode === 0 && data.output) {
        data.output.split('\n').slice(0, 8).forEach((line: string) => {
          if (line.trim()) addLog(`[traceroute L3] ${line}`);
        });
      } else if (data.output) {
        addLog(`[traceroute L3] (rc=${data.exitCode}) ${data.output.slice(0, 200)}`);
      }
    } catch (e) {
      addLog(`[traceroute] 失败: ${(e as Error).message}`);
    }
  };

  const handleClearLogs = useCallback(() => {
    addLog('[ui] 日志清空（功能待接入）');
  }, [addLog]);

  const elapsedMin = Math.floor(status.elapsed / 60);
  const elapsedSec = status.elapsed % 60;
  const totalMin = Math.floor(config.simulationTime / 60);
  const totalSec = config.simulationTime % 60;

  return (
    <div className="h-screen bg-background flex overflow-hidden">
      {/* 左侧边栏 */}
      <aside className="w-52 border-r bg-card flex flex-col shrink-0">
        <div className="h-14 border-b flex items-center px-4 gap-3 shrink-0">
          <div className="h-8 w-8 rounded-lg bg-primary flex items-center justify-center shrink-0">
            <Network className="h-4 w-4 text-primary-foreground" />
          </div>
          <div className="overflow-hidden">
            <h1 className="text-sm font-bold leading-tight truncate">NS-3 MANET</h1>
            <p className="text-[10px] text-muted-foreground truncate">仿真控制面板</p>
          </div>
        </div>

        <nav className="flex-1 p-1.5 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.map(item => {
            const Icon = item.icon;
            const isActive = activePage === item.key;
            return (
              <button
                key={item.key}
                onClick={() => setActivePage(item.key)}
                className={cn(
                  'w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors',
                  isActive
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="p-2 border-t shrink-0">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <div className={cn(
              'h-2 w-2 rounded-full',
              status.running ? 'bg-green-500 animate-pulse' : 'bg-red-500'
            )} />
            <span>{status.running ? '运行中' : '空闲'}</span>
          </div>
        </div>
      </aside>

      {/* 主内容区 */}
      <main className="flex-1 min-w-0 flex flex-col">
        {/* 顶部工具栏：标题 + 仿真控制 + 快捷操作 */}
        <header className="border-b bg-card shrink-0">
          <div className="px-3 py-2 flex items-center gap-3">
            <h2 className="text-base font-semibold shrink-0">
              {NAV_ITEMS.find(n => n.key === activePage)?.label}
            </h2>

            <div className="flex-1 flex items-center justify-end gap-3 flex-wrap">
              {/* 仿真状态 */}
              <div className="flex items-center gap-2 shrink-0">
                <div className={cn(
                  'h-2.5 w-2.5 rounded-full',
                  status.running ? 'bg-green-500 animate-pulse' : 'bg-red-500'
                )} />
                <span className="text-sm font-medium">
                  {status.running ? '运行中' : '已停止'}
                </span>
                {status.running && (
                  <span className="text-xs text-muted-foreground font-mono">
                    {elapsedMin}:{elapsedSec.toString().padStart(2, '0')} / {totalMin}:{totalSec.toString().padStart(2, '0')}
                  </span>
                )}
              </div>

              <div className="h-4 w-px bg-border shrink-0" />

              {/* 核心控制 */}
              <Button size="sm" onClick={handleStart} disabled={status.running} className="h-8 gap-1">
                <Play className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">启动</span>
              </Button>
              <Button size="sm" variant="destructive" onClick={stopSimulation} disabled={!status.running} className="h-8 gap-1">
                <Square className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">停止</span>
              </Button>

              <div className="h-4 w-px bg-border shrink-0" />

              {/* 快捷操作 */}
              <Button size="sm" variant="outline" onClick={handleRestart} disabled={false} className="h-8 gap-1">
                <RotateCw className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">重启</span>
              </Button>
              <Button size="sm" variant="outline" onClick={handleIperf3} disabled={!status.running} className="h-8 gap-1">
                <Wifi className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">iperf3</span>
              </Button>
              <Button size="sm" variant="outline" onClick={handleTraceroute} disabled={!status.running} className="h-8 gap-1">
                <Route className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">路由追踪</span>
              </Button>

              {saveStatus && saveStatus !== 'idle' && activePage === 'config' && (
                <span className={cn(
                  'text-xs font-medium shrink-0',
                  saveStatus === 'saving' && 'text-amber-600',
                  saveStatus === 'saved' && 'text-green-600',
                  saveStatus === 'error' && 'text-red-600'
                )}>
                  {saveStatus === 'saving' ? '保存中...' :
                   saveStatus === 'saved' ? '已保存' : '保存失败'}
                </span>
              )}
            </div>
          </div>
        </header>

        {/* 页面内容 */}
        <div className="flex-1 overflow-auto">
          {activePage === 'dashboard' && (
            <div className="h-full flex flex-col overflow-hidden p-2 space-y-2">
              <Dashboard status={status} flows={flows} nodes={nodes} />
              <div className="flex-1 min-h-0 overflow-auto">
                <TopologyView nodes={nodes} flows={flows} running={status.running} compact />
              </div>
            </div>
          )}

          {activePage === 'config' && (
            <div className="h-full overflow-auto p-3">
              <ConfigPanel
                config={config}
                activePreset={activePreset}
                presets={presets}
                saveStatus={saveStatus}
                updateConfig={updateConfig}
                loadPreset={loadPreset}
                resetToDefault={resetToDefault}
                exportConfig={exportConfig}
                importConfig={importConfig}
              />
            </div>
          )}

          {activePage === 'dynamic' && (
            <div className="h-full overflow-auto p-3">
              <DynamicControl status={status} nodes={nodes} config={config} env={env} />
            </div>
          )}

          {activePage === 'logs' && (
            <div className="h-full overflow-auto p-3">
              <LogView logs={logs} onClear={handleClearLogs} />
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
