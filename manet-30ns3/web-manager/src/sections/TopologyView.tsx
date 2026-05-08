import { useEffect, useRef, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { NodeStatus, FlowStats } from '@/types/config';
import {
  Wifi, WifiOff, AlertTriangle,
  Move, Activity, Grid3x3,
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
  if (status === 'online') return <Wifi className="h-4 w-4 text-green-500" />;
  if (status === 'busy') return <AlertTriangle className="h-4 w-4 text-yellow-500" />;
  return <WifiOff className="h-4 w-4 text-red-500" />;
}

function StatusBadge({ status }: { status: string }) {
  if (status === 'online') return <Badge variant="outline" className="text-green-600 border-green-600 text-xs">在线</Badge>;
  if (status === 'busy') return <Badge variant="outline" className="text-yellow-600 border-yellow-600 text-xs">忙碌</Badge>;
  return <Badge variant="outline" className="text-red-600 border-red-600 text-xs">离线</Badge>;
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

// 节点对流量矩阵单元格颜色:吞吐 0..6 Mbps → 透明度 0..0.85,色相紫色
function reachabilityCellStyle(reachable: boolean): { background: string; color: string } {
  if (reachable) {
    return { background: 'rgba(34, 197, 94, 0.15)', color: '#166534' };
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

  // Grid + axis labels
  ctx.strokeStyle = '#e5e7eb';
  ctx.lineWidth = 1;
  const gridStepPx = 50;
  ctx.fillStyle = '#9ca3af';
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

  // Scale bar (bottom-right)
  const scaleBarMeters = Math.pow(10, Math.floor(Math.log10(100 / g.scale)));
  const scaleBarPx = scaleBarMeters * g.scale;
  const sbX = g.w - scaleBarPx - 12;
  const sbY = g.h - 28;
  ctx.strokeStyle = '#374151';
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
  ctx.fillStyle = '#374151';
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

  // Flow arrows (animated)
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

    // 把箭头起止点缩短到节点圆边缘外
    const ux = dxv / dist;
    const uy = dyv / dist;
    const sx2 = sx + ux * (NODE_RADIUS + 2);
    const sy2 = sy + uy * (NODE_RADIUS + 2);
    const dx2 = dxc - ux * (NODE_RADIUS + 4);
    const dy2 = dyc - uy * (NODE_RADIUS + 4);

    // 吞吐 → 线宽 + 颜色透明度
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

    // 箭头头
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

    // 中点 Mbps 标签
    if (tput > 0.05) {
      const mx = (sx2 + dx2) / 2;
      const my = (sy2 + dy2) / 2;
      const label = tput >= 1 ? `${tput.toFixed(2)} Mbps` : `${(tput * 1000).toFixed(0)} kbps`;
      ctx.font = '10px sans-serif';
      const tw = ctx.measureText(label).width;
      ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
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

  // 拖拽中的浮动 (x, y) 提示
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

  // Latest props in refs so the single RAF loop always reads fresh values
  const propsRef = useRef({ nodes, flows, drag, hoverId });
  useEffect(() => {
    propsRef.current = { nodes, flows, drag, hoverId };
  }, [nodes, flows, drag, hoverId]);

  // Single RAF render loop — always running so flow dashes animate continuously
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

  // 鼠标坐标转 canvas 内 CSS pixel
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
        <Card className="lg:col-span-2">
          <CardHeader className="pb-2 py-2">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-sm">网络拓扑</CardTitle>
                <p className="text-xs text-muted-foreground">
                  {running ? '拖拽节点重新定位 · 数据流箭头按吞吐着色' : '仿真未运行 · 拖拽功能已禁用'}
                </p>
              </div>
              <div className="flex items-center gap-2 text-xs">
                {running && (
                  <Badge variant="outline" className="gap-1 h-5 px-1">
                    <Move className="h-3 w-3" /> 可拖拽
                  </Badge>
                )}
                <Badge variant="outline" className="gap-1 text-purple-600 border-purple-300 h-5 px-1">
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
                style={{ width: '100%', height: compact ? '280px' : '440px', borderRadius: '8px', background: '#f9fafb', display: 'block' }}
                className={cursorClass}
              />
              {toast && (
                <div className="absolute top-2 right-2 px-3 py-1.5 rounded-md bg-blue-600 text-white text-xs shadow-md">
                  {toast}
                </div>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-1.5 text-[10px] text-muted-foreground">
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-green-500 inline-block" /> 在线</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-yellow-500 inline-block" /> 忙碌</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full bg-red-500 inline-block" /> 离线</span>
              <span className="flex items-center gap-1"><span className="w-6 h-0.5 bg-blue-300 inline-block" /> 邻居链路</span>
              <span className="flex items-center gap-1"><span className="w-6 h-0.5 bg-purple-500 inline-block" /> 数据流</span>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2 py-2">
            <CardTitle className="text-sm">节点状态</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ScrollArea className={compact ? 'h-[280px]' : 'h-[440px]'}>
              <div className="space-y-1 px-3 pb-3">
                {nodes.map(node => (
                  <div key={node.id} className="flex items-center gap-2 py-1 border-b border-gray-100 last:border-0">
                    <StatusIcon status={node.status} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-xs font-semibold">N{node.id}</span>
                        <StatusBadge status={node.status} />
                        {node.role !== 'client' && (
                          <Badge variant="secondary" className="text-[10px] px-1 py-0 h-4">{node.role}</Badge>
                        )}
                      </div>
                      <div className="text-[10px] text-muted-foreground font-mono">{node.ip}</div>
                    </div>
                    <div className="text-right text-[10px] text-muted-foreground">
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

      {/* 节点对可达性矩阵 NxN: 行=源,列=目标,单元格=距离+可达状态 */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base flex items-center gap-2">
              <Grid3x3 className="h-4 w-4" />
              节点可达性矩阵
            </CardTitle>
            <Badge variant="outline" className="text-xs">
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
                      <th className="sticky top-0 left-0 z-20 bg-muted px-2 py-1 border border-gray-200 text-muted-foreground font-normal">
                        ↓src \ dst→
                      </th>
                      {nodes.map(d => (
                        <th
                          key={d.id}
                          className="sticky top-0 z-10 bg-muted px-2 py-1 border border-gray-200 text-center font-semibold"
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
                          <th className="sticky left-0 z-10 bg-muted px-2 py-1 border border-gray-200 text-left font-semibold">
                            N{s.id}
                          </th>
                          {nodes.map(d => {
                            if (s.id === d.id) {
                              return (
                                <td
                                  key={d.id}
                                  title={`N${s.id}\nRX: ${s.rxPackets.toLocaleString()} pkts\nTX: ${s.txPackets.toLocaleString()} pkts`}
                                  className="px-2 py-1 border border-gray-200 text-center text-muted-foreground"
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
                                className="px-2 py-1 border border-gray-200 text-center font-mono"
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
          <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs text-muted-foreground">
            <span className="flex items-center gap-1"><span className="w-3 h-3 inline-block rounded-sm" style={{ background: 'rgba(34,197,94,0.15)' }} /> 可达</span>
            <span className="flex items-center gap-1"><span className="w-3 h-3 inline-block rounded-sm border border-gray-200" /> 不可达</span>
            <span className="flex items-center gap-1">— 对角线 (节点自身 RX/TX hover 可看)</span>
          </div>
        </CardContent>
      </Card>

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
