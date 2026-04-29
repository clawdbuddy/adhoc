/*
 * manet-30nodes.cc
 * NS-3 802.11 AdHoc (IBSS) 30-Node MANET Simulation with TapBridge
 * Fully configurable via CommandLine arguments
 *
 * Usage:
 *   sudo ./ns3 run "scratch/manet-30nodes --nNodes=30 --simulationTime=300"
 *   sudo ./ns3 run "scratch/manet-30nodes --configFile=/path/to/config.json"
 *
 * Parameter Categories:
 *   - PHY: wifi standard, tx/rx power, cca, propagation models
 *   - MAC: adhoc mac, rts/cts, fragmentation, rate control, cw, slot time
 *   - Routing: aodv/olsr/dsdv/dsr/none with per-protocol params
 *   - Mobility: random-walk/grid/constant-position with per-model params
 *   - Simulation: node count, time, seed, logging, tracing
 *   - TapBridge: mode, device naming pattern
 */

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/mobility-module.h"
#include "ns3/wifi-module.h"
#include "ns3/tap-bridge-module.h"
#include "ns3/internet-module.h"
#include "ns3/ipv4-global-routing-helper.h"
#include "ns3/flow-monitor-module.h"
#include "ns3/aodv-module.h"
#include "ns3/olsr-module.h"
#include "ns3/dsdv-module.h"
#include "ns3/dsr-module.h"

#include <fstream>
#include <sstream>

using namespace ns3;

NS_LOG_COMPONENT_DEFINE("Manet30Nodes");

// ============================================================================
// Configuration Structure
// ============================================================================
struct SimConfig {
    // --- General ---
    uint32_t nNodes = 30;
    double simulationTime = 300.0;
    uint32_t seed = 1;
    uint32_t run = 1;
    std::string logComponents = "";
    
    // --- PHY ---
    std::string standard = "80211g";
    std::string dataRate = "ErpOfdmRate54Mbps";
    double txPowerStart = 20.0;
    double txPowerEnd = 20.0;
    uint32_t txPowerLevels = 1;
    double rxSensitivity = -85.0;
    double ccaThreshold = -62.0;
    double antennaGain = 0.0;
    std::string errorRateModel = "NistErrorRateModel";
    
    // --- Propagation ---
    std::string propagationDelay = "ConstantSpeed";
    std::string pathLossModel = "LogDistance";
    double pathLossExponent = 3.0;
    double pathLossRefLoss = 46.6777;
    double pathLossRefDistance = 1.0;
    bool enableFading = true;
    std::string fadingModel = "Nakagami";
    double nakagamiM0 = 1.5;
    double nakagamiM1 = 1.0;
    double nakagamiM2 = 0.75;
    double nakagamiD1 = 50.0;
    double nakagamiD2 = 100.0;
    
    // --- MAC ---
    std::string macType = "AdhocWifiMac";
    std::string ssid = "adhoc-30ns3";
    std::string bssid = "00:00:00:00:AD:H0";
    std::string rateControl = "Arf";
    uint32_t rtsCtsThreshold = 2200;
    uint32_t fragmentationThreshold = 2200;
    bool nonUnicastMode = false;
    uint32_t beaconInterval = 100;
    bool enableCtsToSelf = false;
    
    // --- MAC Extended (CW, slot, etc) ---
    uint32_t cwMin = 15;
    uint32_t cwMax = 1023;
    uint32_t slotTime = 9;           // microseconds
    uint32_t sifs = 10;              // microseconds
    uint32_t preambleDetectionModel = 0;
    
    // --- Routing ---
    std::string routingProtocol = "aodv";
    // AODV params
    double aodvHelloInterval = 1.0;
    uint32_t aodvRreqRetries = 2;
    double aodvActiveRouteTimeout = 3.0;
    double aodvDeletePeriod = 5.0;
    uint32_t aodvNetDiameter = 35;
    bool aodvEnableHello = true;
    // OLSR params
    double olsrHelloInterval = 2.0;
    double olsrTcInterval = 5.0;
    double olsrMidInterval = 5.0;
    double olsrWilligness = 7;
    // DSDV params
    double dsdvPeriodicUpdateInterval = 15.0;
    uint32_t dsdvSettlingTime = 6;
    // DSR params
    uint32_t dsrMaxSendBuffLen = 64;
    uint32_t dsrMaxRreqRetx = 16;
    
    // --- Mobility ---
    std::string mobilityModel = "random-walk";
    // Random walk params
    double mobilityMinX = 0.0;
    double mobilityMaxX = 500.0;
    double mobilityMinY = 0.0;
    double mobilityMaxY = 500.0;
    double rwMinSpeed = 0.5;
    double rwMaxSpeed = 3.0;
    double rwDistance = 20.0;
    std::string rwMode = "Time";
    double rwTime = 1.0;
    // Grid params
    double gridMinX = 10.0;
    double gridMinY = 10.0;
    double gridDeltaX = 80.0;
    double gridDeltaY = 80.0;
    uint32_t gridWidth = 6;
    std::string gridLayout = "RowFirst";
    // Gauss-Markov (if enabled)
    double gmAlpha = 0.85;
    double gmMeanVelocity = 1.0;
    double gmMeanDirection = 0.0;
    double gmMeanPitch = 0.0;
    // Waypoint
    std::string ns2TraceFile = "";
    
    // --- Tracing ---
    bool pcapTracing = true;
    bool asciiTracing = false;
    bool flowMonitor = true;
    std::string pcapPrefix = "manet-30nodes-adhoc";
    std::string asciiFile = "manet-30nodes-adhoc.tr";
    bool enableMobilityTrace = false;
    
    // --- TapBridge ---
    std::string tapMode = "UseBridge";
    std::string tapPrefix = "tap-";
    bool tapBridgeAll = true;
    
    // --- Config file ---
    std::string configFile = "";
};

// ============================================================================
// Parse config from JSON-like simple format
// ============================================================================
SimConfig ParseConfigFile(const std::string& filepath) {
    SimConfig cfg;
    std::ifstream ifs(filepath);
    if (!ifs.is_open()) {
        NS_LOG_WARN("Cannot open config file: " << filepath);
        return cfg;
    }
    std::string line;
    while (std::getline(ifs, line)) {
        // Skip comments and empty lines
        size_t cmt = line.find("//");
        if (cmt != std::string::npos) line = line.substr(0, cmt);
        if (cmt == 0) continue;
        
        size_t eq = line.find("=");
        if (eq == std::string::npos) continue;
        
        std::string key = line.substr(0, eq);
        std::string val = line.substr(eq + 1);
        
        // Trim whitespace
        auto trim = [](std::string& s) {
            size_t a = s.find_first_not_of(" \t\"'");
            size_t b = s.find_last_not_of(" \t\"',\r\n");
            if (a == std::string::npos) s = "";
            else s = s.substr(a, b - a + 1);
        };
        trim(key); trim(val);
        
        // Map keys to config fields
        if (key == "nNodes") cfg.nNodes = std::stoul(val);
        else if (key == "simulationTime") cfg.simulationTime = std::stod(val);
        else if (key == "seed") cfg.seed = std::stoul(val);
        else if (key == "run") cfg.run = std::stoul(val);
        else if (key == "logComponents") cfg.logComponents = val;
        else if (key == "standard") cfg.standard = val;
        else if (key == "dataRate") cfg.dataRate = val;
        else if (key == "txPowerStart") cfg.txPowerStart = std::stod(val);
        else if (key == "txPowerEnd") cfg.txPowerEnd = std::stod(val);
        else if (key == "txPowerLevels") cfg.txPowerLevels = std::stoul(val);
        else if (key == "rxSensitivity") cfg.rxSensitivity = std::stod(val);
        else if (key == "ccaThreshold") cfg.ccaThreshold = std::stod(val);
        else if (key == "antennaGain") cfg.antennaGain = std::stod(val);
        else if (key == "errorRateModel") cfg.errorRateModel = val;
        else if (key == "propagationDelay") cfg.propagationDelay = val;
        else if (key == "pathLossModel") cfg.pathLossModel = val;
        else if (key == "pathLossExponent") cfg.pathLossExponent = std::stod(val);
        else if (key == "pathLossRefLoss") cfg.pathLossRefLoss = std::stod(val);
        else if (key == "pathLossRefDistance") cfg.pathLossRefDistance = std::stod(val);
        else if (key == "enableFading") cfg.enableFading = (val == "true" || val == "1");
        else if (key == "fadingModel") cfg.fadingModel = val;
        else if (key == "nakagamiM0") cfg.nakagamiM0 = std::stod(val);
        else if (key == "nakagamiM1") cfg.nakagamiM1 = std::stod(val);
        else if (key == "nakagamiM2") cfg.nakagamiM2 = std::stod(val);
        else if (key == "nakagamiD1") cfg.nakagamiD1 = std::stod(val);
        else if (key == "nakagamiD2") cfg.nakagamiD2 = std::stod(val);
        else if (key == "macType") cfg.macType = val;
        else if (key == "ssid") cfg.ssid = val;
        else if (key == "bssid") cfg.bssid = val;
        else if (key == "rateControl") cfg.rateControl = val;
        else if (key == "rtsCtsThreshold") cfg.rtsCtsThreshold = std::stoul(val);
        else if (key == "fragmentationThreshold") cfg.fragmentationThreshold = std::stoul(val);
        else if (key == "nonUnicastMode") cfg.nonUnicastMode = (val == "true" || val == "1");
        else if (key == "beaconInterval") cfg.beaconInterval = std::stoul(val);
        else if (key == "enableCtsToSelf") cfg.enableCtsToSelf = (val == "true" || val == "1");
        else if (key == "cwMin") cfg.cwMin = std::stoul(val);
        else if (key == "cwMax") cfg.cwMax = std::stoul(val);
        else if (key == "slotTime") cfg.slotTime = std::stoul(val);
        else if (key == "sifs") cfg.sifs = std::stoul(val);
        else if (key == "routingProtocol") cfg.routingProtocol = val;
        else if (key == "aodvHelloInterval") cfg.aodvHelloInterval = std::stod(val);
        else if (key == "aodvRreqRetries") cfg.aodvRreqRetries = std::stoul(val);
        else if (key == "aodvActiveRouteTimeout") cfg.aodvActiveRouteTimeout = std::stod(val);
        else if (key == "aodvDeletePeriod") cfg.aodvDeletePeriod = std::stod(val);
        else if (key == "aodvNetDiameter") cfg.aodvNetDiameter = std::stoul(val);
        else if (key == "aodvEnableHello") cfg.aodvEnableHello = (val == "true" || val == "1");
        else if (key == "olsrHelloInterval") cfg.olsrHelloInterval = std::stod(val);
        else if (key == "olsrTcInterval") cfg.olsrTcInterval = std::stod(val);
        else if (key == "olsrWillingness") cfg.olsrWilligness = std::stoul(val);
        else if (key == "dsdvPeriodicUpdateInterval") cfg.dsdvPeriodicUpdateInterval = std::stod(val);
        else if (key == "dsdvSettlingTime") cfg.dsdvSettlingTime = std::stoul(val);
        else if (key == "dsrMaxSendBuffLen") cfg.dsrMaxSendBuffLen = std::stoul(val);
        else if (key == "dsrMaxRreqRetx") cfg.dsrMaxRreqRetx = std::stoul(val);
        else if (key == "mobilityModel") cfg.mobilityModel = val;
        else if (key == "mobilityMinX") cfg.mobilityMinX = std::stod(val);
        else if (key == "mobilityMaxX") cfg.mobilityMaxX = std::stod(val);
        else if (key == "mobilityMinY") cfg.mobilityMinY = std::stod(val);
        else if (key == "mobilityMaxY") cfg.mobilityMaxY = std::stod(val);
        else if (key == "rwMinSpeed") cfg.rwMinSpeed = std::stod(val);
        else if (key == "rwMaxSpeed") cfg.rwMaxSpeed = std::stod(val);
        else if (key == "rwDistance") cfg.rwDistance = std::stod(val);
        else if (key == "rwMode") cfg.rwMode = val;
        else if (key == "rwTime") cfg.rwTime = std::stod(val);
        else if (key == "gridMinX") cfg.gridMinX = std::stod(val);
        else if (key == "gridMinY") cfg.gridMinY = std::stod(val);
        else if (key == "gridDeltaX") cfg.gridDeltaX = std::stod(val);
        else if (key == "gridDeltaY") cfg.gridDeltaY = std::stod(val);
        else if (key == "gridWidth") cfg.gridWidth = std::stoul(val);
        else if (key == "gridLayout") cfg.gridLayout = val;
        else if (key == "gmAlpha") cfg.gmAlpha = std::stod(val);
        else if (key == "ns2TraceFile") cfg.ns2TraceFile = val;
        else if (key == "pcapTracing") cfg.pcapTracing = (val == "true" || val == "1");
        else if (key == "asciiTracing") cfg.asciiTracing = (val == "true" || val == "1");
        else if (key == "flowMonitor") cfg.flowMonitor = (val == "true" || val == "1");
        else if (key == "pcapPrefix") cfg.pcapPrefix = val;
        else if (key == "asciiFile") cfg.asciiFile = val;
        else if (key == "enableMobilityTrace") cfg.enableMobilityTrace = (val == "true" || val == "1");
        else if (key == "tapMode") cfg.tapMode = val;
        else if (key == "tapPrefix") cfg.tapPrefix = val;
        else if (key == "tapBridgeAll") cfg.tapBridgeAll = (val == "true" || val == "1");
    }
    ifs.close();
    NS_LOG_INFO("Loaded configuration from: " << filepath);
    return cfg;
}

// ============================================================================
// Print configuration summary
// ============================================================================
void PrintConfig(const SimConfig& cfg) {
    std::cout << "\n========================================\n";
    std::cout << "  AdHoc Simulation Configuration\n";
    std::cout << "========================================\n";
    std::cout << "Nodes: " << cfg.nNodes << "  Time: " << cfg.simulationTime << "s\n";
    std::cout << "Seed: " << cfg.seed << "  Run: " << cfg.run << "\n\n";
    
    std::cout << "--- PHY ---\n";
    std::cout << "Standard: " << cfg.standard << "  DataRate: " << cfg.dataRate << "\n";
    std::cout << "TxPower: " << cfg.txPowerStart << "~" << cfg.txPowerEnd << " dBm (levels=" << cfg.txPowerLevels << ")\n";
    std::cout << "RxSensitivity: " << cfg.rxSensitivity << " dBm  CCA: " << cfg.ccaThreshold << " dBm\n";
    std::cout << "AntennaGain: " << cfg.antennaGain << " dBi  ErrorModel: " << cfg.errorRateModel << "\n";
    std::cout << "PropDelay: " << cfg.propagationDelay << "\n";
    std::cout << "PathLoss: " << cfg.pathLossModel << "(n=" << cfg.pathLossExponent << ")\n";
    std::cout << "Fading: " << (cfg.enableFading ? cfg.fadingModel : "disabled") << "\n";
    if (cfg.enableFading && cfg.fadingModel == "Nakagami") {
        std::cout << "  Nakagami M0=" << cfg.nakagamiM0 << " M1=" << cfg.nakagamiM1 
                  << " M2=" << cfg.nakagamiM2 << "\n";
    }
    
    std::cout << "\n--- MAC ---\n";
    std::cout << "MacType: " << cfg.macType << "  SSID: " << cfg.ssid << "\n";
    std::cout << "BSSID: " << cfg.bssid << "\n";
    std::cout << "RateControl: " << cfg.rateControl << "\n";
    std::cout << "RTS/CTS: " << cfg.rtsCtsThreshold << " bytes  Frag: " << cfg.fragmentationThreshold << " bytes\n";
    std::cout << "CWmin: " << cfg.cwMin << "  CWmax: " << cfg.cwMax << "\n";
    std::cout << "SlotTime: " << cfg.slotTime << "us  SIFS: " << cfg.sifs << "us\n";
    std::cout << "BeaconInterval: " << cfg.beaconInterval << " TU\n";
    
    std::cout << "\n--- Routing ---\n";
    std::cout << "Protocol: " << cfg.routingProtocol << "\n";
    if (cfg.routingProtocol == "aodv") {
        std::cout << "  Hello=" << cfg.aodvHelloInterval << "s  RreqRetries=" << cfg.aodvRreqRetries
                  << "  RouteTimeout=" << cfg.aodvActiveRouteTimeout << "s\n";
    } else if (cfg.routingProtocol == "olsr") {
        std::cout << "  Hello=" << cfg.olsrHelloInterval << "s  TC=" << cfg.olsrTcInterval
                  << "s  Willingness=" << cfg.olsrWilligness << "\n";
    }
    
    std::cout << "\n--- Mobility ---\n";
    std::cout << "Model: " << cfg.mobilityModel << "\n";
    std::cout << "Area: [" << cfg.mobilityMinX << "," << cfg.mobilityMaxX << "] x ["
              << cfg.mobilityMinY << "," << cfg.mobilityMaxY << "]\n";
    if (cfg.mobilityModel == "random-walk") {
        std::cout << "Speed: " << cfg.rwMinSpeed << "~" << cfg.rwMaxSpeed << " m/s\n";
        std::cout << "Mode: " << cfg.rwMode << "  Time=" << cfg.rwTime << "s\n";
    } else if (cfg.mobilityModel == "grid") {
        std::cout << "Delta: " << cfg.gridDeltaX << "x" << cfg.gridDeltaY 
                  << "  Width=" << cfg.gridWidth << "\n";
    }
    
    std::cout << "\n--- Tracing ---\n";
    std::cout << "PCAP: " << (cfg.pcapTracing ? "yes" : "no");
    std::cout << "  ASCII: " << (cfg.asciiTracing ? "yes" : "no");
    std::cout << "  FlowMon: " << (cfg.flowMonitor ? "yes" : "no");
    std::cout << "  MobTrace: " << (cfg.enableMobilityTrace ? "yes" : "no") << "\n";
    
    std::cout << "\n--- TapBridge ---\n";
    std::cout << "Mode: " << cfg.tapMode << "  Prefix: " << cfg.tapPrefix << "\n";
    std::cout << "========================================\n\n";
}

// ============================================================================
// Setup WiFi Standard
// ============================================================================
void SetupWifiStandard(WifiHelper& wifi, const std::string& standard) {
    if (standard == "80211b") {
        wifi.SetStandard(WIFI_STANDARD_80211b);
    } else if (standard == "80211a") {
        wifi.SetStandard(WIFI_STANDARD_80211a);
    } else if (standard == "80211g") {
        wifi.SetStandard(WIFI_STANDARD_80211g);
    } else if (standard == "80211n-2.4GHz") {
        wifi.SetStandard(WIFI_STANDARD_80211n);
        Config::SetDefault("ns3::WifiPhy::ChannelSettings", StringValue("{7, 20, BAND_2_4GHZ, 0}"));
    } else if (standard == "80211n-5GHz") {
        wifi.SetStandard(WIFI_STANDARD_80211n);
        Config::SetDefault("ns3::WifiPhy::ChannelSettings", StringValue("{36, 20, BAND_5GHZ, 0}"));
    } else if (standard == "80211ac") {
        wifi.SetStandard(WIFI_STANDARD_80211ac);
    } else if (standard == "80211ax-2.4GHz") {
        wifi.SetStandard(WIFI_STANDARD_80211ax);
        Config::SetDefault("ns3::WifiPhy::ChannelSettings", StringValue("{7, 20, BAND_2_4GHZ, 0}"));
    } else if (standard == "80211ax-5GHz") {
        wifi.SetStandard(WIFI_STANDARD_80211ax);
        Config::SetDefault("ns3::WifiPhy::ChannelSettings", StringValue("{36, 20, BAND_5GHZ, 0}"));
    } else {
        NS_LOG_WARN("Unknown standard '" << standard << "', using 802.11g");
        wifi.SetStandard(WIFI_STANDARD_80211g);
    }
}

// ============================================================================
// Setup Rate Control
// ============================================================================
void SetupRateControl(WifiHelper& wifi, const SimConfig& cfg) {
    std::string ruMode = cfg.nonUnicastMode ? ",NonUnicastMode=" + cfg.dataRate : "";
    
    if (cfg.rateControl == "Arf" || cfg.rateControl == "arf") {
        wifi.SetRemoteStationManager("ns3::ArfWifiManager",
            "RtsCtsThreshold", UintegerValue(cfg.rtsCtsThreshold),
            "FragmentationThreshold", UintegerValue(cfg.fragmentationThreshold)
            + (cfg.nonUnicastMode ? ",NonUnicastMode=" + cfg.dataRate : StringValue("")));
    } else if (cfg.rateControl == "Aarf" || cfg.rateControl == "aarf") {
        wifi.SetRemoteStationManager("ns3::AarfWifiManager",
            "RtsCtsThreshold", UintegerValue(cfg.rtsCtsThreshold),
            "FragmentationThreshold", UintegerValue(cfg.fragmentationThreshold));
    } else if (cfg.rateControl == "Onoe" || cfg.rateControl == "onoe") {
        wifi.SetRemoteStationManager("ns3::OnoeWifiManager",
            "RtsCtsThreshold", UintegerValue(cfg.rtsCtsThreshold),
            "FragmentationThreshold", UintegerValue(cfg.fragmentationThreshold));
    } else if (cfg.rateControl == "Constant" || cfg.rateControl == "constant") {
        wifi.SetRemoteStationManager("ns3::ConstantRateWifiManager",
            "DataMode", StringValue(cfg.dataRate),
            "ControlMode", StringValue(cfg.dataRate),
            "RtsCtsThreshold", UintegerValue(cfg.rtsCtsThreshold),
            "FragmentationThreshold", UintegerValue(cfg.fragmentationThreshold));
    } else if (cfg.rateControl == "Minstrel" || cfg.rateControl == "minstrel") {
        wifi.SetRemoteStationManager("ns3::MinstrelWifiManager",
            "RtsCtsThreshold", UintegerValue(cfg.rtsCtsThreshold),
            "FragmentationThreshold", UintegerValue(cfg.fragmentationThreshold));
    } else {
        NS_LOG_WARN("Unknown rate control '" << cfg.rateControl << "', using ARF");
        wifi.SetRemoteStationManager("ns3::ArfWifiManager",
            "RtsCtsThreshold", UintegerValue(cfg.rtsCtsThreshold),
            "FragmentationThreshold", UintegerValue(cfg.fragmentationThreshold));
    }
}

// ============================================================================
// Setup Propagation Models
// ============================================================================
void SetupPropagation(YansWifiChannelHelper& channel, const SimConfig& cfg) {
    // Propagation delay
    if (cfg.propagationDelay == "ConstantSpeed") {
        channel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
    } else if (cfg.propagationDelay == "Random") {
        channel.SetPropagationDelay("ns3::RandomPropagationDelayModel",
            "Variable", StringValue("ns3::UniformRandomVariable[Min=0.0|Max=1.0]"));
    } else {
        channel.SetPropagationDelay("ns3::ConstantSpeedPropagationDelayModel");
    }
    
    // Path loss
    if (cfg.pathLossModel == "LogDistance") {
        channel.AddPropagationLoss("ns3::LogDistancePropagationLossModel",
            "Exponent", DoubleValue(cfg.pathLossExponent),
            "ReferenceLoss", DoubleValue(cfg.pathLossRefLoss),
            "ReferenceDistance", DoubleValue(cfg.pathLossRefDistance));
    } else if (cfg.pathLossModel == "FreeSpace") {
        channel.AddPropagationLoss("ns3::FriisPropagationLossModel",
            "Frequency", DoubleValue(2.4e9));
    } else if (cfg.pathLossModel == "TwoRayGround") {
        channel.AddPropagationLoss("ns3::TwoRayGroundPropagationLossModel",
            "Frequency", DoubleValue(2.4e9),
            "HeightAboveZ", DoubleValue(1.5));
    } else if (cfg.pathLossModel == "ThreeLogDistance") {
        channel.AddPropagationLoss("ns3::ThreeLogDistancePropagationLossModel");
    } else if (cfg.pathLossModel == "Cost231") {
        channel.AddPropagationLoss("ns3::Cost231PropagationLossModel");
    } else if (cfg.pathLossModel == "Range") {
        channel.AddPropagationLoss("ns3::RangePropagationLossModel");
    } else {
        channel.AddPropagationLoss("ns3::LogDistancePropagationLossModel",
            "Exponent", DoubleValue(cfg.pathLossExponent),
            "ReferenceLoss", DoubleValue(cfg.pathLossRefLoss),
            "ReferenceDistance", DoubleValue(cfg.pathLossRefDistance));
    }
    
    // Fading
    if (cfg.enableFading) {
        if (cfg.fadingModel == "Nakagami") {
            channel.AddPropagationLoss("ns3::NakagamiPropagationLossModel",
                "Distance1", DoubleValue(cfg.nakagamiD1),
                "Distance2", DoubleValue(cfg.nakagamiD2),
                "M0", DoubleValue(cfg.nakagamiM0),
                "M1", DoubleValue(cfg.nakagamiM1),
                "M2", DoubleValue(cfg.nakagamiM2));
        } else if (cfg.fadingModel == "Jakes") {
            channel.AddPropagationLoss("ns3::JakesPropagationLossModel");
        }
    }
}

// ============================================================================
// Setup Routing
// ============================================================================
void SetupRouting(InternetStackHelper& stack, const SimConfig& cfg) {
    if (cfg.routingProtocol == "aodv" || cfg.routingProtocol == "AODV") {
        AodvHelper aodv;
        aodv.Set("HelloInterval", TimeValue(Seconds(cfg.aodvHelloInterval)));
        aodv.Set("RreqRetries", UintegerValue(cfg.aodvRreqRetries));
        aodv.Set("ActiveRouteTimeout", TimeValue(Seconds(cfg.aodvActiveRouteTimeout)));
        aodv.Set("DeletePeriod", TimeValue(Seconds(cfg.aodvDeletePeriod)));
        aodv.Set("NetDiameter", UintegerValue(cfg.aodvNetDiameter));
        aodv.Set("EnableHello", BooleanValue(cfg.aodvEnableHello));
        stack.SetRoutingHelper(aodv);
        NS_LOG_INFO("Routing: AODV");
    } 
    else if (cfg.routingProtocol == "olsr" || cfg.routingProtocol == "OLSR") {
        OlsrHelper olsr;
        olsr.Set("HelloInterval", TimeValue(Seconds(cfg.olsrHelloInterval)));
        olsr.Set("TcInterval", TimeValue(Seconds(cfg.olsrTcInterval)));
        olsr.Set("MidInterval", TimeValue(Seconds(cfg.olsrMidInterval)));
        olsr.Set("Willingness", UintegerValue(cfg.olsrWilligness));
        stack.SetRoutingHelper(olsr);
        NS_LOG_INFO("Routing: OLSR");
    }
    else if (cfg.routingProtocol == "dsdv" || cfg.routingProtocol == "DSDV") {
        DsdvHelper dsdv;
        dsdv.Set("PeriodicUpdateInterval", TimeValue(Seconds(cfg.dsdvPeriodicUpdateInterval)));
        dsdv.Set("SettlingTime", UintegerValue(cfg.dsdvSettlingTime));
        stack.SetRoutingHelper(dsdv);
        NS_LOG_INFO("Routing: DSDV");
    }
    else if (cfg.routingProtocol == "dsr" || cfg.routingProtocol == "DSR") {
        DsrHelper dsr;
        DsrMainHelper dsrMain;
        // DSR uses different install mechanism
        stack.Install(NodeContainer()); // placeholder, handled below
        NS_LOG_INFO("Routing: DSR (note: DSR requires special handling)");
    }
    else {
        NS_LOG_INFO("Routing: None (flat L2 bridging)");
    }
}

// ============================================================================
// Setup Mobility
// ============================================================================
void SetupMobility(MobilityHelper& mobility, NodeContainer& nodes, const SimConfig& cfg) {
    std::ostringstream xStr, yStr;
    xStr << "ns3::UniformRandomVariable[Min=" << cfg.mobilityMinX << "|Max=" << cfg.mobilityMaxX << "]";
    yStr << "ns3::UniformRandomVariable[Min=" << cfg.mobilityMinY << "|Max=" << cfg.mobilityMaxY << "]";
    
    if (cfg.mobilityModel == "random-walk") {
        mobility.SetPositionAllocator("ns3::RandomRectanglePositionAllocator",
            "X", StringValue(xStr.str()),
            "Y", StringValue(yStr.str()));
        
        std::string modeStr = cfg.rwMode;
        RandomWalk2dMobilityModel::Mode mode = RandomWalk2dMobilityModel::MODE_TIME;
        if (modeStr == "Distance") mode = RandomWalk2dMobilityModel::MODE_DISTANCE;
        
        mobility.SetMobilityModel("ns3::RandomWalk2dMobilityModel",
            "Bounds", RectangleValue(Rectangle(cfg.mobilityMinX, cfg.mobilityMaxX, cfg.mobilityMinY, cfg.mobilityMaxY)),
            "Speed", StringValue("ns3::UniformRandomVariable[Min=" + std::to_string(cfg.rwMinSpeed) + "|Max=" + std::to_string(cfg.rwMaxSpeed) + "]"),
            "Distance", DoubleValue(cfg.rwDistance),
            "Time", TimeValue(Seconds(cfg.rwTime)),
            "Mode", EnumValue(mode));
        NS_LOG_INFO("Mobility: RandomWalk2d");
    }
    else if (cfg.mobilityModel == "gauss-markov") {
        mobility.SetPositionAllocator("ns3::RandomRectanglePositionAllocator",
            "X", StringValue(xStr.str()),
            "Y", StringValue(yStr.str()));
        mobility.SetMobilityModel("ns3::GaussMarkovMobilityModel",
            "Bounds", RectangleValue(Rectangle(cfg.mobilityMinX, cfg.mobilityMaxX, cfg.mobilityMinY, cfg.mobilityMaxY)),
            "Alpha", DoubleValue(cfg.gmAlpha),
            "MeanVelocity", StringValue("ns3::UniformRandomVariable[Min=" + std::to_string(cfg.rwMinSpeed) + "|Max=" + std::to_string(cfg.rwMaxSpeed) + "]"),
            "MeanDirection", DoubleValue(cfg.gmMeanDirection),
            "MeanPitch", DoubleValue(cfg.gmMeanPitch));
        NS_LOG_INFO("Mobility: GaussMarkov");
    }
    else if (cfg.mobilityModel == "grid") {
        mobility.SetPositionAllocator("ns3::GridPositionAllocator",
            "MinX", DoubleValue(cfg.gridMinX),
            "MinY", DoubleValue(cfg.gridMinY),
            "DeltaX", DoubleValue(cfg.gridDeltaX),
            "DeltaY", DoubleValue(cfg.gridDeltaY),
            "GridWidth", UintegerValue(cfg.gridWidth),
            "LayoutType", StringValue(cfg.gridLayout));
        mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
        NS_LOG_INFO("Mobility: Fixed Grid");
    }
    else if (cfg.mobilityModel == "constant") {
        mobility.SetPositionAllocator("ns3::GridPositionAllocator",
            "MinX", DoubleValue(cfg.gridMinX),
            "MinY", DoubleValue(cfg.gridMinY),
            "DeltaX", DoubleValue(cfg.gridDeltaX),
            "DeltaY", DoubleValue(cfg.gridDeltaY),
            "GridWidth", UintegerValue(cfg.gridWidth),
            "LayoutType", StringValue(cfg.gridLayout));
        mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
        NS_LOG_INFO("Mobility: Constant Position");
    }
    else {
        NS_LOG_WARN("Unknown mobility '" << cfg.mobilityModel << "', using grid");
        mobility.SetPositionAllocator("ns3::GridPositionAllocator",
            "MinX", DoubleValue(10.0),
            "MinY", DoubleValue(10.0),
            "DeltaX", DoubleValue(80.0),
            "DeltaY", DoubleValue(80.0),
            "GridWidth", UintegerValue(6),
            "LayoutType", StringValue("RowFirst"));
        mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    }
    
    mobility.Install(nodes);
}

// ============================================================================
// Setup Tracing
// ============================================================================
void SetupTracing(const YansWifiPhyHelper& wifiPhy, const NodeContainer& nodes,
                  const NetDeviceContainer& devices, const SimConfig& cfg) {
    if (cfg.pcapTracing) {
        wifiPhy.EnablePcapAll(cfg.pcapPrefix);
    }
    if (cfg.asciiTracing) {
        AsciiTraceHelper ascii;
        wifiPhy.EnableAsciiAll(ascii.CreateFileStream(cfg.asciiFile));
    }
    if (cfg.enableMobilityTrace) {
        AsciiTraceHelper ascii;
        MobilityHelper::EnableAsciiAll(ascii.CreateFileStream(cfg.pcapPrefix + ".mob"));
    }
}

// ============================================================================
// Print Results
// ============================================================================
void PrintResults(Ptr<FlowMonitor> monitor, const FlowMonitorHelper& flowmon, double simTime) {
    monitor->CheckForLostPackets();
    Ptr<Ipv4FlowClassifier> classifier = DynamicCast<Ipv4FlowClassifier>(flowmon.GetClassifier());
    if (!classifier) return;
    std::map<FlowId, FlowMonitor::FlowStats> stats = monitor->GetFlowStats();

    uint64_t totalTx = 0, totalRx = 0, totalLost = 0;
    double totalDelay = 0.0;
    uint32_t flowCount = 0;

    std::cout << "\n========== Flow Statistics ==========\n";
    for (auto const &flow : stats) {
        Ipv4FlowClassifier::FiveTuple t = classifier->FindFlow(flow.first);
        double delay = flow.second.rxPackets > 0
            ? flow.second.delaySum.GetSeconds() / flow.second.rxPackets : 0.0;
        double throughput = flow.second.rxBytes * 8.0 / simTime / 1e6;

        std::cout << "Flow " << flow.first
                  << " (" << t.sourceAddress << " -> " << t.destinationAddress << ")\n"
                  << "  Tx/Rx: " << flow.second.txPackets << "/" << flow.second.rxPackets
                  << " pkts  Lost: " << flow.second.lostPackets
                  << "  AvgDelay: " << delay << " s"
                  << "  Throughput: " << throughput << " Mbps\n";

        totalTx += flow.second.txPackets;
        totalRx += flow.second.rxPackets;
        totalLost += flow.second.lostPackets;
        totalDelay += flow.second.delaySum.GetSeconds();
        ++flowCount;
    }

    std::cout << "\n--- Aggregate ---\n"
              << "Total Flows: " << flowCount << "\n"
              << "Total Tx:    " << totalTx << " pkts\n"
              << "Total Rx:    " << totalRx << " pkts\n"
              << "Total Lost:  " << totalLost << " pkts"
              << " (" << (totalTx > 0 ? (totalLost * 100.0 / totalTx) : 0.0) << "%)\n"
              << "Avg Delay:   " << (totalRx > 0 ? totalDelay / totalRx : 0.0) << " s\n";
}

// ============================================================================
// MAIN
// ============================================================================
int main(int argc, char *argv[])
{
    SimConfig cfg;
    
    // --- Parse command line ---
    CommandLine cmd;
    
    // General
    cmd.AddValue("configFile", "Configuration file path (.conf format)", cfg.configFile);
    cmd.AddValue("nNodes", "Number of AdHoc nodes", cfg.nNodes);
    cmd.AddValue("simulationTime", "Simulation duration (seconds)", cfg.simulationTime);
    cmd.AddValue("seed", "Random seed", cfg.seed);
    cmd.AddValue("run", "Run number", cfg.run);
    cmd.AddValue("logComponents", "Comma-separated log components", cfg.logComponents);
    
    // PHY
    cmd.AddValue("standard", "802.11 standard (80211b/80211a/80211g/80211n-2.4GHz/80211n-5GHz/80211ac/80211ax-2.4GHz/80211ax-5GHz)", cfg.standard);
    cmd.AddValue("dataRate", "Wifi data rate mode", cfg.dataRate);
    cmd.AddValue("txPowerStart", "Tx power start (dBm)", cfg.txPowerStart);
    cmd.AddValue("txPowerEnd", "Tx power end (dBm)", cfg.txPowerEnd);
    cmd.AddValue("txPowerLevels", "Number of tx power levels", cfg.txPowerLevels);
    cmd.AddValue("rxSensitivity", "Rx sensitivity (dBm)", cfg.rxSensitivity);
    cmd.AddValue("ccaThreshold", "CCA energy detection threshold (dBm)", cfg.ccaThreshold);
    cmd.AddValue("antennaGain", "Antenna gain (dBi)", cfg.antennaGain);
    cmd.AddValue("errorRateModel", "Error rate model (Nist/Yans)", cfg.errorRateModel);
    
    // Propagation
    cmd.AddValue("propagationDelay", "Propagation delay model (ConstantSpeed/Random)", cfg.propagationDelay);
    cmd.AddValue("pathLossModel", "Path loss model (LogDistance/FreeSpace/TwoRayGround/ThreeLogDistance/Cost231/Range)", cfg.pathLossModel);
    cmd.AddValue("pathLossExponent", "Path loss exponent", cfg.pathLossExponent);
    cmd.AddValue("pathLossRefLoss", "Reference loss at 1m (dB)", cfg.pathLossRefLoss);
    cmd.AddValue("pathLossRefDistance", "Reference distance (m)", cfg.pathLossRefDistance);
    cmd.AddValue("enableFading", "Enable fading model", cfg.enableFading);
    cmd.AddValue("fadingModel", "Fading model (Nakagami/Jakes)", cfg.fadingModel);
    cmd.AddValue("nakagamiM0", "Nakagami m parameter (d < d1)", cfg.nakagamiM0);
    cmd.AddValue("nakagamiM1", "Nakagami m parameter (d1 < d < d2)", cfg.nakagamiM1);
    cmd.AddValue("nakagamiM2", "Nakagami m parameter (d > d2)", cfg.nakagamiM2);
    cmd.AddValue("nakagamiD1", "Nakagami distance boundary 1 (m)", cfg.nakagamiD1);
    cmd.AddValue("nakagamiD2", "Nakagami distance boundary 2 (m)", cfg.nakagamiD2);
    
    // MAC
    cmd.AddValue("macType", "MAC type (AdhocWifiMac only)", cfg.macType);
    cmd.AddValue("ssid", "SSID for IBSS", cfg.ssid);
    cmd.AddValue("bssid", "BSSID for IBSS", cfg.bssid);
    cmd.AddValue("rateControl", "Rate control algorithm (Arf/Aarf/Onoe/Constant/Minstrel)", cfg.rateControl);
    cmd.AddValue("rtsCtsThreshold", "RTS/CTS threshold (bytes, 65535=disabled)", cfg.rtsCtsThreshold);
    cmd.AddValue("fragmentationThreshold", "Fragmentation threshold (bytes)", cfg.fragmentationThreshold);
    cmd.AddValue("nonUnicastMode", "Use constant rate for non-unicast", cfg.nonUnicastMode);
    cmd.AddValue("beaconInterval", "Beacon interval (TU)", cfg.beaconInterval);
    cmd.AddValue("enableCtsToSelf", "Enable CTS-to-self", cfg.enableCtsToSelf);
    cmd.AddValue("cwMin", "Minimum contention window", cfg.cwMin);
    cmd.AddValue("cwMax", "Maximum contention window", cfg.cwMax);
    cmd.AddValue("slotTime", "Slot time (microseconds)", cfg.slotTime);
    cmd.AddValue("sifs", "SIFS (microseconds)", cfg.sifs);
    
    // Routing
    cmd.AddValue("routingProtocol", "Routing protocol (aodv/olsr/dsdv/dsr/none)", cfg.routingProtocol);
    cmd.AddValue("aodvHelloInterval", "AODV hello interval (s)", cfg.aodvHelloInterval);
    cmd.AddValue("aodvRreqRetries", "AODV RREQ retries", cfg.aodvRreqRetries);
    cmd.AddValue("aodvActiveRouteTimeout", "AODV active route timeout (s)", cfg.aodvActiveRouteTimeout);
    cmd.AddValue("aodvDeletePeriod", "AODV delete period (s)", cfg.aodvDeletePeriod);
    cmd.AddValue("aodvNetDiameter", "AODV network diameter (hops)", cfg.aodvNetDiameter);
    cmd.AddValue("aodvEnableHello", "AODV enable hello messages", cfg.aodvEnableHello);
    cmd.AddValue("olsrHelloInterval", "OLSR hello interval (s)", cfg.olsrHelloInterval);
    cmd.AddValue("olsrTcInterval", "OLSR TC interval (s)", cfg.olsrTcInterval);
    cmd.AddValue("olsrWillingness", "OLSR willingness (0-7)", cfg.olsrWilligness);
    cmd.AddValue("dsdvPeriodicUpdateInterval", "DSDV update interval (s)", cfg.dsdvPeriodicUpdateInterval);
    cmd.AddValue("dsdvSettlingTime", "DSDV settling time multiplier", cfg.dsdvSettlingTime);
    cmd.AddValue("dsrMaxSendBuffLen", "DSR send buffer length", cfg.dsrMaxSendBuffLen);
    cmd.AddValue("dsrMaxRreqRetx", "DSR RREQ max retransmissions", cfg.dsrMaxRreqRetx);
    
    // Mobility
    cmd.AddValue("mobilityModel", "Mobility model (random-walk/gauss-markov/grid/constant)", cfg.mobilityModel);
    cmd.AddValue("mobilityMinX", "Mobility area min X", cfg.mobilityMinX);
    cmd.AddValue("mobilityMaxX", "Mobility area max X", cfg.mobilityMaxX);
    cmd.AddValue("mobilityMinY", "Mobility area min Y", cfg.mobilityMinY);
    cmd.AddValue("mobilityMaxY", "Mobility area max Y", cfg.mobilityMaxY);
    cmd.AddValue("rwMinSpeed", "RandomWalk min speed (m/s)", cfg.rwMinSpeed);
    cmd.AddValue("rwMaxSpeed", "RandomWalk max speed (m/s)", cfg.rwMaxSpeed);
    cmd.AddValue("rwDistance", "RandomWalk distance mode (m)", cfg.rwDistance);
    cmd.AddValue("rwMode", "RandomWalk mode (Time/Distance)", cfg.rwMode);
    cmd.AddValue("rwTime", "RandomWalk time step (s)", cfg.rwTime);
    cmd.AddValue("gridMinX", "Grid start X", cfg.gridMinX);
    cmd.AddValue("gridMinY", "Grid start Y", cfg.gridMinY);
    cmd.AddValue("gridDeltaX", "Grid spacing X", cfg.gridDeltaX);
    cmd.AddValue("gridDeltaY", "Grid spacing Y", cfg.gridDeltaY);
    cmd.AddValue("gridWidth", "Grid nodes per row", cfg.gridWidth);
    cmd.AddValue("gridLayout", "Grid layout (RowFirst/ColumnFirst)", cfg.gridLayout);
    cmd.AddValue("gmAlpha", "GaussMarkov alpha (0-1)", cfg.gmAlpha);
    cmd.AddValue("ns2TraceFile", "NS-2 movement trace file", cfg.ns2TraceFile);
    
    // Tracing
    cmd.AddValue("pcap", "Enable PCAP tracing", cfg.pcapTracing);
    cmd.AddValue("ascii", "Enable ASCII tracing", cfg.asciiTracing);
    cmd.AddValue("flowMonitor", "Enable FlowMonitor", cfg.flowMonitor);
    cmd.AddValue("pcapPrefix", "PCAP filename prefix", cfg.pcapPrefix);
    cmd.AddValue("asciiFile", "ASCII trace filename", cfg.asciiFile);
    cmd.AddValue("enableMobilityTrace", "Enable mobility ASCII trace", cfg.enableMobilityTrace);
    
    // TapBridge
    cmd.AddValue("tapMode", "TapBridge mode (UseBridge/UseLocal/UseLocalBridge)", cfg.tapMode);
    cmd.AddValue("tapPrefix", "TAP device name prefix", cfg.tapPrefix);
    cmd.Parse(argc, argv);
    
    // Load config file if specified
    if (!cfg.configFile.empty()) {
        cfg = ParseConfigFile(cfg.configFile);
    }
    
    // Apply CW defaults
    Config::SetDefault("ns3::DcfState::CwMin", UintegerValue(cfg.cwMin));
    Config::SetDefault("ns3::DcfState::CwMax", UintegerValue(cfg.cwMax));
    
    // Seed
    RngSeedManager::SetSeed(cfg.seed);
    RngSeedManager::SetRun(cfg.run);
    
    // Enable logging if requested
    if (!cfg.logComponents.empty()) {
        std::istringstream iss(cfg.logComponents);
        std::string comp;
        while (std::getline(iss, comp, ',')) {
            LogComponentEnable(comp.c_str(), LOG_LEVEL_INFO);
        }
    }
    
    // Realtime mode for TapBridge
    GlobalValue::Bind("SimulatorImplementationType",
                      StringValue("ns3::RealtimeSimulatorImpl"));
    GlobalValue::Bind("ChecksumEnabled", BooleanValue(true));
    
    PrintConfig(cfg);
    
    // ================================================================
    // Create Nodes
    // ================================================================
    NodeContainer nodes;
    nodes.Create(cfg.nNodes);
    
    // ================================================================
    // 1. PHY + Channel
    // ================================================================
    YansWifiChannelHelper wifiChannel;
    SetupPropagation(wifiChannel, cfg);
    
    YansWifiPhyHelper wifiPhy;
    wifiPhy.SetChannel(wifiChannel.Create());
    wifiPhy.Set("TxPowerStart", DoubleValue(cfg.txPowerStart));
    wifiPhy.Set("TxPowerEnd", DoubleValue(cfg.txPowerEnd));
    wifiPhy.Set("TxPowerLevels", UintegerValue(cfg.txPowerLevels));
    wifiPhy.Set("RxSensitivity", DoubleValue(cfg.rxSensitivity));
    wifiPhy.Set("CcaEdThreshold", DoubleValue(cfg.ccaThreshold));
    if (cfg.antennaGain != 0.0) {
        wifiPhy.Set("RxGain", DoubleValue(cfg.antennaGain));
        wifiPhy.Set("TxGain", DoubleValue(cfg.antennaGain));
    }
    
    // ================================================================
    // 2. WiFi Standard + Rate Control
    // ================================================================
    WifiHelper wifi;
    SetupWifiStandard(wifi, cfg.standard);
    SetupRateControl(wifi, cfg);
    
    // ================================================================
    // 3. MAC (AdHoc IBSS)
    // ================================================================
    WifiMacHelper wifiMac;
    Mac48AddressValue bssidValue(Mac48Address(cfg.bssid.c_str()));
    wifiMac.SetType("ns3::AdhocWifiMac",
                    "Ssid", SsidValue(Ssid(cfg.ssid)),
                    "Bssid", bssidValue);
    
    if (cfg.beaconInterval != 100) {
        Config::SetDefault("ns3::AdhocWifiMac::BeaconInterval", 
                           TimeValue(MicroSeconds(1024 * cfg.beaconInterval)));
    }
    
    NetDeviceContainer devices = wifi.Install(wifiPhy, wifiMac, nodes);
    
    // ================================================================
    // 4. Mobility
    // ================================================================
    MobilityHelper mobility;
    SetupMobility(mobility, nodes, cfg);
    
    // ================================================================
    // 5. Internet Stack + Routing
    // ================================================================
    InternetStackHelper stack;
    SetupRouting(stack, cfg);
    stack.Install(nodes);
    
    Ipv4AddressHelper address;
    address.SetBase("10.0.0.0", "255.255.255.0");
    Ipv4InterfaceContainer interfaces = address.Assign(devices);
    
    // ================================================================
    // 6. TapBridge
    // ================================================================
    TapBridgeHelper tapBridge;
    tapBridge.SetAttribute("Mode", StringValue(cfg.tapMode));
    
    if (cfg.tapBridgeAll) {
        for (uint32_t i = 0; i < cfg.nNodes; ++i) {
            std::string tapName = cfg.tapPrefix + std::to_string(i);
            tapBridge.SetAttribute("DeviceName", StringValue(tapName));
            tapBridge.Install(nodes.Get(i), devices.Get(i));
        }
    }
    
    // ================================================================
    // 7. Tracing
    // ================================================================
    SetupTracing(wifiPhy, nodes, devices, cfg);
    
    // ================================================================
    // 8. FlowMonitor
    // ================================================================
    Ptr<FlowMonitor> monitor;
    FlowMonitorHelper flowmon;
    if (cfg.flowMonitor) {
        monitor = flowmon.InstallAll();
    }
    
    // ================================================================
    // 9. Run
    // ================================================================
    Simulator::Stop(Seconds(cfg.simulationTime));
    std::cout << "=== Starting simulation ===\n";
    Simulator::Run();
    
    // ================================================================
    // 10. Results
    // ================================================================
    if (cfg.flowMonitor && monitor) {
        PrintResults(monitor, flowmon, cfg.simulationTime);
    }
    
    std::cout << "\n=== Simulation complete ===\n";
    Simulator::Destroy();
    return 0;
}
