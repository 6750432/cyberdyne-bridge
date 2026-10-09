#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复核车厢 —— 离线测试。

English: Offline tests for the missing middle layer: every tick it re-reads the live
frame, compares it against what the step assumed, and quotes the account out loud.

跑法：python3 外挂/测复核.py
"""

import importlib.util
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
外挂根 = os.path.join(ROOT, "外挂")
通过, 失败 = [], []


def 试(名, 条件, 为啥="条件不成立"):
    (通过 if 条件 else 失败).append(名 if 条件 else {"名": 名, "为啥": 为啥})
    return bool(条件)


class 假任务栈:
    """照主链的形状：真 `任务栈.跑` 返回布尔 ✓，任务挂在 `self.任务` 上 ✓"""

    def __init__(self, 任务=None):
        self.任务 = 任务
        self.跑过 = 0

    def 跑(self, s):
        self.跑过 += 1
        return False


class 假bridge:
    pass


def 载(名):
    p = os.path.join(外挂根, 名, "补丁.py")
    spec = importlib.util.spec_from_file_location(f"测_{名}", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"测_{名}"] = m
    sys.path.insert(0, os.path.join(外挂根, 名))
    spec.loader.exec_module(m)
    return m


def 造环境(步骤, 第几步=0):
    b = 假bridge()
    类 = type("栈类", (), dict(vars(假任务栈)))
    b.任务栈 = 类
    栈 = 类({"状态": "跑", "第几步": 第几步, "步骤": 步骤, "步骤开始": time.time()})
    return b, 类, 栈


def 主():
    sys.path.insert(0, 外挂根)
    sys.path.insert(0, ROOT)
    复 = 载("复核")
    import tempfile
    复.账本 = os.path.join(tempfile.mkdtemp(), "复核.jsonl")
    复._说过.clear()

    print("── A 组：装上 / 卸下 ──")
    b, 类, 栈 = 造环境([{"动作": "挖", "p": [10, 60, 10], "方块": "stone"}])
    r = 复.装上(b)
    试("A1 装上了", bool(r.get("好")), str(r))
    r2 = 复.装上(b)
    试("A2 ★★ 重复装是幂等的（不许套两层 ✓ 今天在别的车厢栽过 ✗）", bool(r2.get("好")), str(r2))

    print("── B 组 ★★★ 现状对不上要出声（今天的 5/5 就是这一类）──")
    # ① 挖 stone，可那一格读到 dirt（实机 15:32 那一幕）
    b, 类, 栈 = 造环境([{"动作": "挖", "p": [10, 60, 10], "方块": "stone"}])
    复.卸下(b)
    复.装上(b)
    复._说过.clear()
    栈.跑({"pos": [12.5, 60, 10.5],
          "blocks": [{"p": [10, 60, 10], "name": "dirt"}], "items": {}})
    条 = [__import__("json").loads(x) for x in open(复.账本, encoding="utf-8")]
    试("B1 ★★★ 「挖 stone」可那一格读到 **dirt** → 判「现状对不上」✗"
       "（实机 15:32 就是这么翻的：陈坐标 → 三连「等了 0 秒」✗）",
       bool(条) and 条[-1]["对得上"] is False and 条[-1]["报了"] is True, str(条[-1:]))

    # ② 走到一个 10.7 格外的坐标（实机 14:47 那一幕）
    b, 类, 栈 = 造环境([{"动作": "走到", "p": [-122, 80, 156]}])
    复.卸下(b)
    复.装上(b)
    复._说过.clear()
    栈.跑({"pos": [-114.5, 80.0, 152.0], "blocks": [], "items": {}})
    条 = [__import__("json").loads(x) for x in open(复.账本, encoding="utf-8")]
    试("B2 ★★★ 「走到」一个 10.7 格外的点 → 判「够不着」✗"
       "（实机 14:47：那地方在 10.7 格外／手最多伸 4.5 格 ✗）",
       bool(条) and 条[-1]["对得上"] is False, str(条[-1:]))

    # ③ 拾 oak_log，可背包里 0（实机 14:28 那一幕）
    b, 类, 栈 = 造环境([{"动作": "拾", "物品": "oak_log", "数量": 1}])
    复.卸下(b)
    复.装上(b)
    复._说过.clear()
    栈.跑({"pos": [0, 60, 0], "blocks": [], "items": {"oak_planks": 4}})
    条 = [__import__("json").loads(x) for x in open(复.账本, encoding="utf-8")]
    试("B3 ★★★ 「拾 oak_log」可背包里是 0 → 判「现状对不上」✗"
       "（实机 14:28：原木早在第 6 步变成木板了 → 干等 60 秒 ×3 ✗）",
       bool(条) and 条[-1]["对得上"] is False, str(条[-1:]))

    print("── C 组：对得上就**别吭声** ✓（不许刷屏 ✗ 那也是另一种静默 ✓）──")
    b, 类, 栈 = 造环境([{"动作": "挖", "p": [10, 60, 10], "方块": "stone"}])
    复.卸下(b)
    复.装上(b)
    复._说过.clear()
    栈.跑({"pos": [12.5, 60, 10.5],
          "blocks": [{"p": [10, 60, 10], "name": "stone"}], "items": {}})
    条 = [__import__("json").loads(x) for x in open(复.账本, encoding="utf-8")]
    试("C1 ★★★ 那一格还是 stone ✓ → **不报**（对得上就别吭声 ✓）",
       bool(条) and 条[-1]["对得上"] is True and 条[-1]["报了"] is False, str(条[-1:]))

    print("── D 组：同一处**只说一次** ✗（不然每拍刷屏 ✓ 那也是静默 ✓）──")
    b, 类, 栈 = 造环境([{"动作": "挖", "p": [10, 60, 10], "方块": "stone"}])
    复.卸下(b)
    复.装上(b)
    复._说过.clear()
    帧坏 = {"pos": [12.5, 60, 10.5],
           "blocks": [{"p": [10, 60, 10], "name": "dirt"}], "items": {}}
    报了 = []
    复._日志 = lambda 文: 报了.append(文)
    for _ in range(5):
        栈.跑(帧坏)
    复._日志 = None
    试("D1 ★★★ 同一处连着 5 拍 → **只出声一次** ✓（说过的就记住 ✓）",
       len(报了) == 1, f"报了 {len(报了)} 次")

    print("── E 组 ★★★ 账：该花多久 vs 已经过了多久（这才是「上牙」✓）──")
    b, 类, 栈 = 造环境([{"动作": "挖", "p": [10, 60, 10], "方块": "obsidian"}], 第几步=0)
    复.卸下(b)
    复.装上(b)
    复._说过.clear()
    栈.任务["步骤开始"] = time.time() - 300      # 假装已经挖了 5 分钟
    栈.任务["步骤"][0]["方块"] = "obsidian"
    报了 = []
    复._日志 = lambda 文: 报了.append(文)
    栈.跑({"pos": [12.5, 60, 10.5],
          "blocks": [{"p": [10, 60, 10], "name": "obsidian"}], "items": {"wooden_pickaxe": 1}})
    复._日志 = None
    条 = [__import__("json").loads(x) for x in open(复.账本, encoding="utf-8")]
    试("E1 ★★★ 黑曜石挖了 300 秒 → **账**算出来了（木镐几十秒一格 ✓）",
       bool(条) and isinstance(条[-1]["账秒"], (int, float)) and 条[-1]["账秒"] > 20,
       str(条[-1:]))
    试("E2 ★★★ **超了账要出声** ✓（「比账上慢 N 倍」✓ —— 主人看得见它卡在哪 ✓）",
       any("慢" in str(x) for x in 报了), str(报了))

    print("── F 组 ★★★ 只报告、**不杀活儿** ✗（主人：「我自己挖石头都要赌一下多久」✓）──")
    b, 类, 栈 = 造环境([{"动作": "挖", "p": [10, 60, 10], "方块": "obsidian"}])
    复.卸下(b)
    复.装上(b)
    复._说过.clear()
    栈.任务["步骤开始"] = time.time() - 300
    栈.跑({"pos": [12.5, 60, 10.5],
          "blocks": [{"p": [10, 60, 10], "name": "obsidian"}], "items": {"wooden_pickaxe": 1}})
    a = 栈.任务["步骤"][0].get("p")
    b2 = 栈.任务["步骤"][0].get("方块")
    试("F1 ★★★ 它**一个字都没改**（不带 `跳过`、不改坐标、不改方块名 ✗）——"
       "「挖多久是活儿说了算，不是表说了算」✓ 复核只报告 ✗ 不杀活儿 ✗",
       list(a) == [10, 60, 10] and b2 == "obsidian"
       and not 栈.任务["步骤"][0].get("跳过")
       and not 栈.任务["步骤"][0].get("超时_ms"),
       str(栈.任务["步骤"][0]))

    print("── G 组：卸下还原 ──")
    复.卸下(b)
    栈2 = 类({"状态": "跑", "第几步": 0,
              "步骤": [{"动作": "挖", "p": [10, 60, 10], "方块": "stone"}],
              "步骤开始": time.time()})
    报了 = []
    复._日志 = lambda 文: 报了.append(文)
    栈2.跑({"pos": [12.5, 60, 10.5],
          "blocks": [{"p": [10, 60, 10], "name": "dirt"}], "items": {}})
    复._日志 = None
    试("G1 ★★ 卸下之后**不再复核**（一声不吭 ✓ 还原干净 ✓）",
       not 报了 and 栈2.跑过 == 1, str(报了))

    print(f"\n{'═' * 62}")
    print(f"复核车厢：{len(通过)} 过 / {len(失败)} 失败")
    for x in 通过:
        print(f"  ✅ {x}")
    for x in 失败:
        print(f"  ❌ {x['名']} —— {x['为啥']}")
    print("═" * 62)
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
