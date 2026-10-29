#pragma once
#include <Python.h>
#include <functional>
#include <algorithm>
#include <ns3/simulator.h>
#include <ns3/nstime.h>
#include <ns3/net-device-container.h>
#include <ns3/wifi-net-device.h>
#include <ns3/mesh-point-device.h>
#include <ns3/peer-management-protocol.h>
#include <ns3/peer-link.h>

namespace manet {
// cppyy 只需转换构造参数；Schedule 始终接收原生 C++ 成员函数。
class Runtime {
public:
    explicit Runtime(std::function<void()> callback) : m_callback(std::move(callback)) {}
    void Start() { ns3::Simulator::ScheduleNow(&Runtime::Tick, this); }
    void Run() {
        auto* saved = PyEval_SaveThread();
        try { ns3::Simulator::Run(); }
        catch (...) { PyEval_RestoreThread(saved); throw; }
        PyEval_RestoreThread(saved);
    }
    static std::vector<uint32_t> Neighbors(const ns3::NetDeviceContainer& devices, uint32_t i) {
        std::vector<uint32_t> result;
        auto mesh = devices.Get(i)->GetObject<ns3::MeshPointDevice>();
        if (!mesh) return result;
        auto pmp = mesh->GetObject<ns3::dot11s::PeerManagementProtocol>();
        if (!pmp) return result;
        for (auto link : pmp->GetPeerLinks()) {
            for (uint32_t j = 0; j < devices.GetN(); ++j) {
                if (i == j) continue;
                auto other = devices.Get(j)->GetObject<ns3::MeshPointDevice>();
                if (!other) continue;
                for (auto iface : other->GetInterfaces()) {
                    if (iface->GetAddress() == link->GetPeerAddress()) {
                        if (std::find(result.begin(), result.end(), j) == result.end()) result.push_back(j);
                    }
                }
            }
        }
        return result;
    }
private:
    void Tick() {
        auto gil = PyGILState_Ensure();
        try { m_callback(); }
        catch (...) { PyGILState_Release(gil); throw; }
        PyGILState_Release(gil);
        ns3::Simulator::Schedule(ns3::MilliSeconds(100), &Runtime::Tick, this);
    }
    std::function<void()> m_callback;
};
}
