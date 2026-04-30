import { useState, useEffect, useCallback, useRef } from 'react';
import type { NodeStatus, FlowStats, SimulationStatus, SimConfig } from '@/types/config';

// API + WS 基础 URL。生产环境中 FastAPI 控制器与前端页面同源提供；
// 开发模式下（vite 在 :3000）vite.config.ts 中的代理将 /api 和 /ws 转发到 localhost:8000。
const API_BASE = '';

function wsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${path}`;
}

interface TelemetryFrame {
  t: number;
  running: boolean;
  nodes: NodeStatus[];
  flows: FlowStats[];
  ts: number;
}

function aggregateStatus(nNodes: number, frame: TelemetryFrame, prevStartTime: string | null): SimulationStatus {
  const onlineNodes = frame.nodes.filter(n => n.status !== 'offline');
  const totalTx = frame.nodes.reduce((s, n) => s + (n.txPackets || 0), 0);
  const totalRx = frame.nodes.reduce((s, n) => s + (n.rxPackets || 0), 0);
  const totalLost = frame.flows.reduce((s, f) => s + (f.lostPackets || 0), 0);
  return {
    running: frame.running,
    startTime: frame.running ? (prevStartTime ?? new Date().toISOString()) : null,
    elapsed: Math.round(frame.t),
    nodesOnline: onlineNodes.length,
    totalNodes: nNodes,
    activeFlows: frame.flows.length,
    totalTx,
    totalRx,
    totalLost,
  };
}

export function useSimulation(nNodes: number) {
  const [status, setStatus] = useState<SimulationStatus>({
    running: false,
    startTime: null,
    elapsed: 0,
    nodesOnline: 0,
    totalNodes: nNodes,
    activeFlows: 0,
    totalTx: 0,
    totalRx: 0,
    totalLost: 0,
  });
  const [nodes, setNodes] = useState<NodeStatus[]>([]);
  const [flows, setFlows] = useState<FlowStats[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const addLog = useCallback((msg: string) => {
    setLogs(prev => [msg, ...prev].slice(0, 500));
  }, []);

  // ---- WebSocket subscription, with auto-reconnect ----
  const connectWs = useCallback(() => {
    if (wsRef.current) return;
    const url = wsUrl('/ws/telemetry');
    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (e) {
      addLog(`[ws] connect threw: ${(e as Error).message}`);
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => addLog(`[ws] connected ${url}`);
    ws.onerror = () => addLog(`[ws] error`);
    ws.onclose = () => {
      wsRef.current = null;
      addLog(`[ws] closed; reconnecting in 3s`);
      reconnectTimerRef.current = setTimeout(connectWs, 3000);
    };
    ws.onmessage = (ev: MessageEvent) => {
      try {
        const frame = JSON.parse(ev.data) as TelemetryFrame;
        setNodes(frame.nodes ?? []);
        setFlows(frame.flows ?? []);
        setStatus(prev => aggregateStatus(nNodes, frame, prev.startTime));
      } catch (e) {
        addLog(`[ws] parse failed: ${(e as Error).message}`);
      }
    };
  }, [addLog, nNodes]);

  useEffect(() => {
    connectWs();
    return () => {
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;  // suppress reconnect on unmount
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connectWs]);

  // ---- REST control ----
  const startSimulation = useCallback(async (config?: SimConfig, preset?: string) => {
    addLog(`[api] POST /api/sim/start`);
    try {
      const res = await fetch(`${API_BASE}/api/sim/start`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ config, preset }),
      });
      if (!res.ok) {
        const text = await res.text();
        addLog(`[api] start failed (${res.status}): ${text}`);
        return;
      }
      addLog(`[api] simulation started`);
      // Make sure WS is alive after a successful start.
      connectWs();
    } catch (e) {
      addLog(`[api] start exception: ${(e as Error).message}`);
    }
  }, [addLog, connectWs]);

  const stopSimulation = useCallback(async () => {
    addLog(`[api] POST /api/sim/stop`);
    try {
      const res = await fetch(`${API_BASE}/api/sim/stop`, { method: 'POST' });
      if (!res.ok) {
        addLog(`[api] stop failed (${res.status})`);
        return;
      }
      addLog(`[api] simulation stopped`);
    } catch (e) {
      addLog(`[api] stop exception: ${(e as Error).message}`);
    }
  }, [addLog]);

  return { status, nodes, flows, logs, startSimulation, stopSimulation, addLog };
}
