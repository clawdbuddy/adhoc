import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { SimulationStatus, FlowStats, NodeStatus } from '@/types/config';
import { Activity, ArrowDownToLine, ArrowUpFromLine, Info, Radio } from 'lucide-react';

interface DashboardProps {
  status: SimulationStatus;
  flows: FlowStats[];
  nodes: NodeStatus[];
  config?: {
    beaconInterval: number;
    ssid: string;
    standard: string;
    dataRate: string;
    txPowerStart: number;
    frequencyMhz: number;
    macMode: string;
  };
}

export function Dashboard({ status, flows, nodes, config }: DashboardProps) {
  const totalTx = flows.reduce((sum, f) => sum + f.txPackets, 0);
  const totalLost = flows.reduce((sum, f) => sum + f.lostPackets, 0);
  const lossRate = totalTx > 0 ? (totalLost / totalTx) * 100 : 0;

  const totalRxNodes = nodes.reduce((sum, n) => sum + n.rxPackets, 0);
  const totalTxNodes = nodes.reduce((sum, n) => sum + n.txPackets, 0);

  return (
    <div className="space-y-3">
      {/* Compact Status Banner */}
      <div className="flex items-center gap-3">
        <div className={`h-2.5 w-2.5 rounded-full ${status.running ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
        <span className="text-sm font-medium">
          仿真{status.running ? '运行中' : '已停止'}
        </span>
        {status.running && (
          <Badge variant="outline" className="text-green-600 border-green-600 text-xs h-5 px-1.5">
            <Activity className="h-3 w-3 mr-0.5" />
            实时
          </Badge>
        )}

        <div className="ml-auto flex items-center gap-4 text-xs text-muted-foreground">
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="flex items-center gap-1 cursor-help">
                <ArrowDownToLine className="h-3 w-3 text-blue-600" />
                节点总接收
                <span className="font-mono font-semibold text-foreground">
                  {totalRxNodes.toLocaleString()}
                </span>
                <Info className="h-3 w-3 opacity-50" />
              </span>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-xs">
              <p>ns-3 WifiNetDevice 接收包总数，含数据包、信标、ACK、广播等控制包。</p>
              <p className="mt-1 text-amber-300">注：广播包会被每个邻居各计一次接收，因此该值通常远大于发送量。</p>
            </TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <span className="flex items-center gap-1 cursor-help">
                <ArrowUpFromLine className="h-3 w-3 text-purple-600" />
                节点总发送
                <span className="font-mono font-semibold text-foreground">
                  {totalTxNodes.toLocaleString()}
                </span>
                <Info className="h-3 w-3 opacity-50" />
              </span>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-xs">
              <p>ns-3 WifiNetDevice 发送包总数，含数据包、信标、RTS/CTS 等控制包。</p>
            </TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <span className="flex items-center gap-1 cursor-help">
                丢包率
                <span className={`font-mono font-semibold ${
                  lossRate > 10 ? 'text-red-600' : lossRate > 1 ? 'text-amber-600' : 'text-green-600'
                }`}>
                  {lossRate.toFixed(2)}%
                </span>
                <span className="text-[10px]">
                  ({totalLost}/{totalTx})
                </span>
                <Info className="h-3 w-3 opacity-50" />
              </span>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-xs">
              <p>FlowMonitor 统计的 IP 层丢包率（仅对 ns-3 内部流量有效）。</p>
              <p className="mt-1 text-amber-300">注：TapBridge 模式下 FlowMonitor 看不到容器流量，此处通常显示 0。</p>
            </TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* MAC Layer Overhead Estimation */}
      {config && (
        <Card className="bg-slate-50 border-slate-200">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs flex items-center gap-2 text-slate-600">
              <Radio className="h-3.5 w-3.5" />
              MAC 层开销估算
              <Tooltip>
                <TooltipTrigger asChild>
                  <Info className="h-3 w-3 opacity-50 cursor-help" />
                </TooltipTrigger>
                <TooltipContent side="bottom" className="max-w-xs">
                  <p>基于配置参数和遥测数据估算的 MAC/PHY 层控制帧开销。</p>
                  <p className="mt-1 text-amber-300">注：实际帧计数未在 Python 绑定中暴露，此处为理论估算。</p>
                </TooltipContent>
              </Tooltip>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              <div className="space-y-1">
                <span className="text-muted-foreground">信标间隔</span>
                <div className="font-mono font-semibold">{(config.beaconInterval * 1.024).toFixed(1)} ms</div>
                <div className="text-[10px] text-muted-foreground">{config.beaconInterval} TU</div>
              </div>
              <div className="space-y-1">
                <span className="text-muted-foreground">估算信标帧长</span>
                <div className="font-mono font-semibold">{80 + config.ssid.length * 2 + 20} B</div>
                <div className="text-[10px] text-muted-foreground">SSID={config.ssid.length} 字节</div>
              </div>
              <div className="space-y-1">
                <span className="text-muted-foreground">ACK 帧长</span>
                <div className="font-mono font-semibold">14 B</div>
                <div className="text-[10px] text-muted-foreground">802.11 固定</div>
              </div>
              <div className="space-y-1">
                <span className="text-muted-foreground">控制帧倍率</span>
                <div className={`font-mono font-semibold ${totalTxNodes > 0 && totalRxNodes / totalTxNodes > 10 ? 'text-amber-600' : ''}`}>
                  {totalTxNodes > 0 ? (totalRxNodes / totalTxNodes).toFixed(1) : '—'}x
                </div>
                <div className="text-[10px] text-muted-foreground">rx/tx</div>
              </div>
            </div>
            {totalTxNodes > 0 && totalRxNodes / totalTxNodes > 10 && (
              <div className="mt-2 text-[10px] text-amber-700 bg-amber-50 rounded px-2 py-1">
                接收量约为发送量的 {(totalRxNodes / totalTxNodes).toFixed(0)} 倍，说明信标/广播等控制帧占主导。
                {config.macMode === 'adhoc' && ' Adhoc 模式下信标和探测帧开销较大，切到 mesh 或增大 beaconInterval 可降低。'}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
