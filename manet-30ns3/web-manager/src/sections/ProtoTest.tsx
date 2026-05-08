import { useState, useRef, useCallback, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import {
  Wifi, Send, Trash2, Radio, Settings, RefreshCw,
  ChevronDown, ChevronRight, Clock, Plug, Unplug,
} from 'lucide-react';

interface Message {
  id: number;
  direction: 'sent' | 'received';
  timestamp: string;
  payload: string;
  pretty?: string;
}

const NET_MODE_OPTIONS = [
  { value: 1, label: '自组网' },
  { value: 2, label: 'LTE' },
  { value: 3, label: '天通' },
  { value: 4, label: '173RAP' },
  { value: 5, label: '173PRN' },
  { value: 6, label: '北斗' },
  { value: 7, label: 'UV' },
  { value: 12, label: '173FCS' },
];

const POWER_OPTIONS = [
  { value: 0, label: '值守' },
  { value: 1, label: '低' },
  { value: 2, label: '中' },
  { value: 3, label: '高' },
];

const RATE_OPTIONS = [
  { value: 1, label: '9.6kb' },
  { value: 2, label: '19.2kb' },
  { value: 3, label: '38.4kb' },
  { value: 4, label: '62.5kb' },
];

function buildFrame(data: Record<string, unknown>) {
  return JSON.stringify({
    data,
    ident: '',
    mnemonic: 0,
    resWord: '',
    type: 0,
    version: 0,
  });
}

export function ProtoTest() {
  const [wsUrl, setWsUrl] = useState('ws://100.100.100.3:8000/ws/radio');
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [customPayload, setCustomPayload] = useState('');
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    query: true,
    set: true,
    report: false,
    reportCfg: false,
  });

  // 上报配置状态
  const [report5002Enabled, setReport5002Enabled] = useState(1);
  const [report5002Period, setReport5002Period] = useState(2000);
  const [report5006Enabled, setReport5006Enabled] = useState(1);
  const [report5006Period, setReport5006Period] = useState(10000);
  const wsRef = useRef<WebSocket | null>(null);
  const msgIdRef = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  // 参数状态
  const [netMode, setNetMode] = useState(1);
  const [ctrl, setCtrl] = useState(1);
  const [power, setPower] = useState(1);
  const [freqNum, setFreqNum] = useState(1);
  const [frequency, setFrequency] = useState(225);
  const [rate, setRate] = useState(2);
  const [extend, setExtend] = useState('KZ');

  // 从 ns3-controller 获取的真实节点状态（用于上报类命令对接）
  const [ns3Nodes, setNs3Nodes] = useState<Array<{ id: number; ip: string; status: string }>>([]);
  const [ns3Loading, setNs3Loading] = useState(false);

  // 拉取 ns3-controller 节点状态
  const fetchNs3Nodes = useCallback(async () => {
    setNs3Loading(true);
    try {
      const res = await fetch('/api/nodes');
      if (res.ok) {
        const data = await res.json();
        setNs3Nodes(data);
      }
    } catch {
      // ignore
    } finally {
      setNs3Loading(false);
    }
  }, []);

  // 组件挂载时拉取一次
  useEffect(() => {
    fetchNs3Nodes();
    const timer = setInterval(fetchNs3Nodes, 5000);
    return () => clearInterval(timer);
  }, [fetchNs3Nodes]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const addMessage = useCallback((direction: 'sent' | 'received', payload: string) => {
    let pretty = '';
    try {
      pretty = JSON.stringify(JSON.parse(payload), null, 2);
    } catch {
      pretty = payload;
    }
    setMessages(prev => [...prev, {
      id: ++msgIdRef.current,
      direction,
      timestamp: new Date().toLocaleTimeString(),
      payload,
      pretty,
    }]);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    try {
      const ws = new WebSocket(wsUrl);
      ws.onopen = () => {
        setConnected(true);
        addMessage('received', `// 已连接到 ${wsUrl}`);
      };
      ws.onmessage = (ev) => {
        addMessage('received', ev.data);
      };
      ws.onclose = () => {
        setConnected(false);
        addMessage('received', `// 连接已关闭 ${wsUrl}`);
        wsRef.current = null;
      };
      ws.onerror = (e) => {
        setConnected(false);
        addMessage('received', `// 连接错误: ${(e as ErrorEvent).message || 'unknown'}`);
        wsRef.current = null;
      };
      wsRef.current = ws;
    } catch (e) {
      addMessage('received', `// 连接失败: ${(e as Error).message}`);
    }
  }, [wsUrl, addMessage]);

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
  }, []);

  const send = useCallback((payload: string) => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
      addMessage('received', '// 错误: WebSocket 未连接');
      return;
    }
    wsRef.current.send(payload);
    addMessage('sent', payload);
  }, [addMessage]);

  const sendCmd = useCallback((cmdCode: number, extra: Record<string, unknown> = {}) => {
    const payload = buildFrame({ cmdCode, extend, ...extra });
    send(payload);
  }, [extend, send]);

  const clearMessages = useCallback(() => setMessages([]), []);

  const toggleGroup = (key: string) => {
    setExpandedGroups(prev => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div className="h-full flex flex-col overflow-hidden p-3 gap-3">
      {/* 顶部连接栏 */}
      <div className="flex items-center gap-3 shrink-0">
        <div className={cn(
          'h-3 w-3 rounded-full shrink-0',
          connected ? 'bg-green-500 animate-pulse' : 'bg-red-500'
        )} />
        <span className="text-sm font-medium shrink-0">
          {connected ? '已连接' : '未连接'}
        </span>
        <Input
          value={wsUrl}
          onChange={e => setWsUrl(e.target.value)}
          placeholder="ws://host:port"
          className="flex-1 h-8 text-sm"
          disabled={connected}
        />
        <Button
          size="sm"
          onClick={connected ? disconnect : connect}
          variant={connected ? 'destructive' : 'default'}
          className="h-8 gap-1"
        >
          {connected ? <Unplug className="h-3.5 w-3.5" /> : <Plug className="h-3.5 w-3.5" />}
          {connected ? '断开' : '连接'}
        </Button>
      </div>

      {/* 主体 */}
      <div className="flex-1 min-h-0 flex gap-3">
        {/* 左侧面板：命令 */}
        <div className="w-[380px] shrink-0 flex flex-col gap-2 overflow-auto pr-1">
          {/* 公共参数 */}
          <div className="border rounded-lg p-2 bg-card space-y-2">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">公共参数</div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-xs text-muted-foreground">extend</label>
                <Input value={extend} onChange={e => setExtend(e.target.value)} className="h-7 text-xs" />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">netMode</label>
                <select
                  value={netMode}
                  onChange={e => setNetMode(Number(e.target.value))}
                  className="h-7 w-full rounded-md border bg-background px-2 text-xs"
                >
                  {NET_MODE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </div>
            </div>
          </div>

          {/* 查询类 */}
          <div className="border rounded-lg bg-card overflow-hidden">
            <button
              onClick={() => toggleGroup('query')}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-accent/50"
            >
              {expandedGroups.query ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              <Radio className="h-3.5 w-3.5 text-blue-500" />
              查询类
            </button>
            {expandedGroups.query && (
              <div className="px-3 pb-2 space-y-1">
                <CmdBtn label="网络模块开关 (1001)" onClick={() => sendCmd(1001)} />
                <CmdBtn label="入网状态 (1025)" onClick={() => sendCmd(1025, { netMode })} />
                <CmdBtn label="功率 (1071)" onClick={() => sendCmd(1071, { netMode })} />
                <CmdBtn label="频表 (1049)" onClick={() => sendCmd(1049, { netMode })} />
                <CmdBtn label="频率 (7001)" onClick={() => sendCmd(7001)} />
                <CmdBtn label="速率 (7003)" onClick={() => sendCmd(7003)} />
              </div>
            )}
          </div>

          {/* 设置类 */}
          <div className="border rounded-lg bg-card overflow-hidden">
            <button
              onClick={() => toggleGroup('set')}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-accent/50"
            >
              {expandedGroups.set ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              <Settings className="h-3.5 w-3.5 text-amber-500" />
              设置类
            </button>
            {expandedGroups.set && (
              <div className="px-3 pb-2 space-y-2">
                <CmdBtn label={`网络模块开关 (2001) ctrl=${ctrl}`} onClick={() => sendCmd(2001, { netMode, ctrl })} />
                <div className="flex gap-2 items-center">
                  <span className="text-xs text-muted-foreground">ctrl:</span>
                  <select value={ctrl} onChange={e => setCtrl(Number(e.target.value))} className="h-6 rounded border bg-background px-1 text-xs">
                    <option value={0}>关</option>
                    <option value={1}>开</option>
                  </select>
                </div>

                <CmdBtn label={`功率 (2043) power=${power}`} onClick={() => sendCmd(2043, { netMode, power })} />
                <div className="flex gap-2 items-center">
                  <span className="text-xs text-muted-foreground">power:</span>
                  <select value={power} onChange={e => setPower(Number(e.target.value))} className="h-6 rounded border bg-background px-1 text-xs">
                    {POWER_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>

                <CmdBtn label={`频表 (2023) freqNum=${freqNum}`} onClick={() => sendCmd(2023, { netMode, freqNum })} />
                <div className="flex gap-2 items-center">
                  <span className="text-xs text-muted-foreground">freqNum:</span>
                  <Input type="number" min={0} max={20} value={freqNum} onChange={e => setFreqNum(Number(e.target.value))} className="h-6 w-16 text-xs" />
                </div>

                <CmdBtn label={`频率 (8001) freq=${frequency}MHz`} onClick={() => sendCmd(8001, { frequency })} />
                <div className="flex gap-2 items-center">
                  <span className="text-xs text-muted-foreground">frequency:</span>
                  <Input type="number" min={225} max={512} value={frequency} onChange={e => setFrequency(Number(e.target.value))} className="h-6 w-20 text-xs" />
                  <span className="text-xs text-muted-foreground">MHz</span>
                </div>

                <CmdBtn label={`速率 (8003) rate=${rate}`} onClick={() => sendCmd(8003, { rate })} />
                <div className="flex gap-2 items-center">
                  <span className="text-xs text-muted-foreground">rate:</span>
                  <select value={rate} onChange={e => setRate(Number(e.target.value))} className="h-6 rounded border bg-background px-1 text-xs">
                    {RATE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
              </div>
            )}
          </div>

          {/* 上报类 */}
          <div className="border rounded-lg bg-card overflow-hidden">
            <button
              onClick={() => toggleGroup('report')}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-accent/50"
            >
              {expandedGroups.report ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
              <Wifi className="h-3.5 w-3.5 text-green-500" />
              上报类（对接 ns3-controller）
            </button>
            {expandedGroups.report && (
              <div className="px-3 pb-2 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">
                    在线节点: {ns3Nodes.filter(n => n.status === 'online').length}/{ns3Nodes.length}
                  </span>
                  <Button size="sm" variant="ghost" onClick={fetchNs3Nodes} disabled={ns3Loading} className="h-6 gap-1 text-xs">
                    <RefreshCw className={cn('h-3 w-3', ns3Loading && 'animate-spin')} />
                    刷新
                  </Button>
                </div>
                <CmdBtn
                  label={`入网断网提示 (5002) state=${ns3Nodes.some(n => n.status === 'online') ? 1 : 0}`}
                  onClick={() => {
                    const state = ns3Nodes.some(n => n.status === 'online') ? 1 : 0;
                    sendCmd(5002, { netMode, state });
                  }}
                />
                <CmdBtn
                  label={`在线信息上报 (5006) IP数=${ns3Nodes.filter(n => n.status === 'online').length}`}
                  onClick={() => {
                    const onlineIps = ns3Nodes.filter(n => n.status === 'online').map(n => n.ip);
                    sendCmd(5006, { netMode, groupMebsIP: onlineIps.length > 0 ? onlineIps : [] });
                  }}
                />
              </div>
            )}
          </div>

          {/* 上报配置 */}
          <div className="border rounded-lg bg-card overflow-hidden">
            <button
              onClick={() => toggleGroup('reportCfg')}
              className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-accent/50"
            >
            {expandedGroups.reportCfg ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
            <Settings className="h-3.5 w-3.5 text-purple-500" />
            上报配置（开关与周期）
          </button>
          {expandedGroups.reportCfg && (
            <div className="px-3 pb-2 space-y-2">
              {/* 5002 */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-16">5002:</span>
                <select
                  value={report5002Enabled}
                  onChange={e => setReport5002Enabled(Number(e.target.value))}
                  className="h-6 rounded border bg-background px-1 text-xs"
                >
                  <option value={1}>开</option>
                  <option value={0}>关</option>
                </select>
                <Input
                  type="number"
                  min={500}
                  max={300000}
                  step={100}
                  value={report5002Period}
                  onChange={e => setReport5002Period(Number(e.target.value))}
                  className="h-6 w-20 text-xs"
                />
                <span className="text-xs text-muted-foreground">ms</span>
              </div>
              {/* 5006 */}
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground w-16">5006:</span>
                <select
                  value={report5006Enabled}
                  onChange={e => setReport5006Enabled(Number(e.target.value))}
                  className="h-6 rounded border bg-background px-1 text-xs"
                >
                  <option value={1}>开</option>
                  <option value={0}>关</option>
                </select>
                <Input
                  type="number"
                  min={500}
                  max={300000}
                  step={100}
                  value={report5006Period}
                  onChange={e => setReport5006Period(Number(e.target.value))}
                  className="h-6 w-20 text-xs"
                />
                <span className="text-xs text-muted-foreground">ms</span>
              </div>
              <div className="flex gap-2 pt-1">
                <CmdBtn
                  label="查询配置 (9001)"
                  onClick={() => sendCmd(9001)}
                />
                <CmdBtn
                  label="应用配置 (9003)"
                  onClick={() =>
                    sendCmd(9003, {
                      report5002Enabled,
                      report5002Period,
                      report5006Enabled,
                      report5006Period,
                    })
                  }
                />
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 右侧：消息日志 + 自定义发送 */}
        <div className="flex-1 min-w-0 flex flex-col gap-2">
          {/* 自定义发送 */}
          <div className="border rounded-lg p-2 bg-card shrink-0">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">自定义 JSON</div>
            <div className="flex gap-2">
              <textarea
                value={customPayload}
                onChange={e => setCustomPayload(e.target.value)}
                placeholder='{"data":{"cmdCode":1001,"extend":"KZ"},...}'
                className="flex-1 h-16 rounded-md border bg-background px-2 py-1 text-xs font-mono resize-none"
              />
              <Button
                size="sm"
                onClick={() => { send(customPayload); setCustomPayload(''); }}
                disabled={!connected || !customPayload.trim()}
                className="h-16 gap-1"
              >
                <Send className="h-3.5 w-3.5" />
                发送
              </Button>
            </div>
          </div>

          {/* 消息日志 */}
          <div className="flex-1 min-h-0 border rounded-lg bg-card flex flex-col overflow-hidden">
            <div className="flex items-center justify-between px-3 py-2 border-b shrink-0">
              <div className="flex items-center gap-2">
                <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-sm font-medium">消息日志</span>
                <span className="text-xs text-muted-foreground">({messages.length})</span>
              </div>
              <Button size="sm" variant="ghost" onClick={clearMessages} className="h-7 gap-1 text-xs">
                <Trash2 className="h-3 w-3" />
                清空
              </Button>
            </div>
            <div ref={scrollRef} className="flex-1 overflow-auto p-2 space-y-1 font-mono text-xs">
              {messages.length === 0 && (
                <div className="text-muted-foreground text-center py-8">暂无消息，连接后发送命令</div>
              )}
              {messages.map(msg => (
                <div
                  key={msg.id}
                  className={cn(
                    'rounded px-2 py-1 border-l-2',
                    msg.direction === 'sent'
                      ? 'bg-blue-50 border-l-blue-500 dark:bg-blue-950/30'
                      : 'bg-green-50 border-l-green-500 dark:bg-green-950/30'
                  )}
                >
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className={cn(
                      'text-[10px] font-bold px-1 rounded',
                      msg.direction === 'sent' ? 'bg-blue-200 text-blue-800' : 'bg-green-200 text-green-800'
                    )}>
                      {msg.direction === 'sent' ? '→ 发送' : '← 接收'}
                    </span>
                    <span className="text-[10px] text-muted-foreground">{msg.timestamp}</span>
                  </div>
                  <pre className="whitespace-pre-wrap break-all text-[11px] leading-relaxed">{msg.pretty || msg.payload}</pre>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function CmdBtn({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button
      size="sm"
      variant="outline"
      onClick={onClick}
      className="w-full h-7 justify-start text-xs gap-1"
    >
      <Send className="h-3 w-3 shrink-0" />
      {label}
    </Button>
  );
}
