import { useState, useEffect, useCallback, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { NodeSpec } from '@/types/config';
import {
  Plus, Trash2, Server, Globe, Wifi,
  Loader2, RefreshCw, Network, Pencil, Save,
} from 'lucide-react';

interface RemoteHost {
  ip: string;
  ssh_user: string;
  capacity: number;
}

interface NodeManagerProps {
  onNodeSpecsChange?: (specs: NodeSpec[] | undefined) => void;
}

export function NodeManager({ onNodeSpecsChange }: NodeManagerProps) {
  // ---- remote host management ----
  const [remoteHosts, setRemoteHosts] = useState<RemoteHost[]>([]);
  const [loadingHosts, setLoadingHosts] = useState(false);

  const [newHostIp, setNewHostIp] = useState('');
  const [newHostUser, setNewHostUser] = useState('root');
  const [newHostKey, setNewHostKey] = useState('');
  const [newHostCapacity, setNewHostCapacity] = useState(4);
  const [registering, setRegistering] = useState(false);
  const [editingHost, setEditingHost] = useState<string | null>(null);
  const [editHostUser, setEditHostUser] = useState('');
  const [editHostKey, setEditHostKey] = useState('');
  const [editHostCapacity, setEditHostCapacity] = useState(4);

  // ---- node configuration ----
  const [nodeSpecs, setNodeSpecs] = useState<NodeSpec[]>([]);
  const [saving, setSaving] = useState(false);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load node specs from backend on mount
  const fetchNodeSpecs = useCallback(async () => {
    try {
      const res = await fetch('/api/nodes/specs');
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0) {
          setNodeSpecs(data);
        } else {
          // Default fallback: 2 local nodes
          setNodeSpecs([
            { id: 0, ip: '192.168.100.10', role: 'server', host: 'local' },
            { id: 1, ip: '192.168.100.11', role: 'client', host: 'local' },
          ]);
        }
      }
    } catch {
      // ignore
    }
  }, []);

  // Save node specs to backend with debounce
  const saveNodeSpecs = useCallback(async (specs: NodeSpec[]) => {
    setSaving(true);
    try {
      await fetch('/api/nodes/specs', {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ specs }),
      });
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  }, []);

  // Debounced save: wait 500ms after last change
  const debouncedSave = useCallback((specs: NodeSpec[]) => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => saveNodeSpecs(specs), 500);
  }, [saveNodeSpecs]);

  const fetchHosts = useCallback(async () => {
    setLoadingHosts(true);
    try {
      const res = await fetch('/api/hosts');
      if (res.ok) {
        const data = await res.json();
        setRemoteHosts(Array.isArray(data) ? data : []);
      }
    } catch {
      // ignore
    } finally {
      setLoadingHosts(false);
    }
  }, []);

  useEffect(() => { fetchHosts(); fetchNodeSpecs(); }, [fetchHosts, fetchNodeSpecs]);

  const registerHost = async () => {
    if (!newHostIp.trim()) return;
    setRegistering(true);
    try {
      const body: Record<string, unknown> = {
        ip: newHostIp.trim(),
        ssh_user: newHostUser,
        capacity: newHostCapacity,
      };
      if (newHostKey.trim()) body.ssh_key = newHostKey.trim();
      const res = await fetch('/api/hosts/register', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        await fetchHosts();
        setNewHostIp('');
        setNewHostUser('root');
        setNewHostKey('');
        setNewHostCapacity(4);
      }
    } catch {
      // ignore
    } finally {
      setRegistering(false);
    }
  };

  const unregisterHost = async (ip: string) => {
    try {
      await fetch(`/api/hosts/${ip}`, { method: 'DELETE' });
      await fetchHosts();
    } catch {
      // ignore
    }
  };

  const startEditHost = (host: RemoteHost) => {
    setEditingHost(host.ip);
    setEditHostUser(host.ssh_user);
    setEditHostKey('');
    setEditHostCapacity(host.capacity);
  };

  const saveEditHost = async () => {
    if (!editingHost) return;
    try {
      const body: Record<string, unknown> = {
        ip: editingHost,
        ssh_user: editHostUser,
        capacity: editHostCapacity,
      };
      if (editHostKey.trim()) body.ssh_key = editHostKey.trim();
      const res = await fetch(`/api/hosts/${editingHost}`, {
        method: 'PUT',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        await fetchHosts();
        setEditingHost(null);
      }
    } catch {
      // ignore
    }
  };

  const cancelEditHost = () => {
    setEditingHost(null);
  };

  // ---- node spec management ----
  const addNode = () => {
    const maxId = nodeSpecs.reduce((max, n) => Math.max(max, n.id), -1);
    const newId = maxId + 1;
    const newIp = `192.168.100.${10 + newId}`;
    const updated = [...nodeSpecs, {
      id: newId,
      ip: newIp,
      role: 'client' as const,
      host: 'local' as const,
    }];
    setNodeSpecs(updated);
    debouncedSave(updated);
  };

  const removeNode = (id: number) => {
    const updated = nodeSpecs.filter(n => n.id !== id);
    setNodeSpecs(updated);
    debouncedSave(updated);
  };

  const updateNode = (id: number, field: keyof NodeSpec, value: string) => {
    const updated = nodeSpecs.map(n =>
      n.id === id ? { ...n, [field]: value } : n
    );
    setNodeSpecs(updated);
    debouncedSave(updated);
  };

  // generate updated NodeSpec list whenever specs change
  const hasRemote = nodeSpecs.some(n => n.host !== 'local');
  useEffect(() => {
    if (onNodeSpecsChange) {
      onNodeSpecsChange(hasRemote ? nodeSpecs : undefined);
    }
  }, [nodeSpecs, hasRemote, onNodeSpecsChange]);

  // Clean up debounce timer on unmount
  useEffect(() => {
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, []);

  return (
    <div className="h-full overflow-auto p-4 space-y-5 max-w-6xl mx-auto animate-fade-in">
      {/* ---- Remote Hosts ---- */}
      <Card>
        <CardHeader className="pb-3 flex flex-row items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Globe className="h-4 w-4 text-primary" />
            远端主机管理
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="text-xs">
              {remoteHosts.length} 台
            </Badge>
            <Button size="sm" variant="ghost" onClick={fetchHosts} disabled={loadingHosts} className="h-7 w-7 p-0">
              <RefreshCw className={cn('h-3.5 w-3.5', loadingHosts && 'animate-spin')} />
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* Add host form */}
          <div className="flex items-end gap-2 flex-wrap">
            <div className="flex-1 min-w-[140px]">
              <Label className="text-xs text-muted-foreground">IP 地址</Label>
              <Input
                value={newHostIp}
                onChange={e => setNewHostIp(e.target.value)}
                placeholder="192.168.1.100"
                className="h-9 text-sm"
              />
            </div>
            <div className="w-[100px]">
              <Label className="text-xs text-muted-foreground">SSH 用户</Label>
              <Input
                value={newHostUser}
                onChange={e => setNewHostUser(e.target.value)}
                placeholder="root"
                className="h-9 text-sm"
              />
            </div>
            <div className="w-[160px]">
              <Label className="text-xs text-muted-foreground">SSH 密钥路径</Label>
              <Input
                value={newHostKey}
                onChange={e => setNewHostKey(e.target.value)}
                placeholder="/path/to/key"
                className="h-9 text-sm"
              />
            </div>
            <div className="w-[80px]">
              <Label className="text-xs text-muted-foreground">容量</Label>
              <Input
                type="number"
                min={1}
                max={64}
                value={newHostCapacity}
                onChange={e => setNewHostCapacity(Number(e.target.value))}
                className="h-9 text-sm"
              />
            </div>
            <Button onClick={registerHost} disabled={registering || !newHostIp.trim()} className="h-9 gap-1.5">
              {registering ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
              注册
            </Button>
          </div>

          {/* Host list */}
          {remoteHosts.length === 0 ? (
            <div className="text-sm text-muted-foreground text-center py-6 border rounded-lg bg-muted/30">
              <Server className="h-6 w-6 mx-auto mb-2 opacity-30" />
              暂无已注册的远端主机
            </div>
          ) : (
            <div className="space-y-1.5">
              {remoteHosts.map(host => (
                editingHost === host.ip ? (
                  <div key={host.ip} className="flex items-end gap-2 px-3 py-2 rounded-lg border bg-accent/30 text-sm">
                    <div className="min-w-0">
                      <Label className="text-xs text-muted-foreground">SSH 用户</Label>
                      <Input value={editHostUser} onChange={e => setEditHostUser(e.target.value)} className="h-8 text-xs mt-0.5" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <Label className="text-xs text-muted-foreground">SSH 密钥路径</Label>
                      <Input value={editHostKey} onChange={e => setEditHostKey(e.target.value)} placeholder="留空不变" className="h-8 text-xs mt-0.5" />
                    </div>
                    <div className="w-[70px]">
                      <Label className="text-xs text-muted-foreground">容量</Label>
                      <Input type="number" min={1} max={64} value={editHostCapacity} onChange={e => setEditHostCapacity(Number(e.target.value))} className="h-8 text-xs mt-0.5" />
                    </div>
                    <Button size="sm" onClick={saveEditHost} className="h-8 gap-1">保存</Button>
                    <Button size="sm" variant="ghost" onClick={cancelEditHost} className="h-8">取消</Button>
                  </div>
                ) : (
                  <div
                    key={host.ip}
                    className="flex items-center gap-3 px-3 py-2 rounded-lg border bg-card text-sm hover:bg-accent/50 transition-colors"
                  >
                    <Globe className="h-4 w-4 text-primary shrink-0" />
                    <span className="font-mono font-medium">{host.ip}</span>
                    <Badge variant="secondary" className="text-[10px]">{host.ssh_user}</Badge>
                    <Badge variant="outline" className="text-[10px] ml-auto">容量 {host.capacity}</Badge>
                    <Button size="sm" variant="ghost" onClick={() => startEditHost(host)} className="h-7 w-7 p-0">
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => unregisterHost(host.ip)} className="h-7 w-7 p-0 text-destructive hover:text-destructive">
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                )
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ---- Node Configuration ---- */}
      <Card>
        <CardHeader className="pb-3 flex flex-row items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Network className="h-4 w-4 text-primary" />
            节点配置
          </CardTitle>
          <div className="flex items-center gap-2">
            {saving ? (
              <Badge variant="outline" className="text-xs text-muted-foreground gap-1">
                <Loader2 className="h-3 w-3 animate-spin" />
                保存中
              </Badge>
            ) : nodeSpecs.length > 0 && (
              <Badge variant="outline" className="text-xs text-green-600 gap-1">
                <Save className="h-3 w-3" />
                已保存
              </Badge>
            )}
            <Badge variant="secondary" className="text-xs">
              {nodeSpecs.length} 节点
            </Badge>
            <Button size="sm" onClick={addNode} className="h-8 gap-1.5">
              <Plus className="h-3.5 w-3.5" />
              添加节点
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {/* Header */}
          <div className="grid grid-cols-12 gap-2 px-3 py-1.5 text-xs font-medium text-muted-foreground border-b">
            <div className="col-span-1">ID</div>
            <div className="col-span-2">IP 地址</div>
            <div className="col-span-2">角色</div>
            <div className="col-span-3">主机</div>
            <div className="col-span-3">镜像版本</div>
            <div className="col-span-1" />
          </div>

          {nodeSpecs.length === 0 ? (
            <div className="text-sm text-muted-foreground text-center py-8 border rounded-lg bg-muted/30">
              <Wifi className="h-6 w-6 mx-auto mb-2 opacity-30" />
              暂无节点，点击"添加节点"创建
            </div>
          ) : (
            nodeSpecs.map((spec) => (
              <div
                key={spec.id}
                className="grid grid-cols-12 gap-2 items-center px-3 py-2 rounded-lg border bg-card hover:bg-accent/30 transition-colors"
              >
                <div className="col-span-1 font-mono text-sm font-medium">{spec.id}</div>
                <div className="col-span-2">
                  <Input
                    value={spec.ip}
                    onChange={e => updateNode(spec.id, 'ip', e.target.value)}
                    className="h-8 text-xs font-mono"
                  />
                </div>
                <div className="col-span-2">
                  <select
                    value={spec.role}
                    onChange={e => updateNode(spec.id, 'role', e.target.value)}
                    className="h-8 w-full rounded-lg border bg-background px-2 text-xs"
                  >
                    <option value="server">Server</option>
                    <option value="client">Client</option>
                    <option value="gateway">Gateway</option>
                  </select>
                </div>
                <div className="col-span-3">
                  <select
                    value={spec.host}
                    onChange={e => updateNode(spec.id, 'host', e.target.value)}
                    className="h-8 w-full rounded-lg border bg-background px-2 text-xs"
                  >
                    <option value="local">本机 (Local)</option>
                    {remoteHosts.map(h => (
                      <option key={h.ip} value={h.ip}>{h.ip}</option>
                    ))}
                  </select>
                </div>
                <div className="col-span-3">
                  <Input
                    value={spec.image ?? 'manet-node:latest'}
                    onChange={e => updateNode(spec.id, 'image' as keyof NodeSpec, e.target.value)}
                    placeholder="manet-node:latest"
                    className="h-8 text-xs font-mono"
                  />
                </div>
                <div className="col-span-1 flex justify-end">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => removeNode(spec.id)}
                    disabled={nodeSpecs.length <= 1}
                    className="h-8 w-8 p-0 text-destructive hover:text-destructive"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>
            ))
          )}

          {hasRemote && (
            <div className="flex items-center gap-2 mt-2 px-3 py-2 rounded-lg bg-amber-50/80 border border-amber-200/60 text-xs text-amber-800">
              <Wifi className="h-3.5 w-3.5 shrink-0" />
              检测到远端节点，启动仿真时将自动创建对应 VXLAN 隧道
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
