#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测本地翻译器.py —— 确定性翻译的断言（主人 2026-10-09 第 4 条 ✓）

覆盖主人点名的两条（「做个石镐」「砍3个木头」）+ 它们的变体 ✓ + **Miss 必须回 None** ✓
（Miss 回 None 是**命门** ✓ —— 它要是瞎猜，后面可就没人兜了 ✗）
"""

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("本地翻译器", os.path.join(ROOT, "tools", "本地翻译器.py"))
本译 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(本译)

过, 失败 = 0, 0


def 试(名, 条件, 证据=""):
    global 过, 失败
    if 条件:
        过 += 1
        print("  ✅ %s" % 名)
    else:
        失败 += 1
        print("  ❌ %s —— %s" % (名, 证据))


def 主():
    # 测试用的小表 ✓（真表由调用方注入 ✓ 这里不复制真表 ✗）
    表 = {"石镐": "stone_pickaxe", "木镐": "wooden_pickaxe", "石头": "stone",
          "圆石": "cobblestone", "木头": "oak_log", "原木": "oak_log",
          "木板": "oak_planks", "木棍": "stick", "工作台": "crafting_table"}

    print("── A 组：精确意图字典（高频句式）──")
    一 = 本译.译一句("做个石镐", 表)
    试("A1 ★★★ 主人的原话「做个石镐」→ stone_pickaxe ✓",
      一 and 一.get("目标") == "stone_pickaxe", str(一))
    试("A2 ★★ 而且标明**哪一层**认出来的（可追溯 ✓）",
      一 and 一.get("层") == "精确意图字典", str(一))
    试("A3 「我要一把石镐」→ 同一个目标 ✓",
       (本译.译一句("我要一把石镐", 表) or {}).get("目标") == "stone_pickaxe")
    试("A4 「来把木镐」→ wooden_pickaxe ✓",
       (本译.译一句("来把木镐", 表) or {}).get("目标") == "wooden_pickaxe")
    试("A5 「帮我做个工作台」→ crafting_table ✓",
       (本译.译一句("帮我做个工作台", 表) or {}).get("目标") == "crafting_table")

    print("── B 组：正则提取器（带数量）──")
    二 = 本译.译一句("砍3个木头", 表)
    试("B1 ★★★ 主人的原话「砍3个木头」→ oak_log × 3 ✓",
      二 and 二.get("目标") == "oak_log" and 二.get("数量") == 3, str(二))
    试("B2 ★★ 「挖五个石头」→ stone × 5（中文数字 ✓）",
       (lambda r: r and r.get("目标") == "stone" and r.get("数量") == 5)(
           本译.译一句("挖五个石头", 表)))
    试("B3 ★★ 「打2根木头」→ 数量 2 ✓",
       (lambda r: r and r.get("数量") == 2)(本译.译一句("打2根木头", 表)))
    试("B4 ★ 「要十五个石头」→ 数量 15 ✓",
       (lambda r: r and r.get("数量") == 15)(本译.译一句("要十五个石头", 表)))
    试("B5 ★ 全角数字「３」也认 ✓",
       (lambda r: r and r.get("数量") == 3)(本译.译一句("挖３个石头", 表)))

    print("── C 组：**Miss 必须回 None**（命门 ✓ 不许瞎猜 ✗）──")
    试("C1 ★★★ 表里没有的东西 → None ✓（绝不猜一个差不多的 ✗）",
       本译.译一句("做个钻石镐", 表) is None, str(本译.译一句("做个钻石镐", 表)))
    试("C2 ★★★ 纯闲聊 → None ✓（交给 LLM 那条慢路 ✓）",
       本译.译一句("今天天气不错", 表) is None)
    试("C3 ★★★ 空话 → None ✓", 本译.译一句("", 表) is None and 本译.译一句(None, 表) is None)
    试("C4 ★★ 没有词表也不许猜 ✗（表是空的时候全部 Miss ✓）",
       本译.译一句("做个石镐", {}) is None and 本译.译一句("做个石镐", None) is None)

    print("── D 组：归一化（语气尾巴/空格）──")
    试("D1 ★★ 「做个石镐吧！」→ 照样认出来 ✓",
       (本译.译一句("做个石镐吧！", 表) or {}).get("目标") == "stone_pickaxe")
    试("D2 ★ 「做个 石镐」带空格也认 ✓",
       (本译.译一句("做个 石镐", 表) or {}).get("目标") == "stone_pickaxe")

    print()
    print("本地翻译器：%d 过 / %d 失败" % (过, 失败))
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
