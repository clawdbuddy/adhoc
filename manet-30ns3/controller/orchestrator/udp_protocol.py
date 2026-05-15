"""UDP 二进制协议帧编解码（api_54.docx 格式）。

帧格式（大端序）:
    [comm_type(1)][res(1)][res(1)][cmd_id(2)][length(2)][payload(N)]
    帧头固定 7 字节，总长度 = 7 + N
"""
from __future__ import annotations

import struct
from typing import Self


class UdpFrame:
    """UDP 协议帧，7 字节头 + N 字节载荷。"""

    HEADER_FMT = ">BBBH"  # comm_type, res, res, cmd_id
    LENGTH_FMT = ">H"     # length (big-endian)
    HEADER_SIZE = 7

    def __init__(self, comm_type: int, cmd_id: int, payload: bytes = b"") -> None:
        self.comm_type = comm_type  # 1=自组网, 3=测控链
        self.res1 = 0
        self.res2 = 0
        self.cmd_id = cmd_id
        self.payload = payload

    @property
    def length(self) -> int:
        return len(self.payload)

    def encode(self) -> bytes:
        header = struct.pack(self.HEADER_FMT, self.comm_type, 0, 0, self.cmd_id)
        length = struct.pack(self.LENGTH_FMT, self.length)
        return header + length + self.payload

    @classmethod
    def decode(cls, data: bytes) -> Self:
        if len(data) < cls.HEADER_SIZE:
            raise ValueError(f"帧太短: {len(data)} < {cls.HEADER_SIZE}")
        comm_type, res1, res2, cmd_id = struct.unpack(cls.HEADER_FMT, data[:5])
        length, = struct.unpack(cls.LENGTH_FMT, data[5:7])
        payload = data[7 : 7 + length]
        if len(payload) != length:
            raise ValueError(f"载荷长度不匹配: expect={length}, got={len(payload)}")
        return cls(comm_type, cmd_id, payload)

    def __repr__(self) -> str:
        return (
            f"UdpFrame(comm_type=0x{self.comm_type:02X}, "
            f"cmd_id=0x{self.cmd_id:04X}, length={self.length})"
        )


# ---------------------------------------------------------------------------
# BCD 编解码辅助函数
# ---------------------------------------------------------------------------

def bcd4_to_mhz(data: bytes) -> float:
    """4 字节压缩 BCD → MHz。

    字节布局（api_54.docx §4.1.1 0x0004）:
        BYTE[0] low-nibble = 1000M digit
        BYTE[1] high/low   = 100M, 10M
        BYTE[2] high/low   = 1M, 100K
        BYTE[3] high/low   = 10K, 1K
    """
    if len(data) != 4:
        raise ValueError(f"BCD4 需要 4 字节，收到 {len(data)}")
    d1000m = data[0] & 0x0F
    d100m = (data[1] >> 4) & 0x0F
    d10m = data[1] & 0x0F
    d1m = (data[2] >> 4) & 0x0F
    d100k = data[2] & 0x0F
    d10k = (data[3] >> 4) & 0x0F
    d1k = data[3] & 0x0F
    return (
        d1000m * 1000.0
        + d100m * 100.0
        + d10m * 10.0
        + d1m
        + d100k * 0.1
        + d10k * 0.01
        + d1k * 0.001
    )


def mhz_to_bcd4(mhz: float) -> bytes:
    """MHz → 4 字节压缩 BCD。"""
    mhz = round(mhz, 3)
    whole = int(mhz)
    frac = int(round((mhz - whole) * 1000))

    d1000m = (whole // 1000) & 0x0F
    whole %= 1000
    d100m = (whole // 100) & 0x0F
    whole %= 100
    d10m = (whole // 10) & 0x0F
    d1m = whole % 10

    d100k = (frac // 100) & 0x0F
    frac %= 100
    d10k = (frac // 10) & 0x0F
    d1k = frac % 10

    return bytes([
        d1000m,
        (d100m << 4) | d10m,
        (d1m << 4) | d100k,
        (d10k << 4) | d1k,
    ])


def bcd1_to_int(data: bytes) -> int:
    """1 字节压缩 BCD → int。"""
    if len(data) != 1:
        raise ValueError(f"BCD1 需要 1 字节，收到 {len(data)}")
    return ((data[0] >> 4) & 0x0F) * 10 + (data[0] & 0x0F)


def int_to_bcd1(val: int) -> bytes:
    """Int → 1 字节压缩 BCD。"""
    tens = (val // 10) & 0x0F
    ones = val % 10
    return bytes([(tens << 4) | ones])
