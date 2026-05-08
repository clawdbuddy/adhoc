import { useState, useCallback, useEffect, useRef } from 'react';
import type { SimConfig, ParamChangeMsg } from '@/types/config';

const API_BASE = '';

// 极小的本地 fallback，用于 API 尚未返回前的占位。
// 权威预设定义在后端 controller/orchestrator/config.py:PRESETS 中。
const FALLBACK_CONFIG: SimConfig = {
  nNodes: 6, simulationTime: 300, seed: 1, run: 1, logComponents: '',
  standard: '80211n-2.4GHz', phyModel: 'yans', frequencyMhz: 2412, channelWidthMhz: 20, rangeTargetM: 4000,
  dataRate: 'HtMcs7',
  txPowerStart: 30, txPowerEnd: 30, txPowerLevels: 1,
  rxSensitivity: -92, ccaThreshold: -82, antennaGain: 3,
  propagationDelay: 'ConstantSpeed', pathLossModel: 'FreeSpace',
  pathLossExponent: 2.0, pathLossRefLoss: 46.6777, pathLossRefDistance: 1.0,
  enableFading: false, fadingModel: 'Nakagami',
  nakagamiM0: 1.5, nakagamiM1: 1.0, nakagamiM2: 0.75, nakagamiD1: 50, nakagamiD2: 100,
  ssid: 'adhoc-30ns3', bssid: '00:00:00:00:AD:H0',
  macMode: 'mesh', rateControl: 'Constant', rtsCtsThreshold: 2200, fragmentationThreshold: 2200,
  nonUnicastMode: false, beaconInterval: 100, cwMin: 15, cwMax: 1023,
  routingProtocol: 'aodv', aodvHelloInterval: 1, aodvRreqRetries: 2,
  aodvActiveRouteTimeout: 3, aodvDeletePeriod: 5, aodvNetDiameter: 35, aodvEnableHello: true,
  olsrHelloInterval: 2, olsrTcInterval: 5, olsrWillingness: 7,
  dsdvPeriodicUpdateInterval: 15, dsdvSettlingTime: 6,
  mobilityModel: 'random-walk', mobilityMinX: 0, mobilityMaxX: 5000, mobilityMinY: 0, mobilityMaxY: 5000,
  rwMinSpeed: 0.5, rwMaxSpeed: 3, rwDistance: 200, rwMode: 'Time', rwTime: 1,
  gridMinX: 100, gridMinY: 100, gridDeltaX: 800, gridDeltaY: 800, gridWidth: 6, gridLayout: 'RowFirst',
  gmAlpha: 0.85, pcap: true, ascii: false, flowMonitor: true,
  pcapPrefix: 'manet-30nodes-adhoc', enableMobilityTrace: false,
  trafficMode: 'tap', onoffDataRate: '6Mbps', onoffPacketSize: 1024,
  onoffMaxBytes: 0, onoffStartTime: 1.0, onoffSinkPort: 5000,
};

// 按钮显示名映射（后端 /api/sim/presets 只返回扁平 SimConfig，没有 name 字段）
export const PRESET_NAMES: Record<string, string> = {
  default: '默认 / AdHoc',
  urban: '城市密集',
  rural: '乡村 / 开阔地带',
  debug: '调试 / 最小配置',
  tactical: '战术 / 10节点',
  throughput: '极限吞吐 / 2节点',
};

interface SimApi {
  batchSetParams: (params: Record<string, unknown>) => Promise<{ ok: boolean; results: Array<{ ok: boolean; key?: string; reason?: string }> }>;
  subscribeParamChange: (cb: (msg: ParamChangeMsg) => void) => () => void;
}

export function useSimConfig(sim?: SimApi) {
  const [presets, setPresets] = useState<Record<string, SimConfig> | null>(null);
  const [ready, setReady] = useState(false);
  const [config, setConfig] = useState<SimConfig>({ ...FALLBACK_CONFIG });
  const [activePreset, setActivePreset] = useState<string>('default');
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 挂载时从后端加载：先读已保存配置，再加载预设作为兜底
  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/config`).then(r => r.ok ? r.json() : null).catch(() => null),
      fetch(`${API_BASE}/api/sim/presets`).then(r => r.json()).catch(() => ({} as Record<string, SimConfig>)),
    ]).then(([saved, presetData]) => {
      setPresets(presetData);
      if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
        // ParamStore.get_all() 返回的是 flat 参数对象；直接合并到 SimConfig
        setConfig(prev => ({ ...prev, ...saved }));
      }
      setReady(true);
    }).catch(() => {
      setReady(true);
    });
  }, []);

  // 监听后端参数变更广播，同步更新本地 config（多客户端场景）
  useEffect(() => {
    if (!sim) return;
    return sim.subscribeParamChange((msg) => {
      setConfig(prev => {
        const key = msg.key as keyof SimConfig;
        // 只更新 SimConfig 中存在的字段
        if (key in prev) {
          return { ...prev, [key]: msg.value as SimConfig[keyof SimConfig] };
        }
        return prev;
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
    const lines: string[] = ['// NS-3 802.11s Mesh / AdHoc Simulation Configuration'];
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
      if (result.ok && result.results.every(r => r.ok)) {
        setSaveStatus('saved');
        setTimeout(() => setSaveStatus('idle'), 2000);
      } else {
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
