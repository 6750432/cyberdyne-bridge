#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M4.1·打击账本对账：跳劈 vs 平A，到底各打多少。

为什么需要它：2026-10-01 第一轮实测想做这个对比，结果回头一看 —— 证据没了。
（重启脚本 `>` 把叙事日志截断吃掉了。）教训是**别把证据寄托在叙事文字上**，
所以手那边现在落两份机器可读的账本：
    logs/全程-<日期>.jsonl   每一帧状态快照
    logs/账本-<日期>.jsonl   挥击 / 掉血 / 我掉血 / 我死了 / 目标倒下

这个脚本只做一件事：把「挥击」和「掉血」按时间戳配对，
把每一下的伤害算出来，按动词（attack / jumpattack）分组统计。

配对规则（写在明处，别让读者猜）：
  · 一条「掉血」认领离它最近、且在它之前 1.5 秒内的那一下「挥击」；
  · 每一下挥击最多认领一条掉血（MC 有 0.5 秒无敌帧，连着挥只有一下算数）；
  · 掉血的「从」和挥击那一刻记的「对方血」不一致时标出来 —— 说明中间
    还夹着别的掉血来源（摔落、别人打的、我上一下的延迟结算）。

⚠ 两个天然的误差，读数字时要记住：
  ① 探针 500ms 问一次，所以掉血事件的时刻有最多半秒的模糊；
  ② 对方如果在回血/吃牛排，掉血幅度会被吃掉一部分 —— **这里量到的是
     "净掉血"，是伤害的下界**。

用法：
    python3 tools/分析打击.py                 # 分析最新的账本
    python3 tools/分析打击.py logs/账本-xxx.jsonl
    python3 tools/分析打击.py --自检           # 用合成数据验一遍配对逻辑
"""
import argparse
import glob
import json
import os
import statistics as 统
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
窗口 = 1500          # 毫秒：掉血往前找挥击的时间窗


def 读账本(路径):
    条 = []
    with open(路径, encoding="utf-8") as f:
        for 行 in f:
            try:
                条.append(json.loads(行))
            except Exception:
                continue
    return 条


def 取结算(条):
    """主路径：直接读手那边落下的「结算」—— 一下一刀的净伤害，不含歧义。"""
    分组 = {}
    for e in 条:
        if e.get("事件") != "结算":
            continue
        伤害 = e.get("掉")
        if not isinstance(伤害, (int, float)):
            continue
        分组.setdefault(e.get("动词", "?"), []).append({
            "t": e["t"], "伤害": 伤害, "距离": e.get("距离"),
            "出手时对方血": e.get("出手时"), "掉血的从": e.get("出手时"), "对得上": True,
        })
    return 分组


def 配对(条):
    """兜底路径：账本里没有「结算」（老账本/结算查询失败）时，
    才退回去按时间窗配对。**有歧义的就丢掉不猜** —— 连击 650ms 一下、
    探针 500ms 一轮，同一个掉血前面常常站着两刀。
    返回 {(动词): [每一下的伤害]}、孤儿、有歧义的掉血。"""
    挥击 = [e for e in 条 if e.get("事件") == "挥击"]
    掉血 = [e for e in 条 if e.get("事件") == "掉血"]
    挥击.sort(key=lambda e: e["t"])
    掉血.sort(key=lambda e: e["t"])
    已认领 = set()
    分组 = {}
    孤儿 = []
    歧义 = []
    for d in 掉血:
        候选们 = [i for i, s in enumerate(挥击)
                  if i not in 已认领 and s["t"] <= d["t"] and d["t"] - s["t"] <= 窗口]
        if not 候选们:
            孤儿.append(d)
            continue
        if len(候选们) > 1:
            歧义.append(d)     # 前头站着不止一刀 —— 这一条不参与统计，不猜
            continue
        候选 = 候选们[0]
        已认领.add(候选)
        s = 挥击[候选]
        分组.setdefault(s.get("动词", "?"), []).append({
            "t": s["t"], "伤害": d.get("掉"), "距离": s.get("距离"),
            "出手时对方血": s.get("对方血"), "掉血的从": d.get("从"),
            "对得上": (s.get("对方血") is None or abs(s["对方血"] - d.get("从", -1)) < 0.11),
        })
    return 分组, 孤儿, 歧义, 挥击, 掉血


def 印表(分组, 孤儿, 歧义, 挥击, 掉血, 条, 来源):
    print(f"伤害来源：{来源}")
    print(f"账本共 {len(条)} 条：挥击 {len(挥击)}、掉血 {len(掉血)}、"
          f"我掉血 {sum(1 for e in 条 if e.get('事件') == '我掉血')}、"
          f"我死了 {sum(1 for e in 条 if e.get('事件') == '我死了')}、"
          f"目标倒下 {sum(1 for e in 条 if e.get('事件') == '目标倒下')}")
    if not 挥击:
        print("还没有挥击记录 —— 先打一场再来算。")
        return

    名 = {"attack": "平A", "jumpattack": "跳劈"}
    print(f"\n{'动词':<6}{'挥了':>5}{'真打中':>7}{'打尸体':>7}{'挥空/无敌帧':>12}"
          f"{'命中率':>8}{'平均':>8}{'中位':>8}{'最大':>8}{'最小':>8}")
    汇总 = {}
    for 动词, 条目 in sorted(分组.items()):
        全部 = [x["伤害"] for x in 条目 if isinstance(x["伤害"], (int, float))]
        尸体 = sum(1 for x in 条目 if isinstance(x.get("出手时对方血"), (int, float))
                   and x["出手时对方血"] <= 0)
        活靶 = len(全部) - 尸体
        伤害 = [x["伤害"] for x in 条目
                if isinstance(x["伤害"], (int, float)) and x["伤害"] > 0.05
                and not (isinstance(x.get("出手时对方血"), (int, float))
                         and x["出手时对方血"] <= 0)]
        总挥 = sum(1 for s in 挥击 if s.get("动词") == 动词)
        打中 = len(伤害)
        # 负数的"掉血"不是挥空，是对方回血/重生 —— 单列出来，别混进挥空
        回血 = sum(1 for x in 条目 if isinstance(x.get("伤害"), (int, float))
                   and x["伤害"] < -0.05)
        挥空 = max(活靶 - 打中 - 回血, 0)
        if not 伤害:
            汇总[动词] = None
            print(f"{名.get(动词, 动词):<6}{总挥:>5}{0:>7}{尸体:>7}{挥空:>12}"
                  f"{'—':>8}{'—':>8}{'—':>8}{'—':>8}{'—':>8}")
            continue
        汇 = (统.mean(伤害), 统.median(伤害), max(伤害), min(伤害))
        汇总[动词] = 汇
        命中 = 打中 / 活靶 * 100 if 活靶 else 0
        print(f"{名.get(动词, 动词):<6}{总挥:>5}{打中:>7}{尸体:>7}{挥空:>12}"
              f"{命中:>7.0f}%{汇[0]:>8.2f}{汇[1]:>8.2f}{汇[2]:>8.2f}{汇[3]:>8.2f}")
        if 回血:
            print(f"             （其中 {回血} 下结算到负数 —— 对方正在回血/重生，"
                  f"既不算命中也不算挥空）")

    if len(汇总) >= 2 and all(v for v in 汇总.values()):
        平 = 汇总.get("attack")
        跳 = 汇总.get("jumpattack")
        if 平 and 跳:
            print(f"\n  跳劈 / 平A = {跳[0]/平[0]:.2f} 倍（用平均值算）")
            print(f"  理论上铁剑：平A 6.0、暴击 9.0 → 1.50 倍")
            print(f"  ⚠ 穿甲之后两边都会被护甲削，比值仍然有参考价值，绝对值没有。")

    对不上 = [x for v in 分组.values() for x in v if not x["对得上"]]
    if 对不上:
        print(f"\n  ⚠ 有 {len(对不上)} 条掉血的起点和出手时记的血量对不上"
              f"（中间夹了别的掉血来源，比如摔落/回血）—— 这些也算进平均了。")
    if 孤儿:
        print(f"  ⚠ 有 {len(孤儿)} 条掉血没找到对应的挥击（大概是"
              f"摔落、自然回血反向、或者挥完超过 1.5 秒才结算）。")
    if 歧义:
        print(f"  ⚠ 有 {len(歧疑) if False else len(歧义)} 条掉血前面站着不止一刀 —— "
              f"按规矩不猜，没算进上面的统计。")

    # 双方的血：这一场"换血"划不划算
    我掉 = [e.get("掉", 0) for e in 条 if e.get("事件") == "我掉血"]
    if 我掉:
        print(f"\n  我这边：被打了 {len(我掉)} 次，一共掉 {sum(我掉):.1f} 血，"
              f"平均每次 {统.mean(我掉):.2f}")


def 自检():
    """用合成数据验配对：一下平A(6)、一下跳劈(9)、一下被无敌帧吃掉、一条孤儿。"""
    合成 = [
        {"t": 1000, "事件": "挥击", "动词": "attack", "对方血": 20.0, "距离": 2.0},
        {"t": 1500, "事件": "掉血", "目标": "X", "从": 20.0, "到": 14.0, "掉": 6.0},
        {"t": 2000, "事件": "挥击", "动词": "jumpattack", "对方血": 14.0, "距离": 2.1},
        {"t": 2200, "事件": "挥击", "动词": "attack", "对方血": 14.0, "距离": 2.0},
        {"t": 2500, "事件": "掉血", "目标": "X", "从": 14.0, "到": 5.0, "掉": 9.0},
        {"t": 9000, "事件": "掉血", "目标": "X", "从": 5.0, "到": 4.0, "掉": 1.0},
    ]
    分组, 孤儿, 歧义, 挥击, 掉血 = 配对(合成)
    平 = [x["伤害"] for x in 分组.get("attack", [])]
    跳 = [x["伤害"] for x in 分组.get("jumpattack", [])]
    合成结算 = [
        {"t": 1000, "事件": "结算", "动词": "attack", "目标": "X", "出手时": 20.0, "掉": 6.0},
        {"t": 2000, "事件": "结算", "动词": "jumpattack", "目标": "X", "出手时": 14.0, "掉": 9.0},
        {"t": 3000, "事件": "结算", "动词": "attack", "目标": "X", "出手时": 5.0, "掉": None},
        {"t": 4000, "事件": "挥击", "动词": "attack", "目标": "X"},   # 结算问不到 → 忽略
    ]
    结 = 取结算(合成结算)
    好 = True
    print("自检：")
    print(f"  ① 兜底配对（老账本）：平A {平}（期望 [6.0]：t=1500 那条前面只有一刀）")
    print(f"     跳劈 {跳}（期望空：t=2500 那条前面站着两刀 → 不猜）")
    print(f"     歧义 {len(歧义)} 条（期望 1 条）、孤儿 {len(孤儿)} 条（期望 1 条：t=9000 超窗口）")
    好 &= (平 == [6.0] and 跳 == [] and len(歧义) == 1 and len(孤儿) == 1)
    print(f"  ② 主路径（结算记录）：平A {[x['伤害'] for x in 结.get('attack',[])]}"
          f"（期望 [6.0]）、跳劈 {[x['伤害'] for x in 结.get('jumpattack',[])]}（期望 [9.0]）")
    print(f"     拿不到血量的那条被丢掉：{'✅' if len(结.get('attack', [])) == 1 else '❌'}")
    好 &= ([x["伤害"] for x in 结.get("attack", [])] == [6.0]
           and [x["伤害"] for x in 结.get("jumpattack", [])] == [9.0])
    print("  自检", "全过 ✅" if 好 else "有失败 ❌")
    return 0 if 好 else 1


def main():
    p = argparse.ArgumentParser()
    p.add_argument("账本", nargs="?", help="账本 jsonl 路径，缺省取最新的")
    p.add_argument("--自检", action="store_true")
    a = p.parse_args()
    if a.自检:
        return 自检()
    路径 = a.账本
    if not 路径:
        候选 = sorted(glob.glob(os.path.join(ROOT, "logs", "账本-*.jsonl")))
        if not 候选:
            print("logs/ 下还没有账本文件 —— 手那边要开着 record_all 跑过才有。")
            return 1
        路径 = 候选[-1]
    print(f"账本：{路径}")
    条 = 读账本(路径)
    挥击 = [e for e in 条 if e.get("事件") == "挥击"]
    掉血 = [e for e in 条 if e.get("事件") == "掉血"]
    分组 = 取结算(条)
    if 分组:
        来源 = "手上的「结算」记录（一刀一次单独问血量，不含歧义）"
        孤儿, 歧义 = [], []
    else:
        分组, 孤儿, 歧义, 挥击, 掉血 = 配对(条)
        来源 = "按时间窗兜底配对（账本里没有「结算」）"
    印表(分组, 孤儿, 歧义, 挥击, 掉血, 条, 来源)
    return 0


if __name__ == "__main__":
    sys.exit(main())
