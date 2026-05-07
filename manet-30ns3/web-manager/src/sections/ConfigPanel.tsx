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
  MOBILITY_MODELS, GRID_LAYOUTS, RW_MODES,
} from '@/types/config';
import type { SimConfig } from '@/types/config';
import { PRESET_NAMES } from '@/hooks/useSimConfig';
import { Save, RotateCcw, Download, Upload, Radio, Wifi, Route, MapPin, BarChart3, AlertTriangle } from 'lucide-react';

interface ConfigPanelProps {
  config: SimConfig;
  activePreset: string;
  presets: Record<string, SimConfig> | null;
  saveStatus?: 'idle' | 'saving' | 'saved' | 'error';
  updateConfig: <K extends keyof SimConfig>(key: K, value: SimConfig[K]) => void;
  loadPreset: (name: string) => void;
  resetToDefault: () => void;
  exportConfig: () => string;
  importConfig: (text: string) => void;
}

export function ConfigPanel({
  config, activePreset, presets, saveStatus, updateConfig, loadPreset, resetToDefault, exportConfig, importConfig,
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

  return (
    <div className="space-y-6">
      {/* Bandwidth limit warning */}
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-800 text-sm flex items-center gap-2">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        <span>
          当前 BestEffort 模式下建议测试速率 <strong>≤ 6 Mbps</strong>，超过此速率可能导致严重丢包。
          如需更高带宽，请关闭跟踪选项（PCAP / ASCII / 移动性跟踪）并减少节点数量。
        </span>
      </div>

      {/* Presets & Actions */}
      <div className="flex flex-wrap items-center gap-3">
        <span className="text-sm text-muted-foreground">预设:</span>
        {presets ? (
          Object.keys(presets)
            .filter(key => !key.startsWith('wifi-'))
            .map(key => (
              <Button
                key={key}
                variant={activePreset === key ? 'default' : 'outline'}
                size="sm"
                onClick={() => loadPreset(key)}
              >
                {PRESET_NAMES[key] || key}
              </Button>
            ))
        ) : (
          <span className="text-xs text-muted-foreground">加载中...</span>
        )}
        {activePreset === 'custom' && (
          <Badge variant="secondary">自定义</Badge>
        )}
        <div className="flex-1" />
        {saveStatus === 'saving' && (
          <Badge variant="outline" className="animate-pulse">保存中...</Badge>
        )}
        {saveStatus === 'saved' && (
          <Badge variant="secondary" className="text-green-600">已保存</Badge>
        )}
        {saveStatus === 'error' && (
          <Badge variant="destructive">保存失败</Badge>
        )}
        <Button variant="outline" size="sm" onClick={handleImport}>
          <Upload className="h-4 w-4 mr-1" /> 导入
        </Button>
        <Button variant="outline" size="sm" onClick={handleExport}>
          <Download className="h-4 w-4 mr-1" /> 导出 .conf
        </Button>
        <Button variant="ghost" size="sm" onClick={resetToDefault}>
          <RotateCcw className="h-4 w-4 mr-1" /> 重置
        </Button>
      </div>

      <Tabs defaultValue="general" className="w-full">
        <TabsList className="grid w-full grid-cols-6">
          <TabsTrigger value="general"><Radio className="h-4 w-4 mr-1" /> 通用</TabsTrigger>
          <TabsTrigger value="phy"><Wifi className="h-4 w-4 mr-1" /> 物理层</TabsTrigger>
          <TabsTrigger value="mac"><Save className="h-4 w-4 mr-1" /> MAC</TabsTrigger>
          <TabsTrigger value="routing"><Route className="h-4 w-4 mr-1" /> 路由</TabsTrigger>
          <TabsTrigger value="mobility"><MapPin className="h-4 w-4 mr-1" /> 移动性</TabsTrigger>
          <TabsTrigger value="tracing"><BarChart3 className="h-4 w-4 mr-1" /> 跟踪</TabsTrigger>
        </TabsList>

        {/* General Tab */}
        <TabsContent value="general">
          <Card>
            <CardHeader><CardTitle>通用参数</CardTitle></CardHeader>
            <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="space-y-2">
                <Label>节点数量</Label>
                <Input type="number" min={2} max={16} value={config.nNodes}
                  onChange={e => updateConfig('nNodes', Number(e.target.value))} />
              </div>
              <div className="space-y-2">
                <Label>仿真时长 (秒)</Label>
                <Input type="number" min={10} max={3600} value={config.simulationTime}
                  onChange={e => updateConfig('simulationTime', Number(e.target.value))} />
              </div>
              <div className="space-y-2">
                <Label>随机种子</Label>
                <Input type="number" min={1} value={config.seed}
                  onChange={e => updateConfig('seed', Number(e.target.value))} />
              </div>
              <div className="space-y-2">
                <Label>运行编号</Label>
                <Input type="number" min={1} value={config.run}
                  onChange={e => updateConfig('run', Number(e.target.value))} />
              </div>
              <div className="space-y-2 col-span-2 md:col-span-4">
                <Label>日志组件 (逗号分隔)</Label>
                <Input placeholder="e.g. Manet30Nodes,AodvRoutingProtocol" value={config.logComponents}
                  onChange={e => updateConfig('logComponents', e.target.value)} />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* PHY Tab */}
        <TabsContent value="phy">
          <Card>
            <CardHeader><CardTitle>物理层</CardTitle></CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label>802.11 标准</Label>
                  <Select value={config.standard} onValueChange={v => updateConfig('standard', v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {STANDARDS.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>PHY 模型</Label>
                  <Select value={config.phyModel} onValueChange={v => updateConfig('phyModel', v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {PHY_MODELS.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>数据速率</Label>
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
                  <Label>频率 (MHz)</Label>
                  <Input type="number" min={100} max={6000} value={config.frequencyMhz}
                    onChange={e => updateConfig('frequencyMhz', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>信道宽度 (MHz)</Label>
                  <Input type="number" min={5} max={160} value={config.channelWidthMhz}
                    onChange={e => updateConfig('channelWidthMhz', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>目标覆盖范围 (m)</Label>
                  <Input type="number" min={10} max={50000} value={config.rangeTargetM}
                    onChange={e => updateConfig('rangeTargetM', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>传播延迟</Label>
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
                  <Label>发射功率起始 (dBm)</Label>
                  <Input type="number" step={0.1} value={config.txPowerStart}
                    onChange={e => updateConfig('txPowerStart', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>发射功率结束 (dBm)</Label>
                  <Input type="number" step={0.1} value={config.txPowerEnd}
                    onChange={e => updateConfig('txPowerEnd', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>发射功率等级</Label>
                  <Input type="number" min={1} value={config.txPowerLevels}
                    onChange={e => updateConfig('txPowerLevels', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>天线增益 (dBi)</Label>
                  <Input type="number" step={0.1} value={config.antennaGain}
                    onChange={e => updateConfig('antennaGain', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>接收灵敏度 (dBm)</Label>
                  <Input type="number" step={0.1} value={config.rxSensitivity}
                    onChange={e => updateConfig('rxSensitivity', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>CCA 阈值 (dBm)</Label>
                  <Input type="number" step={0.1} value={config.ccaThreshold}
                    onChange={e => updateConfig('ccaThreshold', Number(e.target.value))} />
                </div>
              </div>

              <div className="border-t pt-4">
                <h4 className="font-semibold mb-3">路径损耗模型</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="space-y-2">
                    <Label>模型</Label>
                    <Select value={config.pathLossModel} onValueChange={v => updateConfig('pathLossModel', v)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        {PATH_LOSS_MODELS.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>指数: {config.pathLossExponent}</Label>
                    <Slider min={1} max={6} step={0.1} value={[config.pathLossExponent]}
                      onValueChange={v => updateConfig('pathLossExponent', v[0])} />
                  </div>
                  <div className="space-y-2">
                    <Label>1m 参考损耗 (dB)</Label>
                    <Input type="number" value={config.pathLossRefLoss}
                      onChange={e => updateConfig('pathLossRefLoss', Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>参考距离 (m)</Label>
                    <Input type="number" value={config.pathLossRefDistance}
                      onChange={e => updateConfig('pathLossRefDistance', Number(e.target.value))} />
                  </div>
                </div>
              </div>

              <div className="border-t pt-4">
                <div className="flex items-center gap-4 mb-3">
                  <h4 className="font-semibold">衰落模型</h4>
                  <Switch checked={config.enableFading} onCheckedChange={v => updateConfig('enableFading', v)} />
                </div>
                {config.enableFading && (
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label>模型</Label>
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
                      <Label>距离 D1 (m)</Label>
                      <Input type="number" value={config.nakagamiD1}
                        onChange={e => updateConfig('nakagamiD1', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>距离 D2 (m)</Label>
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
            <CardHeader><CardTitle>MAC 层 (AdHoc / Mesh)</CardTitle></CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <Label>MAC 模式</Label>
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
                  <Label>速率控制</Label>
                  <Select value={config.rateControl} onValueChange={v => updateConfig('rateControl', v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {RATE_CONTROLS.map(r => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>信标间隔 (TU)</Label>
                  <Input type="number" value={config.beaconInterval}
                    onChange={e => updateConfig('beaconInterval', Number(e.target.value))} />
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="space-y-2">
                  <Label>RTS/CTS 阈值: {config.rtsCtsThreshold === 65535 ? '禁用' : config.rtsCtsThreshold}</Label>
                  <Slider min={0} max={65535} step={100} value={[config.rtsCtsThreshold]}
                    onValueChange={v => updateConfig('rtsCtsThreshold', v[0])} />
                </div>
                <div className="space-y-2">
                  <Label>分片阈值</Label>
                  <Input type="number" value={config.fragmentationThreshold}
                    onChange={e => updateConfig('fragmentationThreshold', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>最小竞争窗口</Label>
                  <Input type="number" min={0} max={1023} value={config.cwMin}
                    onChange={e => updateConfig('cwMin', Number(e.target.value))} />
                </div>
                <div className="space-y-2">
                  <Label>最大竞争窗口</Label>
                  <Input type="number" min={0} max={1023} value={config.cwMax}
                    onChange={e => updateConfig('cwMax', Number(e.target.value))} />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Switch id="non-unicast" checked={config.nonUnicastMode}
                  onCheckedChange={v => updateConfig('nonUnicastMode', v)} />
                <Label htmlFor="non-unicast">非单播模式 (广播/组播使用最低数据速率)</Label>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Routing Tab */}
        <TabsContent value="routing">
          <Card>
            <CardHeader><CardTitle>路由协议</CardTitle></CardHeader>
            <CardContent className="space-y-6">
              <div className="space-y-2">
                <Label>协议</Label>
                <Select value={config.routingProtocol} onValueChange={v => updateConfig('routingProtocol', v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {ROUTING_PROTOCOLS.map(p => <SelectItem key={p} value={p}>{p.toUpperCase()}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>

              {config.routingProtocol === 'aodv' && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-3">AODV 参数</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label>Hello 间隔 (s)</Label>
                      <Input type="number" step={0.1} value={config.aodvHelloInterval}
                        onChange={e => updateConfig('aodvHelloInterval', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>RREQ 重试次数</Label>
                      <Input type="number" value={config.aodvRreqRetries}
                        onChange={e => updateConfig('aodvRreqRetries', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>活跃路由超时 (s)</Label>
                      <Input type="number" step={0.1} value={config.aodvActiveRouteTimeout}
                        onChange={e => updateConfig('aodvActiveRouteTimeout', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>删除周期 (s)</Label>
                      <Input type="number" step={0.1} value={config.aodvDeletePeriod}
                        onChange={e => updateConfig('aodvDeletePeriod', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>网络直径 (跳)</Label>
                      <Input type="number" value={config.aodvNetDiameter}
                        onChange={e => updateConfig('aodvNetDiameter', Number(e.target.value))} />
                    </div>
                    <div className="flex items-center gap-2 pt-6">
                      <Switch id="aodv-hello" checked={config.aodvEnableHello}
                        onCheckedChange={v => updateConfig('aodvEnableHello', v)} />
                      <Label htmlFor="aodv-hello">启用 Hello</Label>
                    </div>
                  </div>
                </div>
              )}

              {config.routingProtocol === 'olsr' && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-3">OLSR 参数</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label>Hello 间隔 (s)</Label>
                      <Input type="number" step={0.1} value={config.olsrHelloInterval}
                        onChange={e => updateConfig('olsrHelloInterval', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>TC 间隔 (s)</Label>
                      <Input type="number" step={0.1} value={config.olsrTcInterval}
                        onChange={e => updateConfig('olsrTcInterval', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>意愿值 (0-7)</Label>
                      <Input type="number" min={0} max={7} value={config.olsrWillingness}
                        onChange={e => updateConfig('olsrWillingness', Number(e.target.value))} />
                    </div>
                  </div>
                </div>
              )}

              {config.routingProtocol === 'dsdv' && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-3">DSDV 参数</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    <div className="space-y-2">
                      <Label>定期更新间隔 (s)</Label>
                      <Input type="number" step={0.1} value={config.dsdvPeriodicUpdateInterval}
                        onChange={e => updateConfig('dsdvPeriodicUpdateInterval', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>稳定时间 (s)</Label>
                      <Input type="number" step={0.1} value={config.dsdvSettlingTime}
                        onChange={e => updateConfig('dsdvSettlingTime', Number(e.target.value))} />
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
            <CardHeader><CardTitle>移动模型</CardTitle></CardHeader>
            <CardContent className="space-y-6">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div className="space-y-2">
                  <Label>模型</Label>
                  <Select value={config.mobilityModel} onValueChange={v => updateConfig('mobilityModel', v)}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {MOBILITY_MODELS.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="border-t pt-4">
                <h4 className="font-semibold mb-3">仿真区域 (米)</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="space-y-2">
                    <Label>最小 X</Label>
                    <Input type="number" value={config.mobilityMinX}
                      onChange={e => updateConfig('mobilityMinX', Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>最大 X</Label>
                    <Input type="number" value={config.mobilityMaxX}
                      onChange={e => updateConfig('mobilityMaxX', Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>最小 Y</Label>
                    <Input type="number" value={config.mobilityMinY}
                      onChange={e => updateConfig('mobilityMinY', Number(e.target.value))} />
                  </div>
                  <div className="space-y-2">
                    <Label>最大 Y</Label>
                    <Input type="number" value={config.mobilityMaxY}
                      onChange={e => updateConfig('mobilityMaxY', Number(e.target.value))} />
                  </div>
                </div>
              </div>

              {(config.mobilityModel === 'random-walk' || config.mobilityModel === 'gauss-markov') && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-3">随机游走参数</h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="space-y-2">
                      <Label>最小速度 (m/s)</Label>
                      <Input type="number" step={0.1} value={config.rwMinSpeed}
                        onChange={e => updateConfig('rwMinSpeed', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>最大速度 (m/s)</Label>
                      <Input type="number" step={0.1} value={config.rwMaxSpeed}
                        onChange={e => updateConfig('rwMaxSpeed', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>模式</Label>
                      <Select value={config.rwMode} onValueChange={v => updateConfig('rwMode', v)}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {RW_MODES.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2">
                      <Label>时间步长 (s)</Label>
                      <Input type="number" step={0.1} value={config.rwTime}
                        onChange={e => updateConfig('rwTime', Number(e.target.value))} />
                    </div>
                  </div>
                </div>
              )}

              {config.mobilityModel === 'gauss-markov' && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-3">高斯-马尔可夫参数</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label>Alpha (记忆系数): {config.gmAlpha.toFixed(2)}</Label>
                      <Slider min={0} max={1} step={0.05} value={[config.gmAlpha]}
                        onValueChange={v => updateConfig('gmAlpha', v[0])} />
                      <p className="text-xs text-muted-foreground">
                        0 = 完全随机; 1 = 完美直线运动
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {(config.mobilityModel === 'grid' || config.mobilityModel === 'constant') && (
                <div className="border-t pt-4">
                  <h4 className="font-semibold mb-3">网格参数</h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="space-y-2">
                      <Label>X 间距 (m)</Label>
                      <Input type="number" value={config.gridDeltaX}
                        onChange={e => updateConfig('gridDeltaX', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>Y 间距 (m)</Label>
                      <Input type="number" value={config.gridDeltaY}
                        onChange={e => updateConfig('gridDeltaY', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>每行节点数</Label>
                      <Input type="number" value={config.gridWidth}
                        onChange={e => updateConfig('gridWidth', Number(e.target.value))} />
                    </div>
                    <div className="space-y-2">
                      <Label>布局</Label>
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
            <CardHeader><CardTitle>跟踪选项</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                <div className="flex items-center gap-3">
                  <Switch id="pcap" checked={config.pcap} onCheckedChange={v => updateConfig('pcap', v)} />
                  <Label htmlFor="pcap">PCAP 跟踪</Label>
                </div>
                <div className="flex items-center gap-3">
                  <Switch id="ascii" checked={config.ascii} onCheckedChange={v => updateConfig('ascii', v)} />
                  <Label htmlFor="ascii">ASCII 跟踪</Label>
                </div>
                <div className="flex items-center gap-3">
                  <Switch id="flowmon" checked={config.flowMonitor} onCheckedChange={v => updateConfig('flowMonitor', v)} />
                  <Label htmlFor="flowmon">流监控</Label>
                </div>
                <div className="flex items-center gap-3">
                  <Switch id="mobtrace" checked={config.enableMobilityTrace} onCheckedChange={v => updateConfig('enableMobilityTrace', v)} />
                  <Label htmlFor="mobtrace">移动性跟踪</Label>
                </div>
              </div>
              <div className="space-y-2">
                <Label>PCAP 文件名前缀</Label>
                <Input value={config.pcapPrefix} onChange={e => updateConfig('pcapPrefix', e.target.value)} />
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
