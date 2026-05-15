import { useState, useEffect, useCallback } from 'react';
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
import type { SimConfig, NodeSpec } from '@/types/config';
import { PRESET_NAMES } from '@/hooks/useSimConfig';
import { Save, RotateCcw, Download, Upload, Radio, Wifi, Route, MapPin, BarChart3, AlertTriangle, CheckCircle2, XCircle, Loader2, Server } from 'lucide-react';

interface RemoteHost {
  ip: string;
  ssh_user: string;
  capacity: number;
}

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
  onNodeSpecsChange?: (specs: NodeSpec[] | undefined) => void;
}

export function ConfigPanel({
  config, activePreset, presets, saveStatus, updateConfig, loadPreset, resetToDefault, exportConfig, importConfig,
  onNodeSpecsChange,
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

  // ---- 多机部署: 节点主机分配 ----
  const [nodeHosts, setNodeHosts] = useState<Record<number, string>>({});
  const [remoteHosts, setRemoteHosts] = useState<RemoteHost[]>([]);
  const [showHostAssign, setShowHostAssign] = useState(false);

  // 拉取已注册远端主机列表
  useEffect(() => {
    fetch('/api/hosts')
      .then(r => r.ok ? r.json() : [])
      .then(data => setRemoteHosts(Array.isArray(data) ? data : []))
      .catch(() => setRemoteHosts([]));
  }, []);

  // 当节点数变化时，初始化未设置的节点为 local
  useEffect(() => {
    setNodeHosts(prev => {
      const next: Record<number, string> = {};
      for (let i = 0; i < config.nNodes; i++) {
        next[i] = prev[i] ?? 'local';
      }
      return next;
    });
  }, [config.nNodes]);

  // 生成 NodeSpec 数组并通知父组件
  const generateNodeSpecs = useCallback((): NodeSpec[] | undefined => {
    const hasRemote = Object.values(nodeHosts).some(h => h !== 'local');
    if (!hasRemote) return undefined;

    const specs: NodeSpec[] = [];
    for (let i = 0; i < config.nNodes; i++) {
      const host = nodeHosts[i] ?? 'local';
      let role = 'client';
      if (i === 0) role = 'server';
      else if (i === 15 && config.nNodes > 15) role = 'gateway';
      specs.push({
        id: i,
        ip: `192.168.100.${10 + i}`,
        role,
        host,
      });
    }
    return specs;
  }, [nodeHosts, config.nNodes]);

  // 通知父组件分配变化
  useEffect(() => {
    if (onNodeSpecsChange) {
      const specs = generateNodeSpecs();
      onNodeSpecsChange(specs);
    }
  }, [nodeHosts, config.nNodes, onNodeSpecsChange, generateNodeSpecs]);

  const autoAssignHosts = () => {
    const hosts = ['local', ...remoteHosts.map(h => h.ip)];
    const capacities = [Infinity, ...remoteHosts.map(h => h.capacity)];
    const used: Record<string, number> = {};
    hosts.forEach(h => used[h] = 0);

    const next: Record<number, string> = {};
    for (let i = 0; i < config.nNodes; i++) {
      // 找到剩余容量最多的主机
      let bestHost = 'local';
      let bestCap = -1;
      for (let j = 0; j < hosts.length; j++) {
        const remaining = capacities[j] - (used[hosts[j]] || 0);
        if (remaining > bestCap) {
          bestCap = remaining;
          bestHost = hosts[j];
        }
      }
      next[i] = bestHost;
      used[bestHost] = (used[bestHost] || 0) + 1;
    }
    setNodeHosts(next);
  };

  return (
    <div className="space-y-5 max-w-6xl mx-auto">
      {/* Bandwidth limit warning */}
      <div className="rounded-xl border border-amber-200/60 bg-amber-50/80 p-3.5 text-amber-800 text-sm flex items-start gap-3 backdrop-blur-sm"
      >
        <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5 text-amber-500" />
        <span>
          当前 BestEffort 模式下建议测试速率 <strong>≤ 6 Mbps</strong>，超过此速率可能导致严重丢包。
          如需更高带宽，请关闭跟踪选项（PCAP / ASCII / 移动性跟踪）并减少节点数量。
        </span>
      </div>

      {/* Presets & Actions */}
      <div className="flex flex-wrap items-center gap-3"
      >
        <span className="text-sm font-medium text-muted-foreground"
        >预设:</span>
        {presets ? (
          Object.keys(presets)
            .filter(key => !key.startsWith('wifi-'))
            .map(key => (
              <Button
                key={key}
                variant={activePreset === key ? 'default' : 'outline'}
                size="sm"
                onClick={() => loadPreset(key)}
                className={activePreset === key ? 'shadow-glow' : ''}
              >
                {PRESET_NAMES[key] || key}
              </Button>
            ))
        ) : (
          <span className="text-xs text-muted-foreground"
          >加载中...</span>
        )}
        {activePreset === 'custom' && (
          <Badge variant="secondary" className="font-medium"
          >自定义</Badge>
        )}
        <div className="flex-1" />
        {saveStatus === 'saving' && (
          <Badge variant="outline" className="animate-pulse gap-1 font-medium"
          >
            <Loader2 className="h-3 w-3 animate-spin" />
            保存中...
          </Badge>
        )}
        {saveStatus === 'saved' && (
          <Badge variant="secondary" className="text-success gap-1 font-medium bg-success/10 border-success/20"
          >
            <CheckCircle2 className="h-3 w-3" />
            已保存
          </Badge>
        )}
        {saveStatus === 'error' && (
          <Badge variant="destructive" className="gap-1 font-medium"
          >
            <XCircle className="h-3 w-3" />
            保存失败
          </Badge>
        )}
        <Button variant="outline" size="sm" onClick={handleImport} className="gap-1.5"
        >
          <Upload className="h-3.5 w-3.5" /> 导入
        </Button>
        <Button variant="outline" size="sm" onClick={handleExport} className="gap-1.5"
        >
          <Download className="h-3.5 w-3.5" /> 导出 .conf
        </Button>
        <Button variant="ghost" size="sm" onClick={resetToDefault} className="gap-1.5"
        >
          <RotateCcw className="h-3.5 w-3.5" /> 重置
        </Button>
      </div>

      <Tabs defaultValue="general" className="w-full"
      >
        <TabsList className="grid w-full grid-cols-6 p-1 bg-muted/50"
        >
          <TabsTrigger value="general" className="gap-1.5 text-xs font-medium"
          >
            <Radio className="h-3.5 w-3.5" /> 通用
          </TabsTrigger>
          <TabsTrigger value="phy" className="gap-1.5 text-xs font-medium"
          >
            <Wifi className="h-3.5 w-3.5" /> 物理层
          </TabsTrigger>
          <TabsTrigger value="mac" className="gap-1.5 text-xs font-medium"
          >
            <Save className="h-3.5 w-3.5" /> MAC
          </TabsTrigger>
          <TabsTrigger value="routing" className="gap-1.5 text-xs font-medium"
          >
            <Route className="h-3.5 w-3.5" /> 路由
          </TabsTrigger>
          <TabsTrigger value="mobility" className="gap-1.5 text-xs font-medium"
          >
            <MapPin className="h-3.5 w-3.5" /> 移动性
          </TabsTrigger>
          <TabsTrigger value="tracing" className="gap-1.5 text-xs font-medium"
          >
            <BarChart3 className="h-3.5 w-3.5" /> 跟踪
          </TabsTrigger>
        </TabsList>

        {/* General Tab */}
        <TabsContent value="general" className="mt-4"
        >
          <Card className="border-slate-200/60 shadow-card"
          >
            <CardHeader className="pb-3"
            >
              <CardTitle className="text-sm font-semibold flex items-center gap-2"
              >
                <div className="h-7 w-7 rounded-lg bg-primary/10 flex items-center justify-center"
                >
                  <Radio className="h-3.5 w-3.5 text-primary" />
                </div>
                通用参数
              </CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-5"
            >
              <div className="space-y-2"
              >
                <Label className="text-xs font-medium text-muted-foreground"
                >节点数量</Label>
                <Input type="number" min={2} max={16} value={config.nNodes}
                  onChange={e => updateConfig('nNodes', Number(e.target.value))} className="h-9"
                />
              </div>
              <div className="space-y-2"
              >
                <Label className="text-xs font-medium text-muted-foreground"
                >仿真时长 (秒)</Label>
                <Input type="number" min={10} max={3600} value={config.simulationTime}
                  onChange={e => updateConfig('simulationTime', Number(e.target.value))} className="h-9"
                />
              </div>
              <div className="space-y-2"
              >
                <Label className="text-xs font-medium text-muted-foreground"
                >随机种子</Label>
                <Input type="number" min={1} value={config.seed}
                  onChange={e => updateConfig('seed', Number(e.target.value))} className="h-9"
                />
              </div>
              <div className="space-y-2"
              >
                <Label className="text-xs font-medium text-muted-foreground"
                >运行编号</Label>
                <Input type="number" min={1} value={config.run}
                  onChange={e => updateConfig('run', Number(e.target.value))} className="h-9"
                />
              </div>
              <div className="space-y-2 col-span-2 md:col-span-4"
              >
                <Label className="text-xs font-medium text-muted-foreground"
                >日志组件 (逗号分隔)</Label>
                <Input placeholder="e.g. Manet30Nodes,AodvRoutingProtocol" value={config.logComponents}
                  onChange={e => updateConfig('logComponents', e.target.value)} className="h-9"
                />
              </div>

              {/* 多机部署: 节点主机分配 */}
              <div className="col-span-2 md:col-span-4 border-t pt-4 mt-2"
              >
                <div className="flex items-center gap-3 mb-3"
                >
                  <Server className="h-4 w-4 text-primary" />
                  <h4 className="text-sm font-semibold"
                  >多机部署</h4>
                  <Button
                    variant="ghost" size="sm" className="h-7 text-xs"
                    onClick={() => setShowHostAssign(v => !v)}
                  >
                    {showHostAssign ? '收起' : '展开'}
                  </Button>
                  <div className="flex-1" />
                  <Button
                    variant="outline" size="sm" className="h-7 text-xs gap-1"
                    onClick={autoAssignHosts}
                    disabled={remoteHosts.length === 0}
                  >
                    自动分配
                  </Button>
                </div>

                {showHostAssign && (
                  <div className="space-y-3"
                  >
                    {remoteHosts.length === 0 && (
                      <p className="text-xs text-muted-foreground"
                      >
                        尚未注册远端主机。请先用 <code className="bg-muted px-1 rounded"
                        >POST /api/hosts/register</code> 注册。
                      </p>
                    )}
                    <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2"
                    >
                      {Array.from({ length: config.nNodes }, (_, i) => (
                        <div key={i} className="space-y-1"
                        >
                          <Label className="text-[10px] font-medium text-muted-foreground"
                          >节点 {i} ({`192.168.100.${10 + i}`})</Label>
                          <Select
                            value={nodeHosts[i] ?? 'local'}
                            onValueChange={v => setNodeHosts(prev => ({ ...prev, [i]: v }))}
                          >
                            <SelectTrigger className="h-8 text-xs"
                            >
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="local"
                              >本地</SelectItem>
                              {remoteHosts.map(h => (
                                <SelectItem key={h.ip} value={h.ip}
                                >{h.ip}</SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      ))}
                    </div>
                    <p className="text-[11px] text-muted-foreground"
                    >
                      {'提示: 节点 0 默认是 server，节点 15 默认是 gateway（当节点数 >15 时）。'}
                    </p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* PHY Tab */}
        <TabsContent value="phy" className="mt-4"
        >
          <Card className="border-slate-200/60 shadow-card"
          >
            <CardHeader className="pb-3"
            >
              <CardTitle className="text-sm font-semibold flex items-center gap-2"
              >
                <div className="h-7 w-7 rounded-lg bg-primary/10 flex items-center justify-center"
                >
                  <Wifi className="h-3.5 w-3.5 text-primary" />
                </div>
                物理层
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-6"
            >
              <div className="grid grid-cols-2 md:grid-cols-3 gap-5"
              >
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >802.11 标准</Label>
                  <Select value={config.standard} onValueChange={v => updateConfig('standard', v)}
                  >
                    <SelectTrigger className="h-9"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {STANDARDS.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >PHY 模型</Label>
                  <Select value={config.phyModel} onValueChange={v => updateConfig('phyModel', v)}
                  >
                    <SelectTrigger className="h-9"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PHY_MODELS.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >数据速率</Label>
                  <Select value={config.dataRate} onValueChange={v => updateConfig('dataRate', v)}
                  >
                    <SelectTrigger className="h-9"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(DATA_RATES[config.standard] || []).map(r => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-5"
              >
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >频率 (MHz)</Label>
                  <Input type="number" min={100} max={6000} value={config.frequencyMhz}
                    onChange={e => updateConfig('frequencyMhz', Number(e.target.value))} className="h-9"
                  />
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >信道宽度 (MHz)</Label>
                  <Input type="number" min={5} max={160} value={config.channelWidthMhz}
                    onChange={e => updateConfig('channelWidthMhz', Number(e.target.value))} className="h-9"
                  />
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >目标覆盖范围 (m)</Label>
                  <Input type="number" min={10} max={50000} value={config.rangeTargetM}
                    onChange={e => updateConfig('rangeTargetM', Number(e.target.value))} className="h-9"
                  />
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >传播延迟</Label>
                  <Select value={config.propagationDelay} onValueChange={v => updateConfig('propagationDelay', v)}
                  >
                    <SelectTrigger className="h-9"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PROPAGATION_DELAYS.map(d => <SelectItem key={d} value={d}>{d}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-5"
              >
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >发射功率起始 (dBm)</Label>
                  <Input type="number" step={0.1} value={config.txPowerStart}
                    onChange={e => updateConfig('txPowerStart', Number(e.target.value))} className="h-9"
                  />
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >发射功率结束 (dBm)</Label>
                  <Input type="number" step={0.1} value={config.txPowerEnd}
                    onChange={e => updateConfig('txPowerEnd', Number(e.target.value))} className="h-9"
                  />
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >发射功率等级</Label>
                  <Input type="number" min={1} value={config.txPowerLevels}
                    onChange={e => updateConfig('txPowerLevels', Number(e.target.value))} className="h-9"
                  />
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >天线增益 (dBi)</Label>
                  <Input type="number" step={0.1} value={config.antennaGain}
                    onChange={e => updateConfig('antennaGain', Number(e.target.value))} className="h-9"
                  />
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >接收灵敏度 (dBm)</Label>
                  <Input type="number" step={0.1} value={config.rxSensitivity}
                    onChange={e => updateConfig('rxSensitivity', Number(e.target.value))} className="h-9"
                  />
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >CCA 阈值 (dBm)</Label>
                  <Input type="number" step={0.1} value={config.ccaThreshold}
                    onChange={e => updateConfig('ccaThreshold', Number(e.target.value))} className="h-9"
                  />
                </div>
              </div>

              <div className="border-t pt-5"
              >
                <h4 className="font-semibold mb-4 text-sm flex items-center gap-2"
                >
                  <div className="h-6 w-6 rounded-md bg-violet-500/10 flex items-center justify-center"
                  >
                    <Route className="h-3 w-3 text-violet-500" />
                  </div>
                  路径损耗模型
                </h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-5"
                >
                  <div className="space-y-2"
                  >
                    <Label className="text-xs font-medium text-muted-foreground"
                    >模型</Label>
                    <Select value={config.pathLossModel} onValueChange={v => updateConfig('pathLossModel', v)}
                    >
                      <SelectTrigger className="h-9"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {PATH_LOSS_MODELS.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2"
                  >
                    <Label className="text-xs font-medium text-muted-foreground"
                    >指数: {config.pathLossExponent}</Label>
                    <Slider min={1} max={6} step={0.1} value={[config.pathLossExponent]}
                      onValueChange={v => updateConfig('pathLossExponent', v[0])}
                    />
                  </div>
                  <div className="space-y-2"
                  >
                    <Label className="text-xs font-medium text-muted-foreground"
                    >1m 参考损耗 (dB)</Label>
                    <Input type="number" value={config.pathLossRefLoss}
                      onChange={e => updateConfig('pathLossRefLoss', Number(e.target.value))} className="h-9"
                    />
                  </div>
                  <div className="space-y-2"
                  >
                    <Label className="text-xs font-medium text-muted-foreground"
                    >参考距离 (m)</Label>
                    <Input type="number" value={config.pathLossRefDistance}
                      onChange={e => updateConfig('pathLossRefDistance', Number(e.target.value))} className="h-9"
                    />
                  </div>
                </div>
              </div>

              <div className="border-t pt-5"
              >
                <div className="flex items-center gap-3 mb-4"
                >
                  <h4 className="font-semibold text-sm flex items-center gap-2"
                  >
                    <div className="h-6 w-6 rounded-md bg-amber-500/10 flex items-center justify-center"
                    >
                      <Wifi className="h-3 w-3 text-amber-500" />
                    </div>
                    衰落模型
                  </h4>
                  <Switch checked={config.enableFading} onCheckedChange={v => updateConfig('enableFading', v)} />
                </div>
                {config.enableFading && (
                  <div className="space-y-5"
                  >
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-5"
                    >
                      <div className="space-y-2"
                      >
                        <Label className="text-xs font-medium text-muted-foreground"
                        >模型</Label>
                        <Select value={config.fadingModel} onValueChange={v => updateConfig('fadingModel', v)}
                        >
                          <SelectTrigger className="h-9"
                          >
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {FADING_MODELS.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                          </SelectContent>
                        </Select>
                      </div>
                      {(config.fadingModel === 'Nakagami' || config.fadingModel === 'Rayleigh' || config.fadingModel === 'Rician') && (
                        <>
                          <div className="space-y-2"
                          >
                            <Label className="text-xs font-medium text-muted-foreground"
                            >距离 D1 (m)</Label>
                            <Input type="number" value={config.nakagamiD1}
                              onChange={e => updateConfig('nakagamiD1', Number(e.target.value))} className="h-9"
                            />
                          </div>
                          <div className="space-y-2"
                          >
                            <Label className="text-xs font-medium text-muted-foreground"
                            >距离 D2 (m)</Label>
                            <Input type="number" value={config.nakagamiD2}
                              onChange={e => updateConfig('nakagamiD2', Number(e.target.value))} className="h-9"
                            />
                          </div>
                        </>
                      )}
                      {config.fadingModel === 'Rician' && (
                        <div className="space-y-2"
                        >
                          <Label className="text-xs font-medium text-muted-foreground"
                          >K 因子 (dB): {config.ricianK}</Label>
                          <Slider min={0} max={30} step={0.5} value={[config.ricianK]}
                            onValueChange={v => updateConfig('ricianK', v[0])}
                          />
                          <p className="text-xs text-muted-foreground"
                          >K=0 退化为 Rayleigh；K 越大越接近 LOS</p>
                        </div>
                      )}
                    </div>
                    {config.fadingModel === 'Nakagami' && (
                      <div className="grid grid-cols-2 md:grid-cols-3 gap-5"
                      >
                        <div className="space-y-2"
                        >
                          <Label className="text-xs font-medium text-muted-foreground"
                          >Nakagami M0 (d&lt;d1): {config.nakagamiM0}</Label>
                          <Slider min={0.1} max={5} step={0.1} value={[config.nakagamiM0]}
                            onValueChange={v => updateConfig('nakagamiM0', v[0])}
                          />
                        </div>
                        <div className="space-y-2"
                        >
                          <Label className="text-xs font-medium text-muted-foreground"
                          >Nakagami M1 (d1&lt;d&lt;d2): {config.nakagamiM1}</Label>
                          <Slider min={0.1} max={5} step={0.1} value={[config.nakagamiM1]}
                            onValueChange={v => updateConfig('nakagamiM1', v[0])}
                          />
                        </div>
                        <div className="space-y-2"
                        >
                          <Label className="text-xs font-medium text-muted-foreground"
                          >Nakagami M2 (d&gt;d2): {config.nakagamiM2}</Label>
                          <Slider min={0.1} max={5} step={0.1} value={[config.nakagamiM2]}
                            onValueChange={v => updateConfig('nakagamiM2', v[0])}
                          />
                        </div>
                      </div>
                    )}
                    {config.fadingModel === 'Rayleigh' && (
                      <p className="text-xs text-muted-foreground"
                      >Rayleigh 衰落是 Nakagami 的特列（m=1），用于纯散射环境（无直射路径）</p>
                    )}
                    {config.fadingModel === 'Rician' && (
                      <p className="text-xs text-muted-foreground"
                      >Rician 衰落通过 Nakagami 近似实现：等效 m = (K+1)²/(2K+1)</p>
                    )}
                  </div>
                )}
              </div>

              {/* Obstacles Section */}
              <div className="border-t pt-5"
              >
                <div className="flex items-center gap-3 mb-4"
                >
                  <h4 className="font-semibold text-sm flex items-center gap-2"
                  >
                    <div className="h-6 w-6 rounded-md bg-emerald-500/10 flex items-center justify-center"
                    >
                      <MapPin className="h-3 w-3 text-emerald-500" />
                    </div>
                    障碍物 / 地形模型
                  </h4>
                  <Switch checked={config.enableObstacles} onCheckedChange={v => updateConfig('enableObstacles', v)} />
                </div>
                {config.enableObstacles && (
                  <div className="space-y-5"
                  >
                    <div className="grid grid-cols-2 md:grid-cols-3 gap-5"
                    >
                      <div className="space-y-2"
                      >
                        <Label className="text-xs font-medium text-muted-foreground"
                        >阴影标准差 (dB): {config.obstacleShadowingSigma}</Label>
                        <Slider min={0} max={12} step={0.5} value={[config.obstacleShadowingSigma]}
                          onValueChange={v => updateConfig('obstacleShadowingSigma', v[0])}
                        />
                        <p className="text-xs text-muted-foreground"
                        >对数正态阴影衰落的标准差；0 表示禁用阴影</p>
                      </div>
                      <div className="space-y-2"
                      >
                        <Label className="text-xs font-medium text-muted-foreground"
                        >穿透损耗 (dB): {config.obstaclePenetrationLoss}</Label>
                        <Slider min={0} max={40} step={1} value={[config.obstaclePenetrationLoss]}
                          onValueChange={v => updateConfig('obstaclePenetrationLoss', v[0])}
                        />
                        <p className="text-xs text-muted-foreground"
                        >NLOS 路径的额外穿透损耗</p>
                      </div>
                      <div className="flex items-center gap-2 pt-6"
                      >
                        <Switch id="diffraction" checked={config.obstacleDiffractionEnabled}
                          onCheckedChange={v => updateConfig('obstacleDiffractionEnabled', v)} />
                        <Label htmlFor="diffraction" className="text-sm cursor-pointer"
                        >启用绕射</Label>
                      </div>
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >障碍物配置 (JSON)</Label>
                      <textarea
                        className="w-full min-h-[80px] rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm font-mono"
                        value={config.obstaclesJson}
                        onChange={e => updateConfig('obstaclesJson', e.target.value)}
                        placeholder='[{"x":100,"y":100,"w":50,"h":50,"loss":15}]'
                      />
                      <p className="text-xs text-muted-foreground"
                      >矩形障碍物列表：x/y 中心坐标，w/h 宽高，loss 穿透损耗(dB)。留空则对所有链路使用固定穿透损耗。</p>
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* MAC Tab */}
        <TabsContent value="mac" className="mt-4"
        >
          <Card className="border-slate-200/60 shadow-card"
          >
            <CardHeader className="pb-3"
            >
              <CardTitle className="text-sm font-semibold"
              >MAC 层 (AdHoc / Mesh)</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6"
            >
              <div className="grid grid-cols-2 md:grid-cols-4 gap-5"
              >
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >MAC 模式</Label>
                  <Select value={config.macMode} onValueChange={v => updateConfig('macMode', v)}
                  >
                    <SelectTrigger className="h-9"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {MAC_MODES.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >SSID</Label>
                  <Input value={config.ssid} onChange={e => updateConfig('ssid', e.target.value)} className="h-9"
                  />
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >BSSID</Label>
                  <Input value={config.bssid} onChange={e => updateConfig('bssid', e.target.value)} className="h-9"
                  />
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >速率控制</Label>
                  <Select value={config.rateControl} onValueChange={v => updateConfig('rateControl', v)}
                  >
                    <SelectTrigger className="h-9"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {RATE_CONTROLS.map(r => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >信标间隔 (TU)</Label>
                  <Input type="number" value={config.beaconInterval}
                    onChange={e => updateConfig('beaconInterval', Number(e.target.value))} className="h-9"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-5"
              >
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >RTS/CTS 阈值: {config.rtsCtsThreshold === 65535 ? '禁用' : config.rtsCtsThreshold}</Label>
                  <Slider min={0} max={65535} step={100} value={[config.rtsCtsThreshold]}
                    onValueChange={v => updateConfig('rtsCtsThreshold', v[0])}
                  />
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >分片阈值</Label>
                  <Input type="number" value={config.fragmentationThreshold}
                    onChange={e => updateConfig('fragmentationThreshold', Number(e.target.value))} className="h-9"
                  />
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >最小竞争窗口</Label>
                  <Input type="number" min={0} max={1023} value={config.cwMin}
                    onChange={e => updateConfig('cwMin', Number(e.target.value))} className="h-9"
                  />
                </div>
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >最大竞争窗口</Label>
                  <Input type="number" min={0} max={1023} value={config.cwMax}
                    onChange={e => updateConfig('cwMax', Number(e.target.value))} className="h-9"
                  />
                </div>
              </div>
              <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/40"
              >
                <Switch id="non-unicast" checked={config.nonUnicastMode}
                  onCheckedChange={v => updateConfig('nonUnicastMode', v)} />
                <Label htmlFor="non-unicast" className="text-sm cursor-pointer"
                >非单播模式 (广播/组播使用最低数据速率)</Label>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Routing Tab */}
        <TabsContent value="routing" className="mt-4"
        >
          <Card className="border-slate-200/60 shadow-card"
          >
            <CardHeader className="pb-3"
            >
              <CardTitle className="text-sm font-semibold"
              >路由协议</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6"
            >
              <div className="space-y-2"
              >
                <Label className="text-xs font-medium text-muted-foreground"
                >协议</Label>
                <Select value={config.routingProtocol} onValueChange={v => updateConfig('routingProtocol', v)}
                >
                  <SelectTrigger className="h-9"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ROUTING_PROTOCOLS.map(p => <SelectItem key={p} value={p}>{p.toUpperCase()}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>

              {config.routingProtocol === 'aodv' && (
                <div className="border-t pt-5"
                >
                  <h4 className="font-semibold mb-4 text-sm"
                  >AODV 参数</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-5"
                  >
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >Hello 间隔 (s)</Label>
                      <Input type="number" step={0.1} value={config.aodvHelloInterval}
                        onChange={e => updateConfig('aodvHelloInterval', Number(e.target.value))} className="h-9"
                      />
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >RREQ 重试次数</Label>
                      <Input type="number" value={config.aodvRreqRetries}
                        onChange={e => updateConfig('aodvRreqRetries', Number(e.target.value))} className="h-9"
                      />
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >活跃路由超时 (s)</Label>
                      <Input type="number" step={0.1} value={config.aodvActiveRouteTimeout}
                        onChange={e => updateConfig('aodvActiveRouteTimeout', Number(e.target.value))} className="h-9"
                      />
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >删除周期 (s)</Label>
                      <Input type="number" step={0.1} value={config.aodvDeletePeriod}
                        onChange={e => updateConfig('aodvDeletePeriod', Number(e.target.value))} className="h-9"
                      />
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >网络直径 (跳)</Label>
                      <Input type="number" value={config.aodvNetDiameter}
                        onChange={e => updateConfig('aodvNetDiameter', Number(e.target.value))} className="h-9"
                      />
                    </div>
                    <div className="flex items-center gap-2 pt-6"
                    >
                      <Switch id="aodv-hello" checked={config.aodvEnableHello}
                        onCheckedChange={v => updateConfig('aodvEnableHello', v)} />
                      <Label htmlFor="aodv-hello" className="text-sm cursor-pointer"
                      >启用 Hello</Label>
                    </div>
                  </div>
                </div>
              )}

              {config.routingProtocol === 'olsr' && (
                <div className="border-t pt-5"
                >
                  <h4 className="font-semibold mb-4 text-sm"
                  >OLSR 参数</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-5"
                  >
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >Hello 间隔 (s)</Label>
                      <Input type="number" step={0.1} value={config.olsrHelloInterval}
                        onChange={e => updateConfig('olsrHelloInterval', Number(e.target.value))} className="h-9"
                      />
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >TC 间隔 (s)</Label>
                      <Input type="number" step={0.1} value={config.olsrTcInterval}
                        onChange={e => updateConfig('olsrTcInterval', Number(e.target.value))} className="h-9"
                      />
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >意愿值 (0-7)</Label>
                      <Input type="number" min={0} max={7} value={config.olsrWillingness}
                        onChange={e => updateConfig('olsrWillingness', Number(e.target.value))} className="h-9"
                      />
                    </div>
                  </div>
                </div>
              )}

              {config.routingProtocol === 'dsdv' && (
                <div className="border-t pt-5"
                >
                  <h4 className="font-semibold mb-4 text-sm"
                  >DSDV 参数</h4>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-5"
                  >
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >定期更新间隔 (s)</Label>
                      <Input type="number" step={0.1} value={config.dsdvPeriodicUpdateInterval}
                        onChange={e => updateConfig('dsdvPeriodicUpdateInterval', Number(e.target.value))} className="h-9"
                      />
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >稳定时间 (s)</Label>
                      <Input type="number" step={0.1} value={config.dsdvSettlingTime}
                        onChange={e => updateConfig('dsdvSettlingTime', Number(e.target.value))} className="h-9"
                      />
                    </div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Mobility Tab */}
        <TabsContent value="mobility" className="mt-4"
        >
          <Card className="border-slate-200/60 shadow-card"
          >
            <CardHeader className="pb-3"
            >
              <CardTitle className="text-sm font-semibold"
              >移动模型</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6"
            >
              <div className="grid grid-cols-2 md:grid-cols-3 gap-5"
              >
                <div className="space-y-2"
                >
                  <Label className="text-xs font-medium text-muted-foreground"
                  >模型</Label>
                  <Select value={config.mobilityModel} onValueChange={v => updateConfig('mobilityModel', v)}
                  >
                    <SelectTrigger className="h-9"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {MOBILITY_MODELS.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="border-t pt-5"
              >
                <h4 className="font-semibold mb-4 text-sm"
                >仿真区域 (米)</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-5"
                >
                  <div className="space-y-2"
                  >
                    <Label className="text-xs font-medium text-muted-foreground"
                    >最小 X</Label>
                    <Input type="number" value={config.mobilityMinX}
                      onChange={e => updateConfig('mobilityMinX', Number(e.target.value))} className="h-9"
                    />
                  </div>
                  <div className="space-y-2"
                  >
                    <Label className="text-xs font-medium text-muted-foreground"
                    >最大 X</Label>
                    <Input type="number" value={config.mobilityMaxX}
                      onChange={e => updateConfig('mobilityMaxX', Number(e.target.value))} className="h-9"
                    />
                  </div>
                  <div className="space-y-2"
                  >
                    <Label className="text-xs font-medium text-muted-foreground"
                    >最小 Y</Label>
                    <Input type="number" value={config.mobilityMinY}
                      onChange={e => updateConfig('mobilityMinY', Number(e.target.value))} className="h-9"
                    />
                  </div>
                  <div className="space-y-2"
                  >
                    <Label className="text-xs font-medium text-muted-foreground"
                    >最大 Y</Label>
                    <Input type="number" value={config.mobilityMaxY}
                      onChange={e => updateConfig('mobilityMaxY', Number(e.target.value))} className="h-9"
                    />
                  </div>
                </div>
              </div>

              {(config.mobilityModel === 'random-walk' || config.mobilityModel === 'gauss-markov') && (
                <div className="border-t pt-5"
                >
                  <h4 className="font-semibold mb-4 text-sm"
                  >随机游走参数</h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-5"
                  >
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >最小速度 (m/s)</Label>
                      <Input type="number" step={0.1} value={config.rwMinSpeed}
                        onChange={e => updateConfig('rwMinSpeed', Number(e.target.value))} className="h-9"
                      />
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >最大速度 (m/s)</Label>
                      <Input type="number" step={0.1} value={config.rwMaxSpeed}
                        onChange={e => updateConfig('rwMaxSpeed', Number(e.target.value))} className="h-9"
                      />
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >模式</Label>
                      <Select value={config.rwMode} onValueChange={v => updateConfig('rwMode', v)}
                      >
                        <SelectTrigger className="h-9"
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {RW_MODES.map(m => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >时间步长 (s)</Label>
                      <Input type="number" step={0.1} value={config.rwTime}
                        onChange={e => updateConfig('rwTime', Number(e.target.value))} className="h-9"
                      />
                    </div>
                  </div>
                </div>
              )}

              {config.mobilityModel === 'gauss-markov' && (
                <div className="border-t pt-5"
                >
                  <h4 className="font-semibold mb-4 text-sm"
                  >高斯-马尔可夫参数</h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-5"
                  >
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >Alpha (记忆系数): {config.gmAlpha.toFixed(2)}</Label>
                      <Slider min={0} max={1} step={0.05} value={[config.gmAlpha]}
                        onValueChange={v => updateConfig('gmAlpha', v[0])}
                      />
                      <p className="text-xs text-muted-foreground"
                      >
                        0 = 完全随机; 1 = 完美直线运动
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {(config.mobilityModel === 'grid' || config.mobilityModel === 'constant') && (
                <div className="border-t pt-5"
                >
                  <h4 className="font-semibold mb-4 text-sm"
                  >网格参数</h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-5"
                  >
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >X 间距 (m)</Label>
                      <Input type="number" value={config.gridDeltaX}
                        onChange={e => updateConfig('gridDeltaX', Number(e.target.value))} className="h-9"
                      />
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >Y 间距 (m)</Label>
                      <Input type="number" value={config.gridDeltaY}
                        onChange={e => updateConfig('gridDeltaY', Number(e.target.value))} className="h-9"
                      />
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >每行节点数</Label>
                      <Input type="number" value={config.gridWidth}
                        onChange={e => updateConfig('gridWidth', Number(e.target.value))} className="h-9"
                      />
                    </div>
                    <div className="space-y-2"
                    >
                      <Label className="text-xs font-medium text-muted-foreground"
                      >布局</Label>
                      <Select value={config.gridLayout} onValueChange={v => updateConfig('gridLayout', v)}
                      >
                        <SelectTrigger className="h-9"
                        >
                          <SelectValue />
                        </SelectTrigger>
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
        <TabsContent value="tracing" className="mt-4"
        >
          <Card className="border-slate-200/60 shadow-card"
          >
            <CardHeader className="pb-3"
            >
              <CardTitle className="text-sm font-semibold"
              >跟踪选项</CardTitle>
            </CardHeader>
            <CardContent className="space-y-5"
            >
              <div className="grid grid-cols-2 md:grid-cols-3 gap-5"
              >
                <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/40"
                >
                  <Switch id="pcap" checked={config.pcap} onCheckedChange={v => updateConfig('pcap', v)} />
                  <Label htmlFor="pcap" className="text-sm cursor-pointer"
                  >PCAP 跟踪</Label>
                </div>
                <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/40"
                >
                  <Switch id="ascii" checked={config.ascii} onCheckedChange={v => updateConfig('ascii', v)} />
                  <Label htmlFor="ascii" className="text-sm cursor-pointer"
                  >ASCII 跟踪</Label>
                </div>
                <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/40"
                >
                  <Switch id="flowmon" checked={config.flowMonitor} onCheckedChange={v => updateConfig('flowMonitor', v)} />
                  <Label htmlFor="flowmon" className="text-sm cursor-pointer"
                  >流监控</Label>
                </div>
                <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/40"
                >
                  <Switch id="mobtrace" checked={config.enableMobilityTrace} onCheckedChange={v => updateConfig('enableMobilityTrace', v)} />
                  <Label htmlFor="mobtrace" className="text-sm cursor-pointer"
                  >移动性跟踪</Label>
                </div>
              </div>
              <div className="space-y-2"
              >
                <Label className="text-xs font-medium text-muted-foreground"
                >PCAP 文件名前缀</Label>
                <Input value={config.pcapPrefix} onChange={e => updateConfig('pcapPrefix', e.target.value)} className="h-9"
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
