import { useState, useEffect, useCallback, useRef } from 'react';
import type { NodeStatus, FlowStats, NodePairFlow, SimulationStatus, SimConfig, TelemetryEnv, ParamResult, ParamBatchResult, ParamChangeMsg, NodeSpec } from '@/types/config';

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
  pairs?: NodePairFlow[];
  env?: TelemetryEnv;
  ts: number;
}

function aggregateStatus(frame: TelemetryFrame, prevStartTime: string | null): SimulationStatus {
  const onlineNodes = frame.nodes.filter(n => n.status !== 'offline');
  const totalTx = frame.nodes.reduce((s, n) => s + (n.txPackets || 0), 0);
  const totalRx = frame.nodes.reduce((s, n) => s + (n.rxPackets || 0), 0);
  const totalLost = frame.flows.reduce((s, f) => s + (f.lostPackets || 0), 0);
  return {
    running: frame.running,
    startTime: frame.running ? (prevStartTime ?? new Date().toISOString()) : null,
    elapsed: Math.round(frame.t),
    nodesOnline: onlineNodes.length,
    totalNodes: frame.nodes.length,
    activeFlows: frame.flows.length,
    totalTx,
    totalRx,
    totalLost,
  };
}

interface PendingRequest {
  resolve: (value: ParamResult | ParamBatchResult) => void;
  reject: (reason: Error) => void;
  timer: ReturnType<typeof setTimeout>;
}

type ParamChangeCallback = (msg: ParamChangeMsg) => void;

export function useSimulation(initialNnodes: number = 5) {
  const [status, setStatus] = useState<SimulationStatus>({
    running: false,
    startTime: null,
    elapsed: 0,
    nodesOnline: 0,
    totalNodes: initialNnodes,
    activeFlows: 0,
    totalTx: 0,
    totalRx: 0,
    totalLost: 0,
  });
  const [nodes, setNodes] = useState<NodeStatus[]>([]);
  const [flows, setFlows] = useState<FlowStats[]>([]);
  const [pairs, setPairs] = useState<NodePairFlow[]>([]);
  const [env, setEnv] = useState<TelemetryEnv | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectWsRef = useRef<(() => void) | null>(null);
  const pendingRef = useRef<Map<string, PendingRequest>>(new Map());
  const paramCallbacksRef = useRef<Set<ParamChangeCallback>>(new Set());

  // 写保护：串行化并发参数写入，避免竞态
  const writeQueueRef = useRef<Array<() => Promise<void>>>([]);
  const isWritingRef = useRef(false);

  const processWriteQueue = useCallback(async () => {
    if (isWritingRef.current) return;
    isWritingRef.current = true;
    while (writeQueueRef.current.length > 0) {
      const fn = writeQueueRef.current.shift()!;
      try { await fn(); } catch { /* ignore */ }
    }
    isWritingRef.current = false;
  }, []);

  const enqueueWrite = useCallback((fn: () => Promise<void>) => {
    return new Promise<void>((resolve, reject) => {
      writeQueueRef.current.push(async () => {
        try { await fn(); resolve(); } catch (e) { reject(e); }
      });
      processWriteQueue();
    });
  }, [processWriteQueue]);

  const addLog = useCallback((msg: string) => {
    setLogs(prev => [msg, ...prev].slice(0, 500));
  }, []);

  // ---- 参数变更监听注册 ----
  const subscribeParamChange = useCallback((cb: ParamChangeCallback) => {
    paramCallbacksRef.current.add(cb);
    return () => { paramCallbacksRef.current.delete(cb); };
  }, []);

  // ---- WebSocket 发送并等待响应 ----
  const sendAndWait = useCallback(<T extends ParamResult | ParamBatchResult>(
    payload: Record<string, unknown>,
    timeoutMs = 5000,
  ): Promise<T> => {
    return new Promise((resolve, reject) => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        reject(new Error('WebSocket not connected'));
        return;
      }
      const reqId = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
      const msg = { ...payload, reqId };
      const timer = setTimeout(() => {
        pendingRef.current.delete(reqId);
        reject(new Error(`WebSocket request timeout: ${payload.type}`));
      }, timeoutMs);
      pendingRef.current.set(reqId, { resolve: resolve as (v: ParamResult | ParamBatchResult) => void, reject, timer });
      ws.send(JSON.stringify(msg));
    });
  }, []);

  // 乐观更新节点位置：写入后立即反映到本地 nodes，避免遥测帧到达前的视觉弹回
  const applyOptimisticPositions = useCallback((value: unknown) => {
    if (typeof value !== 'object' || value === null) return;
    const updates = value as Record<string, { x?: number; y?: number; z?: number }>;
    setNodes(prev => {
      const next = [...prev];
      for (const [nodeIdStr, pos] of Object.entries(updates)) {
        const nodeId = parseInt(nodeIdStr, 10);
        const idx = next.findIndex(n => n.id === nodeId);
        if (idx >= 0 && pos) {
          next[idx] = { ...next[idx], x: pos.x ?? next[idx].x, y: pos.y ?? next[idx].y };
        }
      }
      return next;
    });
  }, []);

  const setParam = useCallback((key: string, value: unknown): Promise<ParamResult> => {
    return new Promise((resolve, reject) => {
      enqueueWrite(async () => {
        if (key === 'positions') {
          applyOptimisticPositions(value);
        }
        const r = await sendAndWait<ParamResult>({ type: 'param_set', key, value });
        resolve(r);
      }).catch(reject);
    });
  }, [sendAndWait, enqueueWrite, applyOptimisticPositions]);

  const getParam = useCallback((key: string): Promise<ParamResult> => {
    return sendAndWait<ParamResult>({ type: 'param_get', key });
  }, [sendAndWait]);

  const batchSetParams = useCallback((params: Record<string, unknown>): Promise<ParamBatchResult> => {
    return new Promise((resolve, reject) => {
      enqueueWrite(async () => {
        if ('positions' in params) {
          applyOptimisticPositions(params.positions);
        }
        const r = await sendAndWait<ParamBatchResult>({ type: 'param_batch_set', params });
        resolve(r);
      }).catch(reject);
    });
  }, [sendAndWait, enqueueWrite, applyOptimisticPositions]);

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
      // 清理所有 pending 请求
      pendingRef.current.forEach(({ reject, timer }) => {
        clearTimeout(timer);
        reject(new Error('WebSocket closed'));
      });
      pendingRef.current.clear();
      addLog(`[ws] closed; reconnecting in 3s`);
      reconnectTimerRef.current = setTimeout(() => connectWsRef.current?.(), 3000);
    };
    ws.onmessage = (ev: MessageEvent) => {
      try {
        const msg = JSON.parse(ev.data) as Record<string, unknown>;
        const msgType = msg.type as string | undefined;

        // 1. 参数响应（匹配 pending request）
        if (msgType === 'param_response' || msgType === 'param_batch_response') {
          const reqId = msg.reqId as string;
          const pending = pendingRef.current.get(reqId);
          if (pending) {
            clearTimeout(pending.timer);
            pendingRef.current.delete(reqId);
            pending.resolve(msg as unknown as ParamResult | ParamBatchResult);
          }
          return;
        }

        // 2. 参数变更广播
        if (msgType === 'param_changed') {
          const changeMsg = msg as unknown as ParamChangeMsg;
          paramCallbacksRef.current.forEach(cb => {
            try { cb(changeMsg); } catch { /* ignore callback errors */ }
          });
          return;
        }

        // 3. 遥测帧（无 type 字段或 type 为 undefined）
        const frame = msg as unknown as TelemetryFrame;
        setNodes(frame.nodes ?? []);
        setFlows(frame.flows ?? []);
        setPairs(frame.pairs ?? []);
        setEnv(frame.env ?? null);
        setStatus(prev => aggregateStatus(frame, prev.startTime));
      } catch (e) {
        addLog(`[ws] parse failed: ${(e as Error).message}`);
      }
    };
  }, [addLog]);

  // 保持 ref 同步，避免 onclose 闭包引用 stale 的 connectWs
  useEffect(() => {
    connectWsRef.current = connectWs;
  }, [connectWs]);

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
  const startSimulation = useCallback(async (config?: SimConfig, preset?: string, nodes?: NodeSpec[]) => {
    addLog(`[api] POST /api/sim/start`);
    try {
      const body: Record<string, unknown> = { config, preset };
      if (nodes && nodes.length > 0) {
        body.nodes = nodes;
      }
      const res = await fetch(`${API_BASE}/api/sim/start`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
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

  return {
    status, nodes, flows, pairs, env, logs,
    startSimulation, stopSimulation, addLog,
    setParam, getParam, batchSetParams,
    subscribeParamChange,
  };
}
