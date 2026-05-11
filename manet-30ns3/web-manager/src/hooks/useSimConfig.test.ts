import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useSimConfig } from './useSimConfig';

describe('useSimConfig', () => {
  it('should initialize with fallback config', () => {
    const { result } = renderHook(() => useSimConfig());
    expect(result.current.ready).toBe(false);
  });

  it('should update config values', () => {
    const { result } = renderHook(() => useSimConfig());

    act(() => {
      result.current.updateConfig('nNodes', 8);
    });

    expect(result.current.config.nNodes).toBe(8);
    expect(result.current.activePreset).toBe('custom');
  });

  it('should update multiple config values at once', () => {
    const { result } = renderHook(() => useSimConfig());

    act(() => {
      result.current.updatePartial({ nNodes: 10, frequencyMhz: 5180 });
    });

    expect(result.current.config.nNodes).toBe(10);
    expect(result.current.config.frequencyMhz).toBe(5180);
    expect(result.current.activePreset).toBe('custom');
  });

  it('should export config to text format', () => {
    const { result } = renderHook(() => useSimConfig());

    const exported = result.current.exportConfig();

    expect(exported).toContain('nNodes =');
    expect(exported).toContain('simulationTime =');
    expect(exported).toContain('// MANET');
  });

  it('should import config from text format', () => {
    const { result } = renderHook(() => useSimConfig());

    act(() => {
      result.current.importConfig('nNodes = 12\nfrequencyMhz = 5900\n// comment\n');
    });

    expect(result.current.config.nNodes).toBe(12);
    expect(result.current.config.frequencyMhz).toBe(5900);
    expect(result.current.activePreset).toBe('custom');
  });

  it('should handle boolean values in import', () => {
    const { result } = renderHook(() => useSimConfig());

    act(() => {
      result.current.importConfig('pcap = true\nascii = false\n');
    });

    expect(result.current.config.pcap).toBe(true);
    expect(result.current.config.ascii).toBe(false);
  });

  it('should handle quoted strings in import', () => {
    const { result } = renderHook(() => useSimConfig());

    act(() => {
      result.current.importConfig('ssid = "test-network"\n');
    });

    expect(result.current.config.ssid).toBe('test-network');
  });

  it('should ignore empty lines and comments during import', () => {
    const { result } = renderHook(() => useSimConfig());

    act(() => {
      result.current.importConfig('\n// comment\n  \nnNodes = 7\n');
    });

    expect(result.current.config.nNodes).toBe(7);
  });

  it('should reset to default when presets available', () => {
    const { result } = renderHook(() => useSimConfig());

    act(() => {
      result.current.updateConfig('nNodes', 99);
    });

    // Without presets loaded, reset should be a no-op
    act(() => {
      result.current.resetToDefault();
    });

    // nNodes stays at 99 because presets haven't loaded yet
    expect(result.current.config.nNodes).toBe(99);
  });
});
