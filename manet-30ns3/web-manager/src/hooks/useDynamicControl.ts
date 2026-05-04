import { useCallback } from 'react';

const API_BASE = '';

async function postJson(path: string, body: Record<string, unknown>) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }
  return res.json();
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
