import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Terminal, Trash2, Clock } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface LogViewProps {
  logs: string[];
  onClear: () => void;
}

function getLogStyle(log: string): { icon: string; bgClass: string; borderClass: string; textClass: string } {
  const lower = log.toLowerCase();
  if (lower.includes('error') || lower.includes('失败') || lower.includes('exception')) {
    return { icon: '◆', bgClass: 'bg-red-50/70', borderClass: 'border-l-red-400', textClass: 'text-red-700' };
  }
  if (lower.includes('warn')) {
    return { icon: '▲', bgClass: 'bg-amber-50/70', borderClass: 'border-l-amber-400', textClass: 'text-amber-700' };
  }
  if (lower.includes('started') || lower.includes('online') || lower.includes('已启动') || lower.includes('成功')) {
    return { icon: '●', bgClass: 'bg-green-50/70', borderClass: 'border-l-green-400', textClass: 'text-green-700' };
  }
  if (lower.includes('stopped') || lower.includes('offline') || lower.includes('已停止')) {
    return { icon: '○', bgClass: 'bg-slate-50/70', borderClass: 'border-l-slate-400', textClass: 'text-slate-600' };
  }
  if (lower.includes('iperf3') || lower.includes('traceroute') || lower.includes('[api]')) {
    return { icon: '▸', bgClass: 'bg-cyan-50/70', borderClass: 'border-l-cyan-400', textClass: 'text-cyan-700' };
  }
  if (lower.includes('ws')) {
    return { icon: '◈', bgClass: 'bg-violet-50/70', borderClass: 'border-l-violet-400', textClass: 'text-violet-700' };
  }
  return { icon: '·', bgClass: 'bg-transparent', borderClass: 'border-l-transparent', textClass: 'text-foreground/80' };
}

export function LogView({ logs, onClear }: LogViewProps) {
  return (
    <Card className="h-full border-slate-200/60 shadow-card">
      <CardHeader className="pb-3 flex flex-row items-center justify-between"
      >
        <CardTitle className="text-sm flex items-center gap-2 font-semibold"
        >
          <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center"
          >
            <Terminal className="h-4 w-4 text-primary" />
          </div
          >
          <div>
            <div className="leading-tight"
            >系统日志</div
            >
            <div className="text-[11px] text-muted-foreground font-normal"
            >
              {logs.length} 条记录
            </div
            >
          </div
          >
        </CardTitle
        >
        <Button variant="ghost" size="sm" onClick={onClear} className="gap-1.5 text-muted-foreground hover:text-foreground"
        >
          <Trash2 className="h-3.5 w-3.5" />
          清空
        </Button>
      </CardHeader>
      <CardContent className="p-0"
      >
        <ScrollArea className="h-[calc(100vh-220px)]"
        >
          <div className="space-y-0 px-4 pb-4"
          >
            {logs.length === 0 && (
              <div className="flex flex-col items-center justify-center py-16 text-muted-foreground"
              >
                <Clock className="h-8 w-8 mb-3 opacity-30" />
                <p className="text-sm"
                >暂无日志</p
                >
                <p className="text-xs mt-1 opacity-60"
                >启动仿真以查看活动</p
                >
              </div
              >
            )}
            {logs.map((log, i) => {
              const style = getLogStyle(log);
              // 尝试提取时间戳前缀
              const timeMatch = log.match(/^(\d{2}:\d{2}:\d{2})/);
              const timeStr = timeMatch ? timeMatch[1] : '';
              const content = timeStr ? log.slice(timeStr.length).trim() : log;

              return (
                <div
                  key={i}
                  className={`font-mono text-xs py-1.5 px-2 rounded-md border-l-2 ${style.bgClass} ${style.borderClass} ${style.textClass} transition-colors hover:bg-opacity-100`}
                >
                  <div className="flex items-start gap-2"
                  >
                    {timeStr && (
                      <span className="text-[10px] text-muted-foreground/60 shrink-0 tabular-nums mt-0.5"
                      >
                        {timeStr}
                      </span
                      >
                    )}
                    <span className="break-all leading-relaxed"
                    >{content}</span
                    >
                  </div
                  >
                </div
                >
              );
            })}
          </div
          >
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
