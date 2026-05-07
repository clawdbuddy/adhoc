// ns-3 MANET 仿真配置类型定义
// 与后端 controller/orchestrator/config.py:SimConfig 逐字段对齐

export interface SimConfig {
  // --- General ---
  nNodes: number;
  simulationTime: number;
  seed: number;
  run: number;
  logComponents: string;

  // --- PHY ---
  standard: string;
  phyModel: string;
  frequencyMhz: number;
  channelWidthMhz: number;
  rangeTargetM: number;
  dataRate: string;
  txPowerStart: number;
  txPowerEnd: number;
  txPowerLevels: number;
  rxSensitivity: number;
  ccaThreshold: number;
  antennaGain: number;

  // --- Propagation ---
  propagationDelay: string;
  pathLossModel: string;
  pathLossExponent: number;
  pathLossRefLoss: number;
  pathLossRefDistance: number;
  enableFading: boolean;
  fadingModel: string;
  nakagamiM0: number;
  nakagamiM1: number;
  nakagamiM2: number;
  nakagamiD1: number;
  nakagamiD2: number;

  // --- MAC ---
  ssid: string;
  bssid: string;
  macMode: string;
  rateControl: string;
  rtsCtsThreshold: number;
  fragmentationThreshold: number;
  nonUnicastMode: boolean;
  beaconInterval: number;
  cwMin: number;
  cwMax: number;

  // --- Routing ---
  routingProtocol: string;
  aodvHelloInterval: number;
  aodvRreqRetries: number;
  aodvActiveRouteTimeout: number;
  aodvDeletePeriod: number;
  aodvNetDiameter: number;
  aodvEnableHello: boolean;
  olsrHelloInterval: number;
  olsrTcInterval: number;
  olsrWillingness: number;
  dsdvPeriodicUpdateInterval: number;
  dsdvSettlingTime: number;

  // --- Mobility ---
  mobilityModel: string;
  mobilityMinX: number;
  mobilityMaxX: number;
  mobilityMinY: number;
  mobilityMaxY: number;
  rwMinSpeed: number;
  rwMaxSpeed: number;
  rwDistance: number;
  rwMode: string;
  rwTime: number;
  gridMinX: number;
  gridMinY: number;
  gridDeltaX: number;
  gridDeltaY: number;
  gridWidth: number;
  gridLayout: string;
  gmAlpha: number;

  // --- Tracing ---
  pcap: boolean;
  ascii: boolean;
  flowMonitor: boolean;
  pcapPrefix: string;
  enableMobilityTrace: boolean;

  // --- Traffic ---
  trafficMode: 'tap' | 'onoff';
  onoffDataRate: string;
  onoffPacketSize: number;
  onoffMaxBytes: number;
  onoffStartTime: number;
  onoffSinkPort: number;
}

export interface NodeStatus {
  id: number;
  ip: string;
  status: 'online' | 'offline' | 'busy';
  role: string;
  rxPackets: number;
  txPackets: number;
  latency: number;
  neighbors: number[];
  x: number;
  y: number;
}

export interface FlowStats {
  flowId: number;
  source: string;
  destination: string;
  txPackets: number;
  rxPackets: number;
  lostPackets: number;
  avgDelay: number;
  throughput: number;
}

// 节点对聚合: 把 (源IP, 目标IP) 维度的多 flow 5-tuple 合并到 (srcId, dstId)
// 维度,用于 NxN 流量矩阵 UI。后端 telemetry.snapshot 中的 pairs 字段。
export interface NodePairFlow {
  srcId: number;
  dstId: number;
  txPackets: number;
  rxPackets: number;
  lostPackets: number;
  throughput: number;  // Mbps
  avgDelay: number;
}

export interface SimulationStatus {
  running: boolean;
  startTime: string | null;
  elapsed: number;
  nodesOnline: number;
  totalNodes: number;
  activeFlows: number;
  totalTx: number;
  totalRx: number;
  totalLost: number;
}

export interface TelemetryEnv {
  txPower: number[];
  rxSensitivity: number[];
  positions: { x: number; y: number; z: number }[];
  pathLossExponent: number;
  frequencyMhz: number;
  channelWidthMhz: number;
  rangeTargetM: number;
  pathLossModel?: string;
}

export const STANDARDS = [
  '80211n-2.4GHz', '80211n-5GHz',
  '80211ac', '80211ax-2.4GHz', '80211ax-5GHz',
];

export const DATA_RATES: Record<string, string[]> = {
  '80211n-2.4GHz': ['HtMcs0', 'HtMcs1', 'HtMcs2', 'HtMcs3', 'HtMcs4', 'HtMcs5', 'HtMcs6', 'HtMcs7'],
  '80211n-5GHz': ['HtMcs0', 'HtMcs1', 'HtMcs2', 'HtMcs3', 'HtMcs4', 'HtMcs5', 'HtMcs6', 'HtMcs7'],
  '80211ac': ['VhtMcs0', 'VhtMcs1', 'VhtMcs2', 'VhtMcs3', 'VhtMcs4', 'VhtMcs5', 'VhtMcs6', 'VhtMcs7', 'VhtMcs8', 'VhtMcs9'],
  '80211ax-2.4GHz': ['HeMcs0', 'HeMcs1', 'HeMcs2', 'HeMcs3', 'HeMcs4', 'HeMcs5', 'HeMcs6', 'HeMcs7', 'HeMcs8', 'HeMcs9', 'HeMcs10', 'HeMcs11'],
  '80211ax-5GHz': ['HeMcs0', 'HeMcs1', 'HeMcs2', 'HeMcs3', 'HeMcs4', 'HeMcs5', 'HeMcs6', 'HeMcs7', 'HeMcs8', 'HeMcs9', 'HeMcs10', 'HeMcs11'],
};

export const PHY_MODELS = ['yans', 'spectrum'];
export const PATH_LOSS_MODELS = ['LogDistance', 'FreeSpace', 'TwoRayGround', 'ThreeLogDistance', 'Cost231', 'Range'];
export const FADING_MODELS = ['Nakagami', 'Jakes'];
export const PROPAGATION_DELAYS = ['ConstantSpeed', 'Random'];
export const RATE_CONTROLS = ['Arf', 'Aarf', 'Onoe', 'Constant', 'Minstrel'];
export const MAC_MODES = ['adhoc', 'mesh'];
export const ROUTING_PROTOCOLS = ['aodv', 'olsr', 'dsdv', 'dsr', 'none'];
export const MOBILITY_MODELS = ['random-walk', 'gauss-markov', 'grid', 'constant'];
export const GRID_LAYOUTS = ['RowFirst', 'ColumnFirst'];
export const RW_MODES = ['Time', 'Distance'];

// 注：PRESETS 与 defaultConfig 已从本文件移除。
// 权威预设定义在后端 controller/orchestrator/config.py 中，
// 前端通过 GET /api/sim/presets 动态加载。
