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
import { ProtoTest } from '@/sections/ProtoTest';
import {
  LayoutDashboard, Settings, Network, ScrollText, Zap, Radio,
  Play, Square, RotateCw, Wifi, Route,
} from 'lucide-react';
import './App.css';

// 构建时间戳：每次修改后更新，确保 Vite 内容哈希变化，避免浏览器缓存旧版本
const BUILD_TIME = '2026-05-08-0015';
void BUILD_TIME;

const NAV_ITEMS = [
  { key: 'dashboard', label: '仪表板', icon: LayoutDashboard },
  { key: 'config', label: '配置', icon: Settings },
  { key: 'dynamic', label: '动态控制', icon: Zap },
  { key: 'proto', label: '协议测试', icon: Radio },
  { key: 'logs', label: '日志', icon: ScrollText },
] as const;

type PageKey = typeof NAV_ITEMS[number]['key'];

function App() {
  const sim = useSimulation();
  const {
    config, activePreset, presets, saveStatus, updateConfig,
    loadPreset, resetToDefault, exportConfig, importConfig,
  } = useSimConfig(sim);

  const { status, nodes, flows, env, logs, startSimulation, stopSimulation, addLog } = sim;

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
    const liveIds = nodes.map(n => n.id);
    const srcId = liveIds[Math.floor(Math.random() * liveIds.length)];
    let dstId = liveIds[Math.floor(Math.random() * liveIds.length)];
    if (dstId === srcId) {
      dstId = liveIds[(liveIds.indexOf(srcId) + 1) % liveIds.length];
    }
    addLog(`[traceroute] 节点${srcId} → 节点${dstId} 路径分析中...`);
    try {
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
      {/* 左侧边栏 - Glass morphism effect */}
      <aside className="w-56 border-r bg-card/80 backdrop-blur-xl flex flex-col shrink-0 shadow-sm">
        {/* Logo area */}
        <div className="h-16 border-b flex items-center px-5 gap-3 shrink-0">
          <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-primary to-cyan-400 flex items-center justify-center shrink-0 shadow-glow">
            <Network className="h-4 w-4 text-white" />
          </div>
          <div className="overflow-hidden">
            <h1 className="text-sm font-bold leading-tight truncate tracking-tight">MANET</h1>
            <p className="text-[11px] text-muted-foreground truncate font-medium">仿真控制面板</p>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-2 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.map(item => {
            const Icon = item.icon;
            const isActive = activePage === item.key;
            return (
              <button
                key={item.key}
                onClick={() => setActivePage(item.key)}
                className={cn(
                  'w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200',
                  isActive
                    ? 'bg-primary text-primary-foreground shadow-glow'
                    : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground'
                )}
              >
                <Icon className={cn('h-4 w-4 shrink-0', isActive && 'text-primary-foreground')} />
                <span>{item.label}</span>
                {isActive && (
                  <div className="ml-auto h-1.5 w-1.5 rounded-full bg-primary-foreground/70" />
                )}
              </button>
            );
          })}
        </nav>

        {/* Bottom status */}
        <div className="p-3 border-t shrink-0">
          <div className="flex items-center gap-2.5 text-xs">
            <div className={cn(
              'h-2.5 w-2.5 rounded-full ring-2 ring-offset-1 ring-offset-background transition-all duration-300',
              status.running ? 'bg-success ring-success/30 status-glow-green animate-pulse-soft' : 'bg-destructive ring-destructive/30 status-glow-red'
            )} />
            <span className="font-medium text-foreground">
              {status.running ? '仿真运行中' : '系统空闲'}
            </span>
            {status.running && (
              <span className="ml-auto font-mono text-[11px] text-muted-foreground tabular-nums">
                {elapsedMin}:{elapsedSec.toString().padStart(2, '0')} / {totalMin}:{totalSec.toString().padStart(2, '0')}
              </span>
            )}
          </div>
        </div>
      </aside>

      {/* 主内容区 */}
      <main className="flex-1 min-w-0 flex flex-col bg-dot-pattern">
        {/* 顶部工具栏 */}
        <header className="border-b bg-card/70 backdrop-blur-lg shrink-0 shadow-xs">
          <div className="px-4 py-2.5 flex items-center gap-4">
            <h2 className="text-base font-semibold shrink-0 tracking-tight">
              {NAV_ITEMS.find(n => n.key === activePage)?.label}
            </h2>

            <div className="flex-1 flex items-center justify-end gap-2 flex-wrap">
              {/* Status badge */}
              <div className="flex items-center gap-2 shrink-0 px-3 py-1 rounded-full bg-muted/70">
                <div className={cn(
                  'h-2 w-2 rounded-full',
                  status.running ? 'bg-success animate-pulse-soft' : 'bg-destructive'
                )} />
                <span className="text-sm font-medium">
                  {status.running ? '运行中' : '已停止'}
                </span>
                {status.running && (
                  <span className="text-xs text-muted-foreground font-mono tabular-nums">
                    {elapsedMin}:{elapsedSec.toString().padStart(2, '0')} / {totalMin}:{totalSec.toString().padStart(2, '0')}
                  </span>
                )}
              </div>

              <div className="h-5 w-px bg-border shrink-0" />

              {/* Core controls */}
              <Button size="sm" onClick={handleStart} disabled={status.running} className="h-8 gap-1.5 bg-success hover:bg-success/90 text-success-foreground">
                <Play className="h-3.5 w-3.5" />
                <span className="hidden sm:inline font-medium">启动</span>
              </Button>
              <Button size="sm" variant="destructive" onClick={stopSimulation} disabled={!status.running} className="h-8 gap-1.5">
                <Square className="h-3.5 w-3.5" />
                <span className="hidden sm:inline font-medium">停止</span>
              </Button>

              <div className="h-5 w-px bg-border shrink-0" />

              {/* Quick actions */}
              <Button size="sm" variant="outline" onClick={handleRestart} disabled={false} className="h-8 gap-1.5">
                <RotateCw className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">重启</span>
              </Button>
              <Button size="sm" variant="outline" onClick={handleIperf3} disabled={!status.running} className="h-8 gap-1.5">
                <Wifi className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">iperf3</span>
              </Button>
              <Button size="sm" variant="outline" onClick={handleTraceroute} disabled={!status.running} className="h-8 gap-1.5">
                <Route className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">路由追踪</span>
              </Button>

              {saveStatus && saveStatus !== 'idle' && activePage === 'config' && (
                <span className={cn(
                  'text-xs font-medium shrink-0 px-2 py-0.5 rounded-full',
                  saveStatus === 'saving' && 'text-amber-700 bg-amber-100',
                  saveStatus === 'saved' && 'text-green-700 bg-green-100',
                  saveStatus === 'error' && 'text-red-700 bg-red-100'
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
            <div className="h-full flex flex-col overflow-hidden p-3 space-y-3 animate-fade-in">
              <Dashboard
                status={status}
                flows={flows}
                nodes={nodes}
                config={{
                  beaconInterval: config.beaconInterval,
                  ssid: config.ssid,
                  standard: config.standard,
                  dataRate: config.dataRate,
                  txPowerStart: config.txPowerStart,
                  frequencyMhz: config.frequencyMhz,
                  macMode: config.macMode,
                }}
              />
              <div className="flex-1 min-h-0 overflow-auto">
                <TopologyView nodes={nodes} flows={flows} running={status.running} compact sim={sim} />
              </div>
            </div>
          )}

          {activePage === 'config' && (
            <div className="h-full overflow-auto p-4 animate-fade-in">
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
            <div className="h-full overflow-auto p-4 animate-fade-in">
              <DynamicControl status={status} nodes={nodes} config={config} env={env} sim={sim} />
            </div>
          )}

          {activePage === 'proto' && (
            <div className="h-full overflow-hidden animate-fade-in">
              <ProtoTest />
            </div>
          )}

          {activePage === 'logs' && (
            <div className="h-full overflow-auto p-4 animate-fade-in">
              <LogView logs={logs} onClear={handleClearLogs} />
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
