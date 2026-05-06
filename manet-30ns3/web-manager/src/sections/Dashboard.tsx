import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { SimulationStatus, FlowStats, NodeStatus } from '@/types/config';
import { Activity, ArrowDownToLine, ArrowUpFromLine, Info } from 'lucide-react';

interface DashboardProps {
  status: SimulationStatus;
  flows: FlowStats[];
  nodes: NodeStatus[];
}

export function Dashboard({ status, flows, nodes }: DashboardProps) {
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

    </div>
  );
}
