import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Separator } from '@/components/ui/separator';
import type { SimulationStatus, SimConfig } from '@/types/config';
import {
  Play, Square, RotateCw, Terminal, Settings,
  Radio, Wifi, Route, MapPin, FileCode
} from 'lucide-react';

interface ControlPanelProps {
  status: SimulationStatus;
  config: SimConfig;
  onStart: () => void;
  onStop: () => void;
}

export function ControlPanel({ status, config, onStart, onStop }: ControlPanelProps) {
  const elapsedMin = Math.floor(status.elapsed / 60);
  const elapsedSec = status.elapsed % 60;
  const progress = config.simulationTime > 0
    ? Math.min((status.elapsed / config.simulationTime) * 100, 100)
    : 0;

  return (
    <div className="space-y-6">
      {/* Main Control */}
      <Card className="border-2">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Terminal className="h-5 w-5" />
            仿真控制
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Status */}
          <div className="flex items-center gap-3">
            <div className={`h-4 w-4 rounded-full ${status.running ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
            <span className="text-lg font-semibold">
              {status.running ? '运行中' : '已停止'}
            </span>
            {status.running && (
              <Badge variant="outline" className="text-green-600 border-green-600">
                {elapsedMin}:{elapsedSec.toString().padStart(2, '0')} / {Math.floor(config.simulationTime / 60)}:{(config.simulationTime % 60).toString().padStart(2, '0')}
              </Badge>
            )}
          </div>

          {/* Progress */}
          {status.running && (
            <div className="space-y-1">
              <Progress value={progress} className="h-3" />
              <p className="text-xs text-muted-foreground text-right">{progress.toFixed(1)}%</p>
            </div>
          )}

          {/* Buttons */}
          <div className="flex gap-3">
            <Button
              onClick={onStart}
              disabled={status.running}
              className="flex-1"
              variant={status.running ? 'outline' : 'default'}
            >
              <Play className="h-4 w-4 mr-2" />
              启动仿真
            </Button>
            <Button
              onClick={onStop}
              disabled={!status.running}
              variant="destructive"
              className="flex-1"
            >
              <Square className="h-4 w-4 mr-2" />
              停止
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Current Config Summary */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Settings className="h-4 w-4" />
            当前配置
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <div className="grid grid-cols-2 gap-2">
            <div className="flex items-center gap-2">
              <Radio className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-muted-foreground">节点数:</span>
              <span className="font-mono font-semibold">{config.nNodes}</span>
            </div>
            <div className="flex items-center gap-2">
              <Wifi className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-muted-foreground">标准:</span>
              <span className="font-mono font-semibold">{config.standard}</span>
            </div>
            <div className="flex items-center gap-2">
              <Route className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-muted-foreground">路由:</span>
              <span className="font-mono font-semibold uppercase">{config.routingProtocol}</span>
            </div>
            <div className="flex items-center gap-2">
              <MapPin className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-muted-foreground">移动模型:</span>
              <span className="font-mono font-semibold">{config.mobilityModel}</span>
            </div>
            <div className="flex items-center gap-2">
              <FileCode className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-muted-foreground">路径损耗:</span>
              <span className="font-mono font-semibold">{config.pathLossModel} n={config.pathLossExponent}</span>
            </div>
            <div className="flex items-center gap-2">
              <Radio className="h-3.5 w-3.5 text-muted-foreground" />
              <span className="text-muted-foreground">速率控制:</span>
              <span className="font-mono font-semibold">{config.rateControl}</span>
            </div>
          </div>

          <Separator />

          <div className="grid grid-cols-2 gap-2 text-xs">
            <div><span className="text-muted-foreground">发射功率:</span> {config.txPowerStart} dBm</div>
            <div><span className="text-muted-foreground">CCA 阈值:</span> {config.ccaThreshold} dBm</div>
            <div><span className="text-muted-foreground">衰落:</span> {config.enableFading ? `${config.fadingModel}(M0=${config.nakagamiM0})` : '关闭'}</div>
            <div><span className="text-muted-foreground">RTS/CTS:</span> {config.rtsCtsThreshold === 65535 ? '禁用' : `${config.rtsCtsThreshold}B`}</div>
            <div><span className="text-muted-foreground">区域:</span> {config.mobilityMaxX}x{config.mobilityMaxY}m</div>
            <div><span className="text-muted-foreground">时长:</span> {config.simulationTime}s</div>
          </div>
        </CardContent>
      </Card>

      {/* Quick Actions */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">快捷操作</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <Button variant="outline" className="w-full justify-start" disabled={!status.running}>
            <RotateCw className="h-4 w-4 mr-2" />
            重启所有节点
          </Button>
          <Button variant="outline" className="w-full justify-start" disabled={!status.running}>
            <Wifi className="h-4 w-4 mr-2" />
            运行 iperf3 测试
          </Button>
          <Button variant="outline" className="w-full justify-start" disabled={!status.running}>
            <Route className="h-4 w-4 mr-2" />
            随机节点 Traceroute
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}
