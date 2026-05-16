import { useState, useCallback, useEffect, useRef } from 'react';
import type { SimConfig, ParamChangeMsg } from '@/types/config';

const API_BASE = '';

// 极小的本地 fallback，用于 API 尚未返回前的占位。
// 权威预设定义在后端 controller/orchestrator/config.py:PRESETS 中。
const FALLBACK_CONFIG: SimConfig = {
  nNodes: 5, simulationTime: 300, seed: 1, run: 1, logComponents: '',
  standard: '80211n-2.4GHz', phyModel: 'yans', frequencyMhz: 2412, channelWidthMhz: 20, rangeTargetM: 4000,
  dataRate: 'HtMcs7',
  txPowerStart: 30, txPowerEnd: 30, txPowerLevels: 1,
  rxSensitivity: -92, ccaThreshold: -82, antennaGain: 3,
  propagationDelay: 'ConstantSpeed', pathLossModel: 'FreeSpace',
  pathLossExponent: 2.0, pathLossRefLoss: 46.6777, pathLossRefDistance: 1.0,
  enableFading: false, fadingModel: 'Nakagami',
  nakagamiM0: 1.5, nakagamiM1: 1.0, nakagamiM2: 0.75, nakagamiD1: 50, nakagamiD2: 100,
  ricianK: 9.0,
  enableObstacles: false, obstacleShadowingSigma: 4.0, obstaclePenetrationLoss: 10.0,
  obstacleDiffractionEnabled: true, obstaclesJson: '[]',
  ssid: 'adhoc-30ns3', bssid: '00:00:00:00:AD:H0',
  macMode: 'mesh', rateControl: 'Constant', rtsCtsThreshold: 2200, fragmentationThreshold: 2200,
  nonUnicastMode: false, beaconInterval: 100, cwMin: 15, cwMax: 1023,
  routingProtocol: 'aodv', aodvHelloInterval: 1, aodvRreqRetries: 2,
  aodvActiveRouteTimeout: 10, aodvDeletePeriod: 5, aodvNetDiameter: 35, aodvEnableHello: true,
  olsrHelloInterval: 2, olsrTcInterval: 5, olsrWillingness: 7,
  dsdvPeriodicUpdateInterval: 15, dsdvSettlingTime: 6,
  mobilityModel: 'random-walk', mobilityMinX: 0, mobilityMaxX: 5000, mobilityMinY: 0, mobilityMaxY: 5000,
  rwMinSpeed: 0.5, rwMaxSpeed: 3, rwDistance: 200, rwMode: 'Time', rwTime: 1,
  gridMinX: 100, gridMinY: 100, gridDeltaX: 800, gridDeltaY: 800, gridWidth: 6, gridLayout: 'RowFirst',
  gmAlpha: 0.85, pcap: true, ascii: false, flowMonitor: true,
  pcapPrefix: 'manet-30nodes-adhoc', enableMobilityTrace: false,
  trafficMode: 'tap', onoffDataRate: '6Mbps', onoffPacketSize: 1024,
  onoffMaxBytes: 0, onoffStartTime: 1.0, onoffSinkPort: 5000,
  tapMode: 'UseLocal', tapPrefix: 'mesh-tap-',
  workMode: 0, fhTableId: 0, nodeMacId: 0, softwareVersion: 'V1.00.03',
};

// 按钮显示名映射（后端 /api/sim/presets 只返回扁平 SimConfig，没有 name 字段）
export const PRESET_NAMES: Record<string, string> = {
  default: '默认 / Mesh',
  urban: '城市密集',
  rural: '乡村 / 开阔地带',
  debug: '调试 / 最小配置',
  tactical: '战术 / 10节点',
  throughput: '极限吞吐 / 2节点',
  'wifi-band-test-2.4g': 'WiFi 2.4GHz 频段',
  'wifi-band-test-5g': 'WiFi 5GHz 频段',
  'wifi-bandwidth-test-20m': 'WiFi 20MHz 带宽',
  'wifi-bandwidth-test-40m': 'WiFi 40MHz 带宽',
  'wifi-distance-test': 'WiFi 距离渐变',
  'wifi-adhoc-multihop': 'WiFi 大规模拓扑',
};

interface SimApi {
  batchSetParams: (params: Record<string, unknown>) => Promise<{ ok: boolean; results: Array<{ ok: boolean; key?: string; reason?: string }> }>;
  subscribeParamChange: (cb: (msg: ParamChangeMsg) => void) => () => void;
}

export function useSimConfig(sim?: SimApi) {
  const [presets, setPresets] = useState<Record<string, SimConfig> | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [config, setConfig] = useState<SimConfig>({ ...FALLBACK_CONFIG });
  const [activePreset, setActivePreset] = useState<string>('default');
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSavedJsonRef = useRef<string>('');

  // 挂载时从后端加载：先读已保存配置，再加载预设作为兜底
  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/config`).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${API_BASE}/api/sim/presets`).then(r => r.ok ? r.json() : (() => { throw new Error(`HTTP ${r.status}`); })()).catch(() => ({} as Record<string, SimConfig>)),
    ]).then(([saved, presetData]) => {
      setPresets(presetData);
      if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
        // ParamStore.get_all() 返回的是 flat 参数对象；直接合并到 SimConfig
        setConfig(prev => ({ ...prev, ...saved }));
      }
      setReady(true);
    }).catch((e) => {
      setError(`加载配置失败: ${(e as Error).message}`);
      setReady(true);
    });
  }, []);

  // 监听后端参数变更广播，同步更新本地 config（多客户端场景）
  useEffect(() => {
    if (!sim) return;
    return sim.subscribeParamChange((msg) => {
      setConfig(prev => {
        const key = msg.key as keyof SimConfig;
        if (!(key in prev)) return prev;
        const prevVal = prev[key];
        const newVal = msg.value as SimConfig[keyof SimConfig];
        // 宽松比较：处理 number/string 类型漂移（如后端广播 "2412" 而前端是 2412）
        const changed = prevVal !== newVal && String(prevVal) !== String(newVal);
        if (!changed) return prev;
        const updated = { ...prev, [key]: newVal };
        // 广播更新时同步更新 lastSavedJsonRef，避免触发 auto-save 循环
        lastSavedJsonRef.current = JSON.stringify(updated);
        return updated;
      });
    });
  }, [sim]);

  const updateConfig = useCallback(<K extends keyof SimConfig>(key: K, value: SimConfig[K]) => {
    setConfig(prev => ({ ...prev, [key]: value }));
    setActivePreset('custom');
  }, []);

  const updatePartial = useCallback((partial: Partial<SimConfig>) => {
    setConfig(prev => ({ ...prev, ...partial }));
    setActivePreset('custom');
  }, []);

  const loadPreset = useCallback((presetName: string) => {
    if (!presets) return;
    const preset = presets[presetName];
    if (preset) {
      setConfig({ ...preset });
      setActivePreset(presetName);
    }
  }, [presets]);

  const resetToDefault = useCallback(() => {
    if (!presets?.default) return;
    setConfig({ ...presets.default });
    setActivePreset('default');
  }, [presets]);

  const exportConfig = useCallback((): string => {
    const lines: string[] = ['// MANET 仿真配置'];
    (Object.keys(config) as Array<keyof SimConfig>).forEach(key => {
      const value = config[key];
      if (typeof value === 'boolean') {
        lines.push(`${key} = ${value ? 'true' : 'false'}`);
      } else if (typeof value === 'string') {
        lines.push(`${key} = ${value}`);
      } else {
        lines.push(`${key} = ${value}`);
      }
    });
    return lines.join('\n');
  }, [config]);

  const importConfig = useCallback((text: string) => {
    const imported: Partial<SimConfig> = {};
    text.split('\n').forEach(line => {
      const cmt = line.indexOf('//');
      if (cmt !== -1) line = line.substring(0, cmt);
      line = line.trim();
      if (!line) return;
      const eq = line.indexOf('=');
      if (eq === -1) return;
      const key = line.substring(0, eq).trim();
      let val = line.substring(eq + 1).trim();
      val = val.replace(/^["']|["']$/g, '');
      const num = Number(val);
      if (!isNaN(num) && val !== '') {
        (imported as Record<string, unknown>)[key] = num;
      } else if (val === 'true' || val === 'false') {
        (imported as Record<string, unknown>)[key] = val === 'true';
      } else {
        (imported as Record<string, unknown>)[key] = val;
      }
    });
    setConfig(prev => ({ ...prev, ...imported }));
    setActivePreset('custom');
  }, []);

  // ---- auto-save to backend via WebSocket (debounce 500ms) ----
  const saveConfig = useCallback(async (cfg: SimConfig) => {
    if (!sim) {
      // 无 WebSocket 时回退到 REST PUT
      setSaveStatus('saving');
      try {
        const res = await fetch(`${API_BASE}/api/config`, {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify(cfg),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        lastSavedJsonRef.current = JSON.stringify(cfg);
        setSaveStatus('saved');
        setTimeout(() => setSaveStatus('idle'), 2000);
      } catch {
        setSaveStatus('error');
      }
      return;
    }

    setSaveStatus('saving');
    try {
      const params: Record<string, unknown> = {};
      (Object.keys(cfg) as Array<keyof SimConfig>).forEach(key => {
        params[key] = cfg[key];
      });
      const result = await sim.batchSetParams(params);
      // 忽略预期内的失败（如运行时不可修改的参数），只把真正异常视为错误
      const realFailures = (result.results || []).filter(
        (r: any) => !r.ok && !(r.reason || '').includes('requires simulator restart')
      );
      if (realFailures.length === 0) {
        lastSavedJsonRef.current = JSON.stringify(cfg);
        setSaveStatus('saved');
        setTimeout(() => setSaveStatus('idle'), 2000);
      } else {
        console.warn('save failed for keys:', realFailures.map((r: any) => r.key));
        setSaveStatus('error');
      }
    } catch {
      setSaveStatus('error');
    }
  }, [sim]);

  useEffect(() => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
    }
    const currentJson = JSON.stringify(config);
    // 配置未变更时不触发保存（避免广播回弹导致循环保存）
    if (currentJson === lastSavedJsonRef.current) return;

    saveTimerRef.current = setTimeout(() => saveConfig(config), 500);
    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
      }
    };
  }, [config, saveConfig]);

  return {
    config,
    activePreset,
    ready,
    error,
    presets,
    saveStatus,
    updateConfig,
    updatePartial,
    loadPreset,
    resetToDefault,
    exportConfig,
    importConfig,
  };
}
