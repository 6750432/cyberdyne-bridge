#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探针：一个「挖 oak_log」为什么会被判成'完成了'（离线复盘，不连服务器）。

English: Probe why a "挖 oak_log" step is judged complete while the block is still
there. Builds a real `任务栈` with the real formation mounted, then asks every layer.

背景（2026-10-09 14:28 实机）：
    第 8 步「挖」用了 0.2 秒就说做完了 ✗ 可雷达上 oak_log(-116,80,152) 还在 ✓
    → 紧接着第 9 步「拾 oak_log」空跑三趟超时 → 整条任务失败 ✗

跑法：python3 tools/探挖完成.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
外挂根 = os.path.join(ROOT, "外挂")
sys.path.insert(0, 外挂根)
sys.path.insert(0, ROOT)

import bridge                      # noqa: E402
import 车钩 as HK                  # noqa: E402

目标 = [-116, 80, 152]
块名 = "oak_log"


def 造帧(块还在=True):
    """造一帧跟实机那一拍同形的最小状态帧。"""
    blocks = [{"p": list(目标), "name": 块名}]
    # 身边四格补上（主链/车厢都可能要看）
    for d in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        blocks.append({"p": [目标[0] + d[0], 目标[1], 目标[2] + d[1]], "name": "air"})
    if not 块还在:
        for b in blocks:
            if b["p"] == list(目标):
                b["name"] = "air"
    drops = [{"name": 块名, "p": [目标[0], 目标[1], 目标[2]]}] if not 块还在 else []
    return {
        "pos": [-114.5, 80.0, 152.0],
        "yaw": 0.0, "pitch": 0.0,
        "blocks": blocks,
        "drops": drops,
        "items": {"oak_planks": 4, "stick": 1, "bread": 3, "dried_kelp": 2},
        "hand": {"动作": "挖", "p": list(目标), "状态": "跑"},
        "now": 1791527322.5,
    }


def 起车():
    """起一列**真**车（真 bridge + 真编组），返回 (车, 栈)。"""
    车 = HK.列车(bridge, 安静=True)
    车.车厢表 = HK.发现车厢()
    编组 = json.load(open(os.path.join(外挂根, "编组.json"), encoding="utf-8"))["编组"]
    r = 车.换轨(编组, "探针")
    print(f"  编组：{编组}")
    print(f"  换轨结果：{r!r}")
    return 车, 车.编组


def 造栈():
    """真任务栈 + 假出口（跟 tools/彩排-够不着.py 同款做法）。"""
    栈 = bridge.任务栈.__new__(bridge.任务栈)
    栈.发的 = []
    栈.发 = lambda m: 栈.发的.append(m)
    栈.日志 = lambda *a, **k: None
    栈.记忆 = None
    栈.m = {}
    栈.任务 = None
    栈._探针 = None
    栈.允许动作 = bridge.任务栈.允许动作
    栈.上次下发 = 0.0
    栈.说 = lambda 文, 紧急=False: None
    栈._记 = lambda *a, **k: None
    栈._存快照 = lambda: None
    return 栈


def 谁判的(栈, 步, s, 任):
    """逐层问：谁会返回 True。"""
    命中 = []
    类 = bridge.任务栈
    # 遍历 MRO 上的所有 `_看完成了没`（车厢是替换类属性，所以只有最外那层能拿到）
    层 = []
    名字 = getattr(类, "_看完成了没", None)
    while 名字 is not None:
        层.append(名字)
        名字 = getattr(getattr(名字, "__wrapped__", None), None) if False else None
    for i, f in enumerate(层):
        try:
            r = f(栈, 步, s, 任)
        except Exception as e:
            r = f"炸了：{type(e).__name__}: {e}"
        print(f"    层[{i}] {getattr(f, '__module__', '?')}.{getattr(f, '__qualname__', f)}")
        print(f"           → {r!r}")
    print(f"  最终类上那一层：{getattr(类._看完成了没, '__module__', '?')}"
          f".{getattr(类._看完成了没, '__qualname__', '?')}")
    return 命中


def main():
    print("═══ 探针：挖 oak_log 为什么被判完成 ═══")
    print("— 起车 —")
    车, _ = 起车()

    print("— 造栈 —")
    栈 = 造栈()
    任 = {"名字": "常识：stone_pickaxe", "第几步": 8}
    栈.任务 = 任

    步 = {"动作": "挖", "p": list(目标)}

    for 标签, 块还在 in (("方块还在（实机那一刻）", True), ("方块真没了", False)):
        s = 造帧(块还在=块还在)
        print(f"— 情形：{标签} —")
        try:
            名 = 栈._方块名(s, 目标)
        except Exception as e:
            名 = f"炸了：{e}"
        print(f"  栈._方块名 → {名!r}")
        谁判的(栈, 步, s, 任)
        try:
            print(f"  → 栈._看完成了没 = {栈._看完成了没(步, s, 任)!r}")
        except Exception as e:
            print(f"  → 栈._看完成了没 炸了：{type(e).__name__}: {e}")
        print()

    # 再加一条：`_有工具` 被谁包着、返回啥
    print("— _有工具(s, 'pickaxe') 的当前实现 —")
    f = bridge.任务栈._有工具
    print(f"  {getattr(f, '__module__', '?')}.{getattr(f, '__qualname__', '?')}")
    print(f"  → {f({'items': {}}, 'pickaxe')!r}")


if __name__ == "__main__":
    main()
