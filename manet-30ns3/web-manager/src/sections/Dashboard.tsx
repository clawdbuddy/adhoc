import { Badge } from '@/components/ui/badge';
import type { SimulationStatus, FlowStats, NodeStatus } from '@/types/config';
import { Activity, ArrowDownToLine, ArrowUpFromLine } from 'lucide-react';

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
          <span className="flex items-center gap-1">
            <ArrowDownToLine className="h-3 w-3 text-blue-600" />
            总接收
            <span className="font-mono font-semibold text-foreground">
              {totalRxNodes.toLocaleString()}
            </span>
          </span>
          <span className="flex items-center gap-1">
            <ArrowUpFromLine className="h-3 w-3 text-purple-600" />
            总发送
            <span className="font-mono font-semibold text-foreground">
              {totalTxNodes.toLocaleString()}
            </span>
          </span>
          <span className="flex items-center gap-1">
            丢包率
            <span className={`font-mono font-semibold ${
              lossRate > 10 ? 'text-red-600' : lossRate > 1 ? 'text-amber-600' : 'text-green-600'
            }`}>
              {lossRate.toFixed(2)}%
            </span>
            <span className="text-[10px]">
              ({totalLost}/{totalTx})
            </span>
          </span>
        </div>
      </div>

    </div>
  );
}
