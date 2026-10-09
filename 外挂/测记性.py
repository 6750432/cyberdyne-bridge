#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""记性车厢 —— 离线测试。

English: Offline tests for the "memory" carriage: remember where we placed things, and
walk back to the remembered crafting table instead of crafting a new one.

跑法：python3 外挂/测记性.py
"""

import importlib.util
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
外挂根 = os.path.join(ROOT, "外挂")
通过, 失败 = [], []


def 试(名, 条件, 为啥="条件不成立"):
    (通过 if 条件 else 失败).append(名 if 条件 else {"名": 名, "为啥": 为啥})
    return bool(条件)


def 载(名):
    p = os.path.join(外挂根, 名, "补丁.py")
    spec = importlib.util.spec_from_file_location(f"测_{名}", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"测_{名}"] = m
    sys.path.insert(0, os.path.join(外挂根, 名))
    spec.loader.exec_module(m)
    return m


class 假任务栈:
    def __init__(self):
        self.接过的 = []

    def 接(self, 名字, 步骤, s):
        self.接过的.append((名字, 步骤))
        return True


class 假bridge:
    pass


def 造环境():
    b = 假bridge()
    类 = type("栈类", (), dict(vars(假任务栈)))
    b.任务栈 = 类
    return b, 类


def 主():
    sys.path.insert(0, 外挂根)
    sys.path.insert(0, ROOT)
    记 = 载("记性")
    # ★★★ 先钉住"账本到底落在哪儿" ✗ —— 我第一版 ROOT 少写了一层 dirname，
    #   账本落到 `外挂/logs/记性.json` 去了 ✗ 而用例当时把路径**整个换掉了** ✓
    #   → 用例全绿、实机全丢 ✓ 这就是「测试没覆盖真实路径」✓
    #   规矩：**先断言真实路径**长什么样 ✓ 再换成临时路径跑其余用例 ✓
    真路径 = os.path.normpath(记.账本路径)
    # 换到临时文件上（别污染实机的记性 ✓）
    记.账本路径 = os.path.join(tempfile.mkdtemp(), "记性.json")
    记._账.clear()
    试("A0 ★★★ 账本落在仓库的 logs/ 下（不是 外挂/logs/ ✗ —— 这里少写过一层 dirname）",
       os.path.basename(真路径) == "记性.json"
       and os.path.basename(os.path.dirname(真路径)) == "logs"
       and os.path.basename(os.path.dirname(os.path.dirname(真路径))) == "cyberdyne-bridge",
       str(真路径))
    b, 类 = 造环境()

    print("── A 组：装上 / 卸下 ──")
    r = 记.装上(b)
    试("A1 装上了", bool(r.get("好")), str(r))
    栈 = 类()
    r2 = 记.装上(b)
    试("A2 重复装是幂等的（不许套两层 ✓）", bool(r2.get("好")), str(r2))

    print("── B 组 ★★★ 记：自己放的，自己记得 ──")
    计划1 = [{"动作": "合成", "物品": "crafting_table", "数量": 1},
            {"动作": "放", "p": [-113, 80, 152], "方块": "crafting_table"},
            {"动作": "合成", "物品": "oak_planks", "数量": 4}]
    栈.接("第一次做东西", 计划1, {})
    试("B1 ★★★ 计划里「放 crafting_table @[-113,80,152]」→ **记下来了** ✓",
       记.想起("crafting_table") == [-113, 80, 152], str(记.想起("crafting_table")))

    print("── C 组 ★★★ 用：不再重做工作台 ──")
    #   ★ 主人原话：「自己放的东西肯定要记得自己放哪儿的啊，不管在哪儿，
    #     总不能又退回说重做工作台吧」✓
    计划2 = [{"动作": "合成", "物品": "crafting_table", "数量": 1},
            {"动作": "放", "p": [-120, 64, 160], "方块": "crafting_table"},
            {"动作": "合成", "物品": "stone_pickaxe", "数量": 1}]
    栈.接过的 = []
    栈.接("第二次做东西", 计划2, {})
    送 = 栈.接过的[-1][1]
    试("C1 ★★★ 又要「合成 crafting_table」→ **换成了「走到记住的坐标」** ✓",
       any(x.get("动作") == "走到" and list(x.get("p") or []) == [-113, 80, 152]
           for x in 送), str(送))
    试("C2 ★★★ 而且**不再重做一个**（合成 crafting_table 那一步没了 ✓）",
       not any(x.get("动作") == "合成" and x.get("物品") == "crafting_table" for x in 送),
       str(送))
    试("C3 ★★★ 后面紧跟的「放 crafting_table」也一并去掉 ✓（走过去了，不用再放 ✗）",
       not any(x.get("动作") == "放" and x.get("方块") == "crafting_table" for x in 送),
       str(送))
    试("C4 ★★ 计划里别的步骤**一字不动** ✓（别顺手改别人 ✗）",
       any(x.get("动作") == "合成" and x.get("物品") == "stone_pickaxe" for x in 送),
       str(送))

    print("── D 组：别的方块不乱动 / 账上没有就照原样 ──")
    栈.接过的 = []
    栈.接("换个东西", [{"动作": "合成", "物品": "furnace", "数量": 1},
                    {"动作": "放", "p": [-130, 70, 170], "方块": "furnace"}], {})
    送2 = 栈.接过的[-1][1]
    试("D1 ★★★ 只换「合成 crafting_table」这一种 ✓ 别的方块一步都不动 ✗"
       "（换个不相干的 = 拿假记忆骗自己 ✗）",
       any(x.get("动作") == "合成" and x.get("物品") == "furnace" for x in 送2), str(送2))
    试("D2 ★★ 顺手把炉子也记下来了 ✓（自己放的都记 ✓）",
       记.想起("furnace") == [-130, 70, 170], str(记.想起("furnace")))

    记._账.pop("crafting_table", None)
    栈.接过的 = []
    栈.接("没记忆了", [{"动作": "合成", "物品": "crafting_table", "数量": 1}], {})
    送3 = 栈.接过的[-1][1]
    试("D3 ★★★ 账上**没有**工作台 → 照原样（该做还是得做 ✓ 不许瞎编一个坐标 ✗）",
       any(x.get("动作") == "合成" and x.get("物品") == "crafting_table" for x in 送3),
       str(送3))

    print("── E 组：重启不丢（落盘 ✓）──")
    记.记("crafting_table", [-113, 80, 152])
    记._账.clear()
    记._读盘()
    试("E1 ★★★ 重启之后账还在 ✓（脑重启很频繁 ✓ 不落盘就等于没记 ✗）",
       记.想起("crafting_table") == [-113, 80, 152], str(记.想起("crafting_table")))

    print("── F 组：坐标形状不对就不记（不猜 ✓）──")
    记._账.clear()
    记.记计划([{"动作": "放", "方块": "chest", "p": None}])
    试("F1 ★★ 计划里那一格坐标是空的 → **不记** ✓（宁可没记性，也不记个假的 ✗）",
       记.想起("chest") is None, str(记.想起("chest")))

    print("── G 组：卸下还原 ──")
    记.卸下(b)
    栈2 = 类()
    栈2.接("卸下之后", [{"动作": "合成", "物品": "crafting_table", "数量": 1}], {})
    送4 = 栈2.接过的[-1][1]
    试("G1 ★★ 卸下之后计划**一字不差**（不再替换 ✓）",
       any(x.get("动作") == "合成" for x in 送4), str(送4))

    print(f"\n{'═' * 62}")
    print(f"记性车厢：{len(通过)} 过 / {len(失败)} 失败")
    for x in 通过:
        print(f"  ✅ {x}")
    for x in 失败:
        print(f"  ❌ {x['名']} —— {x['为啥']}")
    print("═" * 62)
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
