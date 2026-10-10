#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""常识库·挖掘判定矩阵 —— 用**真数据**回答「这个方块我挖不挖得动」。

┌───────────────────────────────────────────────────────────────────┐
│ 它替换掉的是什么（2026-10-07 对账出来的）                         │
└───────────────────────────────────────────────────────────────────┘
主链 `bridge.py:1251` 和手侧 `proto_body.js:58` 各有一份**几乎一样**的正则：

    /(_ore|stone|deepslate|cobblestone|bricks|…|_block$)/

拿 1060 个方块逐条对账，结果：

    真·需要镐子的方块：385 个
    误报 51 个   （grass_block / redstone_torch / stone_button / glowstone / …）
    漏报 151 个  （granite / diorite / andesite / iron_door / chain / …）

★ 漏报是最危险的一类：正则说「不用工具」，于是**徒手硬挖** ——
  石头系方块徒手也能挖碎，但**什么都不掉**，而手侧会回报 `ok: true`。
  于是「挖了 12 块花岗岩」变成「背包里一块都没有」的**静默失败**。
  这正是本项目最恨的失败方式。

┌───────────────────────────────────────────────────────────────────┐
│ 数据里本来就有答案                                                │
└───────────────────────────────────────────────────────────────────┘
    blocks.json 的 `harvestTools` = {工具物品ID: true}
    stone         → 6 种镐（木/石/铁/金/钻石/下界合金）
    iron_ore      → 4 种镐（石/铁/钻石/下界合金）  ← **没有金镐**
    diamond_ore   → 3 种镐（铁/钻石/下界合金）
    obsidian      → 2 种镐（钻石/下界合金）
    oak_log / dirt / sand → **空 = 徒手就行**

★ 顺带修掉一个真 bug：手侧挑镐子的材质排序写的是
  `['wooden','stone','iron','golden','diamond','netherite']` ——
  把**金镐排在铁镐前面**。可金镐的挖掘等级**只有 1（跟木镐一样）**，
  挖 iron_ore / diamond_ore 都不掉东西。所以「手里有金镐+铁镐」时
  它会换金镐，然后挖不动铁矿。
  本文件的 `最好的工具()` 用**数据推出来的档位**排，不用写死的表。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import 常识数据 as 数据模块          # noqa: E402

_档位 = None          # {工具名: 档位整数}；None 表示还没算
_档位说明 = ""


def _工具类(名):
    """`wooden_pickaxe` → `pickaxe`。不是工具就返回 None。"""
    if not isinstance(名, str):
        return None
    for 类 in ("pickaxe", "axe", "shovel", "hoe", "shears", "sword"):
        if 名.endswith("_" + 类) or 名 == 类:
            return 类
    return None


def 该用什么工具(方块名):
    """这个方块需要**哪一类**工具？不需要就返回 None。

    真数据判定：`需要工具` 为空 = 徒手就行（木头、泥土、沙子…）。
    """
    数 = 数据模块.载入()
    b = 数["方块"].get(方块名)
    if not b:
        return None
    if not b["需要工具"]:
        return None
    类 = [ _工具类(x) for x in b["需要工具"] ]
    类 = [c for c in 类 if c]
    if not 类:
        return None
    # 一类不够齐就报第一类（MC 里一个方块基本只要一类工具）
    return sorted(set(类))[0]


def 需要哪些(方块名):
    """这个方块允许的工具**集合**（精确到物品名）。空集 = 徒手就行。"""
    数 = 数据模块.载入()
    b = 数["方块"].get(方块名)
    return frozenset(b["需要工具"]) if b else frozenset()


# ══════════════════════════ 档位序（从数据里推，不写死） ══════════════════════════

_各类档位 = {}          # 类名 -> {工具名: 档位}


def 算档位(类="pickaxe"):
    """按「这个工具能挖的方块集合」做包含关系排序。**必须按类分开算。**

    ★ 第一版把所有工具混在一起排，当场就红了：
        「diamond_pickaxe 与 diamond_shovel 能挖的方块互相不包含」
      —— 镐挖石头、铲挖泥土，两组集合**根本不相交**，当然不是全序。
      所以档位只在**同一类工具内部**才有意义（镐跟镐比）。

    ★ 本函数**会验证这是不是一个全序**。不是就返回 None，
      调用方退化为「能挖的方块数多者优先」，**绝不硬排一个假档位**。
    """
    global _档位说明
    if 类 in _各类档位:
        return _各类档位[类]
    数 = 数据模块.载入()

    能挖 = {}
    for 名, b in 数["方块"].items():
        for t in b["需要工具"]:
            if _工具类(t) == 类:
                能挖.setdefault(t, set()).add(名)
    if not 能挖:
        _档位说明 = f"数据里没有「需要 {类}」的方块"
        return None

    名们 = sorted(能挖)
    for a in 名们:
        交叉 = [b for b in 名们 if b != a
                and not (能挖[b] <= 能挖[a]) and not (能挖[a] <= 能挖[b])]
        if 交叉:
            _档位说明 = (f"{类}：**不是全序** —— {a} 与 {交叉[0]} 能挖的方块互相不包含，"
                       f"退化为逐方块独立判定，不硬排档位")
            return None

    序 = sorted(名们, key=lambda x: (len(能挖[x]), x))
    表 = {a: i for i, a in enumerate(序)}
    _各类档位[类] = 表
    _档位说明 = "、".join(f"{a}={表[a]}" for a in 序)
    return 表


def 档位说明(类="pickaxe"):
    算档位(类)
    return _档位说明


def 档位(工具名, 类=None):
    """这个工具在第几档？推不出序就返回 None。"""
    类 = 类 or _工具类(工具名) or "pickaxe"
    序 = 算档位(类)
    return 序.get(工具名) if 序 else None


def 最好的工具(背包, 类="pickaxe"):
    """从背包里挑一把**这个类里最好**的。

    ★ 用手侧那种写死的材质表会错（金镐排在铁镐前面）。
      这里用**数据推出来的档位**；推不出来就退回「够用就行」：
      按「能挖的方块数」多者优先 —— 那至少不会挑一把挖不动的。
    """
    数 = 数据模块.载入()
    有 = [x for x in (背包 or []) if _工具类(x) == 类]
    if not 有:
        return None
    序 = 算档位(类)
    if 序:
        return max(有, key=lambda x: (序.get(x, -1), -有.index(x)))
    # 退化路径：能挖的方块多的优先
    能 = {t: len([1 for b in 数["方块"].values() if t in b["需要工具"]]) for t in 有}
    return max(有, key=lambda x: 能.get(x, 0))


# ══════════════════════════ 主判定 ══════════════════════════

def 挖得动吗(方块名, 背包):
    """返回 (能不能, 为什么, 该用哪把工具)。

    三道：
      ① 方块本身是不是「能挖」（基岩那种永远挖不动）
      ② 徒手就行吗（需要工具为空）→ 放行，只是慢
      ③ 需要工具 → 背包里有没有**任何一把**在集合里的
    """
    数 = 数据模块.载入()
    b = 数["方块"].get(方块名)
    if not b:
        return False, f"我不认识「{方块名}」这个方块", None

    if not b["能挖"]:
        return False, f"「{方块名}」是挖不动的（基岩/传送门那一类）", None

    要 = b["需要工具"]
    if not 要:
        return True, f"「{方块名}」徒手就能挖（慢一点）", None

    背包 = set(背包 or [])
    有 = 要 & 背包
    if 有:
        最好的 = 最好的工具([x for x in 有], _工具类(next(iter(要))) or "pickaxe")
        return True, f"「{方块名}」需要 {'/'.join(sorted(要))}，背包里有 {sorted(有)}", 最好的

    差 = sorted(要)[0]
    return (False,
            f"「{方块名}」必须用 {'、'.join(sorted(要))} 才掉东西，"
            f"我背包里一把都没有（最低得是 {差}）",
            None)


# ══════════════════════════ 命令行自检 ══════════════════════════

if __name__ == "__main__":
    print("═══ 档位序（从数据推的，按工具类分开）═══")
    for 类 in ("pickaxe", "shovel", "axe"):
        print(f"  [{类}] {档位说明(类) or '（推不出来）'}")
    print()
    print("═══ 关键方块逐条看 ═══")
    for 名 in ("oak_log", "dirt", "granite", "stone", "coal_ore", "iron_ore",
               "diamond_ore", "obsidian", "bedrock", "redstone_torch",
               "grass_block", "glowstone"):
        b = 数据模块.载入()["方块"].get(名)
        if not b:
            print(f"  {名:16s} （数据里没有）"); continue
        v = "徒手就行" if not b["需要工具"] else f"要 {len(b['需要工具'])} 种"
        ok, 为, 用 = 挖得动吗(名, [])
        print(f"  {名:16s} 硬度={str(b['硬度']):>5}  {v:<12} 空手结论={'✅能' if ok else '❌不能'}")
