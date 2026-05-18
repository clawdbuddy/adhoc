#!/usr/bin/env python3
"""UDP 二进制协议测试脚本（api_54.docx）。

用法:
    python3 test_udp_protocol.py [--host 127.0.0.1] [--port 62450]

测试项:
    1. 静态参数查询 (0x0041~0x0045)
    2. 静态参数设置 (0x0001~0x0005) + ACK/NACK
    3. 动态参数查询 (0x0141~0x0142)
    4. 动态参数设置 (0x0101~0x0102) + ACK/NACK
    5. 版本查询 (0x0203)
    6. 拓扑查询 (0x0310) — 仿真未运行时预期返回 NACK
    7. 周期上报 — 订阅后等待 5~6 秒接收 0x0310 / 0x02AF
"""
from __future__ import annotations

import argparse
import socket
import struct
import sys
import time


def build_frame(cmd_id: int, payload: bytes = b"", comm_type: int = 1) -> bytes:
    """构造 UDP 协议帧。"""
    header = struct.pack(">BBBH", comm_type, 0, 0, cmd_id)
    length = struct.pack(">H", len(payload))
    return header + length + payload


def parse_frame(data: bytes) -> tuple[int, int, bytes]:
    """解析 UDP 协议帧，返回 (comm_type, cmd_id, payload)。"""
    if len(data) < 7:
        raise ValueError(f"帧太短: {len(data)}")
    comm_type, _, _, cmd_id = struct.unpack(">BBBH", data[:5])
    length, = struct.unpack(">H", data[5:7])
    payload = data[7 : 7 + length]
    return comm_type, cmd_id, payload


def hex_bytes(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


class UdpTester:
    def __init__(self, host: str, port: int, timeout: float = 3.0):
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(timeout)
        self.sock.bind(("0.0.0.0", 0))  # 任意源端口

    def send_recv(self, cmd_id: int, payload: bytes = b"", comm_type: int = 1) -> tuple[int, int, bytes] | None:
        """发送一帧并等待响应。返回 (comm_type, cmd_id, payload) 或 None（超时）。"""
        req = build_frame(cmd_id, payload, comm_type)
        self.sock.sendto(req, (self.host, self.port))
        try:
            data, addr = self.sock.recvfrom(2048)
            return parse_frame(data)
        except socket.timeout:
            return None

    # ------------------------------------------------------------------ 测试用例

    def test_static_query(self) -> bool:
        """测试静态参数查询。"""
        print("\n[1] 静态参数查询")
        ok = True
        queries = [
            (0x0041, 0x0081, "网络规模"),
            (0x0042, 0x0082, "工作模式"),
            (0x0043, 0x0083, "MAC 地址"),
            (0x0044, 0x0084, "定频频率"),
            (0x0045, 0x0085, "跳频表号"),
        ]
        for req_cmd, expected_resp_cmd, name in queries:
            resp = self.send_recv(req_cmd)
            if resp is None:
                print(f"  FAIL [{name}] 超时")
                ok = False
                continue
            _, resp_cmd, payload = resp
            if resp_cmd == expected_resp_cmd:
                print(f"  PASS [{name}] 0x{resp_cmd:04X} payload={hex_bytes(payload)}")
            else:
                print(f"  FAIL [{name}] 期望 0x{expected_resp_cmd:04X}, 收到 0x{resp_cmd:04X}")
                ok = False
        return ok

    def test_static_set(self) -> bool:
        """测试静态参数设置 + ACK/NACK。"""
        print("\n[2] 静态参数设置")
        ok = True

        # 2.1 设置网络规模 = 8 (0x0008)
        resp = self.send_recv(0x0001, struct.pack(">H", 8))
        ok = self._check_ack(resp, 0x0001, "设置网络规模=8") and ok

        # 2.2 设置工作模式 = 2 (FCS)
        resp = self.send_recv(0x0002, bytes([2]))
        ok = self._check_ack(resp, 0x0002, "设置工作模式=2") and ok

        # 2.3 设置 MAC 地址 = 10
        resp = self.send_recv(0x0003, struct.pack(">H", 10))
        ok = self._check_ack(resp, 0x0003, "设置 MAC 地址=10") and ok

        # 2.4 设置定频频率 = 505.54 MHz (BCD: 00 50 55 40)
        resp = self.send_recv(0x0004, bytes([0x00, 0x50, 0x55, 0x40]))
        ok = self._check_ack(resp, 0x0004, "设置频率=505.54MHz") and ok

        # 2.5 设置跳频表号 = 5
        resp = self.send_recv(0x0005, bytes([5]))
        ok = self._check_ack(resp, 0x0005, "设置跳频表号=5") and ok

        # 2.6 查询验证写入值
        print("  查询验证...")
        resp = self.send_recv(0x0041)
        if resp and resp[1] == 0x0081:
            val = struct.unpack(">H", resp[2])[0]
            print(f"    网络规模 = {val} {'PASS' if val == 8 else 'FAIL'}")
            ok = ok and (val == 8)

        resp = self.send_recv(0x0044)
        if resp and resp[1] == 0x0084:
            # BCD 解码简单验证
            print(f"    频率 payload = {hex_bytes(resp[2])}")

        return ok

    def test_dynamic_query(self) -> bool:
        """测试动态参数查询。"""
        print("\n[3] 动态参数查询")
        ok = True
        queries = [
            (0x0141, 0x0181, "传输速率"),
            (0x0142, 0x0182, "发射功率"),
        ]
        for req_cmd, expected_resp_cmd, name in queries:
            resp = self.send_recv(req_cmd)
            if resp is None:
                print(f"  FAIL [{name}] 超时")
                ok = False
                continue
            _, resp_cmd, payload = resp
            if resp_cmd == expected_resp_cmd:
                print(f"  PASS [{name}] 0x{resp_cmd:04X} payload={hex_bytes(payload)}")
            else:
                print(f"  FAIL [{name}] 期望 0x{expected_resp_cmd:04X}, 收到 0x{resp_cmd:04X}")
                ok = False
        return ok

    def test_dynamic_set(self) -> bool:
        """测试动态参数设置。"""
        print("\n[4] 动态参数设置")
        ok = True

        # 4.1 设置速率档位 = 5 (宽 4Mbps)
        resp = self.send_recv(0x0101, bytes([0x05]))
        ok = self._check_ack(resp, 0x0101, "设置速率档位=5") and ok

        # 4.2 设置功率档位 = 2 (小功率)
        resp = self.send_recv(0x0102, bytes([0x02]))
        ok = self._check_ack(resp, 0x0102, "设置功率档位=2") and ok

        # 4.3 查询验证
        resp = self.send_recv(0x0141)
        if resp and resp[1] == 0x0181 and len(resp[2]) == 1:
            level = resp[2][0]
            print(f"    速率档位 = {level} {'PASS' if level == 5 else 'FAIL'}")
            ok = ok and (level == 5)

        resp = self.send_recv(0x0142)
        if resp and resp[1] == 0x0182 and len(resp[2]) == 1:
            level = resp[2][0]
            print(f"    功率档位 = {level} {'PASS' if level == 2 else 'FAIL'}")
            ok = ok and (level == 2)

        return ok

    def test_version(self) -> bool:
        """测试版本查询。"""
        print("\n[5] 版本查询")
        resp = self.send_recv(0x0203)
        if resp is None:
            print("  FAIL 超时")
            return False
        _, resp_cmd, payload = resp
        if resp_cmd == 0x02A3:
            version = payload.decode("ascii", errors="replace")
            print(f"  PASS 版本 = {version}")
            return True
        else:
            print(f"  FAIL 期望 0x02A3, 收到 0x{resp_cmd:04X}")
            return False

    def test_topology(self) -> bool:
        """测试拓扑查询 — 仿真未运行时预期返回 NACK。"""
        print("\n[6] 拓扑查询（仿真未运行）")
        resp = self.send_recv(0x0310)
        if resp is None:
            print("  FAIL 超时")
            return False
        _, resp_cmd, payload = resp
        if resp_cmd == 0x02A1:  # NACK
            acked_cmd = struct.unpack(">H", payload)[0]
            print(f"  PASS 返回 NACK (仿真未运行), acked_cmd=0x{acked_cmd:04X}")
            return True
        elif resp_cmd == 0x0310:
            print(f"  INFO 返回拓扑数据 payload={hex_bytes(payload)}")
            return True
        else:
            print(f"  FAIL 期望 NACK 或 0x0310, 收到 0x{resp_cmd:04X}")
            return False

    def test_periodic_report(self) -> bool:
        """测试周期上报 — 等待 6 秒接收自动推送。"""
        print("\n[7] 周期上报（等待 6 秒）")
        print("  先发送一帧以激活订阅...")
        self.send_recv(0x0041)  # 任意合法帧，使控制器记录源地址

        print("  等待 0x0310 拓扑 / 0x02AF 状态上报...")
        self.sock.settimeout(6.5)
        found_topo = False
        found_status = False
        deadline = time.time() + 6.0
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            self.sock.settimeout(max(0.1, remaining))
            try:
                data, addr = self.sock.recvfrom(2048)
                _, cmd_id, payload = parse_frame(data)
                if cmd_id == 0x0310:
                    print(f"  收到拓扑上报 0x0310 payload_len={len(payload)}")
                    found_topo = True
                elif cmd_id == 0x02AF:
                    print(f"  收到状态上报 0x02AF payload={hex_bytes(payload)}")
                    found_status = True
            except socket.timeout:
                pass

        ok = found_topo or found_status
        if not ok:
            print("  WARN 未收到周期上报（仿真未运行时不发送）")
        return ok

    # ------------------------------------------------------------------ 辅助

    def _check_ack(self, resp: tuple | None, expected_ack_cmd: int, desc: str) -> bool:
        if resp is None:
            print(f"  FAIL [{desc}] 超时")
            return False
        _, resp_cmd, payload = resp
        if resp_cmd == 0x02A0:  # ACK
            acked = struct.unpack(">H", payload)[0]
            if acked == expected_ack_cmd:
                print(f"  PASS [{desc}] ACK")
                return True
            else:
                print(f"  FAIL [{desc}] ACK 了错误的命令 0x{acked:04X}")
                return False
        elif resp_cmd == 0x02A1:  # NACK
            acked = struct.unpack(">H", payload)[0]
            print(f"  FAIL [{desc}] NACK (acked=0x{acked:04X})")
            return False
        else:
            print(f"  FAIL [{desc}] 意外响应 0x{resp_cmd:04X}")
            return False

    def close(self) -> None:
        self.sock.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="UDP 二进制协议测试")
    parser.add_argument("--host", default="127.0.0.1", help="控制器地址")
    parser.add_argument("--port", type=int, default=62450, help="UDP 端口")
    parser.add_argument("--skip-periodic", action="store_true", help="跳过周期上报测试")
    args = parser.parse_args()

    tester = UdpTester(args.host, args.port)
    all_ok = True
    try:
        all_ok = tester.test_static_query() and all_ok
        all_ok = tester.test_static_set() and all_ok
        all_ok = tester.test_dynamic_query() and all_ok
        all_ok = tester.test_dynamic_set() and all_ok
        all_ok = tester.test_version() and all_ok
        all_ok = tester.test_topology() and all_ok
        if not args.skip_periodic:
            tester.test_periodic_report()  # 不影响总结果
    finally:
        tester.close()

    print("\n" + "=" * 50)
    if all_ok:
        print("所有测试通过!")
        return 0
    else:
        print("部分测试失败，请检查日志。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
