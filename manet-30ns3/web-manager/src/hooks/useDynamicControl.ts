import { useCallback } from 'react';

const API_BASE = '';

export interface DynamicResult {
  ok: boolean;
  applied: boolean;
  reason?: string;
  [key: string]: unknown;
}

async function postJson(path: string, body: Record<string, unknown>): Promise<DynamicResult> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ ok: false }));
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${data.detail || JSON.stringify(data)}`);
  }
  return data as DynamicResult;
}

export function useDynamicControl() {
  const setNodePosition = useCallback(async (nodeId: number, x: number, y: number, z = 0) => {
    return postJson(`/api/env/position`, { nodeId, x, y, z });
  }, []);

  const setTxPower = useCallback(async (nodeId: number, dbm: number) => {
    return postJson(`/api/env/txpower`, { nodeId, dbm });
  }, []);

  const setRxSensitivity = useCallback(async (nodeId: number, dbm: number) => {
    return postJson(`/api/env/rxsens`, { nodeId, dbm });
  }, []);

  const setPathLossExponent = useCallback(async (exponent: number) => {
    return postJson(`/api/env/pathloss`, { exponent });
  }, []);

  const setFrequency = useCallback(async (mhz: number) => {
    return postJson(`/api/env/frequency`, { mhz });
  }, []);

  const setChannelWidth = useCallback(async (mhz: number) => {
    return postJson(`/api/env/channelwidth`, { mhz });
  }, []);

  const setRangeTarget = useCallback(async (meters: number) => {
    return postJson(`/api/env/range`, { meters });
  }, []);

  return {
    setNodePosition,
    setTxPower,
    setRxSensitivity,
    setPathLossExponent,
    setFrequency,
    setChannelWidth,
    setRangeTarget,
  };
}
