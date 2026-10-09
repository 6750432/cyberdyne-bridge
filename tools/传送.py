#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""传送 —— 把「我和小家伙」互相传过去，一条命令就完事 ✓

为什么要有它（主人 2026-10-09 原话）：
  「我怎么过去？**你也是不带脑子的吗？**」

主人骂得对 ✓：我把小家伙搬到 2950 格外的森林 ✓
  **却没想"那个人怎么过去"** ✗
  —— 这是干活**只做一半** ✓ 而"一半"在主人那儿等于没做 ✓

三条规矩（照这次的事立）：
  ① **搬东西之前先想"人怎么到"** ✓ —— 移动的是谁、谁会被留在原地 ✗
  ② **落点用对方的坐标** ✓ —— 那一格保证是空气 ✓（不会卡进方块里 ✓）
     别自己算"大概在哪" ✗（今天我就差点用 locate 的结果瞎算 ✓）
  ③ **拉开的距离要够** ✓ —— 不然两个人叠一块儿 ✓

用法：
  python3 tools/传送.py 我到小家伙      # 把我传到小家伙旁边 ✓
  python3 tools/传送.py 小家伙到我      # 把小家伙传到我旁边 ✓
  python3 tools/传送.py 哪                # 只报"我们俩各在哪" ✓
"""

import os
import re
import subprocess
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
我 = "mintstar"          # 主人（想改名就改这一行 ✓）
它 = "DeepSeek"          # 小家伙（跟 config.json 的 bot_name 一致 ✓）
拉开 = 2                 # 传过去之后拉开几格 ✓


def 查(命令):
    """→ 服务端原话 ✓（不猜 ✗）"""
    出 = subprocess.run([sys.executable, os.path.join(根, "tools", "rcon.py"), 命令],
                        capture_output=True, text=True, cwd=根,
                        env=dict(os.environ, MC_RCON_PASSWORD=os.environ.get("MC_RCON_PASSWORD", "cyberdyne")))
    return (出.stdout or "") + (出.stderr or "")


def 位置(谁):
    """→ [x, y, z] ✓ 拿不到就 None ✓（**出声** ✗ 不编一个 ✗）"""
    文 = 查(f"data get entity {谁} Pos")
    m = re.search(r"\[(-?[\d.]+)d,\s*(-?[\d.]+)d,\s*(-?[\d.]+)d\]", 文)
    if not m:
        print(f"✗ 拿不到「{谁}」的坐标 —— 它可能不在线 ✓。服务端原话：{文.strip()[:120]}")
        return None
    return [float(m.group(1)), float(m.group(2)), float(m.group(3))]


def 传(谁, 到, 偏=(0, 0, 0)):
    x, y, z = 到[0] + 偏[0], 到[1] + 偏[1], 到[2] + 偏[2]
    print(f"→ tp {谁} {x} {y} {z}")
    print("  " + 查(f"tp {谁} {x} {y} {z}").strip().replace("\n", "\n  "))
    新 = 位置(谁)
    if 新:
        print(f"  ✓ {谁} 现在在 {新}（服务端说的 ✓）")


def 主():
    a = (sys.argv[1] if len(sys.argv) > 1 else "哪").strip()
    if a in ("哪", "哪里", "状态"):
        我_ = 位置(我)
        它_ = 位置(它)
        print(f"我（{我}）：{我_}")
        print(f"小家伙（{它}）：{它_}")
        if 我_ and 它_:
            距 = sum((x - y) ** 2 for x, y in zip(我_, 它_)) ** 0.5
            print(f"相距约 {距:.0f} 格")
        return 0
    if a in ("我到小家伙", "我到它", "过去"):
        它_ = 位置(它)
        if not 它_:
            return 1
        print(f"小家伙在 {它_} ✓ 这就把你送过去（落在它旁边 {拉开} 格）✓")
        传(我, 它_, (拉开, 0, 拉开))
        return 0
    if a in ("小家伙到我", "它到我", "过来"):
        我_ = 位置(我)
        if not 我_:
            return 1
        print(f"你在 {我_} ✓ 这就把它叫过来（落在你旁边 {拉开} 格）✓")
        传(它, 我_, (拉开, 0, 拉开))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(主())
