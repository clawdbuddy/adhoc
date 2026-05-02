import { useRef, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { NodeStatus, FlowStats } from '@/types/config';
import { Wifi, WifiOff, AlertTriangle, Crosshair, ArrowUp, ArrowDown } from 'lucide-react';

interface TopologyViewProps {
  nodes: NodeStatus[];
  flows: FlowStats[];
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'online') return <Wifi className="h-4 w-4 text-green-500" />;
  if (status === 'busy') return <AlertTriangle className="h-4 w-4 text-yellow-500" />;
  return <WifiOff className="h-4 w-4 text-red-500" />;
}

function StatusBadge({ status }: { status: string }) {
  if (status === 'online') return <Badge variant="outline" className="text-green-600 border-green-600 text-xs">在线</Badge>;
  if (status === 'busy') return <Badge variant="outline" className="text-yellow-600 border-yellow-600 text-xs">忙碌</Badge>;
  return <Badge variant="outline" className="text-red-600 border-red-600 text-xs">离线</Badge>;
}

export function TopologyView({ nodes, flows }: TopologyViewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || nodes.length === 0) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const padding = 30;

    // Find bounds
    const maxX = Math.max(...nodes.map(n => n.x), 500) + padding;
    const maxY = Math.max(...nodes.map(n => n.y), 500) + padding;
    const scaleX = (w - padding * 2) / maxX;
    const scaleY = (h - padding * 2) / maxY;
    const scale = Math.min(scaleX, scaleY);

    ctx.clearRect(0, 0, w, h);

    // Draw grid
    ctx.strokeStyle = '#e5e7eb';
    ctx.lineWidth = 1;
    for (let x = padding; x < w; x += 50) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = padding; y < h; y += 50) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    // Draw connections (neighbors)
    ctx.strokeStyle = '#93c5fd';
    ctx.lineWidth = 1;
    nodes.forEach(node => {
      const nx = padding + node.x * scale;
      const ny = padding + node.y * scale;
      node.neighbors.forEach(nbId => {
        const nb = nodes.find(n => n.id === nbId);
        if (nb && nb.status !== 'offline') {
          const nbx = padding + nb.x * scale;
          const nby = padding + nb.y * scale;
          ctx.beginPath();
          ctx.moveTo(nx, ny);
          ctx.lineTo(nbx, nby);
          ctx.stroke();
        }
      });
    });

    // Draw nodes
    nodes.forEach(node => {
      const nx = padding + node.x * scale;
      const ny = padding + node.y * scale;

      // Outer circle
      ctx.beginPath();
      ctx.arc(nx, ny, 12, 0, Math.PI * 2);
      if (node.status === 'online') ctx.fillStyle = '#22c55e';
      else if (node.status === 'busy') ctx.fillStyle = '#eab308';
      else ctx.fillStyle = '#ef4444';
      ctx.fill();
      ctx.strokeStyle = '#374151';
      ctx.lineWidth = 2;
      ctx.stroke();

      // Node ID
      ctx.fillStyle = '#ffffff';
      ctx.font = 'bold 10px sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(node.id), nx, ny);

      // Role indicator
      ctx.fillStyle = '#6b7280';
      ctx.font = '9px sans-serif';
      ctx.fillText(node.role.charAt(0).toUpperCase(), nx, ny + 20);
    });
  }, [nodes]);

  const onlineCount = nodes.filter(n => n.status !== 'offline').length;
  const totalRx = nodes.reduce((s, n) => s + n.rxPackets, 0);
  const totalTx = nodes.reduce((s, n) => s + n.txPackets, 0);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <Crosshair className="h-5 w-5 text-blue-500" />
            <div>
              <p className="text-2xl font-bold">{nodes.length}</p>
              <p className="text-xs text-muted-foreground">总节点数</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <Wifi className="h-5 w-5 text-green-500" />
            <div>
              <p className="text-2xl font-bold">{onlineCount}</p>
              <p className="text-xs text-muted-foreground">在线</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <ArrowDown className="h-5 w-5 text-blue-500" />
            <div>
              <p className="text-2xl font-bold">{totalRx.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">总接收</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 flex items-center gap-3">
            <ArrowUp className="h-5 w-5 text-purple-500" />
            <div>
              <p className="text-2xl font-bold">{totalTx.toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">总发送</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Topology Canvas */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-base">网络拓扑</CardTitle>
            <p className="text-xs text-muted-foreground">实时节点位置与邻居链路</p>
          </CardHeader>
          <CardContent>
            <canvas
              ref={canvasRef}
              style={{ width: '100%', height: '400px', borderRadius: '8px', background: '#f9fafb' }}
            />
            <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-green-500 inline-block" /> 在线</span>
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-yellow-500 inline-block" /> 忙碌</span>
              <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-full bg-red-500 inline-block" /> 离线</span>
              <span className="flex items-center gap-1"><span className="w-8 h-0.5 bg-blue-300 inline-block" /> 邻居链路</span>
            </div>
          </CardContent>
        </Card>

        {/* Node List */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">节点状态</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ScrollArea className="h-[400px]">
              <div className="space-y-1 px-4 pb-4">
                {nodes.map(node => (
                  <div key={node.id} className="flex items-center gap-2 py-1.5 border-b border-gray-100 last:border-0">
                    <StatusIcon status={node.status} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-semibold">Node-{node.id}</span>
                        <StatusBadge status={node.status} />
                        {node.role !== 'client' && (
                          <Badge variant="secondary" className="text-xs">{node.role}</Badge>
                        )}
                      </div>
                      <div className="text-xs text-muted-foreground font-mono">{node.ip}</div>
                    </div>
                    <div className="text-right text-xs text-muted-foreground">
                      <div>Rx: {(node.rxPackets / 1000).toFixed(1)}k</div>
                      <div>Tx: {(node.txPackets / 1000).toFixed(1)}k</div>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      {/* Flow Statistics */}
      {flows.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">流统计</CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[250px]">
              <div className="space-y-2">
                {flows.slice(0, 20).map(flow => (
                  <div key={flow.flowId} className="flex items-center gap-3 py-2 border-b border-gray-100 text-sm">
                    <span className="font-mono text-xs w-12">Flow-{flow.flowId}</span>
                    <span className="font-mono text-xs text-blue-600">{flow.source}</span>
                    <span className="text-muted-foreground">{'->'}</span>
                    <span className="font-mono text-xs text-green-600">{flow.destination}</span>
                    <div className="flex-1" />
                    <span className="text-xs">发: {flow.txPackets.toLocaleString()}</span>
                    <span className="text-xs">收: {flow.rxPackets.toLocaleString()}</span>
                    <span className="text-xs text-red-500">丢失: {flow.lostPackets}</span>
                    <span className="text-xs text-purple-600">{(flow.throughput).toFixed(2)} Mbps</span>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
