import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import type { SimulationStatus, NodeStatus } from '@/types/config';
import {
  Activity, Clock, Network, Server, ArrowUpDown,
  Wifi, WifiOff, AlertTriangle, Zap
} from 'lucide-react';

interface DashboardProps {
  status: SimulationStatus;
  nodes: NodeStatus[];
}

export function Dashboard({ status, nodes }: DashboardProps) {
  const onlineNodes = nodes.filter(n => n.status !== 'offline').length;
  const busyNodes = nodes.filter(n => n.status === 'busy').length;
  const offlineNodes = nodes.filter(n => n.status === 'offline').length;
  const avgLatency = nodes.length > 0
    ? nodes.filter(n => n.status !== 'offline').reduce((s, n) => s + n.latency, 0) / onlineNodes
    : 0;
  const packetLoss = status.totalTx > 0 ? (status.totalLost / status.totalTx * 100).toFixed(2) : '0';
  const elapsedMin = Math.floor(status.elapsed / 60);
  const elapsedSec = status.elapsed % 60;

  return (
    <div className="space-y-6">
      {/* Status Banner */}
      <div className="flex items-center gap-4">
        <div className={`h-3 w-3 rounded-full ${status.running ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
        <h2 className="text-xl font-semibold">
          Simulation {status.running ? 'Running' : 'Stopped'}
        </h2>
        {status.running && (
          <Badge variant="outline" className="text-green-600 border-green-600">
            <Activity className="h-3 w-3 mr-1" />
            Live
          </Badge>
        )}
      </div>

      {/* Key Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Network className="h-4 w-4" />
              Nodes Online
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{onlineNodes}/{status.totalNodes}</div>
            <Progress value={(onlineNodes / status.totalNodes) * 100} className="mt-2 h-2" />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Clock className="h-4 w-4" />
              Elapsed Time
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{elapsedMin}:{elapsedSec.toString().padStart(2, '0')}</div>
            <p className="text-xs text-muted-foreground mt-1">
              {status.startTime ? new Date(status.startTime).toLocaleString() : '--'}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <ArrowUpDown className="h-4 w-4" />
              Total Traffic
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{(status.totalTx + status.totalRx).toLocaleString()}</div>
            <p className="text-xs text-muted-foreground mt-1">
              Tx: {status.totalTx.toLocaleString()} / Rx: {status.totalRx.toLocaleString()}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              Packet Loss
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{packetLoss}%</div>
            <p className="text-xs text-muted-foreground mt-1">
              {status.totalLost.toLocaleString()} packets lost
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Second Row Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Server className="h-4 w-4" />
              Active Flows
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{status.activeFlows}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Zap className="h-4 w-4" />
              Avg Latency
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{avgLatency.toFixed(1)} ms</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <Wifi className="h-4 w-4" />
              Busy Nodes
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{busyNodes}</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <WifiOff className="h-4 w-4" />
              Offline Nodes
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{offlineNodes}</div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
