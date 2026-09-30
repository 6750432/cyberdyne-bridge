#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M3·指令层回归测试。**不花钱、不连网、不连游戏**，纯离线断言。

为什么要有它：
    2026-09-30 出过一次经典 bug —— 「跟紧我」被解析成"我跟着 XiaoJiaHuo（它自己）"。
    根因是**代词被一路漂到了云端**，让大模型替我们做指代消解。
    当时的"修法"是改提示词措辞，看着好了，其实只是把 bug 藏起来。

    所以这里把「代词归一」和「指令解析」都钉成用例。
    以后谁改了这两块，跑一下就知道有没有退化。

用法：
    python3 tools/测指令.py            # 全部跑一遍
    python3 tools/测指令.py --详细      # 连通过的用例也打出来

退出码：0 = 全过；1 = 有失败。
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import bridge  # noqa: E402

自己名 = "XiaoJiaHuo"


def 建指令层():
    发出去的 = []
    d = bridge.指令层({"command": {"enable": True, "reply": False}},
                     lambda s, 紧急=False, not_used=None: None,
                     lambda c: 发出去的.append(c))
    d.发出的 = 发出去的
    return d


def 用例_代词():
    """指代消解：代词必须在进下游之前就被换成名字。"""
    别人 = ["mintstar", "小明"]
    return [
        # (原文, 说话人, 别人, 归一后必须包含, 归一后必须不含)
        ("跟紧我，别走丢了", "mintstar", ["mintstar"], "mintstar", "我"),
        ("跟着我", "mintstar", ["mintstar"], "mintstar", "我"),
        ("你过来", "mintstar", ["mintstar"], 自己名, "你"),
        ("我们自己玩", "mintstar", ["mintstar"], "mintstar", "我们"),
        # 「他」的判据：除了说话人和自己之外，在场的人**唯一**才敢认
        ("去找他", "mintstar", ["mintstar", "小明"], "小明", ""),          # 只有一个第三方 → 认
        ("去找他", "mintstar", ["mintstar", "小明", "小红"], "他", ""),     # 两个第三方 → 不敢认，原样留
        ("这是我的世界", "mintstar", ["mintstar"], "我的世界", ""),   # 误伤词要罩住
        ("那其他东西呢", "mintstar", ["mintstar"], "其他", ""),       # 误伤词要罩住
    ]


def 用例_解析():
    """指令层模板：说得清楚的话必须听懂，说不清楚必须老实说听不懂。"""
    return [
        # (说话人, 原文, 期望 act 或 None, 期望的 who/name)
        ("mintstar", "跟着我", "follow", "mintstar"),
        ("mintstar", "别跟了", "stop", None),
        ("mintstar", "他是我朋友", "friend", "mintstar"),
        ("mintstar", "不是我朋友了", "unfriend", "mintstar"),      # 否定句不能被肯定句抢走
        ("mintstar", "别打那只猫", "friend", "cat"),               # 口语名要翻成实体名
        ("mintstar", "别打苦力怕", "friend", "creeper"),
        ("mintstar", "去 10 70 5", "goto", None),
        ("mintstar", "吃东西", "eat", None),
        ("mintstar", "你血怎么样", "status", None),
        ("mintstar", "停", "stop", None),
        ("mintstar", "今天天气真好", None, None),                   # 必须听不懂，不能瞎猜
        ("mintstar", "给我建个房子", None, None),
        # ── M4 身体动作（手 + 腿）：全部本地确定性，不经过大模型 ──
        ("mintstar", "蹲下", "sneak", None),
        ("mintstar", "跳劈它", "jumpattack", None),      # 必须排在「跳」前面
        ("mintstar", "跳一下", "jump", None),
        ("mintstar", "潜下去", "swimdown", None),
        ("mintstar", "挖 10 64 5", "dig", None),
        ("mintstar", "放下 10 65 5", "place", None),
        ("mintstar", "合成面包", "craft", None),
        ("mintstar", "开箱子 5 64 5", "use", None),
    ]


def 用例_校验():
    """白名单校验：不进名单的动作一律丢弃。"""
    基 = {"bot": 自己名, "pos": [0.0, 78.0, 0.0],
          "players": [{"name": "mintstar", "dist": 8.0, "pos": [0, 78, 8]}]}
    大 = bridge.大模型层({"llm": {}}, lambda s, 紧急=False: None, "/tmp")
    return [
        ('{"act":"follow","who":"mintstar"}', 基, True),
        ('{"act":"follow","who":"%s"}' % 自己名, 基, False),        # ★ 跟着自己跑 → 荒谬
        ('{"act":"follow","who":"查无此人"}', 基, False),
        ('{"act":"attack","target":"mintstar"}', 基, False),        # 攻击类不给
        ('{"act":"mine"}', 基, False),
        ('{"act":"self_destruct"}', 基, False),
        ('{"act":"goto","p":[500,70,500]}', 基, False),             # 太远
        ('{"act":"goto","p":[10,70,5]}', 基, True),
        ('{"act":"say","text":"你好"}', 基, True),
        ('我今天心情不错', 基, False),
        ('{}', 基, False),
    ] + [(x, 基, False) for x in ["{}"]]


def 主():
    p = argparse.ArgumentParser()
    p.add_argument("--详细", action="store_true")
    a = p.parse_args()

    过 = 失 = 0
    失败明细 = []

    def 判(名, 条件, 说明=""):
        nonlocal 过, 失
        if 条件:
            过 += 1
            if a.详细:
                print(f"    ✓ {名}")
        else:
            失 += 1
            失败明细.append(f"{名}  {说明}")
            print(f"    ✗ {名}  {说明}")

    print("① 指代消解（代词必须在进下游前换成名字）")
    for 原, 谁, 别人, 必须含, 必须不含 in 用例_代词():
        出, 换 = bridge.代词.归一(原, 谁, 自己名, 别人)
        说明 = f"「{原}」→「{出}」换了{换}"
        判(f"{原} @{谁}", 必须含 in 出, 说明)
        if 必须不含:
            判(f"{原} 不含「{必须不含}」", 必须不含 not in 出, 说明)

    print("② 指令解析（说得清楚要懂，说不清楚要老实说不会）")
    d = 建指令层()
    for 谁, 原, 期望, 期望谁 in 用例_解析():
        动 = d.解析(谁, 原)
        真 = 动.get("act") if 动 else None
        判(f"「{原}」→ {期望}", 真 == 期望, f"实际 {真}")
        if 期望 and 期望谁:
            实谁 = (动 or {}).get("who") or (动 or {}).get("name")
            判(f"「{原}」的 who/name = {期望谁}", 实谁 == 期望谁, f"实际 {实谁}")

    print("③ 白名单校验（不进名单的一律丢弃）")
    大 = bridge.大模型层({"llm": {}}, lambda s, 紧急=False: None, "/tmp")
    for 回复, 基, 期望通过 in 用例_校验():
        出 = 大.校验(回复, 基)
        判(f"校验 {str(回复)[:34]}", bool(出) == 期望通过,
           f"期望{'通过' if 期望通过 else '丢弃'}，实际{'通过' if 出 else '丢弃'}")

    print()
    print(f"═══ 共 {过 + 失} 条：通过 {过}，失败 {失} ═══")
    if 失败明细:
        print("失败明细：")
        for x in 失败明细:
            print("  ✗ " + x)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(主())
