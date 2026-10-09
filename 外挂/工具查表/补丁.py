#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具查表车厢 —— 把主链里那条硬编码的「要镐子」换成查真表。

主人 2026-10-09 早：「又不动了」
================================
查下来真凶在**主链**里（bridge.py 第 1901 行附近）：

    if 名 and _要镐子(名) and not self._有工具(s, "pickaxe"):
        return self._失败(步, f"我手里没有镐子，挖不了「{名}」", s)

它有一条**自己的、硬编码的**「哪些方块要镐子」判断 ✗ —— 认为 grass_block 要镐子。
于是：**在把手之前就判死了** ✗
  · 手侧（proto_body.js）我昨晚已经改成查真表了 ✓
  · 可那一步**根本轮不到手说话** —— 脑先拒 ✓
  · 结论：修了手、也修了表，它还是不动（主人：「又不动了」）

bridge.py 是红线（一个字节不许改）✗ —— 所以这节车厢在**内存里**把
`bridge._要镐子` 换成查真表的版本 ✓ 磁盘上 bridge.py 一字不动 ✓

规矩
====
1. 表里有的方块 → **按表说**（草/土/沙/砾/原木/树叶 → 不要镐子 ✓；石头/煤/铁 → 要 ✓）
2. 表里**没有**的方块 → **交回原来那个函数**（fail-safe：宁可守着老规矩，也不乱放行 ✗）
3. 卸下时**一字不差还原** ✓；装上**幂等** ✓
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_日志 = None
_原件 = {}
_表 = None


def _说(文):
    if _日志:
        try:
            _日志(文)
            return
        except Exception:
            pass
    print(文, flush=True)


def _载表():
    global _表
    if _表 is not None:
        return _表
    for 路 in (os.path.join(ROOT, "外挂", "常识", "方块交互表.json"),
               os.path.join(ROOT, "常识库", "方块交互表.json")):
        try:
            with open(路, encoding="utf-8") as f:
                _表 = (json.load(f) or {}).get("方块") or {}
            return _表
        except Exception:
            continue
    _表 = {}
    return _表


def 要镐子吗(名, 原函数=None):
    """查表：这个方块要不要镐子才掉东西。表里没有 → 交回原函数。"""
    条 = _载表().get(str(名))
    if isinstance(条, dict):
        return "镐子" in (条.get("要") or [])
    if 原函数 is not None:
        try:
            return bool(原函数(名))
        except Exception:
            return False
    return False


def 装上(bridge, 日志=None, **kw):
    global _日志
    _日志 = 日志
    表 = _载表()
    if not 表:
        return {"好": False, "为什么": "方块交互表读不到（外挂/常识/方块交互表.json）",
                "打了": []}
    原名 = "_要镐子"
    if getattr(bridge, "_工具查表装了", False):
        return {"好": True, "为什么": "已经装过了（幂等）", "打了": []}
    原 = getattr(bridge, 原名, None)
    if not callable(原):
        return {"好": False, "为什么": f"bridge.{原名} 不是函数（锚点没了）", "打了": []}
    _原件[id(bridge)] = (原名, 原)

    def 新的(名):
        return 要镐子吗(名, 原)

    新的.__name__ = getattr(原, "__name__", 原名)
    setattr(bridge, 原名, 新的)
    bridge._工具查表装了 = True
    _说(f"[工具查表] 挂上了：{原名} 换成查真表（{len(表)} 个方块）—— "
        f"草/土/沙/砾/原木 不再要镐子")
    return {"好": True, "为什么": "", "打了": [
        f"bridge.{原名}()  ← 换成查表（表里没有的交回原函数，fail-safe）"]}


def 卸下(bridge):
    global _日志
    原 = _原件.pop(id(bridge), None)
    if not 原:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    名, 函 = 原
    setattr(bridge, 名, 函)
    try:
        del bridge._工具查表装了
    except AttributeError:
        pass
    _日志 = None
    return {"好": True, "为什么": "", "打了": [f"还原 bridge.{名}()"]}
