import { useEffect, useRef, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { NodeStatus, FlowStats } from '@/types/config';
import {
  Wifi, WifiOff, AlertTriangle,
  Move, Activity, Grid3x3, Radio,
} from 'lucide-react';
import { useDynamicControl } from '@/hooks/useDynamicControl';

interface SimApi {
  setParam: (key: string, value: unknown) => Promise<{
    ok: boolean;
    key?: string;
    reason?: string;
    results?: Array<{ ok: boolean; nodeId?: number; reason?: string }>;
  }>;
}

interface TopologyViewProps {
  nodes: NodeStatus[];
  flows: FlowStats[];
  running: boolean;
  compact?: boolean;
  sim?: SimApi;
}

interface DragState {
  nodeId: number;
  simX: number;
  simY: number;
  moved: boolean;
}

interface Geom {
  w: number;
  h: number;
  padding: number;
  scale: number;
}

const PADDING = 30;
const NODE_RADIUS = 12;
const HIT_RADIUS = 16;

function StatusIcon({ status }: { status: string }) {
  if (status === 'online') return <Wifi className="h-4 w-4 text-success" />;
  if (status === 'busy') return <AlertTriangle className="h-4 w-4 text-warning" />;
  return <WifiOff className="h-4 w-4 text-destructive" />;
}

function StatusBadge({ status }: { status: string }) {
  if (status === 'online') return <Badge variant="outline" className="text-success border-success/40 text-xs font-medium">在线</Badge>;
  if (status === 'busy') return <Badge variant="outline" className="text-warning border-warning/40 text-xs font-medium">忙碌</Badge>;
  return <Badge variant="outline" className="text-destructive border-destructive/40 text-xs font-medium">离线</Badge>;
}

function computeGeom(canvas: HTMLCanvasElement, nodes: NodeStatus[], drag?: DragState | null): Geom {
  const rect = canvas.getBoundingClientRect();
  const viewNodes = drag ? applyDragOverride(nodes, drag) : nodes;
  const maxNodeX = viewNodes.length > 0 ? Math.max(...viewNodes.map(n => n.x)) : 0;
  const maxNodeY = viewNodes.length > 0 ? Math.max(...viewNodes.map(n => n.y)) : 0;
  const maxX = Math.max(2000, maxNodeX);
  const maxY = Math.max(2000, maxNodeY);
  const usableW = rect.width - PADDING * 2;
  const usableH = rect.height - PADDING * 2;
  const scaleX = usableW / (maxX + PADDING);
  const scaleY = usableH / (maxY + PADDING);
  const scale = Math.min(scaleX, scaleY);
  return { w: rect.width, h: rect.height, padding: PADDING, scale };
}

function simToCanvas(g: Geom, x: number, y: number): [number, number] {
  return [g.padding + x * g.scale, g.padding + y * g.scale];
}

function canvasToSim(g: Geom, cx: number, cy: number): [number, number] {
  const x = (cx - g.padding) / g.scale;
  const y = (cy - g.padding) / g.scale;
  return [Math.max(0, x), Math.max(0, y)];
}

function findNodeAt(nodes: NodeStatus[], g: Geom, cx: number, cy: number): NodeStatus | null {
  for (let i = nodes.length - 1; i >= 0; i--) {
    const n = nodes[i];
    const [nx, ny] = simToCanvas(g, n.x, n.y);
    const dx = cx - nx;
    const dy = cy - ny;
    if (dx * dx + dy * dy <= HIT_RADIUS * HIT_RADIUS) return n;
  }
  return null;
}

function applyDragOverride(nodes: NodeStatus[], drag: DragState | null): NodeStatus[] {
  if (!drag) return nodes;
  return nodes.map(n => n.id === drag.nodeId ? { ...n, x: drag.simX, y: drag.simY } : n);
}

function reachabilityCellStyle(reachable: boolean): { background: string; color: string } {
  if (reachable) {
    return { background: 'rgba(34, 197, 94, 0.12)', color: '#166534' };
  }
  return { background: 'transparent', color: '#9ca3af' };
}

function drawScene(
  canvas: HTMLCanvasElement,
  nodes: NodeStatus[],
  flows: FlowStats[],
  drag: DragState | null,
  hoverId: number | null,
  phase: number,
) {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const view = applyDragOverride(nodes, drag);
  const g = computeGeom(canvas, view);
  const dpr = window.devicePixelRatio || 1;
  const targetW = Math.round(g.w * dpr);
  const targetH = Math.round(g.h * dpr);
  if (canvas.width !== targetW) canvas.width = targetW;
  if (canvas.height !== targetH) canvas.height = targetH;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, g.w, g.h);

  // Subtle grid background
  ctx.strokeStyle = '#f1f5f9';
  ctx.lineWidth = 1;
  const gridStepPx = 50;
  ctx.fillStyle = '#94a3b8';
  ctx.font = '9px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let cx = g.padding; cx < g.w; cx += gridStepPx) {
    ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, g.h); ctx.stroke();
    const simX = Math.round((cx - g.padding) / g.scale);
    if (simX >= 0) ctx.fillText(`${simX}m`, cx, g.h - 14);
  }
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  for (let cy = g.padding; cy < g.h; cy += gridStepPx) {
    ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(g.w, cy); ctx.stroke();
    const simY = Math.round((cy - g.padding) / g.scale);
    if (simY >= 0) ctx.fillText(`${simY}m`, 4, cy);
  }

  // Scale bar
  const scaleBarMeters = Math.pow(10, Math.floor(Math.log10(100 / g.scale)));
  const scaleBarPx = scaleBarMeters * g.scale;
  const sbX = g.w - scaleBarPx - 12;
  const sbY = g.h - 28;
  ctx.strokeStyle = '#475569';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(sbX, sbY);
  ctx.lineTo(sbX + scaleBarPx, sbY);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(sbX, sbY - 4);
  ctx.lineTo(sbX, sbY + 4);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(sbX + scaleBarPx, sbY - 4);
  ctx.lineTo(sbX + scaleBarPx, sbY + 4);
  ctx.stroke();
  ctx.fillStyle = '#475569';
  ctx.font = '10px sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'bottom';
  ctx.fillText(`${scaleBarMeters}m`, sbX + scaleBarPx / 2, sbY - 4);

  // Neighbor links
  ctx.strokeStyle = '#bfdbfe';
  ctx.lineWidth = 1;
  view.forEach(node => {
    const [nx, ny] = simToCanvas(g, node.x, node.y);
    node.neighbors.forEach(nbId => {
      const nb = view.find(n => n.id === nbId);
      if (nb && nb.status !== 'offline') {
        const [nbx, nby] = simToCanvas(g, nb.x, nb.y);
        ctx.beginPath(); ctx.moveTo(nx, ny); ctx.lineTo(nbx, nby); ctx.stroke();
      }
    });
  });

  // Flow arrows
  const ipToNode = new Map<string, NodeStatus>();
  view.forEach(n => ipToNode.set(n.ip, n));
  const activeFlows = flows.filter(f => f.txPackets > 0);
  activeFlows.forEach(flow => {
    const src = ipToNode.get(flow.source);
    const dst = ipToNode.get(flow.destination);
    if (!src || !dst || src.id === dst.id) return;
    const [sx, sy] = simToCanvas(g, src.x, src.y);
    const [dxc, dyc] = simToCanvas(g, dst.x, dst.y);
    const dxv = dxc - sx;
    const dyv = dyc - sy;
    const dist = Math.hypot(dxv, dyv);
    if (dist < NODE_RADIUS * 2) return;

    const ux = dxv / dist;
    const uy = dyv / dist;
    const sx2 = sx + ux * (NODE_RADIUS + 2);
    const sy2 = sy + uy * (NODE_RADIUS + 2);
    const dx2 = dxc - ux * (NODE_RADIUS + 4);
    const dy2 = dyc - uy * (NODE_RADIUS + 4);

    const tput = Math.max(0, flow.throughput);
    const width = Math.max(1.5, Math.min(6, 1.5 + Math.log10(Math.max(0.01, tput) + 1) * 2.5));
    const alpha = Math.min(0.9, 0.45 + tput / 50);

    ctx.strokeStyle = `rgba(168, 85, 247, ${alpha})`;
    ctx.fillStyle = `rgba(168, 85, 247, ${Math.min(1, alpha + 0.1)})`;
    ctx.lineWidth = width;
    ctx.setLineDash([8, 6]);
    ctx.lineDashOffset = -phase;
    ctx.beginPath();
    ctx.moveTo(sx2, sy2);
    ctx.lineTo(dx2, dy2);
    ctx.stroke();
    ctx.setLineDash([]);

    const angle = Math.atan2(dyv, dxv);
    const headLen = 10;
    ctx.beginPath();
    ctx.moveTo(dx2, dy2);
    ctx.lineTo(
      dx2 - headLen * Math.cos(angle - Math.PI / 6),
      dy2 - headLen * Math.sin(angle - Math.PI / 6),
    );
    ctx.lineTo(
      dx2 - headLen * Math.cos(angle + Math.PI / 6),
      dy2 - headLen * Math.sin(angle + Math.PI / 6),
    );
    ctx.closePath();
    ctx.fill();

    if (tput > 0.05) {
      const mx = (sx2 + dx2) / 2;
      const my = (sy2 + dy2) / 2;
      const label = tput >= 1 ? `${tput.toFixed(2)} Mbps` : `${(tput * 1000).toFixed(0)} kbps`;
      ctx.font = '10px sans-serif';
      const tw = ctx.measureText(label).width;
      ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
      ctx.fillRect(mx - tw / 2 - 4, my - 12, tw + 8, 14);
      ctx.fillStyle = '#7c3aed';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, mx, my - 5);
    }
  });

  // Nodes
  view.forEach(node => {
    const [nx, ny] = simToCanvas(g, node.x, node.y);
    const isDragging = drag?.nodeId === node.id;
    const isHover = hoverId === node.id && !drag;
    const r = isDragging ? 14 : NODE_RADIUS;

    if (isDragging || isHover) {
      ctx.beginPath();
      ctx.arc(nx, ny, r + 5, 0, Math.PI * 2);
      ctx.fillStyle = isDragging ? 'rgba(59, 130, 246, 0.28)' : 'rgba(59, 130, 246, 0.15)';
      ctx.fill();
    }

    ctx.beginPath();
    ctx.arc(nx, ny, r, 0, Math.PI * 2);
    if (node.status === 'online') ctx.fillStyle = '#22c55e';
    else if (node.status === 'busy') ctx.fillStyle = '#eab308';
    else ctx.fillStyle = '#ef4444';
    ctx.fill();
    ctx.strokeStyle = isDragging ? '#1d4ed8' : '#374151';
    ctx.lineWidth = isDragging ? 2.5 : 2;
    ctx.stroke();

    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 10px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(node.id), nx, ny);

    ctx.fillStyle = '#6b7280';
    ctx.font = '9px sans-serif';
    ctx.fillText(node.role.charAt(0).toUpperCase(), nx, ny + r + 8);
  });

  if (drag) {
    const [nx, ny] = simToCanvas(g, drag.simX, drag.simY);
    const label = `(${drag.simX.toFixed(0)}, ${drag.simY.toFixed(0)})m`;
    ctx.font = '11px sans-serif';
    const tw = ctx.measureText(label).width;
    ctx.fillStyle = 'rgba(30, 64, 175, 0.92)';
    ctx.fillRect(nx + 18, ny - 10, tw + 10, 18);
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, nx + 23, ny - 1);
  }
}

export function TopologyView({ nodes, flows, running, compact, sim }: TopologyViewProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const ctrl = useDynamicControl(sim);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [hoverId, setHoverId] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const propsRef = useRef({ nodes, flows, drag, hoverId });
  useEffect(() => {
    propsRef.current = { nodes, flows, drag, hoverId };
  }, [nodes, flows, drag, hoverId]);

  useEffect(() => {
    let phase = 0;
    let raf = 0;
    const tick = () => {
      const canvas = canvasRef.current;
      if (canvas) {
        const p = propsRef.current;
        drawScene(canvas, p.nodes, p.flows, p.drag, p.hoverId, phase);
      }
      phase = (phase + 0.6) % 1024;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const eventCoords = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return [0, 0] as [number, number];
    const rect = canvas.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top] as [number, number];
  };

  const onMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas || !running) return;
    const [cx, cy] = eventCoords(e);
    const viewNodes = applyDragOverride(nodes, drag);
    const g = computeGeom(canvas, viewNodes);
    const hit = findNodeAt(viewNodes, g, cx, cy);
    if (!hit) return;
    setDrag({ nodeId: hit.id, simX: hit.x, simY: hit.y, moved: false });
  };

  const onMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const [cx, cy] = eventCoords(e);
    const viewNodes = applyDragOverride(nodes, drag);
    const g = computeGeom(canvas, viewNodes);
    if (drag) {
      const [sx, sy] = canvasToSim(g, cx, cy);
      setDrag({ ...drag, simX: sx, simY: sy, moved: true });
    } else {
      const hit = findNodeAt(viewNodes, g, cx, cy);
      const id = hit ? hit.id : null;
      if (id !== hoverId) setHoverId(id);
    }
  };

  const onMouseUp = async () => {
    if (!drag) return;
    const target = drag;
    if (!target.moved) {
      setDrag(null);
      return;
    }
    const result = await ctrl.setNodePosition(target.nodeId, target.simX, target.simY);
    setDrag(null);
    if (result.ok) {
      setToast(`node-${target.nodeId} → (${target.simX.toFixed(0)}, ${target.simY.toFixed(0)})m`);
    } else {
      setToast(`提交失败: ${result.reason || 'unknown'}`);
    }
    window.setTimeout(() => setToast(null), 2500);
  };

  const onMouseLeave = () => {
    setHoverId(null);
    if (drag) onMouseUp();
  };

  const activeFlowCount = flows.filter(f => f.txPackets > 0).length;
  const cursorClass = drag ? 'cursor-grabbing' : (running && hoverId !== null ? 'cursor-grab' : 'cursor-default');

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <Card className="lg:col-span-2 border-slate-200/60 shadow-card">
          <CardHeader className="pb-2 py-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <div className="h-7 w-7 rounded-lg bg-primary/10 flex items-center justify-center">
                    <Radio className="h-3.5 w-3.5 text-primary" />
                  </div>
                  网络拓扑
                </CardTitle>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {running ? '拖拽节点重新定位 · 数据流箭头按吞吐着色' : '仿真未运行 · 拖拽功能已禁用'}
                </p>
              </div>
              <div className="flex items-center gap-2 text-xs">
                {running && (
                  <Badge variant="outline" className="gap-1 h-6 px-2 font-medium">
                    <Move className="h-3 w-3" /> 可拖拽
                  </Badge>
                )}
                <Badge variant="outline" className="gap-1 text-purple-600 border-purple-300/60 h-6 px-2 font-medium">
                  <Activity className="h-3 w-3" /> {activeFlowCount} 活跃流
                </Badge>
              </div>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="relative">
              <canvas
                ref={canvasRef}
                onMouseDown={onMouseDown}
                onMouseMove={onMouseMove}
                onMouseUp={onMouseUp}
                onMouseLeave={onMouseLeave}
                style={{ width: '100%', height: compact ? '280px' : '440px', borderRadius: '12px', background: '#f8fafc', display: 'block' }}
                className={cursorClass}
              />
              {toast && (
                <div className="absolute top-3 right-3 px-3 py-1.5 rounded-lg bg-primary text-white text-xs shadow-glow animate-scale-in font-medium">
                  {toast}
                </div>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2 text-[11px] text-muted-foreground">
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-success inline-block shadow-sm" /> 在线</span>
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-warning inline-block shadow-sm" /> 忙碌</span>
              <span className="flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-full bg-destructive inline-block shadow-sm" /> 离线</span>
              <span className="flex items-center gap-1.5"><span className="w-6 h-0.5 bg-blue-300 inline-block rounded-full" /> 邻居链路</span>
              <span className="flex items-center gap-1.5"><span className="w-6 h-0.5 bg-purple-500 inline-block rounded-full" /> 数据流</span>
            </div>
          </CardContent>
        </Card>

        <Card className="border-slate-200/60 shadow-card">
          <CardHeader className="pb-2 py-3">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <div className="h-7 w-7 rounded-lg bg-emerald-500/10 flex items-center justify-center">
                <Wifi className="h-3.5 w-3.5 text-emerald-500" />
              </div>
              节点状态
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ScrollArea className={compact ? 'h-[280px]' : 'h-[440px]'}>
              <div className="space-y-0.5 px-3 pb-3">
                {nodes.map(node => (
                  <div key={node.id} className="flex items-center gap-2.5 py-2 px-2 rounded-lg hover:bg-muted/50 transition-colors border-b border-border/50 last:border-0">
                    <StatusIcon status={node.status} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-xs font-bold">N{node.id}</span>
                        <StatusBadge status={node.status} />
                        {node.role !== 'client' && (
                          <Badge variant="secondary" className="text-[10px] px-1 py-0 h-4 font-medium">{node.role}</Badge>
                        )}
                      </div>
                      <div className="text-[10px] text-muted-foreground font-mono mt-0.5">{node.ip}</div>
                    </div>
                    <div className="text-right text-[10px] text-muted-foreground font-mono tabular-nums">
                      <div>Rx {(node.rxPackets / 1000).toFixed(1)}k</div>
                      <div>Tx {(node.txPackets / 1000).toFixed(1)}k</div>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      {/* Reachability Matrix */}
      <Card className="border-slate-200/60 shadow-card">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2 font-semibold">
              <div className="h-8 w-8 rounded-lg bg-violet-500/10 flex items-center justify-center">
                <Grid3x3 className="h-4 w-4 text-violet-500" />
              </div>
              节点可达性矩阵
            </CardTitle>
            <Badge variant="outline" className="text-xs font-medium">
              {nodes.length} 节点
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          {nodes.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无节点数据</p>
          ) : (
            <ScrollArea className="max-h-[420px]">
              <div className="overflow-x-auto">
                <table className="text-xs font-mono border-separate border-spacing-0 w-full">
                  <thead>
                    <tr>
                      <th className="sticky top-0 left-0 z-20 bg-muted px-2 py-1.5 border border-border text-muted-foreground font-medium rounded-tl-lg">
                        ↓src \ dst→
                      </th>
                      {nodes.map(d => (
                        <th
                          key={d.id}
                          className="sticky top-0 z-10 bg-muted px-2 py-1.5 border border-border text-center font-semibold"
                        >
                          N{d.id}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {nodes.map(s => {
                      const neighborSet = new Set(s.neighbors ?? []);
                      return (
                        <tr key={s.id}>
                          <th className="sticky left-0 z-10 bg-muted px-2 py-1.5 border border-border text-left font-semibold">
                            N{s.id}
                          </th>
                          {nodes.map(d => {
                            if (s.id === d.id) {
                              return (
                                <td
                                  key={d.id}
                                  title={`N${s.id}\nRX: ${s.rxPackets.toLocaleString()} pkts\nTX: ${s.txPackets.toLocaleString()} pkts`}
                                  className="px-2 py-1.5 border border-border text-center text-muted-foreground"
                                >
                                  —
                                </td>
                              );
                            }
                            const dist = Math.hypot(s.x - d.x, s.y - d.y);
                            const reachable = neighborSet.has(d.id);
                            return (
                              <td
                                key={d.id}
                                title={`N${s.id} → N${d.id}\n距离: ${dist.toFixed(0)} m\n${reachable ? '可达 (在通信范围内)' : '不可达 (超出通信范围)'}`}
                                className="px-2 py-1.5 border border-border text-center font-mono transition-colors"
                                style={reachabilityCellStyle(reachable)}
                              >
                                {dist >= 1000 ? `${(dist / 1000).toFixed(1)}km` : `${dist.toFixed(0)}m`}
                              </td>
                            );
                          })}
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </ScrollArea>
          )}
          <div className="flex flex-wrap gap-x-5 gap-y-1 mt-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 inline-block rounded-sm" style={{ background: 'rgba(34,197,94,0.12)' }} /> 可达</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 inline-block rounded-sm border border-border" /> 不可达</span>
            <span className="flex items-center gap-1.5">— 对角线</span>
          </div>
        </CardContent>
      </Card>

      {flows.length > 0 && (
        <Card className="border-slate-200/60 shadow-card">
          <CardHeader className="pb-3">
            <CardTitle className="text-base font-semibold">流统计</CardTitle>
          </CardHeader>
          <CardContent>
            <ScrollArea className="h-[250px]">
              <div className="space-y-1">
                {flows.slice(0, 20).map(flow => (
                  <div key={flow.flowId} className="flex items-center gap-3 py-2.5 px-3 rounded-lg hover:bg-muted/40 transition-colors border-b border-border/40 last:border-0 text-sm">
                    <span className="font-mono text-xs w-12 font-bold text-muted-foreground">Flow-{flow.flowId}</span>
                    <span className="font-mono text-xs text-primary font-medium">{flow.source}</span>
                    <span className="text-muted-foreground text-xs">{'->'}</span>
                    <span className="font-mono text-xs text-success font-medium">{flow.destination}</span>
                    <div className="flex-1" />
                    <span className="text-xs font-mono tabular-nums">发: {flow.txPackets.toLocaleString()}</span>
                    <span className="text-xs font-mono tabular-nums">收: {flow.rxPackets.toLocaleString()}</span>
                    <span className="text-xs text-destructive font-mono tabular-nums">丢失: {flow.lostPackets}</span>
                    <span className="text-xs text-purple-600 font-mono tabular-nums font-medium">{(flow.throughput).toFixed(2)} Mbps</span>
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
