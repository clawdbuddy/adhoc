import { useState, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import {
  Radio, Settings2, Send, CheckCircle, AlertCircle,
  Antenna, Zap, Wifi, Gauge, Signal, Activity, Network,
} from 'lucide-react';

// ---------------------------------------------------------------------
// API constants
// ---------------------------------------------------------------------

const PROTOCOL_HOST = '100.100.100.3';
const PROTOCOL_PORT = 62450;
const API_BASE = 'http://100.100.100.3:8000';

// ---------------------------------------------------------------------
// UDP frame builder (api_54 binary protocol)
// ---------------------------------------------------------------------

interface FrameResult {
  ok: boolean;
  msg: string;
  raw?: string;
}

function buildFrame(commType: 1 | 3, signalId: number, payload: Uint8Array): Uint8Array {
  const infoLen = payload.length;
  const frame = new Uint8Array(7 + infoLen);
  frame[0] = commType; frame[1] = 0; frame[2] = 0;
  frame[3] = (signalId >> 8) & 0xff; frame[4] = signalId & 0xff;
  frame[5] = (infoLen >> 8) & 0xff; frame[6] = infoLen & 0xff;
  frame.set(payload, 7);
  return frame;
}

function toBe2(v: number) { return Uint8Array.from([(v >> 8) & 0xff, v & 0xff]); }
function toBe1(v: number) { return Uint8Array.from([v & 0xff]); }
function toHex(bytes: Uint8Array) { return Array.from(bytes).map(b => b.toString(16).padStart(2, '0')).join(' '); }

function mhzToBcd(mhz: number): Uint8Array {
  const khz = Math.round(mhz * 1000);
  return Uint8Array.from([
    Math.floor(khz / 1000000) & 15,
    Math.floor((khz % 1000000) / 10000) & 0xff,
    Math.floor((khz % 10000) / 100) & 0xff,
    Math.floor(khz % 100) & 0xff,
  ]);
}

async function sendUdp(frame: Uint8Array, host: string, port: number): Promise<FrameResult> {
  try {
    const res = await fetch(`${API_BASE}/api/radio/raw`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ host, port, frame: Array.from(frame) }),
    });
    const data = await res.json();
    if (!res.ok) return { ok: false, msg: data.reason || '发送失败' };
    if (data.reply) return { ok: true, msg: `回复: ${toHex(Uint8Array.from(data.reply))}`, raw: toHex(Uint8Array.from(data.reply)) };
    return { ok: true, msg: '发送成功（无回复）' };
  } catch (e) { return { ok: false, msg: (e as Error).message }; }
}

// ---------------------------------------------------------------------
// Mode / rate tables
// ---------------------------------------------------------------------

const WORK_MODE_MAP: Record<number, string> = { 0: '定频', 1: '跳频', 2: 'FCS', 3: '定-密', 4: '跳-密', 5: 'FCS-密' };
const RATE_MAP: Record<number, string> = {
  0: '自适应', 1: '窄512k', 2: '窄1M', 3: '窄2M', 4: '宽2M', 5: '宽4M', 6: '宽8M', 7: '宽10M',
  8: '宽16M', 9: '窄4M', 10: '2M', 11: '4M', 12: '5M', 13: '8M', 14: '10M', 15: '宽20M', 16: '64k', 17: '512k', 18: '2M',
};
const POWER_MAP: Record<number, string> = { 4: '自适应', 3: '值守', 2: '小功率', 1: '中功率', 0: '大功率' };

// ---------------------------------------------------------------------
// Shared UI components
// ---------------------------------------------------------------------

interface StatCardProps {
  label: string;
  value: string;
  sub?: string;
  icon: React.ReactNode;
  iconBg: string;
  tooltip?: string;
}

function StatCard({ label, value, sub, icon, iconBg, tooltip }: StatCardProps) {
  return (
    <div className="bg-card rounded-lg border p-2 shadow-card hover:shadow-card-hover transition-all duration-200 card-lift cursor-default" title={tooltip}>
      <div className="flex items-start justify-between">
        <div className="space-y-0.5">
          <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">{label}</p>
          <span className="text-lg font-bold tracking-tight">{value}</span>
          {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
        </div>
        <div className={cn('h-7 w-7 rounded-lg flex items-center justify-center shrink-0', iconBg)}>{icon}</div>
      </div>
    </div>
  );
}

interface ParamCardProps {
  title: string;
  signalId: number;
  icon: React.ReactNode;
  iconBg: string;
  children: React.ReactNode;
}

function ParamCard({ title, signalId, icon, iconBg, children }: ParamCardProps) {
  return (
    <div className="bg-card rounded-xl border shadow-card">
      <div className="px-4 py-3 border-b flex items-center gap-3">
        <div className={cn('h-8 w-8 rounded-lg flex items-center justify-center shrink-0', iconBg)}>{icon}</div>
        <div className="flex-1">
          <span className="text-sm font-semibold">{title}</span>
          <span className="text-xs text-muted-foreground ml-2 font-mono">0x{signalId.toString(16).toUpperCase().padStart(4, '0')}</span>
        </div>
      </div>
      <div className="p-4 space-y-3">{children}</div>
    </div>
  );
}

function ResultBanner({ result }: { result: FrameResult | null }) {
  if (!result) return null;
  return (
    <div className={cn('rounded-xl border p-3.5 text-sm flex items-center gap-2.5 animate-scale-in',
      result.ok ? 'border-green-200 bg-green-50/80 text-green-800' : 'border-red-200 bg-red-50/80 text-red-800')}>
      {result.ok ? <CheckCircle className="h-4 w-4 shrink-0" /> : <AlertCircle className="h-4 w-4 shrink-0" />}
      <span className="font-mono text-xs break-all">{result.msg}</span>
    </div>
  );
}

function SectionHeader({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <div className="h-6 w-6 rounded-md bg-primary/10 flex items-center justify-center text-primary">{icon}</div>
      <span className="text-sm font-semibold">{label}</span>
    </div>
  );
}

// ---------------------------------------------------------------------
// Static Params Tab
// ---------------------------------------------------------------------

function StaticParamsTab({ host, port }: { host: string; port: number }) {
  const [netScale, setNetScale] = useState('16');
  const [workMode, setWorkMode] = useState(0);
  const [macAddr, setMacAddr] = useState('0');
  const [freqMhz, setFreqMhz] = useState('505.54');
  const [hopTable, setHopTable] = useState('0');
  const [result, setResult] = useState<FrameResult | null>(null);

  const sendFrame = useCallback(async (_desc: string, signalId: number, payload: Uint8Array) => {
    const r = await sendUdp(buildFrame(1, signalId, payload), host, port);
    setResult(r); return r;
  }, [host, port]);

  return (
    <div className="space-y-5">
      {/* Info Banner */}
      <div className="rounded-xl border border-slate-200/60 bg-slate-50/60 p-3 text-slate-700 text-xs flex items-start gap-3">
        <Antenna className="h-4 w-4 shrink-0 mt-0.5 text-primary" />
        <span>静态参数由 <strong>波形软件</strong> 管理，设置后需重启生效。信令通过 UDP 二进制帧发送到目标电台。</span>
      </div>

      {/* Stat Summary Row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard label="网络规模" value={netScale} sub="2-128" icon={<Wifi className="h-4 w-4 text-primary" />} iconBg="bg-primary/10" />
        <StatCard label="工作模式" value={WORK_MODE_MAP[workMode] ?? '—'} sub="当前模式" icon={<Radio className="h-4 w-4 text-cyan-500" />} iconBg="bg-cyan-500/10" />
        <StatCard label="MAC地址" value={macAddr} sub="0-127" icon={<Settings2 className="h-4 w-4 text-violet-500" />} iconBg="bg-violet-500/10" />
        <StatCard label="定频频率" value={`${freqMhz}MHz`} sub="480~1710" icon={<Signal className="h-4 w-4 text-rose-500" />} iconBg="bg-rose-500/10" />
        <StatCard label="跳频表号" value={hopTable} sub="0-19" icon={<Zap className="h-4 w-4 text-amber-500" />} iconBg="bg-amber-500/10" />
      </div>

      {/* Param Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ParamCard title="网络规模" signalId={0x0001} icon={<Wifi className="h-4 w-4 text-primary" />} iconBg="bg-primary/10">
          <div><Label className="text-xs text-muted-foreground">节点数 (2-128)</Label><Input type="number" value={netScale} onChange={e => setNetScale(e.target.value)} min={2} max={128} className="h-9 mt-1.5 font-mono" /></div>
          <Button size="sm" className="w-full gap-1.5" onClick={async () => { const v = parseInt(netScale); if (v < 2 || v > 128) { setResult({ ok: false, msg: '范围: 2-128' }); return; } await sendFrame('网络规模', 0x0001, toBe2(v)); }}><Send className="h-3.5 w-3.5" /> 设置</Button>
        </ParamCard>

        <ParamCard title="工作模式" signalId={0x0002} icon={<Radio className="h-4 w-4 text-cyan-500" />} iconBg="bg-cyan-500/10">
          <div className="grid grid-cols-3 gap-2">{Object.entries(WORK_MODE_MAP).map(([k, v]) => (<Button key={k} size="sm" variant={workMode === parseInt(k) ? 'default' : 'outline'} onClick={() => setWorkMode(parseInt(k))}>{v}</Button>))}</div>
          <Button size="sm" className="w-full gap-1.5" onClick={() => sendFrame('工作模式', 0x0002, toBe1(workMode))}><Send className="h-3.5 w-3.5" /> 设置</Button>
        </ParamCard>

        <ParamCard title="MAC地址" signalId={0x0003} icon={<Settings2 className="h-4 w-4 text-violet-500" />} iconBg="bg-violet-500/10">
          <div><Label className="text-xs text-muted-foreground">MAC (0-127)</Label><Input type="number" value={macAddr} onChange={e => setMacAddr(e.target.value)} min={0} max={127} className="h-9 mt-1.5 font-mono" /></div>
          <Button size="sm" className="w-full gap-1.5" onClick={async () => { const v = parseInt(macAddr); if (v < 0 || v > 127) { setResult({ ok: false, msg: '范围: 0-127' }); return; } await sendFrame('MAC地址', 0x0003, toBe2(v)); }}><Send className="h-3.5 w-3.5" /> 设置</Button>
        </ParamCard>

        <ParamCard title="定频频率" signalId={0x0004} icon={<Signal className="h-4 w-4 text-rose-500" />} iconBg="bg-rose-500/10">
          <div><Label className="text-xs text-muted-foreground">频率 MHz (480~650 / 1410~1710)</Label><Input type="number" value={freqMhz} onChange={e => setFreqMhz(e.target.value)} step={0.01} className="h-9 mt-1.5 font-mono" /></div>
          <Button size="sm" className="w-full gap-1.5" onClick={() => { const v = parseFloat(freqMhz); if (v < 480 || v > 1710) { setResult({ ok: false, msg: '频率范围: 480~1710 MHz' }); return; } sendFrame('定频频率', 0x0004, mhzToBcd(v)); }}><Send className="h-3.5 w-3.5" /> 设置</Button>
        </ParamCard>

        <ParamCard title="跳频表号" signalId={0x0005} icon={<Zap className="h-4 w-4 text-amber-500" />} iconBg="bg-amber-500/10">
          <div><Label className="text-xs text-muted-foreground">表号 (0-19)</Label><Input type="number" value={hopTable} onChange={e => setHopTable(e.target.value)} min={0} max={19} className="h-9 mt-1.5 font-mono" /></div>
          <Button size="sm" className="w-full gap-1.5" onClick={async () => { const v = parseInt(hopTable); if (v < 0 || v > 19) { setResult({ ok: false, msg: '范围: 0-19' }); return; } await sendFrame('跳频表号', 0x0005, toBe1(v)); }}><Send className="h-3.5 w-3.5" /> 设置</Button>
        </ParamCard>
      </div>

      {/* Query Row */}
      <div>
        <SectionHeader icon={<Activity className="h-4 w-4" />} label="静态参数查询" />
        <div className="flex flex-wrap gap-2">
          {[{ label: '网络规模', id: 0x0041 }, { label: '工作模式', id: 0x0042 }, { label: 'MAC地址', id: 0x0043 }, { label: '定频频率', id: 0x0044 }, { label: '跳频表号', id: 0x0045 }].map(({ label, id }) => (
            <Button key={id} size="sm" variant="outline" className="gap-1.5" onClick={() => sendFrame(label, id, new Uint8Array())}><Send className="h-3.5 w-3.5" /> 查询{label}</Button>
          ))}
        </div>
      </div>

      <ResultBanner result={result} />
    </div>
  );
}

// ---------------------------------------------------------------------
// Dynamic Params Tab
// ---------------------------------------------------------------------

function DynamicParamsTab({ host, port }: { host: string; port: number }) {
  const [rate, setRate] = useState(0);
  const [power, setPower] = useState(0);
  const [result, setResult] = useState<FrameResult | null>(null);

  const sendFrame = useCallback(async (_desc: string, signalId: number, payload: Uint8Array) => {
    const r = await sendUdp(buildFrame(3, signalId, payload), host, port);
    setResult(r); return r;
  }, [host, port]);

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-green-200/60 bg-green-50/60 p-3 text-green-700 text-xs flex items-start gap-3">
        <Zap className="h-4 w-4 shrink-0 mt-0.5 text-green-500" />
        <span>动态参数由 <strong>测控链波形</strong> 管理，设置后立即生效。</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ParamCard title="传输速率" signalId={0x0101} icon={<Gauge className="h-4 w-4 text-amber-500" />} iconBg="bg-amber-500/10">
          <div className="grid grid-cols-3 lg:grid-cols-6 gap-1.5">{Object.entries(RATE_MAP).map(([k, v]) => (<Button key={k} size="sm" variant={rate === parseInt(k) ? 'default' : 'outline'} onClick={() => setRate(parseInt(k))} className="text-xs h-7">{v}</Button>))}</div>
          <Button size="sm" className="w-full gap-1.5" onClick={() => sendFrame('传输速率', 0x0101, toBe1(rate))}><Send className="h-3.5 w-3.5" /> 设置</Button>
        </ParamCard>

        <ParamCard title="发射功率" signalId={0x0102} icon={<Zap className="h-4 w-4 text-amber-500" />} iconBg="bg-amber-500/10">
          <div className="grid grid-cols-5 gap-1">{Object.entries(POWER_MAP).map(([k, v]) => (<Button key={k} size="sm" variant={power === parseInt(k) ? 'default' : 'outline'} onClick={() => setPower(parseInt(k))} className="text-xs h-7">{v}</Button>))}</div>
          <Button size="sm" className="w-full gap-1.5" onClick={() => sendFrame('发射功率', 0x0102, toBe1(power))}><Send className="h-3.5 w-3.5" /> 设置</Button>
        </ParamCard>
      </div>

      <div>
        <SectionHeader icon={<Activity className="h-4 w-4" />} label="动态参数查询" />
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" className="gap-1.5" onClick={() => sendFrame('传输速率', 0x0141, new Uint8Array())}><Send className="h-3.5 w-3.5" /> 查询传输速率</Button>
          <Button size="sm" variant="outline" className="gap-1.5" onClick={() => sendFrame('发射功率', 0x0142, new Uint8Array())}><Send className="h-3.5 w-3.5" /> 查询发射功率</Button>
        </div>
      </div>

      <ResultBanner result={result} />
    </div>
  );
}

// ---------------------------------------------------------------------
// Status Query Tab
// ---------------------------------------------------------------------

function StatusTab({ host, port }: { host: string; port: number }) {
  const [result, setResult] = useState<FrameResult | null>(null);

  const sendFrame = useCallback(async (_desc: string, signalId: number, payload: Uint8Array, commType: 1 | 3 = 1) => {
    const r = await sendUdp(buildFrame(commType, signalId, payload), host, port);
    setResult(r); return r;
  }, [host, port]);

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { icon: <Settings2 className="h-5 w-5" />, label: '版本信息', desc: '查询固件版本', id: 0x0203, iconBg: 'bg-primary/10 text-primary' },
          { icon: <Antenna className="h-5 w-5" />, label: '自组网拓扑', desc: '5秒周期主动上报', id: 0x0310, iconBg: 'bg-cyan-500/10 text-cyan-500' },
          { icon: <Signal className="h-5 w-5" />, label: '主动上报订阅', desc: '订阅状态主动推送', id: 0x02AF, iconBg: 'bg-rose-500/10 text-rose-500' },
        ].map(({ icon, label, desc, id, iconBg }) => (
          <div key={id} className="bg-card rounded-xl border shadow-card hover:shadow-card-hover transition-all duration-200 p-4">
            <div className="flex items-start gap-3">
              <div className={cn('h-10 w-10 rounded-xl flex items-center justify-center shrink-0', iconBg)}>{icon}</div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold">{label}</p>
                <p className="text-xs text-muted-foreground mt-0.5">{desc}</p>
                <p className="text-xs font-mono text-muted-foreground mt-1">0x{id.toString(16).toUpperCase()}</p>
              </div>
            </div>
            <Button size="sm" variant="outline" className="w-full mt-3 gap-1.5"
              onClick={() => sendFrame(label, id, id === 0x02AF ? new Uint8Array([1, 1, 1, 0, 0, 0, 0]) : new Uint8Array())}>
              <Send className="h-3.5 w-3.5" /> 查询
            </Button>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-amber-200/60 bg-amber-50/80 p-3 text-amber-800 text-xs flex items-start gap-3">
        <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-amber-500" />
        <span><strong>主动上报 (0x02AF)</strong>：基带波形加载后按 <strong>5 秒周期</strong>主动上报。BYTE[0]=1 启用，BYTE[1]=1 ZZW 同步，BYTE[2]=1 CKL 同步。拓扑 (0x0310) 每条链路 5 字节：源MAC + 目的MAC + 链路质量。</span>
      </div>

      <ResultBanner result={result} />
    </div>
  );
}

// ---------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------

export function RadioDeviceControl() {
  const [host, setHost] = useState(PROTOCOL_HOST);
  const [port, setPort] = useState(PROTOCOL_PORT.toString());

  return (
    <div className="space-y-4 max-w-6xl mx-auto">
      {/* Page Header */}
      <div className="flex items-center gap-3">
        <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-primary to-cyan-400 flex items-center justify-center shrink-0 shadow-glow">
          <Radio className="h-5 w-5 text-white" />
        </div>
        <div>
          <h1 className="text-base font-bold tracking-tight">电台设备控制</h1>
        </div>
      </div>

      {/* Connection Config Row */}
      <div className="bg-card rounded-xl border shadow-card">
        <div className="px-4 py-3 border-b flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary"><Network className="h-4 w-4" /></div>
          <span className="text-sm font-semibold">目标连接</span>
        </div>
        <div className="p-4">
          <div className="flex gap-4 items-end flex-wrap">
            <div><Label className="text-xs text-muted-foreground">目标 IP</Label><Input value={host} onChange={e => setHost(e.target.value)} className="h-9 mt-1.5 font-mono w-44" /></div>
            <div><Label className="text-xs text-muted-foreground">端口</Label><Input value={port} onChange={e => setPort(e.target.value)} type="number" className="h-9 mt-1.5 font-mono w-28" /></div>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <Tabs defaultValue="static" className="w-full">
        <TabsList className="grid w-fit grid-cols-3">
          <TabsTrigger value="static"><Wifi className="h-3.5 w-3.5 mr-1.5" />静态参数</TabsTrigger>
          <TabsTrigger value="dynamic"><Zap className="h-3.5 w-3.5 mr-1.5" />动态参数</TabsTrigger>
          <TabsTrigger value="status"><Activity className="h-3.5 w-3.5 mr-1.5" />状态查询</TabsTrigger>
        </TabsList>

        <TabsContent value="static" className="mt-5">
          <StaticParamsTab host={host} port={parseInt(port)} />
        </TabsContent>
        <TabsContent value="dynamic" className="mt-5">
          <DynamicParamsTab host={host} port={parseInt(port)} />
        </TabsContent>
        <TabsContent value="status" className="mt-5">
          <StatusTab host={host} port={parseInt(port)} />
        </TabsContent>
      </Tabs>
    </div>
  );
}