#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""依赖账 —— 手侧到底拉进来多少个包、多大、什么许可证、哪些是**可选的**。

English: Prints the hand's dependency ledger: direct deps, licences, size, and which
packages are optional engines (i.e. what we could drop by turning a switch off).

★ 为什么要有它（主人 2026-10-09 问的）
======================================
    「**这么多依赖库能不能只留 Py 的，如果不行请说明是否能转译**」

  要回答这个问题，第一件事是**数清楚** ✗ 不能凭印象 ✓
  （一数就明白了：**直接依赖只有 2 个** ✓ 那 88 个是**传递依赖** ✗）

  顺带一条纪律（跟"写出来要有人读"同族）：
    **依赖账要随时能查** ✓ 不然"它是不是又胖了"永远是个感觉 ✗
"""

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = os.path.join(ROOT, "node")


def 读(p):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def 主():
    pkg = 读(os.path.join(NODE, "package.json"))
    直接 = pkg.get("dependencies") or {}
    print("═══ 手侧依赖账 ═══\n")
    print(f"【直接依赖】我们**自己写进** package.json 的：{len(直接)} 个")
    for k, v in 直接.items():
        print(f"    {k:<34} {v}")

    mods = os.path.join(NODE, "node_modules")
    名 = []
    if os.path.isdir(mods):
        名 = sorted(d for d in os.listdir(mods)
                   if not d.startswith(".") and os.path.isdir(os.path.join(mods, d)))
    print(f"\n【装到盘上的包】含传递依赖：{len(名)} 个")

    # 体积
    if 名:
        大 = []
        for d in 名:
            p = os.path.join(mods, d)
            try:
                总 = 0
                for 根, _, 文件们 in os.walk(p):
                    for f in 文件们:
                        try:
                            总 += os.path.getsize(os.path.join(根, f))
                        except Exception:
                            pass
                大.append((总, d))
            except Exception:
                pass
        大.sort(reverse=True)
        总大小 = sum(x for x, _ in 大)
        print(f"            一共 {总大小 / 1048576:.0f} MB")
        print("            最占地方的 5 个：")
        for 字, d in 大[:5]:
            print(f"              {字 / 1048576:>7.0f} MB  {d}")

    # 许可证（只查**直接依赖**；传递依赖由各自的包声明负责 ✓）
    print("\n【直接依赖的许可证】")
    for k in 直接:
        lic = "?"
        try:
            信息 = 读(os.path.join(mods, k, "package.json"))
            lic = 信息.get("license") or 信息.get("licenses") or "?"
        except Exception:
            pass
        print(f"    {k:<34} {lic}")

    # ★ 可选引擎：能力那层挂着的，每一个都是"关了就不用装"的 ✓
    能力根 = os.path.join(NODE, "plugins", "能力")
    可选 = []
    if os.path.isdir(能力根):
        for 能 in sorted(os.listdir(能力根)):
            m = 读(os.path.join(能力根, 能, "manifest.json"))
            for 引擎名, 引擎 in (m.get("引擎") or {}).items():
                可选.append((能, 引擎名, 引擎.get("包"), 引擎.get("许可证")))
    print(f"\n【可选引擎】能力层挂着的（关了就不用装 ✓）：{len(可选)} 个")
    for 能, 引擎名, 包, lic in 可选:
        print(f"    {能}/{引擎名:<14} 包={包}  许可证={lic}")
    正装 = set(直接)
    没用到 = [x for x in 可选 if x[2] and x[2] not in 正装]
    if 没用到:
        print(f"    ⚠ 有 {len(没用到)} 个可选引擎的包**还没装** ✓"
              f"（这正是「开关一拨就不用装」的字面意思 ✓）")

    print("\n★ 一句话：**直接依赖越少，账越好算** ✓ ——")
    print("  新能力一律走「可选引擎」✓ 用不着就不装 ✓ 别把库铺进主链 ✗")
    return 0


if __name__ == "__main__":
    sys.exit(主())
