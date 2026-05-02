import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useSimConfig } from '@/hooks/useSimConfig';
import { useSimulation } from '@/hooks/useSimulation';
import { Dashboard } from '@/sections/Dashboard';
import { ConfigPanel } from '@/sections/ConfigPanel';
import { TopologyView } from '@/sections/TopologyView';
import { ControlPanel } from '@/sections/ControlPanel';
import { LogView } from '@/sections/LogView';
import {
  LayoutDashboard, Settings, Network, Activity, ScrollText
} from 'lucide-react';
import './App.css';

function App() {
  const {
    config, activePreset, updateConfig,
    loadPreset, resetToDefault, exportConfig, importConfig,
  } = useSimConfig();

  const { status, nodes, flows, logs, startSimulation, stopSimulation } = useSimulation(config.nNodes);

  const [activeTab, setActiveTab] = useState('dashboard');

  const handleStart = () => {
    startSimulation(config);
    setActiveTab('topology');
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b bg-card sticky top-0 z-50">
        <div className="max-w-[1600px] mx-auto px-4 py-3 flex items-center gap-4">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-primary flex items-center justify-center">
              <Network className="h-5 w-5 text-primary-foreground" />
            </div>
            <div>
              <h1 className="text-lg font-bold leading-tight">NS-3 MANET Manager</h1>
              <p className="text-xs text-muted-foreground">802.11s Mesh / AdHoc Simulation Control Panel</p>
            </div>
          </div>
          <div className="flex-1" />
          <div className="flex items-center gap-2">
            <div className={`h-2.5 w-2.5 rounded-full ${status.running ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`} />
            <span className="text-sm font-medium">
              {status.running ? 'Simulation Active' : 'Idle'}
            </span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-[1600px] mx-auto px-4 py-4">
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Left: Main Tabs */}
          <div className="lg:col-span-9">
            <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
              <TabsList className="grid w-full grid-cols-5">
                <TabsTrigger value="dashboard">
                  <LayoutDashboard className="h-4 w-4 mr-1.5" /> Dashboard
                </TabsTrigger>
                <TabsTrigger value="config">
                  <Settings className="h-4 w-4 mr-1.5" /> Configuration
                </TabsTrigger>
                <TabsTrigger value="topology">
                  <Network className="h-4 w-4 mr-1.5" /> Topology
                </TabsTrigger>
                <TabsTrigger value="status">
                  <Activity className="h-4 w-4 mr-1.5" /> Realtime
                </TabsTrigger>
                <TabsTrigger value="logs">
                  <ScrollText className="h-4 w-4 mr-1.5" /> Logs
                </TabsTrigger>
              </TabsList>

              <div className="mt-4">
                <TabsContent value="dashboard">
                  <Dashboard status={status} nodes={nodes} />
                </TabsContent>

                <TabsContent value="config">
                  <ConfigPanel
                    config={config}
                    activePreset={activePreset}
                    updateConfig={updateConfig}
                    loadPreset={loadPreset}
                    resetToDefault={resetToDefault}
                    exportConfig={exportConfig}
                    importConfig={importConfig}
                  />
                </TabsContent>

                <TabsContent value="topology">
                  <TopologyView nodes={nodes} flows={flows} />
                </TabsContent>

                <TabsContent value="status">
                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                    <div className="lg:col-span-1">
                      <ControlPanel
                        status={status}
                        config={config}
                        onStart={handleStart}
                        onStop={stopSimulation}
                      />
                    </div>
                    <div className="lg:col-span-2">
                      <TopologyView nodes={nodes} flows={flows} />
                    </div>
                  </div>
                </TabsContent>

                <TabsContent value="logs">
                  <LogView logs={logs} onClear={() => {}} />
                </TabsContent>
              </div>
            </Tabs>
          </div>

          {/* Right: Sidebar Control */}
          <div className="lg:col-span-3 space-y-4">
            <ControlPanel
              status={status}
              config={config}
              onStart={handleStart}
              onStop={stopSimulation}
            />
            <LogView logs={logs.slice(0, 50)} onClear={() => {}} />
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t bg-card mt-8">
        <div className="max-w-[1600px] mx-auto px-4 py-3 flex items-center justify-between text-xs text-muted-foreground">
          <span>NS-3 802.11s Mesh / AdHoc 30-Node Simulation | linux/amd64</span>
          <span>Each container = one independent node | All traffic through ns-3 mesh / adhoc channel</span>
        </div>
      </footer>
    </div>
  );
}

export default App;
