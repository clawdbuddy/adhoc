import { useState, useEffect, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { useDynamicControl } from '@/hooks/useDynamicControl';
import type { NodeStatus, SimulationStatus, SimConfig, TelemetryEnv, ParamChangeMsg } from '@/types/config';
import {
  Zap, MapPin, Radio, Activity, Settings2,
  Send, CheckCircle, AlertCircle, Info,
  TowerControl, Waves, Radar,
} from 'lucide-react';

interface SimApi {
  setParam: (key: string, value: unknown) => Promise<{
    ok: boolean;
    key?: string;
    reason?: string;
    results?: Array<{ ok: boolean; nodeId?: number; reason?: string }>;
  }>;
  subscribeParamChange: (cb: (msg: ParamChangeMsg) => void) => () => void;
}

interface DynamicControlProps {
  status: SimulationStatus;
  nodes: NodeStatus[];
  config: SimConfig;
  env: TelemetryEnv | null;
  sim: SimApi;
}

export function DynamicControl({ status, nodes, config, env, sim }: DynamicControlProps) {
  const ctrl = useDynamicControl(sim);
  const [selectedNode, setSelectedNode] = useState(0);
  const [posX, setPosX] = useState('');
  const [posY, setPosY] = useState('');
  const [txPower, setTxPower] = useState([env?.txPower?.[selectedNode] ?? config.txPowerStart]);
  const [rxSens, setRxSens] = useState([env?.rxSensitivity?.[selectedNode] ?? config.rxSensitivity]);
  const [pathLossExp, setPathLossExp] = useState([env?.pathLossExponent ?? config.pathLossExponent]);
  const [frequency, setFrequency] = useState([env?.frequencyMhz ?? config.frequencyMhz]);
  const [channelWidth, setChannelWidth] = useState([env?.channelWidthMhz ?? config.channelWidthMhz]);
  const [rangeTarget, setRangeTarget] = useState([env?.rangeTargetM ?? config.rangeTargetM]);

  useEffect(() => {
    const node = nodes.find(n => n.id === selectedNode);
    if (node) {
      setPosX(node.x.toFixed(1));
      setPosY(node.y.toFixed(1));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNode, nodes]);

  const prevEnvRef = useRef<TelemetryEnv | null>(null);
  useEffect(() => {
    if (!env) return;
    const isFirstEnv = prevEnvRef.current === null;
    prevEnvRef.current = env;

    if (!isFirstEnv && isDirty()) return;

    if (isFirstEnv) {
      setPathLossExp([env.pathLossExponent]);
      setFrequency([env.frequencyMhz]);
      setChannelWidth([env.channelWidthMhz]);
      setRangeTarget([env.rangeTargetM]);
      if (env.txPower[selectedNode] !== undefined) {
        setTxPower([env.txPower[selectedNode]]);
      }
      if (env.rxSensitivity[selectedNode] !== undefined) {
        setRxSens([env.rxSensitivity[selectedNode]]);
      }
    } else {
      setPathLossExp([env.pathLossExponent]);
      setFrequency([env.frequencyMhz]);
      setChannelWidth([env.channelWidthMhz]);
      setRangeTarget([env.rangeTargetM]);
    }
    if (env.positions?.[selectedNode]) {
      setPosX(env.positions[selectedNode].x.toFixed(1));
      setPosY(env.positions[selectedNode].y.toFixed(1));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [env, selectedNode]);

  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  const dirtyRef = useRef(false);
  const dirtyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isDirty = () => dirtyRef.current;
  const markDirty = () => {
    dirtyRef.current = true;
    if (dirtyTimerRef.current) {
      clearTimeout(dirtyTimerRef.current);
    }
    dirtyTimerRef.current = setTimeout(() => {
      dirtyRef.current = false;
    }, 3000);
  };

  const running = status.running;

  const doAction = async (action: () => Promise<{ applied?: boolean; reason?: string } | void>, desc: string) => {
    if (!running) {
      setResult({ ok: false, msg: '仿真未运行' });
      return;
    }
    try {
      const res = await action();
      if (res && 'applied' in res && res.applied === false) {
        setResult({ ok: false, msg: `${desc} 未生效: ${res.reason || '当前配置不支持此修改'}` });
      } else {
        setResult({ ok: true, msg: `${desc} 已生效` });
      }
    } catch (e) {
      setResult({ ok: false, msg: `${desc} 失败: ${(e as Error).message}` });
    }
  };

  return (
    <div className="space-y-4 max-w-6xl mx-auto">
      {!running && (
        <div className="rounded-xl border border-amber-200/60 bg-amber-50/80 p-4 text-amber-800 text-sm flex items-center gap-3 backdrop-blur-sm"
        >
          <AlertCircle className="h-5 w-5 shrink-0 text-amber-500" />
          仿真未运行，动态控制功能不可用。请先启动仿真。
        </div>
      )}

      {result && (
        <div className={`rounded-xl border p-3.5 text-sm flex items-center gap-2.5 animate-scale-in ${
          result.ok ? 'border-green-200 bg-green-50/80 text-green-800' : 'border-red-200 bg-red-50/80 text-red-800'
        }`}
        >
          {result.ok ? <CheckCircle className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
          {result.msg}
        </div>
      )}

      <div className="rounded-xl border border-slate-200/60 bg-slate-50/60 p-4 text-slate-700 text-xs flex items-start gap-3"
      >
        <Info className="h-4 w-4 shrink-0 mt-0.5 text-primary" />
        <span>
          所有动态参数均作用于 <strong>Controller</strong> 仿真层（传播模型 / PHY / MAC），
          不会下发到节点容器。
        </span>
      </div>

      {/* Node Selector */}
      <Card className="border-slate-200/60 shadow-card"
      >
        <CardHeader className="pb-3"
        >
          <CardTitle className="text-sm flex items-center gap-2 font-semibold"
          >
            <div className="h-7 w-7 rounded-lg bg-primary/10 flex items-center justify-center"
            >
              <Settings2 className="h-3.5 w-3.5 text-primary" />
            </div>
            节点选择
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2"
          >
            {nodes.map(n => (
              <button
                key={n.id}
                onClick={() => setSelectedNode(n.id)}
                className={`px-3.5 py-2 rounded-xl text-xs font-mono border transition-all duration-200 ${
                  selectedNode === n.id
                    ? 'bg-primary text-primary-foreground border-primary shadow-glow'
                    : 'bg-background border-border hover:bg-accent hover:border-accent'
                }`}
              >
                节点 {n.id}
                <span className="ml-1.5 opacity-70"
                >({n.x.toFixed(0)}, {n.y.toFixed(0)})</span>
              </button>
            ))}
            {nodes.length === 0 && (
              <span className="text-xs text-muted-foreground"
              >暂无节点数据</span>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4"
      >
        {/* Per-Node Position */}
        <Card className="border-slate-200/60 shadow-card card-lift"
        >
          <CardHeader className="pb-3"
          >
            <CardTitle className="text-sm flex items-center gap-2 font-semibold"
            >
              <div className="h-7 w-7 rounded-lg bg-emerald-500/10 flex items-center justify-center"
              >
                <MapPin className="h-3.5 w-3.5 text-emerald-500" />
              </div>
              节点位置跃迁
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4 ml-auto font-mono"
              >仿真</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3"
          >
            <div className="grid grid-cols-2 gap-3"
            >
              <div>
                <Label className="text-xs font-medium text-muted-foreground"
                >X (米)</Label>
                <Input
                  type="number"
                  value={posX}
                  onChange={e => { setPosX(e.target.value); markDirty(); }}
                  placeholder="0"
                  disabled={!running}
                  className="h-9 mt-1.5"
                />
              </div>
              <div>
                <Label className="text-xs font-medium text-muted-foreground"
                >Y (米)</Label>
                <Input
                  type="number"
                  value={posY}
                  onChange={e => { setPosY(e.target.value); markDirty(); }}
                  placeholder="0"
                  disabled={!running}
                  className="h-9 mt-1.5"
                />
              </div>
            </div>
            <Button
              size="sm"
              className="w-full gap-1.5"
              disabled={!running || posX === '' || posY === ''}
              onClick={() => doAction(
                () => ctrl.setNodePosition(selectedNode, parseFloat(posX), parseFloat(posY)),
                `节点 ${selectedNode} 位置设置`
              )}
            >
              <Send className="h-3.5 w-3.5" />
              应用位置
            </Button>
          </CardContent>
        </Card>

        {/* Per-Node Tx Power */}
        <Card className="border-slate-200/60 shadow-card card-lift"
        >
          <CardHeader className="pb-3"
          >
            <CardTitle className="text-sm flex items-center gap-2 font-semibold"
            >
              <div className="h-7 w-7 rounded-lg bg-amber-500/10 flex items-center justify-center"
              >
                <Zap className="h-3.5 w-3.5 text-amber-500" />
              </div>
              发射功率
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4 ml-auto font-mono"
              >仿真</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3"
          >
            <div className="flex items-center justify-between text-xs text-muted-foreground"
            >
              <span>0 dBm</span>
              <Badge variant="outline" className="font-mono text-sm"
              >{txPower[0]} dBm</Badge>
              <span>40 dBm</span>
            </div>
            <Slider
              value={txPower}
              onValueChange={v => { setTxPower(v); markDirty(); }}
              min={0}
              max={40}
              step={1}
              disabled={!running}
            />
            <Button
              size="sm"
              className="w-full gap-1.5"
              disabled={!running}
              onClick={() => doAction(
                () => ctrl.setTxPower(selectedNode, txPower[0]),
                `节点 ${selectedNode} 功率设置`
              )}
            >
              <Send className="h-3.5 w-3.5" />
              应用功率
            </Button>
          </CardContent>
        </Card>

        {/* Per-Node Rx Sensitivity */}
        <Card className="border-slate-200/60 shadow-card card-lift"
        >
          <CardHeader className="pb-3"
          >
            <CardTitle className="text-sm flex items-center gap-2 font-semibold"
            >
              <div className="h-7 w-7 rounded-lg bg-violet-500/10 flex items-center justify-center"
              >
                <Activity className="h-3.5 w-3.5 text-violet-500" />
              </div>
              接收灵敏度
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4 ml-auto font-mono"
              >仿真</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3"
          >
            <div className="flex items-center justify-between text-xs text-muted-foreground"
            >
              <span>-110 dBm</span>
              <Badge variant="outline" className="font-mono text-sm"
              >{rxSens[0]} dBm</Badge>
              <span>-60 dBm</span>
            </div>
            <Slider
              value={rxSens}
              onValueChange={v => { setRxSens(v); markDirty(); }}
              min={-110}
              max={-60}
              step={1}
              disabled={!running}
            />
            <Button
              size="sm"
              className="w-full gap-1.5"
              disabled={!running}
              onClick={() => doAction(
                () => ctrl.setRxSensitivity(selectedNode, rxSens[0]),
                `节点 ${selectedNode} 灵敏度设置`
              )}
            >
              <Send className="h-3.5 w-3.5" />
              应用灵敏度
            </Button>
          </CardContent>
        </Card>

        {/* Global Path Loss */}
        <Card className="border-slate-200/60 shadow-card card-lift"
        >
          <CardHeader className="pb-3"
          >
            <CardTitle className="text-sm flex items-center gap-2 font-semibold"
            >
              <div className="h-7 w-7 rounded-lg bg-cyan-500/10 flex items-center justify-center"
              >
                <Waves className="h-3.5 w-3.5 text-cyan-500" />
              </div>
              路径损耗指数
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4 ml-auto font-mono"
              >仿真</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3"
          >
            {env?.pathLossModel && env.pathLossModel !== 'LogDistance' && (
              <div className="text-xs text-amber-600 bg-amber-50/80 border border-amber-200/60 rounded-lg px-3 py-2 flex items-center gap-1.5"
              >
                <AlertCircle className="h-3 w-3" />
                当前模型为 {env.pathLossModel}，仅 LogDistance 支持路径损耗指数调整
              </div>
            )}
            <div className="flex items-center justify-between text-xs text-muted-foreground"
            >
              <span>1.0 (自由空间)</span>
              <Badge variant="outline" className="font-mono text-sm"
              >{pathLossExp[0].toFixed(1)}</Badge>
              <span>6.0 (高密度城市)</span>
            </div>
            <Slider
              value={pathLossExp}
              onValueChange={v => { setPathLossExp(v); markDirty(); }}
              min={1.0}
              max={6.0}
              step={0.1}
              disabled={!running || (env?.pathLossModel ? env.pathLossModel !== 'LogDistance' : false)}
            />
            <Button
              size="sm"
              className="w-full gap-1.5"
              disabled={!running || (env?.pathLossModel ? env.pathLossModel !== 'LogDistance' : false)}
              onClick={() => doAction(
                () => ctrl.setPathLossExponent(pathLossExp[0]),
                '路径损耗指数设置'
              )}
            >
              <Send className="h-3.5 w-3.5" />
              应用路径损耗
            </Button>
          </CardContent>
        </Card>

        {/* Global Frequency */}
        <Card className="border-slate-200/60 shadow-card card-lift"
        >
          <CardHeader className="pb-3"
          >
            <CardTitle className="text-sm flex items-center gap-2 font-semibold"
            >
              <div className="h-7 w-7 rounded-lg bg-rose-500/10 flex items-center justify-center"
              >
                <Radio className="h-3.5 w-3.5 text-rose-500" />
              </div>
              中心频率
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4 ml-auto font-mono"
              >仿真</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3"
          >
            <div className="flex items-center justify-between text-xs text-muted-foreground"
            >
              <span>300 MHz</span>
              <Badge variant="outline" className="font-mono text-sm"
              >{frequency[0]} MHz</Badge>
              <span>5800 MHz</span>
            </div>
            <Slider
              value={frequency}
              onValueChange={v => { setFrequency(v); markDirty(); }}
              min={300}
              max={5800}
              step={10}
              disabled={!running}
            />
            <Button
              size="sm"
              className="w-full gap-1.5"
              disabled={!running}
              onClick={() => doAction(
                () => ctrl.setFrequency(frequency[0]),
                '频率设置'
              )}
            >
              <Send className="h-3.5 w-3.5" />
              应用频率
            </Button>
          </CardContent>
        </Card>

        {/* Global Channel Width */}
        <Card className="border-slate-200/60 shadow-card card-lift"
        >
          <CardHeader className="pb-3"
          >
            <CardTitle className="text-sm flex items-center gap-2 font-semibold"
            >
              <div className="h-7 w-7 rounded-lg bg-indigo-500/10 flex items-center justify-center"
              >
                <TowerControl className="h-3.5 w-3.5 text-indigo-500" />
              </div>
              信道宽度
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4 ml-auto font-mono"
              >仿真</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3"
          >
            <p className="text-xs text-amber-600 bg-amber-50/60 rounded-lg px-3 py-2 border border-amber-200/40"
            >
              运行时修改不生效，需重启仿真才能应用
            </p>
            <div className="flex items-center justify-between text-xs text-muted-foreground"
            >
              <span>5 MHz</span>
              <Badge variant="outline" className="font-mono text-sm"
              >{channelWidth[0]} MHz</Badge>
              <span>80 MHz</span>
            </div>
            <Slider
              value={channelWidth}
              onValueChange={v => { setChannelWidth(v); markDirty(); }}
              min={5}
              max={80}
              step={5}
              disabled={!running}
            />
            <Button
              size="sm"
              className="w-full gap-1.5"
              disabled={!running}
              onClick={() => doAction(
                () => ctrl.setChannelWidth(channelWidth[0]),
                '信道宽度设置'
              )}
            >
              <Send className="h-3.5 w-3.5" />
              应用信道宽度
            </Button>
          </CardContent>
        </Card>

        {/* Global Range Target */}
        <Card className="lg:col-span-2 border-slate-200/60 shadow-card card-lift"
        >
          <CardHeader className="pb-3"
          >
            <CardTitle className="text-sm flex items-center gap-2 font-semibold"
            >
              <div className="h-7 w-7 rounded-lg bg-teal-500/10 flex items-center justify-center"
              >
                <Radar className="h-3.5 w-3.5 text-teal-500" />
              </div>
              最大通信距离 (Range 模型)
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0 h-4 ml-auto font-mono"
              >仿真</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3"
          >
            <div className="flex items-center justify-between text-xs text-muted-foreground"
            >
              <span>100 m</span>
              <Badge variant="outline" className="font-mono text-sm"
              >{rangeTarget[0]} m</Badge>
              <span>10000 m</span>
            </div>
            <Slider
              value={rangeTarget}
              onValueChange={v => { setRangeTarget(v); markDirty(); }}
              min={100}
              max={10000}
              step={100}
              disabled={!running}
            />
            <Button
              size="sm"
              className="w-full gap-1.5"
              disabled={!running}
              onClick={() => doAction(
                () => ctrl.setRangeTarget(rangeTarget[0]),
                '最大通信距离设置'
              )}
            >
              <Send className="h-3.5 w-3.5" />
              应用通信距离
            </Button>
          </CardContent>
        </Card>
      </div>

      <Separator className="my-2"
      />

      {/* Quick Presets */}
      <Card className="border-slate-200/60 shadow-card"
      >
        <CardHeader className="pb-3"
        >
          <CardTitle className="text-sm flex items-center gap-2 font-semibold"
          >
            <div className="h-7 w-7 rounded-lg bg-primary/10 flex items-center justify-center"
            >
              <Zap className="h-3.5 w-3.5 text-primary" />
            </div>
            电磁环境快速预设
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3"
        >
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3"
          >
            <Button
              size="sm"
              variant="outline"
              disabled={!running}
              onClick={() => doAction(async () => {
                await ctrl.setPathLossExponent(2.0);
                await ctrl.setFrequency(590);
                await ctrl.setChannelWidth(20);
              }, '自由空间 / UHF 预设')}
              className="h-10 gap-1.5"
            >
              自由空间 / UHF
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!running}
              onClick={() => doAction(async () => {
                await ctrl.setPathLossExponent(3.5);
                await ctrl.setFrequency(2400);
                await ctrl.setChannelWidth(20);
              }, '城市 / 2.4GHz 预设')}
              className="h-10 gap-1.5"
            >
              城市 / 2.4GHz
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!running}
              onClick={() => doAction(async () => {
                await ctrl.setPathLossExponent(2.0);
                await ctrl.setFrequency(5200);
                await ctrl.setChannelWidth(40);
              }, '开阔地 / 5GHz 预设')}
              className="h-10 gap-1.5"
            >
              开阔地 / 5GHz
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!running}
              onClick={() => doAction(async () => {
                await ctrl.setPathLossExponent(4.0);
                await ctrl.setFrequency(590);
                await ctrl.setChannelWidth(10);
              }, '高密度城市 / UHF 预设')}
              className="h-10 gap-1.5"
            >
              高密度城市
            </Button>
          </div>
          <p className="text-xs text-muted-foreground"
          >
            快速预设同时调整路径损耗指数、频率和信道宽度。通信距离还受节点功率和接收灵敏度影响。
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
