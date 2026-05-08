import { useCallback } from 'react';

export interface DynamicResult {
  ok: boolean;
  applied: boolean;
  reason?: string;
  [key: string]: unknown;
}

interface SimApi {
  setParam: (key: string, value: unknown) => Promise<{
    ok: boolean;
    key?: string;
    reason?: string;
    results?: Array<{ ok: boolean; nodeId?: number; reason?: string }>;
  }>;
}

export function useDynamicControl(sim?: SimApi) {
  const _setParam = useCallback(async (key: string, value: unknown, desc: string): Promise<DynamicResult> => {
    if (!sim) {
      return { ok: false, applied: false, reason: `${desc}: WebSocket not available` };
    }
    try {
      const r = await sim.setParam(key, value);
      if (r.ok) {
        return { ok: true, applied: true };
      }
      return { ok: false, applied: false, reason: r.reason || `${desc} failed` };
    } catch (e) {
      return { ok: false, applied: false, reason: (e as Error).message };
    }
  }, [sim]);

  const setNodePosition = useCallback(async (nodeId: number, x: number, y: number, z = 0) => {
    return _setParam('positions', { [nodeId]: { x, y, z } }, `node-${nodeId} position`);
  }, [_setParam]);

  const setTxPower = useCallback(async (nodeId: number, dbm: number) => {
    return _setParam('txPower', { [nodeId]: dbm }, `node-${nodeId} txpower`);
  }, [_setParam]);

  const setRxSensitivity = useCallback(async (nodeId: number, dbm: number) => {
    return _setParam('rxSensitivity', { [nodeId]: dbm }, `node-${nodeId} rxsens`);
  }, [_setParam]);

  const setPathLossExponent = useCallback(async (exponent: number) => {
    return _setParam('pathLossExponent', exponent, 'pathLossExponent');
  }, [_setParam]);

  const setFrequency = useCallback(async (mhz: number) => {
    return _setParam('frequencyMhz', mhz, 'frequencyMhz');
  }, [_setParam]);

  const setChannelWidth = useCallback(async (mhz: number) => {
    return _setParam('channelWidthMhz', mhz, 'channelWidthMhz');
  }, [_setParam]);

  const setRangeTarget = useCallback(async (meters: number) => {
    return _setParam('rangeTargetM', meters, 'rangeTargetM');
  }, [_setParam]);

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
