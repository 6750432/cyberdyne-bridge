#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""常识库·数据层 —— 读原版数据，建内存缓存。

┌───────────────────────────────────────────────────────────────────┐
│ 数据从哪来（本机实测出来的路径，不是猜的）                        │
└───────────────────────────────────────────────────────────────────┘
    node/node_modules/minecraft-data/minecraft-data/data/pc/1.21.1/
        recipes.json   382 KB   782 条配方   ← 键是**结果物品 ID**
        blocks.json    765 KB  1060 个方块   ← 硬度 / harvestTools / 掉落
        items.json     165 KB  1333 个物品   ← ID ↔ 名字

★ **一个新库都不装。** 这三个文件就是全部原料。
★ 读一次进内存（实测 ~150ms），之后常驻。**绝不每步重读。**

┌───────────────────────────────────────────────────────────────────┐
│ 为什么不用 prismarine-recipe                                      │
└───────────────────────────────────────────────────────────────────┘
它回答的是「**能不能**合成这个」（手侧的 craft 正用它）。
我们要回答的是「合成它**需要什么、还差什么、先干什么**」——
那是**反向 DAG**，直接读 recipes.json 更直接，而且零依赖、可离线测。
"""

import io
import json
import os
import re
import sys

# 外挂/常识/数据.py → 仓库根
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_缓存 = None


def _找数据目录(版本="1.21.1"):
    """在 node_modules 里找 minecraft-data 的版本数据目录。

    ★ 实测：这个包里**嵌了一层同名目录**
      （node_modules/minecraft-data/minecraft-data/data/…），
      所以不能硬写一层，得真去找。找不到就报清楚，别静默返回空。
    """
    起 = os.path.join(ROOT, "node", "node_modules")
    候选 = [
        os.path.join(起, "minecraft-data", "minecraft-data", "data", "pc", 版本),
        os.path.join(起, "minecraft-data", "data", "pc", 版本),
    ]
    for p in 候选:
        if os.path.isfile(os.path.join(p, "recipes.json")):
            return p
    # 最后一招：全盘扫 node_modules 下的 data/pc/<版本>
    for 根, 目录们, _ in os.walk(起):
        if 根.endswith(os.path.join("data", "pc", 版本)):
            if os.path.isfile(os.path.join(根, "recipes.json")):
                return 根
    raise FileNotFoundError(
        f"找不到 {版本} 的原版数据（在 {起} 下面翻了）—— "
        f"常识库没有原料就跑不了，不猜、不用空表兜底")


def _读(目录, 名):
    with io.open(os.path.join(目录, 名), encoding="utf-8") as f:
        return json.load(f)


def 载入(版本="1.21.1", 重载=False):
    """把三份数据读进内存。返回一个大字典（同一个对象，别改它）。"""
    global _缓存
    if _缓存 is not None and not 重载:
        return _缓存

    目录 = _找数据目录(版本)
    物品表 = _读(目录, "items.json")          # [{"id","name","displayName","stackSize"}]
    方块表 = _读(目录, "blocks.json")
    配方原 = _读(目录, "recipes.json")

    编号到名 = {x["id"]: x["name"] for x in 物品表}
    名到编号 = {x["name"]: x["id"] for x in 物品表}

    方块 = {}
    for b in 方块表:
        工 = b.get("harvestTools") or {}
        方块[b["name"]] = {
            "名": b["name"],
            "硬度": b.get("hardness"),
            "能挖": bool(b.get("diggable", True)),
            "材料": b.get("material"),
            "需要工具": frozenset(编号到名.get(int(k), f"#{k}") for k in 工),
            "掉落": tuple(编号到名.get(d, f"#{d}") for d in (b.get("drops") or [])),
        }

    # ── 配方：**优先用服务端 jar 里那 1290 条**（含烧炼/高炉/切石/锻造）──
    #    minecraft-data 的 recipes.json 只有合成，而且把「木镐」展开成了 11 个变体
    #    （每种木板一条，没有 tag）；jar 版就一条 `wooden_pickaxe.json`，
    #    用料写的是 `#minecraft:planks` 这个**标签**，而标签定义 jar 里也带着。
    #    所以「哪些木板能互换」由原版自己说了算 —— 不用我们去猜、去推。
    产物到配方, 标签, 跳过 = {}, {}, {}
    try:
        import 原版配方 as 原版模块
        原 = 原版模块.载入()
        产物到配方 = 原["配方"]
        标签 = 原["标签"]
        跳过 = 原.get("跳过") or {}
        配方来源 = (f"服务端 jar（{len(产物到配方)} 种产物，"
                   f"{len(标签)} 个标签，含烧炼/高炉/切石/锻造）")
    except Exception as e:
        # ★ jar 读不了就退回 minecraft-data 那份（只有合成），
        #   并且**把这件事写在明面上** —— 不静默用一份残缺的数据。
        配方来源 = f"⚠ minecraft-data 兜底（jar 读不了：{type(e).__name__}: {e}）"
        for 键, 条 in 配方原.items():
            for r in (条 if isinstance(条, list) else [条]):
                if isinstance(r, dict):
                    _收配方(产物到配方, 编号到名, r)

    # 方块 → 哪个方块掉这个物品（给「挖掘获取」用）
    掉落索引 = {}
    for 名, b in 方块.items():
        for d in b["掉落"]:
            掉落索引.setdefault(d, []).append(名)

    _缓存 = {
        "目录": 目录,
        "版本": 版本,
        "物品": 物品表,
        "方块": 方块,
        "编号到名": 编号到名,
        "名到编号": 名到编号,
        "产物到配方": 产物到配方,
        "标签": 标签,                    # {标签名: [物品名,…]} —— 原版自己定义的等价类
        "配方来源": 配方来源,
        "跳过": 跳过,                    # 建模不了的配方类型（染色/烟花那种特殊合成）
        "掉落索引": 掉落索引,
    }
    return _缓存


def _收配方(产物到配方, 编号到名, r):
    """一条原版配方 → 我们的形状。

    原版两种形态：
        inShape:  [[id, id, id], [null, id, null]]   有序网格
        ingredients: [id, [id, id], …]                无序（每个位置可能是一组可互换的）
    """
    结 = r.get("result") or {}
    产物 = 编号到名.get(结.get("id"))
    if not 产物:
        return
    料 = {}
    if r.get("inShape"):
        for 行 in r["inShape"]:
            for c in 行:
                if c:
                    料[编号到名.get(c, f"#{c}")] = 料.get(编号到名.get(c, f"#{c}"), 0) + 1
    else:
        for c in (r.get("ingredients") or []):
            组 = c if isinstance(c, list) else [c]
            名 = 编号到名.get(组[0]) if 组 else None
            if 名:
                料[名] = 料.get(名, 0) + 1
    if not 料:
        return
    产物到配方.setdefault(产物, []).append({
        "产物": 产物,
        "产出数": int(结.get("count") or 1),
        "材料": 料,
        "有形状": bool(r.get("inShape")),
    })


# ══════════════════════════ 名字工具 ══════════════════════════

_木头种类 = None


def 木头种类():
    """所有木头种类（oak / spruce / cherry …）—— 从数据里推，不写死。

    ★ 为什么需要：原版 JSON 把「木板」展开成了 11 条配方（每种木头一条），
      没有 tag。求解器得知道这些是**可互换的**。
    """
    global _木头种类
    if _木头种类 is None:
        数 = 载入()
        _木头种类 = sorted({n[:-7] for n in 数["名到编号"] if n.endswith("_planks")})
    return _木头种类


def 同类物品(名):
    """给一个物品名，返回「和它可互换」的一族名字（含它自己）。

    现在只处理木板这一族（实测最常撞上）。其它族（原木、石头变体）以后要用再加。
    """
    if 名.endswith("_planks"):
        种 = 名[:-7]
        return [f"{x}_planks" for x in 木头种类()]
    return [名]


def 是木板(名):
    return 名.endswith("_planks")


# ══════════════════════════ 命令行自检 ══════════════════════════

if __name__ == "__main__":
    数 = 载入()
    print(f"数据目录：{os.path.relpath(数['目录'], ROOT)}")
    print(f"  版本 {数['版本']}")
    print(f"  物品 {len(数['物品'])} 个 / 方块 {len(数['方块'])} 个 / "
          f"有配方的产物 {len(数['产物到配方'])} 种 / 掉落索引 {len(数['掉落索引'])} 种")
    print(f"  配方来源：{数['配方来源']}")
    print(f"  物品标签 {len(数['标签'])} 个；建模不了的配方类型：{len(数['跳过'])} 种")
    print(f"  木头种类 {len(木头种类())} 种（从数据推的）")
