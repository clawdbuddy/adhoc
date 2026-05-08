import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { SimulationStatus, FlowStats, NodeStatus } from '@/types/config';
import {
  Activity, ArrowDownToLine, ArrowUpFromLine,
  Wifi, Router, TrendingUp, TrendingDown,
} from 'lucide-react';

interface DashboardProps {
  status: SimulationStatus;
  flows: FlowStats[];
  nodes: NodeStatus[];
}

interface StatCardProps {
  label: string;
  value: string | number;
  subValue?: string;
  icon: React.ReactNode;
  iconBg: string;
  trend?: 'up' | 'down' | 'neutral';
  tooltip?: string;
}

function StatCard({ label, value, subValue, icon, iconBg, trend, tooltip }: StatCardProps) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="bg-card rounded-lg border p-2 shadow-card hover:shadow-card-hover transition-all duration-200 card-lift cursor-default">
          <div className="flex items-start justify-between">
            <div className="space-y-0.5">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">{label}</p>
              <div className="flex items-baseline gap-1.5">
                <span className="text-lg font-bold tracking-tight">{value}</span>
                {trend && trend !== 'neutral' && (
                  trend === 'up'
                    ? <TrendingUp className="h-3 w-3 text-success" />
                    : <TrendingDown className="h-3 w-3 text-destructive" />
                )}
              </div>
              {subValue && <p className="text-[10px] text-muted-foreground">{subValue}</p>}
            </div>
            <div className={`h-7 w-7 rounded-lg flex items-center justify-center shrink-0 ${iconBg}`}>
              {icon}
            </div>
          </div>
        </div>
      </TooltipTrigger>
      {tooltip && (
        <TooltipContent side="bottom" className="max-w-xs text-xs">
          {tooltip}
        </TooltipContent>
      )}
    </Tooltip>
  );
}

export function Dashboard({ status, flows, nodes }: DashboardProps) {
  const totalRxNodes = nodes.reduce((sum, n) => sum + n.rxPackets, 0);
  const totalTxNodes = nodes.reduce((sum, n) => sum + n.txPackets, 0);

  const onlineNodes = nodes.filter(n => n.status === 'online').length;
  const activeFlowCount = flows.filter(f => f.txPackets > 0).length;

  return (
    <div className="space-y-3">
      {/* Status Banner */}
      <div className="flex items-center gap-3">
        <div className={`h-2.5 w-2.5 rounded-full ${status.running ? 'bg-success ring-2 ring-success/20 status-glow-green animate-pulse-soft' : 'bg-destructive ring-2 ring-destructive/20 status-glow-red'}`} />
        <span className="text-sm font-semibold">
          仿真{status.running ? '运行中' : '已停止'}
        </span>
        {status.running && (
          <Badge variant="outline" className="text-success border-success/40 text-xs h-5 px-2 font-medium gap-1">
            <Activity className="h-3 w-3" />
            实时
          </Badge>
        )}

      </div>

      {/* Stat Cards Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          label="在线节点"
          value={`${onlineNodes}/${nodes.length}`}
          subValue={status.running ? '实时更新' : '仿真未运行'}
          icon={<Wifi className="h-4 w-4 text-success" />}
          iconBg="bg-success/10"
          tooltip="当前处于 online 状态的节点数量"
        />
        <StatCard
          label="活跃流量"
          value={activeFlowCount}
          subValue={`${flows.length} 总流`}
          icon={<Router className="h-4 w-4 text-primary" />}
          iconBg="bg-primary/10"
          tooltip="当前有数据包发送的活跃流量数"
        />
        <StatCard
          label="总发送量"
          value={totalTxNodes > 1000 ? `${(totalTxNodes / 1000).toFixed(1)}k` : totalTxNodes}
          subValue="packets"
          icon={<ArrowUpFromLine className="h-4 w-4 text-cyan-500" />}
          iconBg="bg-cyan-500/10"
          tooltip="所有节点 WifiNetDevice 发送包总数"
        />
        <StatCard
          label="总接收量"
          value={totalRxNodes > 1000 ? `${(totalRxNodes / 1000).toFixed(1)}k` : totalRxNodes}
          subValue="packets"
          icon={<ArrowDownToLine className="h-4 w-4 text-violet-500" />}
          iconBg="bg-violet-500/10"
          tooltip="所有节点 WifiNetDevice 接收包总数（含广播重复计数）"
        />
      </div>
    </div>
  );
}
