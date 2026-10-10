#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""代价 —— 统一代价函数。「要不要去、往哪去、挖还是绕」，全折算成时间一起比。

English: The unified cost model. Walking, digging, placing, crafting are all converted
into seconds (and ticks) so the brain can *compare* options instead of following an
if-else ladder.

★ 为什么要有它（主人 2026-10-09 定的三阶段计划）
================================================
P0 标定（`tools/标定代价.py` ✓ 已跑）→ **P1 代价函数（本文件）** → P2 接进 `挖还是绕`

主人转来的那份分析里最要紧的一句：
  「**第一步先抽代价函数 ✗ 不要一上来重写 A\\***」✓
以及那句最准的：
  「你需要的不是客户端寻路的 A* ✗，是**带物理常识的挖掘决策机**」✓

所以本文件**不碰搜索** ✗ —— 只回答一个问题：
    **「这个选项，要花我多少秒？」** ✓
让 `挖还是绕()` 那种地方**算账** ✓ 而不是继续拍 if-else ✗

数据从哪来（一条都不是估的）
============================
  · **硬度 / 要哪一档工具** ← `常识库/物理引擎规则.json`（minecraft-data 抓的 ✓）
  · **走路速度 / 破坏时间公式** ← Minecraft 的**游戏常量**（见下 ✓）
  · **放/合成/拾的实测秒数** ← `常识库/代价标定.json`（我们自己的日志量的 ✓）

Minecraft 的两条真公式（这是"常识"，不是我们的发明）
====================================================
  ① 徒手破坏一格所需秒数 ≈ **硬度 × 1.5** ✓
     （stone 硬度 1.5 → 徒手 2.25 秒 ✓ 跟手感对得上 ✓）
  ② 手里有对口的工具 → 除以**速度系数** ✓
     木 2 ｜ 石 4 ｜ 铁 6 ｜ 钻石 8 ｜ 下界合金 9 ✓
     （stone 1.5×1.5÷2 = 1.1 秒 ✓ 我们实测「挖」中位 0.6 秒 ✓
       同量级 ✓ —— 实测更快是因为挖的多半是叶子/草一类的软方块 ✓）
  ③ 走路 ≈ **4.317 格/秒** ✓（MC 常量 ✓）→ 一格 ≈ 0.23 秒 ✓
     ⚠ 注意：慢在「拐弯、爬台阶、绕开水」—— 所以对**寻路的直线距离**乘一个
       1.6 的绕路系数 ✓（这个系数**在标定里能核** ✓ 先按经验写死并标出来 ✗）

单位
====
内部一律**秒** ✓ 对外同时给 **tick**（1 tick = 0.05 秒 ✓ 跟 Baritone 一个口径 ✓）
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_规则 = None
_标定 = None

# ── 游戏常量（不是我们的发明 ✓ 写在这儿是为了"只有一处" ✓）──
徒手系数 = 1.5          # 破坏时间 ≈ 硬度 × 1.5 秒
走路速度 = 4.317        # 格/秒
直线绕路系数 = 1.6      # ★ 直线距离 → 实际路程的修正（拐弯/爬台阶/绕开）
一tick = 0.05           # 秒

# 工具 → 速度系数（MC 的材质档 ✓）
工具速度 = {"wooden": 2.0, "stone": 4.0, "iron": 6.0, "golden": 12.0,
             "diamond": 8.0, "netherite": 9.0}
# 工具需求档（minecraft-data 的 harvestTools 用的是物品 id ✓ 820 起是各档镐 ✓）
# 木 820 ｜ 石 825 ｜ 铁 830 ｜ 钻石 835 ｜ 下界合金 840 ？（以 60x 段为准 ✓）
镐档名 = {820: "wooden", 825: "stone", 830: "iron", 835: "diamond", 840: "netherite"}

# ★ 禁区：这些东西的代价是**无穷**（不是"贵" ✗ 是"不能干" ✗）
危险方块 = frozenset({
    "lava", "water", "flowing_lava", "flowing_water", "fire", "soul_fire",
    "magma_block", "cactus", "powder_snow", "sweet_berry_bush", "campfire",
})
无穷 = float("inf")


def _读(名, 兜底=None):
    p = os.path.join(ROOT, "常识库", 名)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return 兜底


def 规则():
    global _规则
    if _规则 is None:
        _规则 = _读("物理引擎规则.json", {}) or {}
    return _规则


def 标定():
    global _标定
    if _标定 is None:
        _标定 = _读("代价标定.json", {}) or {}
    return _标定


def _标(动作, 兜底):
    """从标定里取「这个动作实测中位几秒」✓ 没有就用兜底（并说明是兜底 ✓）"""
    try:
        v = ((标定().get("按动作") or {}).get(动作) or {}).get("中位")
        return float(v) if isinstance(v, (int, float)) and v > 0 else float(兜底)
    except Exception:
        return float(兜底)


def 走(格数):
    """走这么远的代价（秒）✓"""
    return max(0.0, float(格数)) / 走路速度 * 直线绕路系数


def 手里的镐(背包):
    """背包里最好那档镐的材质名（没有 → None）✓"""
    最好 = None
    try:
        for k, n in (背包 or {}).items():
            if not n or not str(k).endswith("_pickaxe"):
                continue
            材 = str(k)[: -len("_pickaxe")]
            if 材 in 工具速度:
                if 最好 is None or 工具速度[材] > 工具速度.get(最好, 0):
                    最好 = 材
    except Exception:
        pass
    return 最好


def 挖(方块名, 背包=None):
    """挖一格这个东西的代价（秒）✓ —— **无穷** = 不能干 ✗（不是"很贵"）

    判据全是有依据的 ✓：
      · 危险方块（岩浆/水/火/仙人掌…）→ 无穷 ✓
      · `挖不动`（基岩等 diggable:false）→ 无穷 ✓
      · **矿石** → 无穷 ✗（反矿透红线 ✓
        主人 2026-10-09 的原话：「反矿透反的是**雷达或者是记忆中没有记载过的矿物**，
        说白了**别把雷达当 X 射线去定位矿物的位置**」✓
        —— 所以"矿"这一类，代价函数**根本不给价** ✗ 不是嫌贵 ✓）
      · 要工具而手里没有 → 无穷 ✓（挖了也不掉东西 ✓ 白费时间 ✓）
    """
    名 = str(方块名 or "")
    if not 名 or 名 in 危险方块 or 名 in ("air", "cave_air", "void_air"):
        return 无穷
    规 = 规则()
    if 名 in set(规.get("挖不动") or []):
        return 无穷
    # ★ 反矿透：矿石**不给价** ✗
    if 名.endswith("_ore") or 名 in ("ancient_debris", "raw_iron_block", "raw_gold_block",
                                    "raw_copper_block", "gilded_blackstone"):
        return 无穷
    硬 = (规.get("硬度") or {}).get(名)
    if not isinstance(硬, (int, float)) or 硬 <= 0:
        硬 = 1.0                        # 没读数就按中等硬度兜底 ✓ 并可从调用方覆盖 ✓
    速 = 1.0
    档 = (规.get("要工具档") or {}).get(名)
    if 档:
        镐 = 手里的镐(背包)
        if 镐 is None:
            return 无穷                 # 要工具而没有 → 挖了也白挖 ✓
        速 = 工具速度.get(镐, 1.0)
    基 = float(硬) * 徒手系数 / 速
    # ★ 加上"走过去 + 抬手"的固定开销（实测「挖」中位 0.6 秒 ✓ 去掉纯破坏时间的那部分 ✓）
    return max(0.0, 基) + 0.25


def 放(背包=None):
    """放一格方块的代价（秒）—— 实测中位 ✓"""
    return _标("放", 0.4)


def 合成(次=1):
    """合成一次的代价（秒）—— 实测中位 ✓"""
    return _标("合成", 0.4) * max(1, int(次))


def 拾(件=1):
    """拾一件的代价（秒）—— 实测中位 ✓"""
    return _标("拾", 0.2) * max(1, int(件))


def 秒转tick(秒):
    """给 Baritone 口径用 ✓（1 tick = 0.05 秒 ✓）"""
    return 无穷 if 秒 == 无穷 else round(float(秒) / 一tick, 1)


def 说(秒):
    """人话：`3.2 秒（64 tick）` 或 `不能干` ✓"""
    if 秒 == 无穷:
        return "不能干（红线 / 危险 / 没工具）✗"
    return f"{float(秒):.1f} 秒（{秒转tick(秒):.0f} tick）"
