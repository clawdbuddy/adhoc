import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Terminal, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface LogViewProps {
  logs: string[];
  onClear: () => void;
}

export function LogView({ logs, onClear }: LogViewProps) {
  return (
    <Card className="h-full">
      <CardHeader className="pb-2 flex flex-row items-center justify-between">
        <CardTitle className="text-sm flex items-center gap-2">
          <Terminal className="h-4 w-4" />
          系统日志
          <Badge variant="secondary" className="text-xs">{logs.length}</Badge>
        </CardTitle>
        <Button variant="ghost" size="sm" onClick={onClear}>
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </CardHeader>
      <CardContent className="p-0">
        <ScrollArea className="h-[500px]">
          <div className="space-y-0 px-4 pb-4">
            {logs.length === 0 && (
              <p className="text-sm text-muted-foreground py-4">暂无日志。启动仿真以查看活动。</p>
            )}
            {logs.map((log, i) => {
              let colorClass = 'text-gray-700';
              if (log.includes('ERROR') || log.includes('error')) colorClass = 'text-red-600';
              else if (log.includes('WARN')) colorClass = 'text-yellow-600';
              else if (log.includes('Started') || log.includes('Online')) colorClass = 'text-green-600';
              else if (log.includes('Stopped') || log.includes('Offline')) colorClass = 'text-red-500';

              return (
                <div key={i} className={`font-mono text-xs py-0.5 border-b border-gray-50 ${colorClass}`}>
                  {log}
                </div>
              );
            })}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
