#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""老祖版 · 手（纯标准库 MC 客户端）  2026-10-09

═══ 为什么要重写 ═══
  · 脑（bridge.py）本来就是**纯标准库** ✓ 整列车只有手是外来的 ✗
  · Node 手拖着 **471 MB node_modules / 88 个包** ✗（mineflayer 自己 1 万行）
  · C++ 那一轮最大的收获不是二进制 ✓ 是**协议全被撞明白了** ✓
      ⇒ 那套知识搬到 Python **只要几百行** ✓（socket/zlib/struct **全在标准库** ✓）

═══ 老祖思想（这一版的三条铁律）═══
  ① **手搓**，不装东西 ✓ —— 只用 socket / zlib / struct / json / threading ✓
  ② **不知道就说不知道** ✗ —— 查不到的方块返回 None ✓ **绝不编一个假的** ✗
     （编了 = 脑照着假世界做决定 ✓ 比报错危险得多 ✓）
  ③ **形状不对就出声** ✗ —— 解压失败/版式歪掉一律喊 ✓ 静默是这个项目最大的罪 ✓

═══ 今天用血换来的协议细节（一句都别丢 ✗）═══
  · 压缩：**一包一个独立的 zlib 流**（每包以 78 9C 开头 ✓）
    ⇒ `zlib.decompress(块)` 一行就行 ✓ 不用手搓 inflate ✗
    症状对照：小包（<256 字节）不压能过 ✓ 一压就全挂 ✗ ⇒ 登录正常而区块全废 ✓
  · 字节序：**全大端** ✓ 位置用 `struct.unpack(">ddd", …)` ✓
  · configuration 是**对话** ✗ 有两处"服务端等你回话"：
      ① select_known_packs(0x0E) 不回 → 它不发注册表、不发 finish
      ② add_resource_pack(0x09) 不回 → 同上；而且回话里**必须带上它给的 UUID** ✗
         （少那 16 字节 → 服务端 DecoderException 直接踢 ✓ 今天实测 ✓）
  · 1.20.3 起**踢人理由是 NBT 文本组件** ✗ 不是字符串 ✓ ⇒ 读不出来就捞明文 ✓
  · NBT：1.20.2 起**匿名根**（根标签不带名字 ✗）
  · 区块正文的版式协议表里**没写** ✗ 得自己解（调色板 + 位打包 ✓ 条目不跨 long ✓）

用法：
    python3 手.py                  # 跑起来，接线口开在 ./手-py.sock
    python3 手.py --自检           # 连上 → 收区块 → 报脚底方块 → 点一遍名 → 退出
    python3 手.py --接线口 路径
"""

import argparse
import json
import os
import socket
import struct
import sys
import threading
import time
import zlib

# ═══════════════ 一、包号（照 proto.yml 掏的 ✓ 不是我编的 ✓）═══════════════
协议版本 = 767                    # 1.21.1

握手 = {0x00: "set_protocol"}
登录_服务器 = {0x00: "login_start", 0x03: "login_acknowledged"}
登录_客户端 = {0x00: "disconnect", 0x01: "encryption_begin", 0x02: "success", 0x03: "compress"}

配置_客户端 = {                    # 服务端 → 我 ✓
    0x00: "cookie_request", 0x01: "custom_payload", 0x02: "disconnect",
    0x03: "finish_configuration", 0x04: "keep_alive", 0x05: "ping",
    0x06: "reset_chat", 0x07: "registry_data", 0x08: "remove_resource_pack",
    0x09: "add_resource_pack", 0x0A: "store_cookie", 0x0B: "transfer",
    0x0C: "feature_flags", 0x0D: "tags", 0x0E: "select_known_packs",
    0x0F: "custom_report_details", 0x10: "server_links",
}
配置_服务器 = {                    # 我 → 服务端 ✓
    0x00: "settings", 0x01: "cookie_response", 0x02: "custom_payload",
    0x03: "finish_configuration", 0x04: "keep_alive", 0x05: "pong",
    0x06: "resource_pack_receive", 0x07: "select_known_packs",
    0x08: "custom_report_details", 0x09: "server_links",
}
play_客户端 = {
    0x0C: "chunk_batch_finished", 0x0D: "chunk_batch_start", 0x1D: "kick_disconnect",
    0x22: "game_state_change", 0x26: "keep_alive", 0x27: "map_chunk",
    0x2B: "login", 0x40: "position", 0x5D: "update_health", 0x6C: "system_chat",
}
play_服务器 = {
    0x00: "teleport_confirm", 0x08: "chunk_batch_received", 0x09: "client_command",
    0x0A: "settings", 0x18: "keep_alive",
}

# ═══════════════ 二、读写（全大端 ✓ 跟 MC 协议一致 ✓）═══════════════
class 读:
    """一堆字节的游标 ✓ 越界就**喊** ✗ 不假装没事 ✓"""
    __slots__ = ("b", "o", "坏")

    def __init__(self, b, o=0):
        self.b = b
        self.o = o
        self.坏 = False

    def 余(self):
        return len(self.b) - self.o

    def 字节(self):
        if self.o + 1 > len(self.b):
            self.坏 = True
            return 0
        v = self.b[self.o]
        self.o += 1
        return v

    def 短(self):
        if self.o + 2 > len(self.b):
            self.坏 = True
            return 0
        v = struct.unpack_from(">H", self.b, self.o)[0]
        self.o += 2
        return v

    def 带号短(self):
        if self.o + 2 > len(self.b):
            self.坏 = True
            return 0
        v = struct.unpack_from(">h", self.b, self.o)[0]
        self.o += 2
        return v

    def 整(self):
        if self.o + 4 > len(self.b):
            self.坏 = True
            return 0
        v = struct.unpack_from(">i", self.b, self.o)[0]
        self.o += 4
        return v

    def 长整(self):
        if self.o + 8 > len(self.b):
            self.坏 = True
            return 0
        v = struct.unpack_from(">q", self.b, self.o)[0]
        self.o += 8
        return v

    def 变长(self):
        v = 0
        for i in range(5):
            if self.o + 1 > len(self.b):
                self.坏 = True
                return 0
            b = self.b[self.o]
            self.o += 1
            v |= (b & 0x7F) << (7 * i)
            if not (b & 0x80):
                return v
        self.坏 = True
        return 0

    def 跳(self, k):
        if self.o + k > len(self.b):
            self.坏 = True
            return False
        self.o += k
        return True

    def 取(self, k):
        if self.o + k > len(self.b):
            self.坏 = True
            return b""
        v = self.b[self.o:self.o + k]
        self.o += k
        return v

    # ── NBT 跳过 ✓（**匿名根**：根标签不带名字 ✗）──
    def 跳NBT(self):
        return self.跳NBT体(self.字节())

    def 跳NBT体(self, 型):
        if 型 == 0:
            return True
        if 型 == 1:
            return self.跳(1)
        if 型 == 2:
            return self.跳(2)
        if 型 in (3, 5):
            return self.跳(4)
        if 型 in (4, 6):
            return self.跳(8)
        if 型 == 7:
            return self.跳(self.整())
        if 型 == 8:
            return self.跳(self.短())
        if 型 == 9:
            元 = self.字节()
            n = self.整()
            for _ in range(max(0, n)):
                if not self.跳NBT体(元):
                    return False
            return not self.坏
        if 型 == 10:
            while True:
                t = self.字节()
                if self.坏:
                    return False
                if t == 0:
                    return True
                if not self.跳(self.短()):
                    return False
                if not self.跳NBT体(t):
                    return False
        if 型 == 11:
            return self.跳(self.整() * 4)
        if 型 == 12:
            return self.跳(self.整() * 8)
        self.坏 = True
        return False


def 写变长(v):
    出 = bytearray()
    while True:
        出.append(v & 0x7F)
        v >>= 7
        if not v:
            return bytes(出)
        出[-1] |= 0x80


def 写串(s):
    b = s.encode("utf-8")
    return 写变长(len(b)) + b


# ═══════════════ 三、方块表（stateId ↔ 名字 ✓ 从 minecraft-data 掏 ✓）═══════════════
方块表 = []          # [(起, 止, 名字), …] 按 起 排序 ✓


def 装方块表(路径):
    """minecraft-data 的 blocks.json ✓ vanilla 注册表 ✓ 1060 个方块 ✓"""
    global 方块表
    with open(路径, encoding="utf-8") as f:
        raw = json.load(f)
    块们 = raw["blocks"] if isinstance(raw, dict) and "blocks" in raw else raw
    段 = sorted((int(b["minStateId"]), int(b.get("maxStateId", b["minStateId"])), b["name"])
                for b in 块们 if "minStateId" in b and "name" in b)
    # ★ 自检：段必须**无缝铺满** ✓ 有洞 = 表不可信 ✗
    洞 = []
    if 段 and 段[0][0] != 0:
        洞.append((0, 段[0][0] - 1))
    for i in range(1, len(段)):
        if 段[i][0] != 段[i - 1][1] + 1:
            洞.append((段[i - 1][1] + 1, 段[i][0] - 1))
    方块表 = 段
    return len(段), (段[-1][1] if 段 else -1), 洞


def 方块名(号):
    """stateId → 名字 ✓ 查不到返回 None ✗ **不编** ✗"""
    if 号 is None or 号 < 0:
        return None
    低, 高 = 0, len(方块表) - 1
    while 低 <= 高:
        中 = (低 + 高) // 2
        if 号 < 方块表[中][0]:
            高 = 中 - 1
        elif 号 > 方块表[中][1]:
            低 = 中 + 1
        else:
            return 方块表[中][2]
    return None


# ═══════════════ 四、世界（区块 → 方块查询 ✓）═══════════════
class 段:
    """一个 16×16×16 的方块容器 ✓ 原样存着，查的时候才解 ✓（省内存 ✓）"""
    __slots__ = ("位数", "调", "数据", "形状歪", "非空数")

    def __init__(self):
        self.位数 = 0
        self.调 = []
        self.数据 = []
        self.形状歪 = False
        self.非空数 = 0

    def 取(self, 序号):
        if self.位数 == 0:
            return self.调[0] if self.调 else -1
        每长 = 64 // self.位数
        第 = 序号 // 每长
        if 第 >= len(self.数据):
            return -1
        偏 = (序号 % 每长) * self.位数
        掩 = (1 << self.位数) - 1
        k = (self.数据[第] >> 偏) & 掩
        return self.调[k] if k < len(self.调) else -1


def 读调色板(r, 项数):
    """调色板容器 ✓ 位数 0 = 单值 ✓ 否则 调色板 + 位打包 ✓"""
    s = 段()
    s.位数 = r.字节()
    if r.坏:
        return None
    if s.位数 == 0:
        v = r.变长()
        s.调 = [v & 0xFFFFFFFF]
        return s
    if s.位数 > 32:
        r.坏 = True
        return None
    调长 = r.变长()
    if r.坏 or 调长 > 8192:
        r.坏 = True
        return None
    s.调 = [r.变长() for _ in range(调长)]
    数长 = r.变长()
    if r.坏 or 数长 > 8192:
        r.坏 = True
        return None
    s.数据 = [r.长整() & 0xFFFFFFFFFFFFFFFF for _ in range(数长)]
    if r.坏:
        return None
    # ★ 形状自检：数据长必须正好等于 ceil(项数 / (64/位数)) ✓
    每长 = 64 // s.位数
    应有 = (项数 + 每长 - 1) // 每长
    s.形状歪 = (len(s.数据) != 应有)
    return s


class 世界:
    __slots__ = ("块们", "收到", "歪的", "段号底", "首歪详情", "_dump过")

    def __init__(self):
        self.块们 = {}          # (cx,cz) → {段号: 段}
        self.收到 = 0
        self.歪的 = 0
        self.段号底 = -4        # 1.21.1 主世界 min_y=-64 ⇒ -64>>4 = -4 ✓
        self.首歪详情 = None
        self._dump过 = False

    def 收(self, 净, id长):
        r = 读(净, id长)
        cx, cz = r.整(), r.整()
        if not r.跳NBT():
            print("[世界] ✗ 区块 (%d,%d) heightmaps 跳不过去 ✗" % (cx, cz))
            return
        正文长 = r.变长()
        if r.坏 or 正文长 > r.余():
            print("[世界] ✗ 区块 (%d,%d) 正文长 %d 越界（余 %d）✗" % (cx, cz, 正文长, r.余()))
            return
        d = 读(r.取(正文长))
        段们 = {}
        号 = self.段号底
        while d.余() > 0 and not d.坏:
            非空 = d.带号短()
            方 = 读调色板(d, 4096)
            if 方 is None or d.坏:
                if len(段们) < 3:
                    print("[世界·调试] (%d,%d) 第 %d 段：方块容器就解不动了 ✗ 已解 %d 字节/共 %d"
                          % (cx, cz, len(段们), d.o, 正文长))
                break
            生 = 读调色板(d, 64)          # ★ 生物群系**必须读掉** ✓ 不读就错位 ✗
            if 生 is None or d.坏:
                if self.首歪详情 is None:
                    self.首歪详情 = "生物群系解不动"
                if len(段们) < 3 and not getattr(self, "_dump过", False):
                    self._dump过 = True
                    头 = d.o
                    print("[世界·调试] (%d,%d) 第 %d 段：方块好 ✓ 生物群系解不动 ✗" % (cx, cz, len(段们)))
                    print("             正方块容器读完的位置 %d／正文长 %d ｜ 生物群系位数 = %r"
                          % (头, 正文长, d.b[头] if 头 < 正文长 else None))
                    print("             那之后的 32 字节：%s" % d.b[头:头 + 32].hex())
                    print("             正文最后 16 字节：%s" % d.b[-16:].hex())
                break
            方.非空数 = 非空
            段们[号] = 方
            if 方.形状歪 and self.首歪详情 is None:
                self.首歪详情 = "(%d,%d) 段 %d：位数 %d 调色板 %d 数据 %d" % (
                    cx, cz, 号, 方.位数, len(方.调), len(方.数据))
            号 += 1
        self.块们[(cx, cz)] = 段们
        self.收到 += 1
        if len(段们) < 24 and self.收到 <= 2:
            print("[世界·调试] ⚠ 区块 (%d,%d) 只解出 %d 段（该 24 段 ✓）"
                  "解完的位置 %d／正文长 %d" % (cx, cz, len(段们), d.o, 正文长))

    def 号(self, x, y, z):
        """→ stateId ✓ 查不到返回 **None = 不知道** ✗ 绝不编 ✓"""
        段们 = self.块们.get((x >> 4, z >> 4))
        if not 段们:
            return None
        s = 段们.get(y >> 4)
        if s is None:
            return None
        v = s.取(((y & 15) << 8) | ((z & 15) << 4) | (x & 15))
        return v if v >= 0 else None

    def 在(self, x, y, z):
        v = self.号(x, y, z)
        return 方块名(v) if v is not None else None

    def 普查(self, 步=11):
        """抽样把世界里的方块点一遍名 ✓ **这是最硬的证据** ✓
        解对了 → 石头/泥土/空气/草方块/树叶… 明明白白 ✓
        解错了 → 一堆 None 或者南辕北辙 ✓"""
        数 = {}
        for 段们 in self.块们.values():
            for s in 段们.values():
                for i in range(0, 4096, 步):
                    n = 方块名(s.取(i))
                    数[n] = 数.get(n, 0) + 1
        排 = sorted(数.items(), key=lambda kv: -kv[1])[:8]
        总 = sum(数.values())
        print("[世界] 方块普查（%d 个区块 ｜ 每 %d 个抽 1 个 ｜ 共 %d 个）：" % (len(self.块们), 步, 总))
        for 名, 个 in 排:
            print("           %-24s %6d 个（%.1f%%）" % (名 if 名 else "**解不出来✗**", 个,
                                                          100.0 * 个 / 总 if 总 else 0.0))


# ═══════════════ 五、接线口（脑 ↔ 手 ✓ 跟 Node 手同一套换行 JSON ✓）═══════════════
class 接线口:
    def __init__(self, 路径):
        self.路径 = 路径
        self.客户 = []
        self.锁 = threading.Lock()
        self.上次推 = 0.0
        if os.path.exists(路径):
            os.unlink(路径)
        self.监听 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.监听.bind(路径)
        self.监听.listen(4)
        self.监听.settimeout(0.2)
        print("[手] 接线口开好了 ✓ %s（脑来连 ✓ 说话的格式跟 Node 手一模一样 ✓）" % 路径)

    def 收新(self):
        try:
            c, _ = self.监听.accept()
        except socket.timeout:
            return
        except OSError:
            return
        c.settimeout(0.0)
        with self.锁:
            self.客户.append(c)
        print("[手] 脑连上来了 ✓")

    def 发(self, 对象):
        行 = (json.dumps(对象, ensure_ascii=False) + "\n").encode("utf-8")
        with self.锁:
            for c in list(self.客户):
                try:
                    c.sendall(行)
                except OSError:
                    self.客户.remove(c)

    def 线(self):
        with self.锁:
            return list(self.客户)

    def 收命令(self):
        for c in self.线():
            try:
                块 = c.recv(65536)
            except BlockingIOError:
                continue
            except OSError:
                self._断(c)
                continue
            if not 块:
                self._断(c)
                continue
            for 行 in 块.decode("utf-8", "replace").split("\n"):
                行 = 行.strip()
                if 行:
                    看命令(self, 行)

    def _断(self, c):
        print("[手] 脑断开了 ✓")
        with self.锁:
            if c in self.客户:
                self.客户.remove(c)
        try:
            c.close()
        except OSError:
            pass

    def 关(self):
        for c in self.线():
            try:
                c.close()
            except OSError:
                pass
        try:
            self.监听.close()
        except OSError:
            pass
        if os.path.exists(self.路径):
            os.unlink(self.路径)


def 看命令(口, 行):
    """★ 没实现的命令**必须回话** ✗ 静默 = 罪 ✓"""
    print("[手] ← 脑下命令：%s" % 行[:160])
    try:
        动 = json.loads(行).get("cmd") or "unknown"
    except Exception:
        动 = "unknown"
    口.发({"type": "event", "kind": "cmdResult", "cmd": 动, "ok": False,
          "why": "老祖版手 v1 只有连接+世界层，这个动作还没实现（位置是真的，动作面还是空的）"})


def 状态帧(位置, 朝向, 世界, 说明尾巴=""):
    """★ 只报**我真知道的** ✗ hp/food/near 还不知道 ⇒ **null/空表** ✓ 绝不编数 ✗
    （编个 hp:20 上去 = 骗脑 ✓ 脑会拿它做生死判断 ✓ 这是最不能干的事 ✓）"""
    x, y, z = 位置
    脚 = 世界.在(int(x // 1), int(y // 1), int(z // 1))
    下 = 世界.在(int(x // 1), int(y // 1) - 1, int(z // 1))
    return {"type": "state", "connected": True,
            "pos": [round(x, 2), round(y, 2), round(z, 2)],
            "look": {"yaw": round(朝向[0], 3), "pitch": round(朝向[1], 3)},
            "hp": None, "food": None, "onGround": None,
            "near": [], "threats": [], "foods": [], "players": [], "friends": [],
            "weapons": [], "held": None, "drops": [], "acting": "idle",
            "手": "py", "脚下方块": 脚, "下方一块": 下,
            "说明": "老祖版 v1：连接+世界层" + 说明尾巴}


# ═══════════════ 六、协议（老祖：直连 ✓ 手搓 ✓）═══════════════
class 手:
    def __init__(self, 主机="127.0.0.1", 端口=25565, 名字="PyBot"):
        self.主机, self.端口, self.名字 = 主机, 端口, 名字
        self.套 = None
        self.压缩 = False
        self.状态 = 2
        self.世界 = 世界()
        self.位置 = [0.0, 0.0, 0.0]
        self.朝向 = [0.0, 0.0]
        self.帧数 = 0
        self.踢因 = None
        self.首次位置 = False
        self.收到区块批 = 0

    # ── 发一包 ✓ 压缩开的时候要**自己压** ✓（阈值以上才压 ✓ 我们发的都小 ⇒ 长度 0 ✗ 不压 ✓）──
    def 发(self, 体):
        if self.压缩:
            体 = b"\x00" + 体
        self.套.sendall(写变长(len(体)) + 体)

    def 连(self):
        self.套 = socket.create_connection((self.主机, self.端口), timeout=20)
        self.套.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print("[手] 连上 %s:%d ✓ 协议 %d" % (self.主机, self.端口, 协议版本))
        # ① 握手
        self.发(写变长(0x00) + 写变长(协议版本) + 写串(self.主机)
                + struct.pack(">H", self.端口) + 写变长(2))
        # ② hello（名字 + 16 字节 UUID ✓ 形状是服务器教的 ✓）
        self.发(写变长(0x00) + 写串(self.名字) + b"\x00" * 16)

    def 收一帧(self, 等=0.2):
        """→ (包号, 净) ✓ 帧 = 变长长度 + 正文；正文 = 变长净长 + 数据 ✓
        ★ 没数据时**立刻返回 None** ✗ 不许在这儿死等 ✓
          （死等 = 接线口被饿死 = 脑那边看着像卡住 ✗ 今天栽过 ✓）
        """
        try:
            self.套.settimeout(等)
            头 = self.套.recv(1)
        except socket.timeout:
            return None
        except OSError:
            return None
        if not 头:
            return None
        长 = 头[0] & 0x7F
        i = 0
        while 头[-1] & 0x80:
            i += 1
            if i > 4:
                return None
            b = self._收满(1)
            if not b:
                return None
            头 += b
            长 |= (b[0] & 0x7F) << (7 * i)
        正文 = self._收满(长)
        if 正文 is None:
            return None
        # ★★★ 一道关键判断（我搬 Python 时漏了它 ✗）：
        #   **压缩还没开的时候，帧里没有"净长"这个字段** ✗
        #   我每次都去读 ⇒ 把 `set_compression` 的**包号 0x03 当成了净长 3** ✗
        #   表现：`03 80 02`（id 0x03 + 阈值 varint 256）被当成"净长 3 的压缩包" ✗
        #        ⇒ 解压报 incorrect header check ✓ 卡在登录那一步 ✓
        if not self.压缩:
            r = 读(正文)
            return r.变长(), 正文
        r = 读(正文)
        净长 = r.变长()
        if r.坏:
            return None
        if 净长 == 0:
            净 = r.b[r.o:]
        else:
            try:
                # ★ 一包一个**独立**的 zlib 流 ✓ 一行就行 ✓（C++ 里要 inflateInit+循环+流尾校验 ✗）
                净 = zlib.decompress(r.b[r.o:])
            except zlib.error as e:
                print("[手] ✗ 解压失败（帧长 %d ｜ 净长 %d ｜ %s）—— **必出声** ✗" % (长, 净长, e))
                print("     原文（前 48 字节）：%s" % 正文[:48].hex())
                return None
            if len(净) != 净长:
                print("[手] ✗ 解压出来的长 %d ≠ 声明的 %d ✗ 版式歪了 ✗" % (len(净), 净长))
        rr = 读(净)
        return rr.变长(), 净

    def _收满(self, n):
        """★ 已经开始读一整帧了 ⇒ 这儿可以死等到底 ✓（不然半帧卡住更糟 ✗）"""
        出 = b""
        while len(出) < n:
            try:
                块 = self.套.recv(n - len(出))
            except socket.timeout:
                print("[手] ⚠ 半帧读超时（差了 %d 字节）✗ 连接大概要完 ✓" % (n - len(出)))
                return None
            except OSError:
                return None
            if not 块:
                return None
            出 += 块
        return 出

    # ── 一个包来了 ──
    def 处理(self, 号, 净):
        # ★★★ 这里我第一版写的是 `id长 = 读(净).o` = **0** ✗
        #   读了包号却没记它"占几个字节" ✓ ⇒ 后面所有字段**全部错位一格** ✗
        #   症状（今天实测 ✓）：区块坐标读成 `0x27FFFFFF` ← **那是包号本身** ✗
        #                      位置读成 8236.00 / 0 / 0 ✗
        #   教训：**偏移量要跟真的读了什么对上** ✗ 不能凭印象 ✗
        id长 = len(写变长(号))
        if self.状态 == 2:
            if 号 == 0x03:                                  # set_compression ✓
                self.压缩 = True
                print("[手] 解压流建好了 ✓（一个包一个独立 zlib 流 ✓）")
            elif 号 == 0x02:                                # login success ✓
                self.发(写变长(0x03))                       # login_acknowledged ✓ 不回进不了下一步 ✗
                self.状态 = 3
                print("[手] **登录成功** ✓ → configuration 状态 ✓")
            elif 号 == 0x00:
                self.踢因 = self._踢人理由(净, id长)
                print("[手] 被踢了：%s" % self.踢因)
                return False
        elif self.状态 == 3:
            if 号 == 0x04:                                  # keep_alive ✓ 必须回 ✗
                rr = 读(净, id长)
                k = rr.长整()
                self.发(写变长(0x04) + struct.pack(">q", k))
                print("[手·cfg] ← 心跳 ✓ 回了 ✓")
            elif 号 == 0x0E:                                # select_known_packs ✓ **不回它就不往下走** ✗
                self.发(写变长(0x07) + 写变长(0))           # 空列表 = "我一个新版数据包都不认识" ✓
                print("[手·cfg] ← 服务端问认识哪些数据包 ✓ 回了空列表 ✓")
            elif 号 == 0x09:                                # add_resource_pack ✓ **要带 uuid** ✗
                rr = 读(净, id长)
                u = rr.取(16)
                址 = rr.取(rr.变长())
                校 = rr.取(rr.变长())
                必需 = rr.字节()
                print("[手·cfg] ← 服务端发资源包 ✓ url=%s ｜ sha1=%.8s… ｜ 必需=%s"
                      % (址.decode("utf-8", "replace"), 校.decode("utf-8", "replace")[:8],
                         "是" if 必需 else "否"))
                # ★ 回话 = **它给的 uuid 原样带回去** + DECLINED(1) ✗ 少 16 字节就被踢 ✓
                self.发(写变长(0x06) + u + 写变长(1))
                print("[手·cfg] → 回了「不要这个资源包」（带上了它给的 UUID ✓）")
            elif 号 == 0x03:                                # finish_configuration ✓
                self.发(写变长(0x03))
                self.状态 = 4
                print("[手] **进了 play 状态** ✓✓✓")
            elif 号 == 0x01:
                print("[手·cfg] ← 服务端品牌 ✓（不回 ✓）")
            elif 号 == 0x0C:
                print("[手·cfg] ← 特性开关 ✓（不回 ✓）")
            else:
                print("[手·cfg] 0x%02X %s（净长 %d）—— 先不处理 ✓ 但要**出声** ✗"
                      % (号, 配置_客户端.get(号, "不认识"), len(净)))
        elif self.状态 == 4:
            if 号 == 0x26:                                  # play keep_alive ✓
                rr = 读(净, id长)
                self.发(写变长(0x18) + struct.pack(">q", rr.长整()))
            elif 号 == 0x40:                                # position ✓
                rr = 读(净, id长)
                # ★★★ **全大端** ✗ 用 struct 一行 ✓
                #   （C++ 里我拿 memcpy 读 = 按本机小端解释 ⇒ 坐标永远是 0.000 ✗ 今天实测 ✓）
                x, y, z, yaw, pitch = struct.unpack_from(">dddff", 净, id长)
                rr.o = id长 + 8 * 3 + 4 * 2
                rr.字节()                                   # flags ✓
                传 = rr.变长()                              # teleportId ✓
                self.位置, self.朝向 = [x, y, z], [yaw, pitch]
                self.发(写变长(0x00) + 写变长(传))          # teleport_confirm ✓ 不回服务端不认账 ✗
                if not self.首次位置:
                    print("[手·play] 位置 ✓ %.2f %.2f %.2f（teleportId %d ✓ 已回声 ✓）"
                          % (x, y, z, 传))
                    self.首次位置 = True
            elif 号 == 0x27:                                # map_chunk ✓
                self.世界.收(净, id长)
                if self.世界.收到 == 1:
                    print("[手·世界] 收到第 1 个区块 ✓")
            elif 号 == 0x0D:                                # chunk_batch_start ✓
                self.收到区块批 += 1
            elif 号 == 0x0C:                                # chunk_batch_finished ✓
                print("[手·世界] 一批区块收完 ✓（累计 %d 个区块 ｜ 本批第 %d 批）"
                      % (self.世界.收到, self.收到区块批))
                # ★ 照协议表：`chunksPerTick: **f32**` ✗ 不是 varint ✓
                #   （我第一版发了个 varint ⇒ 服务端 DecoderException 把我踢了 ✓ 今天实测 ✓）
                self.发(写变长(0x08) + struct.pack(">f", 7.0))
            elif 号 == 0x1D:
                self.踢因 = self._踢人理由(净, id长)
                print("[手·play] 被踢了：%s" % self.踢因)
                return False
            elif 号 == 0x6C:
                rr = 读(净, id长)
                t = rr.取(rr.变长()).decode("utf-8", "replace")
                print("[手·聊天] %s" % t)
        return True

    def _踢人理由(self, 净, id长):
        """★ 1.20.3 起踢人理由是 **NBT 文本组件** ✗ 不是字符串 ✓
        不解析 NBT 也能读 ✓ 把明文捞出来就够用了 ✓（踢人不给理由 = 静默 = 罪 ✓）"""
        可打 = "".join(chr(c) if 32 <= c < 127 or c > 127 else "." for c in 净[id长:])
        return 可打[:400]

    def 跑(self, 秒=None, 接线口=None):
        起 = time.time()
        self.套.settimeout(1.0)
        while True:
            if 秒 and time.time() - 起 > 秒:
                print("[手] 到点了 ✓")
                break
            if 接线口:
                接线口.收新()
                接线口.收命令()
                现在 = time.time()
                if 现在 - 接线口.上次推 >= 0.25:
                    接线口.发(状态帧(self.位置, self.朝向, self.世界))
                    接线口.上次推 = 现在
            f = self.收一帧(等=0.2)
            if f is None:
                continue                      # 暂时没包 ✓ 下一轮（接线口还等着呢 ✓）
            号, 净 = f
            self.帧数 += 1
            if not self.处理(号, 净):
                break
            if self.帧数 % 2000 == 0:
                print("[手] 心跳：已收 %d 帧 ｜ 状态 %d ｜ 区块 %d"
                      % (self.帧数, self.状态, self.世界.收到))


# ═══════════════ 七、自检（不能自检的产物不算数 ✓）═══════════════
def 自检():
    过, 不过 = [], []

    def 记(名, 好, 说明=""):
        (过 if 好 else 不过).append(名)
        print(("  ✓ " if 好 else "  ✗ ") + 名 + (("  ｜ " + 说明) if 说明 else ""))

    print("═══ 老祖版手 · 自检 ═══")
    表路径 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "node",
                          "node_modules", "minecraft-data", "minecraft-data", "data", "pc",
                          "1.21.1", "blocks.json")
    n, 最大, 洞 = 装方块表(os.path.abspath(表路径))
    记("方块表装上了", n > 1000, "%d 段 ｜ stateId 0~%d" % (n, 最大))
    记("方块表无缝铺满（0~%d 没有洞）" % 最大, not 洞, "洞 %s" % (洞[:3] if 洞 else "无 ✓"))
    记("抽查 air=0", 方块名(0) == "air", "方块名(0)=%r" % 方块名(0))
    记("抽查 stone=1", 方块名(1) == "stone", "方块名(1)=%r" % 方块名(1))
    记("查不到返回 None（绝不编）", 方块名(99999) is None, "方块名(99999)=%r" % 方块名(99999))

    口 = 接线口(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "手-py.sock"))
    h = 手(名字="PyBot")
    try:
        h.连()
        print("… 收包中（最多 60 秒）…")
        h.跑(秒=60, 接线口=口)
    finally:
        try:
            h.套.close()
        except Exception:
            pass
        口.关()

    记("进了 play 状态", h.状态 == 4, "状态=%d" % h.状态)
    记("收到区块", h.世界.收到 > 0, "%d 个" % h.世界.收到)
    记("没被踢", h.踢因 is None, str(h.踢因)[:80])
    x, y, z = [int(v) for v in h.位置]
    脚 = h.世界.在(x, y, z)
    记("拿到位置（不是 0,0,0）", any(abs(v) > 0.01 for v in h.位置),
       "pos=%s" % [round(v, 2) for v in h.位置])
    if h.世界.收到:
        h.世界.普查()
        记("脚底下解出来了（空气 ✓）", 脚 is not None, "(%d,%d,%d)=%r" % (x, y, z, 脚))
        下方 = [h.世界.在(x, y - i, z) for i in (1, 2, 3)]
        记("往下几格有实心方块", any(块 and 块 != "air" for 块 in 下方), str(下方))
    print("\n═══ 结果：%d 过 / %d 失败 ═══" % (len(过), len(不过)))
    for 名 in 不过:
        print("  ✗ " + 名)
    return 0 if not 不过 else 1


def 主():
    p = argparse.ArgumentParser()
    p.add_argument("--自检", action="store_true")
    p.add_argument("--接线口", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                                   "手-py.sock"))
    p.add_argument("--秒", type=float, default=0)
    p.add_argument("--名字", default="PyBot")
    a = p.parse_args()
    if a.自检:
        return 自检()
    表路径 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "node", "node_modules",
                          "minecraft-data", "minecraft-data", "data", "pc", "1.21.1", "blocks.json")
    n, 最大, 洞 = 装方块表(os.path.abspath(表路径))
    print("[手] 方块表 %d 段 ✓ stateId 0~%d ✓ 洞 %s" % (n, 最大, 洞 if 洞 else "无 ✓"))
    口 = 接线口(os.path.abspath(a.接线口))
    h = 手(名字=a.名字)
    try:
        h.连()
        h.跑(秒=a.秒 or None, 接线口=口)
    except KeyboardInterrupt:
        print("\n[手] 收到 Ctrl-C ✓")
    finally:
        h.世界.普查()
        print("[手] 收工（%d 帧 ｜ %d 个区块 ｜ 踢因 %s）" % (h.帧数, h.世界.收到, h.踢因))
        口.关()
    return 0


if __name__ == "__main__":
    sys.exit(主())
