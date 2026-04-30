import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

import {
  STANDARDS, DATA_RATES, PHY_MODELS, PATH_LOSS_MODELS, FADING_MODELS,
  PROPAGATION_DELAYS, RATE_CONTROLS, MAC_MODES, ROUTING_PROTOCOLS,
  MOBILITY_MODELS, GRID_LAYOUTS, RW_MODES, PRESETS,
} from '@/types/config';
import type { SimConfig } from '@/types/config';
import { Save, RotateCcw, Download, Upload, Radio, Wifi, Route, MapPin, BarChart3 } from 'lucide-react';

interface ConfigPanelProps {
  config: SimConfig;
  activePreset: string;
  updateConfig: <K extends keyof SimConfig>(key: K, value: SimConfig[K]) => void;
  loadPreset: (name: string) => void;
  resetToDefault: () => void;
  exportConfig: () => string;
  importConfig: (text: string) => void;
}

export function ConfigPanel({
  config, activePreset, updateConfig, loadPreset, resetToDefault, exportConfig, importConfig,
}: ConfigPanelProps) {
  const handleImport = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.conf';
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (file) {
        const reader = new FileReader();
        reader.onload = () => importConfig(reader.result as string);
        reader.readAsText(file);
      }
    };
    input.click();
  };

  const handleExport = () => {
    const blob = new Blob([exportConfig()], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'simulation.conf';
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleGenerateScript = () => {
    const lines = Object.entries(config).map(([key, value]) => {
      const envKey = key.replace(/([A-Z])/g, '_$1').toUpperCase().replace(/^_/, '');
      return `export ${envKey}="${value}"`;
    });
    const script = `#!/bin/bash\n# Auto-generated NS-3 AdHoc launch script\n${lines.join('\n')}\n\n./start-simulation.sh\n`;
    const blob = new Blob([script], { type: 'text/x-shellscript' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'launch.sh';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      {/* Presets & Actions */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-muted-foreground">Presets:</span>
        {Object.entries(PRESETS).map(([key, preset]) => (
          <Button
            key={key}
            variant={activePreset === key ? 'default' : 'outline'}
            size="sm"
            onClick={() => loadPreset(key)}
          >
            {preset.name}
          </Button>
        ))}
        {activePreset === 'custom' && (
          <Badge variant="secondary">Custom</Badge>
        )}
        <div className="flex-1" />
        <Button variant="outline" size="sm" onClick={handleImport}>
          <Upload className="h-4 w-4 mr-1" /> Import
        </Button>
        <Button variant="outline" size="sm" onClick={handleExport}>
          <Download className="h-4 w-4 mr-1" /> Export .conf
        </Button>
        <Button variant="outline" size="sm" onClick={handleGenerateScript}>
          <Download className="h-4 w-4 mr-1" /> Export .sh
        </Button>
        <Button variant="ghost" size="sm" onClick={resetToDefault}>
          <RotateCcw className="h-4 w-4 mr-1" /> Reset
        </Button>
      </div>

      <Tabs defaultValue="general" className="w-full">
        <TabsList className="grid w-full grid-cols-6">
          <TabsTrigger value="general"><Radio className="h-4 w-4 mr-1" /> General</TabsTrigger>
          <TabsTrigger value="phy"><Wifi className="h-4 w-4 mr-1" /> PHY</TabsTrigger>
          <TabsTrigger value="mac"><Save className="h-4 w-4 mr-1" /> MAC</TabsTrigger>
          <TabsTrigger value="routing"><Route className="h-4 w-4 mr-1" /> Routing</TabsTrigger>
          <TabsTrigger value="mobility"><MapPin className="h-4 w-4 mr-1" /> Mobility</TabsTrigger>
          <TabsTrigger value="tracing"><BarChart3 className="h-4 w-4 mr-1" /> Tracing</TabsTrigger>
        </TabsList>

        {/* General Tab */}
        <TabsContent value="general">
          <Card>
            <CardHeader><CardTitle>General Parameters</CardTitle></CardHeader>
            <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="space-y-2">
                <Label>Number of Nodes</Label>
                <Input type="number" min={2} max={100} value={config.nNodes}
                  onChange={e => updateConfig('nNodes', Number(e.target.value))} />
              </div>
              <div className="space-y-2">
                <Label>Simulation Time (seconds)</Label>
                <Input type="number" min={10} max={3600} value={config.simulationTime}
                  onChange={e => updateConfig('simulationTime', Number(e.target.value))} />
              </div>
              <div className="space-y-2">
                <Label>Random Seed</Label>
                <Input type="number" min={1} value={config.seed}
                  onChange={e => updateConfig('seed', Number(e.target.value))} />
              </div>
              <div className="space-y-2">
                <Label>Run Number</Label>
                <Input type="number" min={1} value={config.run}
                  onChange={e => updateConfig('run', Number(e.target.value))} />
              </div>
              <div className="space-y-2 col-span-2 md:col-span-4">
                <Label>Log Components (comma-separated)</Label>
                <Input placeholder="e.g. Manet30Nodes,AodvRoutingProtocol" value={config.logComponents}
                  onChange={e => updateConfig('logComponents', e.target.value)} />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* PHY Tab */}
        <TabsContent value="phy">
          <Card>
            <CardHeader><CardTitle>Physical Layer</CardTitle></CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label>802.11 Standard</Label>
                  <Select value={config.standard} onValueChange={v => updateConfig('standard', v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {STANDARDS.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>PHY Model</Label>
                  <Select value={config.phyModel} onValueChange={v => updateConfig('phyModel', v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {PHY_MODELS.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Data Rate</Label>
                  <Select value={config.dataRate} onValueChange={v => updateConfig('dataRate', v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {(DATA_RATES[config.standard] || []).map(r => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <Label>Frequency (MHz)</Label>
                  <Input type="number" min={100} max={6000} value={config.frequencyMhz}
                    onChange={e => updateConfig('frequencyMhz', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>Channel Width (MHz)</Label>
                  <Input type="number" min={5} max={160} value={config.channelWidthMhz}
                    onChange={e => updateConfig('channelWidthMhz', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>Range Target (m)</Label>
                  <Input type="number" min={10} max={50000} value={config.rangeTargetM}
                    onChange={e => updateConfig('rangeTargetM', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>Propagation Delay</Label>
                  <Select value={config.propagationDelay} onValueChange={v => updateConfig('propagationDelay', v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {PROPAGATION_DELAYS.map(d => <SelectItem key={d} value={d}>{d}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <Label>Tx Power Start (dBm)</Label>
                  <Input type="number" step={0.1} value={config.txPowerStart}
                    onChange={e => updateConfig('txPowerStart', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>Tx Power End (dBm)</Label>
                  <Input type="number" step={0.1} value={config.txPowerEnd}
                    onChange={e => updateConfig('txPowerEnd', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>Rx Sensitivity (dBm)</Label>
                  <Input type="number" step={0.1} value={config.rxSensitivity}
                    onChange={e => updateConfig('rxSensitivity', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>CCA Threshold (dBm)</Label>
                  <Input type="number" step={0.1} value={config.ccaThreshold}
                    onChange={e => updateConfig('ccaThreshold', Number(e.target.value))} />
                </div>
              </div>

              <div className="border-t pt-4">
                <h4 className="font-semibold mb-3">Path Loss Model</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="space-y-2">
                    <Label>Model</Label>
                    <Select value={config.pathLossModel} onValueChange={v => updateConfig('pathLossModel', v)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {PATH_LOSS_MODELS.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Exponent: {config.pathLossExponent}</Label>
                    <Slider min={1} max={6} step={0.1} value={[config.pathLossExponent]}
                      onValueChange={v => updateConfig('pathLossExponent', v[0])} />
                  </div>
                  <div className="space-y-2">
                    <Label>Ref Loss at 1m (dB)</Label>
                    <Input type="number" value={config.pathLossRefLoss}
                      onChange={e => updateConfig('pathLossRefLoss', Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Ref Distance (m)</Label>
                    <Input type="number" value={config.pathLossRefDistance}
                      onChange={e => updateConfig('pathLossRefDistance', Number(e.target.value))} />
                  </div>
                </div>
              </div>

              <div className="border-t pt-4">
                <div className="flex items-center gap-4 mb-3">
                  <h4 className="font-semibold">Fading Model</h4>
                  <Switch checked={config.enableFading} onCheckedChange={v => updateConfig('enableFading', v)} />
                </div>
                {config.enableFading && (
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label>Model</Label>
                      <Select value={config.fadingModel} onValueChange={v => updateConfig('fadingModel', v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {FADING_MODELS.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>Nakagami M0 (d&lt;d1): {config.nakagamiM0}</Label>
                      <Slider min={0.1} max={5} step={0.1} value={[config.nakagamiM0]}
                        onValueChange={v => updateConfig('nakagamiM0', v[0])} />
                    </div>
                    <div className="space-y-2">
                      <Label>Nakagami M1 (d1&lt;d&lt;d2): {config.nakagamiM1}</Label>
                      <Slider min={0.1} max={5} step={0.1} value={[config.nakagamiM1]}
                        onValueChange={v => updateConfig('nakagamiM1', v[0])} />
                    </div>
                    <div className="space-y-2">
                      <Label>Nakagami M2 (d&gt;d2): {config.nakagamiM2}</Label>
                      <Slider min={0.1} max={5} step={0.1} value={[config.nakagamiM2]}
                        onValueChange={v => updateConfig('nakagamiM2', v[0])} />
                    </div>
                    <div className="space-y-2">
                      <Label>Distance D1 (m)</Label>
                      <Input type="number" value={config.nakagamiD1}
                        onChange={e => updateConfig('nakagamiD1', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>Distance D2 (m)</Label>
                      <Input type="number" value={config.nakagamiD2}
                        onChange={e => updateConfig('nakagamiD2', Number(e.target.value))} />
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* MAC Tab */}
        <TabsContent value="mac">
          <Card>
            <CardHeader><CardTitle>MAC Layer (AdHoc / Mesh)</CardTitle></CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <Label>MAC Mode</Label>
                  <Select value={config.macMode} onValueChange={v => updateConfig('macMode', v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {MAC_MODES.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>SSID</Label>
                  <Input value={config.ssid} onChange={e => updateConfig('ssid', e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label>BSSID</Label>
                  <Input value={config.bssid} onChange={e => updateConfig('bssid', e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label>Rate Control</Label>
                  <Select value={config.rateControl} onValueChange={v => updateConfig('rateControl', v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {RATE_CONTROLS.map(r => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>Beacon Interval (TU)</Label>
                  <Input type="number" value={config.beaconInterval}
                    onChange={e => updateConfig('beaconInterval', Number(e.target.value))} />
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <Label>RTS/CTS Threshold: {config.rtsCtsThreshold === 65535 ? 'Disabled' : config.rtsCtsThreshold}</Label>
                  <Slider min={0} max={65535} step={100} value={[config.rtsCtsThreshold]}
                    onValueChange={v => updateConfig('rtsCtsThreshold', v[0])} />
                </div>
                <div className="space-y-2">
                  <Label>Fragmentation Threshold</Label>
                  <Input type="number" value={config.fragmentationThreshold}
                    onChange={e => updateConfig('fragmentationThreshold', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>CW Min</Label>
                  <Input type="number" min={0} max={1023} value={config.cwMin}
                    onChange={e => updateConfig('cwMin', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>CW Max</Label>
                  <Input type="number" min={0} max={1023} value={config.cwMax}
                    onChange={e => updateConfig('cwMax', Number(e.target.value))} />
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Routing Tab */}
        <TabsContent value="routing">
          <Card>
            <CardHeader><CardTitle>Routing Protocol</CardTitle></CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2 max-w-xs">
                <Label>Protocol</Label>
                <Select value={config.routingProtocol} onValueChange={v => updateConfig('routingProtocol', v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {ROUTING_PROTOCOLS.map(p => <SelectItem key={p} value={p}>{p.toUpperCase()}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>

              {config.routingProtocol === 'aodv' && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-3">AODV Parameters</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label>Hello Interval (s)</Label>
                      <Input type="number" step={0.1} value={config.aodvHelloInterval}
                        onChange={e => updateConfig('aodvHelloInterval', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>RREQ Retries</Label>
                      <Input type="number" value={config.aodvRreqRetries}
                        onChange={e => updateConfig('aodvRreqRetries', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>Active Route Timeout (s)</Label>
                      <Input type="number" step={0.1} value={config.aodvActiveRouteTimeout}
                        onChange={e => updateConfig('aodvActiveRouteTimeout', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>Delete Period (s)</Label>
                      <Input type="number" step={0.1} value={config.aodvDeletePeriod}
                        onChange={e => updateConfig('aodvDeletePeriod', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>Net Diameter (hops)</Label>
                      <Input type="number" value={config.aodvNetDiameter}
                        onChange={e => updateConfig('aodvNetDiameter', Number(e.target.value))} />
                    </div>
                    <div className="flex items-center gap-2 pt-6">
                      <Switch id="aodv-hello" checked={config.aodvEnableHello}
                        onCheckedChange={v => updateConfig('aodvEnableHello', v)} />
                      <Label htmlFor="aodv-hello">Enable Hello</Label>
                    </div>
                  </div>
                </div>
              )}

              {config.routingProtocol === 'olsr' && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-3">OLSR Parameters</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label>Hello Interval (s)</Label>
                      <Input type="number" step={0.1} value={config.olsrHelloInterval}
                        onChange={e => updateConfig('olsrHelloInterval', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>TC Interval (s)</Label>
                      <Input type="number" step={0.1} value={config.olsrTcInterval}
                        onChange={e => updateConfig('olsrTcInterval', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>Willingness (0-7)</Label>
                      <Input type="number" min={0} max={7} value={config.olsrWillingness}
                        onChange={e => updateConfig('olsrWillingness', Number(e.target.value))} />
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Mobility Tab */}
        <TabsContent value="mobility">
          <Card>
            <CardHeader><CardTitle>Mobility Model</CardTitle></CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label>Model</Label>
                  <Select value={config.mobilityModel} onValueChange={v => updateConfig('mobilityModel', v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {MOBILITY_MODELS.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="border-t pt-4">
                <h4 className="font-semibold mb-3">Simulation Area (meters)</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="space-y-2">
                    <Label>Min X</Label>
                    <Input type="number" value={config.mobilityMinX}
                      onChange={e => updateConfig('mobilityMinX', Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max X</Label>
                    <Input type="number" value={config.mobilityMaxX}
                      onChange={e => updateConfig('mobilityMaxX', Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Min Y</Label>
                    <Input type="number" value={config.mobilityMinY}
                      onChange={e => updateConfig('mobilityMinY', Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>Max Y</Label>
                    <Input type="number" value={config.mobilityMaxY}
                      onChange={e => updateConfig('mobilityMaxY', Number(e.target.value))} />
                  </div>
                </div>
              </div>

              {(config.mobilityModel === 'random-walk' || config.mobilityModel === 'gauss-markov') && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-3">Random Walk Parameters</h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="space-y-2">
                      <Label>Min Speed (m/s)</Label>
                      <Input type="number" step={0.1} value={config.rwMinSpeed}
                        onChange={e => updateConfig('rwMinSpeed', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>Max Speed (m/s)</Label>
                      <Input type="number" step={0.1} value={config.rwMaxSpeed}
                        onChange={e => updateConfig('rwMaxSpeed', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>Mode</Label>
                      <Select value={config.rwMode} onValueChange={v => updateConfig('rwMode', v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {RW_MODES.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>Time Step (s)</Label>
                      <Input type="number" step={0.1} value={config.rwTime}
                        onChange={e => updateConfig('rwTime', Number(e.target.value))} />
                    </div>
                  </div>
                </div>
              )}

              {(config.mobilityModel === 'grid' || config.mobilityModel === 'constant') && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-3">Grid Parameters</h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="space-y-2">
                      <Label>Delta X (m)</Label>
                      <Input type="number" value={config.gridDeltaX}
                        onChange={e => updateConfig('gridDeltaX', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>Delta Y (m)</Label>
                      <Input type="number" value={config.gridDeltaY}
                        onChange={e => updateConfig('gridDeltaY', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>Nodes per Row</Label>
                      <Input type="number" value={config.gridWidth}
                        onChange={e => updateConfig('gridWidth', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>Layout</Label>
                      <Select value={config.gridLayout} onValueChange={v => updateConfig('gridLayout', v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {GRID_LAYOUTS.map(l => <SelectItem key={l} value={l}>{l}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tracing Tab */}
        <TabsContent value="tracing">
          <Card>
            <CardHeader><CardTitle>Tracing Options</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div className="flex items-center gap-3">
                  <Switch id="pcap" checked={config.pcap} onCheckedChange={v => updateConfig('pcap', v)} />
                  <Label htmlFor="pcap">PCAP Tracing</Label>
                </div>
                <div className="flex items-center gap-3">
                  <Switch id="ascii" checked={config.ascii} onCheckedChange={v => updateConfig('ascii', v)} />
                  <Label htmlFor="ascii">ASCII Tracing</Label>
                </div>
                <div className="flex items-center gap-3">
                  <Switch id="flowmon" checked={config.flowMonitor} onCheckedChange={v => updateConfig('flowMonitor', v)} />
                  <Label htmlFor="flowmon">Flow Monitor</Label>
                </div>
                <div className="flex items-center gap-3">
                  <Switch id="mobtrace" checked={config.enableMobilityTrace} onCheckedChange={v => updateConfig('enableMobilityTrace', v)} />
                  <Label htmlFor="mobtrace">Mobility Trace</Label>
                </div>
              </div>
              <div className="space-y-2 max-w-md">
                <Label>PCAP Filename Prefix</Label>
                <Input value={config.pcapPrefix} onChange={e => updateConfig('pcapPrefix', e.target.value)} />
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
