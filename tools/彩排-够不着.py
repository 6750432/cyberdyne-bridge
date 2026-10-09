#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端彩排：手侧回执 → 车厢 → 主链任务循环（离线，不连服务器）。

English: Rehearses the full round trip offline — a real `任务栈` instance accepts a
task, the hand refuses because the target is out of reach, the carriage inserts a walk
step, and the main chain's own loop then walks instead of retrying the refusal.

为什么要它（单元断言的缺口）
============================
`测够不着自愈.py` 证的是"车厢自己干得对" ✓
可它**证不了**"车厢插的那一步，主链的任务循环真会去走它" ✗ ——
中间隔着 `_下一步()` 的步数推进、退避、节流……哪一环接不上，
实机上照样是"插了步却不动" ✓

所以这儿**起一个真任务栈**（主链那个类 ✓ 不是替身），只把它跟外面通消息的出口换成
一个列表 ✓ —— 然后走一遍完整链路：

    接单 → 跑一拍（发 place）→ 手回「够不着」→ 车厢插一步
         → 再跑一拍 → **应该发 goto**（而不是继续 place ✓）

⚠ 这是"**真**任务栈 + 假出口"，不是"假任务栈" ✓ —— 两者的区别就是本文件的全部价值 ✓
   （今天在"替身和被测对象不同源"上栽过四轮 ✓ 见交接文档【八】2）

跑法：python3 tools/彩排-够不着.py
"""

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
外挂根 = os.path.join(ROOT, "外挂")
sys.path.insert(0, 外挂根)
sys.path.insert(0, ROOT)

通过, 失败 = [], []


def 试(名, 条件, 为啥="条件不成立"):
    (通过 if 条件 else 失败).append(名 if 条件 else {"名": 名, "为啥": 为啥})
    return bool(条件)


def 造真栈():
    """起一个**真**任务栈（主链那个类），只把往外通的出口换成列表 ✓"""
    import bridge
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
    栈._撤探针 = lambda: None
    栈._数 = lambda 名, 缺: {"每步重试上限": 2, "重试倍率": 1.0, "动手重下毫秒": 0,
                          "走路重下毫秒": 0, "到点半径": 2.5}.get(名, 缺)
    return 栈


def 造帧():
    帧 = {"pos": [5.5, 64.0, 30.5], "items": {"crafting_table": 1}, "blocks": [], "scan": {}}
    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            帧["blocks"].append({"p": [10 + dx, 64, 10 + dz], "name": "air"})
            帧["blocks"].append({"p": [10 + dx, 63, 10 + dz], "name": "stone"})
    return 帧


def 主():
    import bridge

    spec = importlib.util.spec_from_file_location(
        "彩排_够不着", os.path.join(外挂根, "够不着自愈", "补丁.py"))
    车 = importlib.util.module_from_spec(spec)
    sys.modules["彩排_够不着"] = 车
    spec.loader.exec_module(车)

    栈 = 造真栈()

    class 假桥:
        pass

    桥 = 假桥()
    桥.任务栈 = type(栈)
    桥.叙事者 = type("叙类", (), {
        "最后状态": None,
        "说": lambda self, *a, **k: None,
        "看回执": lambda self, e: None,
    })
    桥.任务栈.车钩活着的实例 = [栈]
    桥.叙事者.车钩活着的实例 = [桥.叙事者()]

    r = 车.装上(桥)
    试("R1 车厢装上了（**三个**补丁点都在：看回执 / _失败 / _下发）",
       r["好"] and len(r["打了"]) == 3, str(r))

    帧 = 造帧()
    好 = 栈.接("放个工作台", [{"动作": "放", "p": [10, 64, 10], "方块": "crafting_table"}], 帧)
    试("R2 真任务栈接了单", 好 is True and 栈.任务["状态"] == "跑", str(好))

    # ── 第 1 拍：主链应该把 place 发出去 ──
    栈.跑(帧)
    发的1 = list(栈.发的)
    试("R3 第 1 拍：主链自己把 `place` 发出去了（不是车厢代劳）",
       any(x.get("cmd") == "place" for x in 发的1), str(发的1))

    # ── 手侧回「够不着」──
    叙 = 桥.叙事者.车钩活着的实例[0]
    叙.最后状态 = 帧
    说明 = 车.处理回执(桥, 帧, {"cmd": "place", "ok": False, "够不着": True, "距": 5.2,
                                "why": "那地方在 5.2 格外，够不着"})
    试("R4 ★★★ 车厢当场把「够不着」变成下一步（插了一步「走到」）",
       bool(说明) and any("走到" in str(说明) or "第 1 次插步" in str(说明) for _ in [0]),
       str(说明))
    步骤 = [x.get("动作") for x in 栈.任务["步骤"]]
    试("R5 ★★★ 插的位置对：**当前那一步之前**（走到在前、放还在后头）",
       步骤 == ["走到", "放"], str(步骤))
    试("R6 ★★ 重试账清零了（不清的话：走完再放一次就被判整任务失败 ✗）",
       栈.任务["重试"] == 0 and 栈.任务["重试到"] == 0.0, str(栈.任务["重试"]))

    # ── 第 2 拍：**主链的任务循环真会去走那一步吗**（本文件的全部价值 ✓）──
    栈.发的 = []
    栈.跑(帧)
    发的2 = list(栈.发的)
    试("R7 ★★★ 第 2 拍：主链**去走那一步了**（发的是 goto，不是继续 place）"
       "—— 插进去的步真被任务循环接住了 ✓",
       any(x.get("act") == "goto" for x in 发的2) and
       not any(x.get("cmd") == "place" for x in 发的2), str(发的2))
    试("R8 ★★ 走的目标就是车厢算的那个「落点旁边」（够得着落点）",
       发的2 and 发的2[0].get("p") is not None
       and max(abs(发的2[0]["p"][0] - 10), abs(发的2[0]["p"][2] - 10)) <= 1.5,
       str(发的2[:1]))

    # ── 走完以后：应该**回头放**（不是把「放」丢了）──
    栈.任务["第几步"] = 1
    栈.发的 = []
    栈.跑(帧)
    发的3 = list(栈.发的)
    试("R9 ★★★ 走完以后**回头放**（原来那一步没被丢掉 ✓）",
       any(x.get("cmd") == "place" for x in 发的3), str(发的3))

    车.卸下(桥)
    试("R10 ★★ 卸下以后一字不差还原（类上的壳还回去了 ✓）",
       栈._下发.__func__ is bridge.任务栈._下发, str(栈._下发))

    print()
    print("═" * 62)
    print(f"彩排·够不着：{len(通过)} 过 / {len(失败)} 失败")
    for x in 失败:
        print(f"  ❌ {x['名']} —— {x['为啥']}")
    print("═" * 62)
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
