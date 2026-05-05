import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Slider } from '@/components/ui/slider';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { useDynamicControl } from '@/hooks/useDynamicControl';
import type { NodeStatus, SimulationStatus, SimConfig, TelemetryEnv } from '@/types/config';
import {
  Zap, MapPin, Radio, Activity, Settings2,
  Send, CheckCircle, AlertCircle
} from 'lucide-react';

interface DynamicControlProps {
  status: SimulationStatus;
  nodes: NodeStatus[];
  config: SimConfig;
  env: TelemetryEnv | null;
}

export function DynamicControl({ status, nodes, config, env }: DynamicControlProps) {
  const ctrl = useDynamicControl();
  const [selectedNode, setSelectedNode] = useState(0);
  const [posX, setPosX] = useState('');
  const [posY, setPosY] = useState('');
  const [txPower, setTxPower] = useState([config.txPowerStart]);
  const [rxSens, setRxSens] = useState([config.rxSensitivity]);
  const [pathLossExp, setPathLossExp] = useState([config.pathLossExponent]);
  const [frequency, setFrequency] = useState([config.frequencyMhz]);
  const [channelWidth, setChannelWidth] = useState([config.channelWidthMhz]);
  const [rangeTarget, setRangeTarget] = useState([config.rangeTargetM]);

  // 当外部配置变化时（如加载新预设），同步滑块值
  useEffect(() => {
    setTxPower([config.txPowerStart]);
    setRxSens([config.rxSensitivity]);
    setPathLossExp([config.pathLossExponent]);
    setFrequency([config.frequencyMhz]);
    setChannelWidth([config.channelWidthMhz]);
    setRangeTarget([config.rangeTargetM]);
  }, [config]);

  // 当切换节点时，从 nodes prop 同步当前位置到输入框
  useEffect(() => {
    const node = nodes.find(n => n.id === selectedNode);
    if (node) {
      setPosX(node.x.toFixed(1));
      setPosY(node.y.toFixed(1));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedNode]);

  // 当遥测帧中的动态参数变化时（如通过其他客户端或 API 修改），同步滑块值与位置输入框
  useEffect(() => {
    if (!env) return;
    if (isDirty()) return; // 用户正在交互，暂停同步防止值被重置
    if (env.txPower[selectedNode] !== undefined) {
      setTxPower([env.txPower[selectedNode]]);
    }
    if (env.rxSensitivity[selectedNode] !== undefined) {
      setRxSens([env.rxSensitivity[selectedNode]]);
    }
    setPathLossExp([env.pathLossExponent]);
    setFrequency([env.frequencyMhz]);
    setChannelWidth([env.channelWidthMhz]);
    setRangeTarget([env.rangeTargetM]);
    if (env.positions?.[selectedNode]) {
      setPosX(env.positions[selectedNode].x.toFixed(1));
      setPosY(env.positions[selectedNode].y.toFixed(1));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [env, selectedNode]);

  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);

  // 脏标志：用户手动修改 Slider/输入框后 3 秒内，暂停从 WebSocket env 同步，
  // 防止遥测帧把正在拖拽的值重置回去。
  const [dirtyUntil, setDirtyUntil] = useState(0);
  const isDirty = () => Date.now() < dirtyUntil;
  const markDirty = () => setDirtyUntil(Date.now() + 3000);

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
    <div className="space-y-4">
      {!running && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-800 text-sm flex items-center gap-2">
          <AlertCircle className="h-4 w-4" />
          仿真未运行，动态控制功能不可用。请先启动仿真。
        </div>
      )}

      {result && (
        <div className={`rounded-lg border p-3 text-sm flex items-center gap-2 ${
          result.ok ? 'border-green-200 bg-green-50 text-green-800' : 'border-red-200 bg-red-50 text-red-800'
        }`}>
          {result.ok ? <CheckCircle className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
          {result.msg}
        </div>
      )}

      {/* Node Selector */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Settings2 className="h-4 w-4" />
            节点选择
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-2">
            {nodes.map(n => (
              <button
                key={n.id}
                onClick={() => setSelectedNode(n.id)}
                className={`px-3 py-1.5 rounded-md text-xs font-mono border transition-colors ${
                  selectedNode === n.id
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'bg-background border-border hover:bg-accent'
                }`}
              >
                节点 {n.id}
                <span className="ml-1 opacity-70">({n.x.toFixed(0)}, {n.y.toFixed(0)})</span>
              </button>
            ))}
            {nodes.length === 0 && (
              <span className="text-xs text-muted-foreground">暂无节点数据</span>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Per-Node Position */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <MapPin className="h-4 w-4" />
              节点位置跃迁
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label className="text-xs">X (米)</Label>
                <Input
                  type="number"
                  value={posX}
                  onChange={e => { setPosX(e.target.value); markDirty(); }}
                  placeholder="0"
                  disabled={!running}
                  className="h-8 text-sm"
                />
              </div>
              <div>
                <Label className="text-xs">Y (米)</Label>
                <Input
                  type="number"
                  value={posY}
                  onChange={e => { setPosY(e.target.value); markDirty(); }}
                  placeholder="0"
                  disabled={!running}
                  className="h-8 text-sm"
                />
              </div>
            </div>
            <Button
              size="sm"
              className="w-full"
              disabled={!running || posX === '' || posY === ''}
              onClick={() => doAction(
                () => ctrl.setNodePosition(selectedNode, parseFloat(posX), parseFloat(posY)),
                `节点 ${selectedNode} 位置设置`
              )}
            >
              <Send className="h-3.5 w-3.5 mr-1.5" />
              应用位置
            </Button>
          </CardContent>
        </Card>

        {/* Per-Node Tx Power */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Zap className="h-4 w-4" />
              发射功率
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">0 dBm</span>
              <Badge variant="outline" className="font-mono">{txPower[0]} dBm</Badge>
              <span className="text-xs text-muted-foreground">40 dBm</span>
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
              className="w-full"
              disabled={!running}
              onClick={() => doAction(
                () => ctrl.setTxPower(selectedNode, txPower[0]),
                `节点 ${selectedNode} 功率设置`
              )}
            >
              <Send className="h-3.5 w-3.5 mr-1.5" />
              应用功率
            </Button>
          </CardContent>
        </Card>

        {/* Per-Node Rx Sensitivity */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Activity className="h-4 w-4" />
              接收灵敏度
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">-110 dBm</span>
              <Badge variant="outline" className="font-mono">{rxSens[0]} dBm</Badge>
              <span className="text-xs text-muted-foreground">-60 dBm</span>
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
              className="w-full"
              disabled={!running}
              onClick={() => doAction(
                () => ctrl.setRxSensitivity(selectedNode, rxSens[0]),
                `节点 ${selectedNode} 灵敏度设置`
              )}
            >
              <Send className="h-3.5 w-3.5 mr-1.5" />
              应用灵敏度
            </Button>
          </CardContent>
        </Card>

        {/* Global Path Loss */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Radio className="h-4 w-4" />
              路径损耗指数
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">1.0 (自由空间)</span>
              <Badge variant="outline" className="font-mono">{pathLossExp[0].toFixed(1)}</Badge>
              <span className="text-xs text-muted-foreground">6.0 (高密度城市)</span>
            </div>
            <Slider
              value={pathLossExp}
              onValueChange={v => { setPathLossExp(v); markDirty(); }}
              min={1.0}
              max={6.0}
              step={0.1}
              disabled={!running}
            />
            <Button
              size="sm"
              className="w-full"
              disabled={!running}
              onClick={() => doAction(
                () => ctrl.setPathLossExponent(pathLossExp[0]),
                '路径损耗指数设置'
              )}
            >
              <Send className="h-3.5 w-3.5 mr-1.5" />
              应用路径损耗
            </Button>
          </CardContent>
        </Card>

        {/* Global Frequency */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Radio className="h-4 w-4" />
              中心频率
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">300 MHz</span>
              <Badge variant="outline" className="font-mono">{frequency[0]} MHz</Badge>
              <span className="text-xs text-muted-foreground">5800 MHz</span>
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
              className="w-full"
              disabled={!running}
              onClick={() => doAction(
                () => ctrl.setFrequency(frequency[0]),
                '频率设置'
              )}
            >
              <Send className="h-3.5 w-3.5 mr-1.5" />
              应用频率
            </Button>
          </CardContent>
        </Card>

        {/* Global Channel Width */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Radio className="h-4 w-4" />
              信道宽度
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">5 MHz</span>
              <Badge variant="outline" className="font-mono">{channelWidth[0]} MHz</Badge>
              <span className="text-xs text-muted-foreground">80 MHz</span>
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
              className="w-full"
              disabled={!running}
              onClick={() => doAction(
                () => ctrl.setChannelWidth(channelWidth[0]),
                '信道宽度设置'
              )}
            >
              <Send className="h-3.5 w-3.5 mr-1.5" />
              应用信道宽度
            </Button>
          </CardContent>
        </Card>

        {/* Global Range Target */}
        <Card className="lg:col-span-2">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2">
              <Radio className="h-4 w-4" />
              最大通信距离 (Range 模型)
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">100 m</span>
              <Badge variant="outline" className="font-mono">{rangeTarget[0]} m</Badge>
              <span className="text-xs text-muted-foreground">10000 m</span>
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
              className="w-full"
              disabled={!running}
              onClick={() => doAction(
                () => ctrl.setRangeTarget(rangeTarget[0]),
                '最大通信距离设置'
              )}
            >
              <Send className="h-3.5 w-3.5 mr-1.5" />
              应用通信距离
            </Button>
          </CardContent>
        </Card>
      </div>

      <Separator />

      {/* Quick Presets */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Zap className="h-4 w-4" />
            电磁环境快速预设
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={!running}
              onClick={() => doAction(async () => {
                await ctrl.setPathLossExponent(2.0);
                await ctrl.setFrequency(590);
                await ctrl.setChannelWidth(20);
              }, '自由空间 / UHF 预设')}
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
            >
              高密度城市
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            快速预设同时调整路径损耗指数、频率和信道宽度。通信距离还受节点功率和接收灵敏度影响。
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
