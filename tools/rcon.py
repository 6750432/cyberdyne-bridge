#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1 测试用的小 RCON 客户端（纯标准库）。

为什么需要它：MC 服务端启动时 stdin 接了 /dev/null，没法从外面敲命令。
开了 RCON 之后就能随时随地：
    /summon 一只僵尸来试试小家伙会不会跑
    /give   点吃的来试试它会不会吃
    /difficulty 调难度

用法：
    python3 rcon.py "summon zombie 4 80 -4"
    python3 rcon.py --多 "time set night" "difficulty normal"
"""
import argparse
import os
import socket
import struct
import sys

HOST = "127.0.0.1"
PORT = 25575
密码 = os.environ.get("MC_RCON_PASSWORD", "")


class RCON:
    def __init__(self, host=HOST, port=PORT, password=密码, 超时=6):
        self.编号 = 0
        self.s = socket.create_connection((host, port), 超时)
        self.s.settimeout(超时)
        self._发(3, password)
        包 = self._收()
        if 包 is None:
            raise RuntimeError("RCON 没回话")
        if 包[0] == -1:
            raise RuntimeError("RCON 认证失败（密码不对？）")

    def _发(self, 类型, 正文):
        self.编号 += 1
        体 = struct.pack("<ii", self.编号, 类型) + 正文.encode("utf-8") + b"\x00\x00"
        self.s.sendall(struct.pack("<i", len(体)) + 体)
        return self.编号

    def _收齐(self, n):
        缓冲 = b""
        while len(缓冲) < n:
            块 = self.s.recv(n - len(缓冲))
            if not 块:
                return None
            缓冲 += 块
        return 缓冲

    def _收(self):
        头 = self._收齐(4)
        if not 头:
            return None
        长 = struct.unpack("<i", 头)[0]
        体 = self._收齐(长)
        if not 体:
            return None
        编号, 类型 = struct.unpack("<ii", 体[:8])
        return 编号, 类型, 体[8:-2].decode("utf-8", "replace")

    def 命令(self, 文本):
        self._发(2, 文本)
        包 = self._收()
        return 包[2] if 包 else ""

    def 关(self):
        try:
            self.s.close()
        except Exception:
            pass


def 主():
    p = argparse.ArgumentParser(description="M1 测试用小 RCON 客户端")
    p.add_argument("命令", nargs="*", help="要发的服务端指令（不带斜杠）")
    p.add_argument("--多", action="store_true", help="命令之间不退出，共用一条连接")
    p.add_argument("--端口", type=int, default=PORT)
    a = p.parse_args()
    if not a.命令:
        print(__doc__)
        return 1
    try:
        r = RCON(port=a.端口)
    except Exception as e:
        print(f"连不上 RCON：{e}")
        return 1
    try:
        for c in a.命令:
            出 = r.命令(c)
            print(f"> {c}\n{出.strip()}" if 出.strip() else f"> {c}\n（服务端没回话）")
    finally:
        r.关()
    return 0


if __name__ == "__main__":
    sys.exit(主())
