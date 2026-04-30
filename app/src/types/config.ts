// ns-3 MANET 仿真配置类型定义
// 参数与 manet-30nodes.cc 及后端 SimConfig 对齐

export interface SimConfig {
  // --- General ---
  nNodes: number;
  simulationTime: number;
  seed: number;
  run: number;
  logComponents: string;

  // --- PHY ---
  standard: string;
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

export const STANDARDS = [
  '80211b', '80211a', '80211g',
  '80211n-2.4GHz', '80211n-5GHz',
  '80211ac', '80211ax-2.4GHz', '80211ax-5GHz',
];

export const DATA_RATES: Record<string, string[]> = {
  '80211b': ['DsssRate1Mbps', 'DsssRate2Mbps', 'DsssRate5_5Mbps', 'DsssRate11Mbps'],
  '80211a': ['OfdmRate6Mbps', 'OfdmRate9Mbps', 'OfdmRate12Mbps', 'OfdmRate18Mbps', 'OfdmRate24Mbps', 'OfdmRate36Mbps', 'OfdmRate48Mbps', 'OfdmRate54Mbps'],
  '80211g': ['ErpOfdmRate6Mbps', 'ErpOfdmRate9Mbps', 'ErpOfdmRate12Mbps', 'ErpOfdmRate18Mbps', 'ErpOfdmRate24Mbps', 'ErpOfdmRate36Mbps', 'ErpOfdmRate48Mbps', 'ErpOfdmRate54Mbps'],
  '80211n-2.4GHz': ['HtMcs0', 'HtMcs1', 'HtMcs2', 'HtMcs3', 'HtMcs4', 'HtMcs5', 'HtMcs6', 'HtMcs7'],
  '80211n-5GHz': ['HtMcs0', 'HtMcs1', 'HtMcs2', 'HtMcs3', 'HtMcs4', 'HtMcs5', 'HtMcs6', 'HtMcs7'],
  '80211ac': ['VhtMcs0', 'VhtMcs1', 'VhtMcs2', 'VhtMcs3', 'VhtMcs4', 'VhtMcs5', 'VhtMcs6', 'VhtMcs7', 'VhtMcs8', 'VhtMcs9'],
  '80211ax-2.4GHz': ['HeMcs0', 'HeMcs1', 'HeMcs2', 'HeMcs3', 'HeMcs4', 'HeMcs5', 'HeMcs6', 'HeMcs7', 'HeMcs8', 'HeMcs9', 'HeMcs10', 'HeMcs11'],
  '80211ax-5GHz': ['HeMcs0', 'HeMcs1', 'HeMcs2', 'HeMcs3', 'HeMcs4', 'HeMcs5', 'HeMcs6', 'HeMcs7', 'HeMcs8', 'HeMcs9', 'HeMcs10', 'HeMcs11'],
};

export const PATH_LOSS_MODELS = ['LogDistance', 'FreeSpace', 'TwoRayGround', 'ThreeLogDistance', 'Cost231', 'Range'];
export const FADING_MODELS = ['Nakagami', 'Jakes'];
export const PROPAGATION_DELAYS = ['ConstantSpeed', 'Random'];
export const RATE_CONTROLS = ['Arf', 'Aarf', 'Onoe', 'Constant', 'Minstrel'];
export const MAC_TYPES = ['AdhocWifiMac'];
export const ROUTING_PROTOCOLS = ['aodv', 'olsr', 'dsdv', 'dsr', 'none'];
export const MOBILITY_MODELS = ['random-walk', 'gauss-markov', 'grid', 'constant'];
export const GRID_LAYOUTS = ['RowFirst', 'ColumnFirst'];
export const RW_MODES = ['Time', 'Distance'];

export const PRESETS = {
  default: {
    name: 'Default / Balanced',
    description: 'Standard 802.11g AdHoc with AODV, LogDistance path loss, moderate fading',
    config: {
      nNodes: 30, simulationTime: 300, seed: 1, run: 1,
      standard: '80211g', dataRate: 'ErpOfdmRate54Mbps',
      txPowerStart: 20, txPowerEnd: 20, txPowerLevels: 1,
      rxSensitivity: -85, ccaThreshold: -62, antennaGain: 0,
      propagationDelay: 'ConstantSpeed', pathLossModel: 'LogDistance',
      pathLossExponent: 3.0, pathLossRefLoss: 46.6777, pathLossRefDistance: 1.0,
      enableFading: true, fadingModel: 'Nakagami',
      nakagamiM0: 1.5, nakagamiM1: 1.0, nakagamiM2: 0.75, nakagamiD1: 50, nakagamiD2: 100,
      ssid: 'adhoc-30ns3', bssid: '00:00:00:00:AD:H0',
      rateControl: 'Arf', rtsCtsThreshold: 2200, fragmentationThreshold: 2200,
      nonUnicastMode: false, beaconInterval: 100, cwMin: 15, cwMax: 1023,
      routingProtocol: 'aodv', aodvHelloInterval: 1, aodvRreqRetries: 2,
      aodvActiveRouteTimeout: 3, aodvDeletePeriod: 5, aodvNetDiameter: 35, aodvEnableHello: true,
      olsrHelloInterval: 2, olsrTcInterval: 5, olsrWillingness: 7,
      dsdvPeriodicUpdateInterval: 15, dsdvSettlingTime: 6,
      mobilityModel: 'random-walk', mobilityMinX: 0, mobilityMaxX: 500, mobilityMinY: 0, mobilityMaxY: 500,
      rwMinSpeed: 0.5, rwMaxSpeed: 3, rwDistance: 20, rwMode: 'Time', rwTime: 1,
      gridMinX: 10, gridMinY: 10, gridDeltaX: 80, gridDeltaY: 80, gridWidth: 6, gridLayout: 'RowFirst',
      gmAlpha: 0.85, pcap: true, ascii: false, flowMonitor: true,
      pcapPrefix: 'manet-30nodes-adhoc', enableMobilityTrace: false,
    } as SimConfig,
  },
  urban: {
    name: 'Urban Dense',
    description: 'Dense urban: heavy path loss, strong fading, AODV fast hello, always RTS/CTS',
    config: {
      nNodes: 30, simulationTime: 300, seed: 1, run: 1,
      standard: '80211g', dataRate: 'ErpOfdmRate24Mbps',
      txPowerStart: 18, txPowerEnd: 18, txPowerLevels: 1,
      rxSensitivity: -82, ccaThreshold: -60, antennaGain: 0,
      propagationDelay: 'ConstantSpeed', pathLossModel: 'LogDistance',
      pathLossExponent: 4.0, pathLossRefLoss: 46.6777, pathLossRefDistance: 1.0,
      enableFading: true, fadingModel: 'Nakagami',
      nakagamiM0: 1.0, nakagamiM1: 0.75, nakagamiM2: 0.5, nakagamiD1: 30, nakagamiD2: 60,
      ssid: 'adhoc-urban', bssid: '00:00:00:00:AD:H0',
      rateControl: 'Aarf', rtsCtsThreshold: 500, fragmentationThreshold: 1000,
      nonUnicastMode: false, beaconInterval: 100, cwMin: 15, cwMax: 1023,
      routingProtocol: 'aodv', aodvHelloInterval: 0.5, aodvRreqRetries: 2,
      aodvActiveRouteTimeout: 2, aodvDeletePeriod: 5, aodvNetDiameter: 20, aodvEnableHello: true,
      olsrHelloInterval: 2, olsrTcInterval: 5, olsrWillingness: 7,
      dsdvPeriodicUpdateInterval: 15, dsdvSettlingTime: 6,
      mobilityModel: 'random-walk', mobilityMinX: 0, mobilityMaxX: 300, mobilityMinY: 0, mobilityMaxY: 300,
      rwMinSpeed: 0.5, rwMaxSpeed: 2, rwDistance: 20, rwMode: 'Time', rwTime: 1,
      gridMinX: 10, gridMinY: 10, gridDeltaX: 50, gridDeltaY: 50, gridWidth: 6, gridLayout: 'RowFirst',
      gmAlpha: 0.85, pcap: true, ascii: false, flowMonitor: true,
      pcapPrefix: 'manet-urban', enableMobilityTrace: false,
    } as SimConfig,
  },
  rural: {
    name: 'Rural / Open Field',
    description: 'Open field: TwoRayGround, light fading, OLSR, disabled RTS/CTS, long range',
    config: {
      nNodes: 30, simulationTime: 300, seed: 1, run: 1,
      standard: '80211a', dataRate: 'OfdmRate54Mbps',
      txPowerStart: 23, txPowerEnd: 23, txPowerLevels: 1,
      rxSensitivity: -90, ccaThreshold: -65, antennaGain: 0,
      propagationDelay: 'ConstantSpeed', pathLossModel: 'TwoRayGround',
      pathLossExponent: 2.0, pathLossRefLoss: 46.6777, pathLossRefDistance: 1.0,
      enableFading: true, fadingModel: 'Nakagami',
      nakagamiM0: 3.0, nakagamiM1: 2.0, nakagamiM2: 1.5, nakagamiD1: 100, nakagamiD2: 200,
      ssid: 'adhoc-rural', bssid: '00:00:00:00:AD:H0',
      rateControl: 'Arf', rtsCtsThreshold: 65535, fragmentationThreshold: 2200,
      nonUnicastMode: false, beaconInterval: 100, cwMin: 15, cwMax: 1023,
      routingProtocol: 'olsr', aodvHelloInterval: 1, aodvRreqRetries: 2,
      aodvActiveRouteTimeout: 3, aodvDeletePeriod: 5, aodvNetDiameter: 35, aodvEnableHello: true,
      olsrHelloInterval: 5, olsrTcInterval: 10, olsrWillingness: 7,
      dsdvPeriodicUpdateInterval: 15, dsdvSettlingTime: 6,
      mobilityModel: 'grid', mobilityMinX: 0, mobilityMaxX: 1000, mobilityMinY: 0, mobilityMaxY: 1000,
      rwMinSpeed: 0.5, rwMaxSpeed: 3, rwDistance: 20, rwMode: 'Time', rwTime: 1,
      gridMinX: 0, gridMinY: 0, gridDeltaX: 150, gridDeltaY: 150, gridWidth: 6, gridLayout: 'RowFirst',
      gmAlpha: 0.85, pcap: true, ascii: false, flowMonitor: true,
      pcapPrefix: 'manet-rural', enableMobilityTrace: false,
    } as SimConfig,
  },
  debug: {
    name: 'Debug / Minimal',
    description: '5 nodes, 60s, no fading, fixed grid, no routing, full tracing',
    config: {
      nNodes: 5, simulationTime: 60, seed: 1, run: 1,
      standard: '80211g', dataRate: 'ErpOfdmRate54Mbps',
      txPowerStart: 20, txPowerEnd: 20, txPowerLevels: 1,
      rxSensitivity: -85, ccaThreshold: -62, antennaGain: 0,
      propagationDelay: 'ConstantSpeed', pathLossModel: 'LogDistance',
      pathLossExponent: 2.0, pathLossRefLoss: 46.6777, pathLossRefDistance: 1.0,
      enableFading: false, fadingModel: 'Nakagami',
      nakagamiM0: 1.5, nakagamiM1: 1.0, nakagamiM2: 0.75, nakagamiD1: 50, nakagamiD2: 100,
      ssid: 'adhoc-debug', bssid: '00:00:00:00:AD:H0',
      rateControl: 'Arf', rtsCtsThreshold: 2200, fragmentationThreshold: 2200,
      nonUnicastMode: false, beaconInterval: 100, cwMin: 15, cwMax: 1023,
      routingProtocol: 'none', aodvHelloInterval: 1, aodvRreqRetries: 2,
      aodvActiveRouteTimeout: 3, aodvDeletePeriod: 5, aodvNetDiameter: 35, aodvEnableHello: true,
      olsrHelloInterval: 2, olsrTcInterval: 5, olsrWillingness: 7,
      dsdvPeriodicUpdateInterval: 15, dsdvSettlingTime: 6,
      mobilityModel: 'grid', mobilityMinX: 0, mobilityMaxX: 250, mobilityMinY: 0, mobilityMaxY: 250,
      rwMinSpeed: 0.5, rwMaxSpeed: 3, rwDistance: 20, rwMode: 'Time', rwTime: 1,
      gridMinX: 10, gridMinY: 10, gridDeltaX: 50, gridDeltaY: 50, gridWidth: 5, gridLayout: 'RowFirst',
      gmAlpha: 0.85, pcap: true, ascii: true, flowMonitor: true,
      pcapPrefix: 'manet-debug', enableMobilityTrace: true,
    } as SimConfig,
  },
};

export const defaultConfig: SimConfig = PRESETS.default.config;
