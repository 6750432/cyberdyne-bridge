#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探雷达.py —— 直接问手侧雷达一句：**「我要找 X，你穷举一遍」**（不开游戏、不花大模型）。

为什么要有它
============
2026-10-09 主人问：「我不是记得我雷达是用来侦测地形和射线（对实心方块无穿透效果）
识别方块类型的吗？」—— **雷达一直就是那样** ✓（`扫环境()` 是半径+步长的体素扫描 +
`看遮挡()` 的射线判定 ✓），坏的不是它 ✗，坏的是**没人跟它点单** ✗：

  · 扫描网格**步长默认 2**，而树干只有 1 格宽 → 网格整个跨过去 ✗
    → `可交互` 空 → 脑侧拿不到坐标 → 每秒重试同一句「要给我一个坐标」✗
  · 脑侧从前落空只会**抱怨一句**，从不回头跟雷达说「我在找这根木头」✗

现在两边都补上了（脑侧 `_要雷达找` 点单 ✓、手侧 `scan.找` 穷举 ✓）。
这个工具是它的**最小闭环**：点单 → 看雷达真报了什么 —— 排查时不用去烦大模型 ✓

用法
====
    python3 tools/探雷达.py spruce_log              # 点单一种方块，看雷达穷举的结果
    python3 tools/探雷达.py oak_log stone --半径 20 # 多种方块一起点
    python3 tools/探雷达.py --看                     # 只看当前点单 + 最近一次扫描的命中
    python3 tools/探雷达.py --清                     # 撤掉点单（还雷达一个干净状态）
    python3 tools/探雷达.py spruce_log --秒 8        # 多等几拍

规矩（跟全项目一致）
====================
① **纯读**：只设置「要找」名单，不动世界、不发任何动作动词；
② 输出**带证据**：命中几条、坐标、距离、`裸露/视线`（射线情报）全打出来 ✓；
③ 撤单**一定撤干净**（`要: []`，不是"没给"）—— 别让主链下一次扫描背着我的点单 ✗
"""

import argparse
import json
import os
import socket
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import bridge  # noqa: E402  只为了复用它的接线口解析（不抄第二遍 ✓）


def 连上():
    cfg = bridge.读配置()
    方式, 目标 = bridge.解析接线口(cfg)
    s = socket.socket(socket.AF_UNIX if 方式 == "unix" else socket.AF_INET,
                      socket.SOCK_STREAM)
    s.connect(目标)
    s.settimeout(0.5)
    return s


def 读帧(s, 缓冲, 秒):
    """读一秒的帧，返回 (新缓冲, 帧列表)。行分隔 JSON ✓（手侧 `send()` 就是这个格式）。"""
    帧们 = []
    截止 = time.monotonic() + 秒
    while time.monotonic() < 截止:
        try:
            块 = s.recv(65536)
        except socket.timeout:
            continue
        except OSError:
            break
        if not 块:
            break
        缓冲 += 块.decode("utf-8", "replace")
        行们 = 缓冲.split("\n")
        缓冲 = 行们.pop()
        for 行 in 行们:
            try:
                帧们.append(json.loads(行))
            except Exception:
                continue
    return 缓冲, 帧们


def 打命中(扫, 要):
    找 = 扫.get("找") or []
    print(f"  点名要找：{扫.get('要找') or []}   ｜ 穷举命中：{len(找)} 条")
    if not 找:
        print("  ⚠ 这一拍没命中 —— 可能是真没有（那就得走几步），也可能是刚点单还没扫到")
        return
    for 条 in 找[:8]:
        遮 = []
        if 条.get("裸露") is not None:
            遮.append("裸露=" + ("是" if 条.get("裸露") else "**否（整个被埋住）**"))
        if 条.get("视线") is not None:
            遮.append("视线=" + ("通" if 条.get("视线") else "**被挡**"))
        if 条.get("挡"):
            遮.append("挡着的是 " + "、".join(map(str, 条["挡"][:3])))
        print(f"    · {条.get('name'):<16} {tuple(条.get('p') or [])}"
              f"  距 {条.get('距')}  ｜ {' ｜ '.join(遮) or '（这一版手没带射线情报）'}")
    print("\n  顺带（这一拍的常规扫描）——")
    print(f"    · 可交互 {len(扫.get('可交互') or [])} 条"
          f" ｜ 危险 {len(扫.get('危险') or [])} 条"
          f" ｜ 石头 {'有' if 扫.get('石头') else '无'}"
          f" ｜ 群系 {扫.get('群系')} ｜ 脚下 {扫.get('脚下')}")


def 主():
    p = argparse.ArgumentParser(description="点单式雷达探针（纯读）")
    p.add_argument("方块", nargs="*", default=[], help="要找的方块名（可给多个）")
    p.add_argument("--半径", type=int, default=20, help="穷举半径（手侧上限 24）")
    p.add_argument("--秒", type=float, default=5.0, help="点单后最多等这么多秒")
    p.add_argument("--看", action="store_true", help="不点单，只看当前扫描（含已有命中）")
    p.add_argument("--清", action="store_true", help="撤掉点单后退出")
    a = p.parse_args()

    try:
        s = 连上()
    except OSError as e:
        print(f"接不上手（{e}）—— 手先跑起来（bash tools/启动手.sh）。")
        return 1

    缓冲 = ""
    缓冲, 帧们 = 读帧(s, 缓冲, 1.0)          # 先吃掉接上就送的那一份状态
    print(f"连上手了 ✓（收到 {len(帧们)} 帧）")

    if a.清:
        s.sendall((json.dumps({"cmd": "scan_environment", "要": []},
                              ensure_ascii=False) + "\n").encode("utf-8"))
        _, 帧们 = 读帧(s, 缓冲, 2.0)
        print("点单已撤干净 ✓（要: []）")
        return 0

    if not a.看 and a.方块:
        令 = {"cmd": "scan_environment", "要": list(a.方块)[:8], "找半径": int(a.半径)}
        s.sendall((json.dumps(令, ensure_ascii=False) + "\n").encode("utf-8"))
        print(f"点单：要找 {'、'.join(a.方块)}（半径 {a.半径}）")

    最好 = None
    截止 = time.monotonic() + a.秒
    while time.monotonic() < 截止:
        缓冲, 帧们 = 读帧(s, 缓冲, 1.0)
        for f in 帧们:
            扫 = f.get("scan") if isinstance(f.get("scan"), dict) else None
            if 扫 is None and isinstance(f.get("state"), dict):
                扫 = f["state"].get("scan")
            if not isinstance(扫, dict):
                continue
            if a.方块 and not (扫.get("要找") or []):
                # 点单还没落地（手侧还没扫到这一拍）
                continue
            最好 = 扫
            if 扫.get("找"):
                break
        if 最好 and 最好.get("找"):
            break

    if 最好 is None:
        print("⚠ 没收到带 `scan` 的状态帧 —— 看看手日志（logs/手.log）。")
        return 1
    print("\n雷达读数：")
    打命中(最好, a.方块)

    if not a.看:
        s.sendall((json.dumps({"cmd": "scan_environment", "要": []},
                              ensure_ascii=False) + "\n").encode("utf-8"))
        读帧(s, 缓冲, 1.5)
        print("\n（点单已撤干净 ✓ 雷达恢复常规扫描）")
    return 0


if __name__ == "__main__":
    sys.exit(主())
