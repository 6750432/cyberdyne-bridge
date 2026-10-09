#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫结构 —— 把主人搭的模型按方块扫出来，画成剖面图。

English: Scans a box of the world over RCON and prints cross-sections, so a structure
the owner built can be read as data (not guessed at).

为什么要有它
============
主人 2026-10-09：「**扫描我游戏内坐标旁边的那一坨黑曜石，我建了一个挖矿通道的模型**」
—— 他要拿亲手搭的模型当范例 ✓ 那我就得**先把模型读成数据** ✓ 不能凭想象 ✗

跑法：
  MC_RCON_PASSWORD=cyberdyne python3 tools/扫结构.py --心 -181 81 183 --半径 12 --高 11
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rcon import RCON          # noqa: E402

# 要区分的方块 → 图上的字符（先到先得 ✓ 前面的是"更想看见"的 ✓）
# ⚠ 顺序 = **查询顺序** ✓ 最常见的排前面（每格要挨个试到命中为止 ✓）
#   我第一版把黑曜石排第一 ✗ —— 那是**最罕见**的 ✓ 每格都要白试一次 ✓ 白白慢一倍 ✓
图例 = [
    ("minecraft:air", "."),
    ("minecraft:stone", "s"),
    ("minecraft:dirt", "d"),
    ("minecraft:grass_block", "G"),
    ("minecraft:deepslate", "D"),
    ("minecraft:obsidian", "#"),
    ("minecraft:crying_obsidian", "@"),
    ("minecraft:torch", "t"),
    ("minecraft:wall_torch", "T"),
    ("minecraft:lantern", "L"),
    ("minecraft:glass", "g"),
    ("minecraft:oak_planks", "p"),
    ("minecraft:cobblestone", "c"),
    ("minecraft:oak_log", "o"),
    ("minecraft:oak_leaves", "*"),
    ("minecraft:water", "~"),
    ("minecraft:lava", "!"),
]


def 问(r, 文):
    try:
        return str(r.命令(文) or "")
    except Exception as e:
        return f"炸了：{e}"


def 是(应答):
    """`execute if block` 的应答：Test passed / Test failed ✓"""
    return "Test passed" in 应答


def 主():
    ap = argparse.ArgumentParser()
    ap.add_argument("--心", nargs=3, type=int, required=True, help="中心 x y z")
    ap.add_argument("--半径", type=int, default=12)
    ap.add_argument("--高", type=int, default=11)
    ap.add_argument("--只", default="", help="只扫这一种方块（省时间）")
    a = ap.parse_args()

    cx, cy, cz = a.心
    r = RCON(password=os.environ.get("MC_RCON_PASSWORD", ""))
    print(f"中心 ({cx},{cy},{cz})  半径 {a.半径}  高 {a.高}")
    print(f"盒子 x {cx - a.半径}..{cx + a.半径}  y {cy}..{cy + a.高 - 1}  z {cz - a.半径}..{cz + a.半径}")
    print()

    想看的 = [(n, c) for n, c in 图例 if not a.只 or n.endswith(a.只)]

    局 = {}          # (x,y,z) -> 字符
    层表 = {}
    for y in range(cy, cy + a.高):
        层 = []
        for z in range(cz - a.半径, cz + a.半径 + 1):
            行 = ""
            for x in range(cx - a.半径, cx + a.半径 + 1):
                字 = "?"
                for 名, 符 in 想看的:
                    if 是(问(r, f"execute if block {x} {y} {z} {名}")):
                        字 = 符
                        局[(x, y, z)] = 名
                        break
                行 += 字
            层.append(行)
        层表[y] = 层

    # ── 画：每层一个剖面（俯视，x 横、z 竖）──
    print("俯视剖面（x 向右、z 向下）★ 图例：" +
          "  ".join(f"{c}={n.split(':')[1]}" for n, c in 图例))
    for y in sorted(层表, reverse=True):
        print(f"\n── y={y} ──")
        print("      " + "".join(str((cx - a.半径 + i) % 10) for i in range(2 * a.半径 + 1)))
        for i, 行 in enumerate(层表[y]):
            print(f"  {cz - a.半径 + i:5d} {行}")

    # ── 统计 ──
    print("\n═══ 方块统计 ═══")
    计 = {}
    for 名 in 局.values():
        计[名] = 计.get(名, 0) + 1
    for 名, n in sorted(计.items(), key=lambda kv: -kv[1]):
        print(f"  {n:6d}  {名}")
    return 0


if __name__ == "__main__":
    sys.exit(主())
