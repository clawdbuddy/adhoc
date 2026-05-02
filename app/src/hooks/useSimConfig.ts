import { useState, useCallback } from 'react';
import type { SimConfig } from '@/types/config';
import { defaultConfig, PRESETS } from '@/types/config';

export function useSimConfig() {
  const [config, setConfig] = useState<SimConfig>({ ...defaultConfig });
  const [activePreset, setActivePreset] = useState<string>('default');

  const updateConfig = useCallback(<K extends keyof SimConfig>(key: K, value: SimConfig[K]) => {
    setConfig(prev => ({ ...prev, [key]: value }));
    setActivePreset('custom');
  }, []);

  const updatePartial = useCallback((partial: Partial<SimConfig>) => {
    setConfig(prev => ({ ...prev, ...partial }));
    setActivePreset('custom');
  }, []);

  const loadPreset = useCallback((presetName: string) => {
    const preset = PRESETS[presetName as keyof typeof PRESETS];
    if (preset) {
      setConfig({ ...preset.config });
      setActivePreset(presetName);
    }
  }, []);

  const resetToDefault = useCallback(() => {
    setConfig({ ...defaultConfig });
    setActivePreset('default');
  }, []);

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

  return {
    config,
    activePreset,
    updateConfig,
    updatePartial,
    loadPreset,
    resetToDefault,
    exportConfig,
    importConfig,
  };
}
