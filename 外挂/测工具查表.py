#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具查表车厢 —— 离线断言。

要证明的四件事：
  A 装上 / 幂等 / 卸下（bridge._要镐子 一字不差还原）
  B ★★★ **拿真主链验**：装上之后，bridge._要镐子("grass_block") 必须是 False
    （这就是主人早上「又不动了」的根：主链认为草方块要镐子 → 把手之前先判死 ✗）
  C 表里没有的方块 → **交回原来那个函数**（fail-safe，不乱放行）
  D 表读不到时**拒绝装**，而且**不许动全局状态**

跑法：python3 外挂/测工具查表.py
"""

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
外挂根 = os.path.join(ROOT, "外挂")
通过, 失败 = [], []


def 试(名, 条件, 为啥="条件不成立"):
    (通过 if 条件 else 失败).append(名 if 条件 else {"名": 名, "为啥": 为啥})
    return bool(条件)


def 载(名):
    p = os.path.join(外挂根, 名, "补丁.py")
    spec = importlib.util.spec_from_file_location(f"测_{名}", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"测_{名}"] = m
    sys.path.insert(0, os.path.join(外挂根, 名))
    spec.loader.exec_module(m)
    return m


def 主():
    sys.path.insert(0, 外挂根)
    sys.path.insert(0, ROOT)
    import bridge
    查 = 载("工具查表")

    # ══════════ B 先看**没装的时候**主链怎么判（拿证据）══════════
    print("── B 组：拿真主链验 ──")
    原草 = bridge._要镐子("grass_block")
    原石 = bridge._要镐子("stone")
    print(f"  装之前：grass_block 要镐子={原草} ｜ stone 要镐子={原石}")
    试("B1 装之前主链认为草方块要镐子（这就是「又不动了」的根 —— 这条算是留证）",
       原草 is True or 原草 is not False, f"实际 {原草!r}")

    # ══════════ A 装上 ══════════
    原函数 = bridge._要镐子
    r = 查.装上(bridge, 日志=lambda *a, **k: None)
    试("A1 装上了", r.get("好") is True, str(r))
    试("A2 打了 1 处补丁（bridge._要镐子）", len(r.get("打了", [])) == 1, str(r.get("打了")))
    试("A3 函数真的被换掉了", bridge._要镐子 is not 原函数)
    试("A4 幂等", 查.装上(bridge)["为什么"].find("已经装过") >= 0)

    # ══════════ B 核心断言 ══════════
    试("B2 ★★★ 装上之后：**草方块不再要镐子**（主人早上卡的就是这条）",
       bridge._要镐子("grass_block") is False, str(bridge._要镐子("grass_block")))
    for 名 in ("dirt", "sand", "gravel", "oak_log", "oak_leaves", "crafting_table"):
        试(f"B3 {名} 不要镐子", bridge._要镐子(名) is False, str(bridge._要镐子(名)))
    for 名 in ("stone", "cobblestone", "coal_ore", "iron_ore"):
        试(f"B4 ★ {名} 要镐子（该守的还得守）",
           bridge._要镐子(名) is True, str(bridge._要镐子(名)))

    # ══════════ C 表里没有 → 交回原函数 ══════════
    试("C1 ★★ 表里没见过的方块 → **交回原函数**（fail-safe，不自己乱判）",
       查.要镐子吗("这不是个方块名", 原函数) == bool(原函数("这不是个方块名")),
       f"新={查.要镐子吗('这不是个方块名', 原函数)} 原={原函数('这不是个方块名')}")

    # ══════════ A 卸下 ══════════
    r2 = 查.卸下(bridge)
    试("A5 卸下返回好", r2.get("好") is True, str(r2))
    试("A6 ★★ 一字不差还原（is 同一个对象）", bridge._要镐子 is 原函数)
    试("A7 卸干净之后再卸也不炸", 查.卸下(bridge).get("好") is True)
    试("A8 还原之后草方块又变回原来的判法（说明真还原了）",
       bridge._要镐子("grass_block") == 原草)

    # ══════════ D 表读不到 → 拒绝装 ══════════
    查._表 = {}                     # 装成"表读不到"
    快照 = bridge._要镐子
    r3 = 查.装上(bridge, 日志=lambda *a, **k: None)
    试("D1 ★★ 表读不到 → **拒绝装**（不装作装上了）", r3.get("好") is False, str(r3))
    试("D2 ★★ 而且**没动全局状态**（函数还是原来那个）", bridge._要镐子 is 快照)
    查._表 = None                   # 复原，别影响别的用例

    print("\n" + "═" * 62)
    print(f"工具查表车厢：{len(通过)} 过 / {len(失败)} 失败")
    for f in 失败:
        print(f"  ❌ {f['名']} —— {f['为啥']}")
    print("═" * 62)
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
