#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标定代价 —— 从**我们自己的日志**里量出「一个动作要几秒」。

English: Calibrates action costs from our own logs. Real measured seconds, not guesses.

★ 为什么先做这个（2026-10-09 定的三阶段计划 P0）
================================================
主人转来的那份分析里，最要紧的一句是「第一步先抽代价函数 ✗ 不要一上来重写 A*」✓
而代价函数要**有单位、有来源** ✓ 不能拍脑袋 ✗
我们**已经有了**最有价值的东西：`logs/任务.jsonl` 里每一条「步骤完成 … 用了 N 秒」✓
—— 那是**真实耗时** ✓ 拿它标定 ✓ 比估强一万倍 ✓

跑法：python3 tools/标定代价.py
      产物：常识库/代价标定.json（代价函数读它 ✓）
"""

import json
import os
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
任务账 = os.path.join(ROOT, "logs", "任务.jsonl")
回执账 = os.path.join(ROOT, "logs", "回执.jsonl")
产物 = os.path.join(ROOT, "常识库", "代价标定.json")


def 量步骤账():
    """从任务账本量：动作 -> [用了秒, ...] ✓"""
    表 = {}
    if not os.path.isfile(任务账):
        return 表
    for ln in open(任务账, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        if d.get("事件") != "步骤完成":
            continue
        动 = str(d.get("动作") or "")
        用 = d.get("用了")
        if 动 and isinstance(用, (int, float)) and 用 >= 0:
            表.setdefault(动, []).append(float(用))
    return 表


def 量回执账():
    """从回执账本量：命令 从"发出"到"有结果"隔了几秒 ✓（配对法 ✓）

    ⚠ 只认**成 = True** 的：失败的那条是"没干成"✓ 不能当"干这件事要多久"✗
    """
    待 = {}                      # (命令, 目标串) -> 发出时刻
    表 = {}
    if not os.path.isfile(回执账):
        return 表
    for ln in open(回执账, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        t = d.get("时刻")
        if not isinstance(t, (int, float)):
            continue
        命 = str(d.get("命令") or "")
        步 = str(d.get("步") or "")
        k = (命, 步)
        if d.get("成不成") is None:            # 刚发出去，还没结果 ✓
            待[k] = t
            continue
        if d.get("成不成") is True and k in 待:
            表.setdefault(命, []).append(round(t - 待.pop(k), 3))
        else:
            待.pop(k, None)
    return 表


def 汇总(v):
    if not v:
        return None
    v = sorted(v)
    return {"次": len(v),
            "中位": round(statistics.median(v), 2),
            "均值": round(sum(v) / len(v), 2),
            "最小": round(v[0], 2),
            "最大": round(v[-1], 2)}


def 主():
    print("═══ 标定代价（数据来自我们自己的日志）═══\n")
    步 = 量步骤账()
    print("【按动作】任务账本「步骤完成 … 用了 N 秒」")
    print(f"  {'动作':<12}{'次数':>6}{'中位':>8}{'均值':>8}{'最小':>8}{'最大':>8}")
    出 = {}
    for 动, v in sorted(步.items(), key=lambda kv: -len(kv[1])):
        s = 汇总(v)
        出[动] = s
        print(f"  {动:<12}{s['次']:>6}{s['中位']:>8}{s['均值']:>8}"
              f"{s['最小']:>8}{s['最大']:>8}")

    回 = 量回执账()
    if 回:
        print("\n【按命令】回执账本「发出 → 有结果」的间隔（只算成功的 ✓）")
        print(f"  {'命令':<14}{'次数':>6}{'中位':>8}{'均值':>8}{'最小':>8}{'最大':>8}")
        for 命, v in sorted(回.items(), key=lambda kv: -len(kv[1])):
            s = 汇总(v)
            print(f"  {命:<14}{s['次']:>6}{s['中位']:>8}{s['均值']:>8}"
                  f"{s['最小']:>8}{s['最大']:>8}")

    出2 = {
        "_说明": "★ 从**我们自己的日志**里量出来的真实耗时 —— 代价函数的**唯一数据来源** ✓ 不是估的 ✗",
        "_怎么来的": "tools/标定代价.py：读 logs/任务.jsonl 的「步骤完成 … 用了 N 秒」"
                 "（按动作分组）+ logs/回执.jsonl 的「发出→有结果」间隔（按命令分组，只算成功的 ✓）",
        "_单位": "秒（跟 Baritone 的 tick 口径可以对上：1 tick = 0.05 秒 ✓ 250 tick = 12.5 秒 ✓）",
        "什么时候量的": time.strftime("%Y-%m-%d %H:%M"),
        "按动作": 出,
        "按命令": {k: 汇总(v) for k, v in 回.items()} if 回 else {},
        "_怎么用": "生存常识的代价函数读这个文件 ✓ —— "
                "「挖一格泥土」的代价 = 这里量出来的秒数 ✓ 不是猜的 ✗",
        "_下次什么时候重量": "队列换手/换版本之后 ✓ 或者主人觉得它变慢或变快了 ✓ 重跑一次就更新 ✓",
    }
    os.makedirs(os.path.dirname(产物), exist_ok=True)
    with open(产物, "w", encoding="utf-8") as f:
        json.dump(出2, f, ensure_ascii=False, indent=1)
    print(f"\n→ 写进 {产物}")
    return 0


if __name__ == "__main__":
    sys.exit(主())
