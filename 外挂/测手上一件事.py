#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手上一件事车厢 —— 离线测试。

English: Offline tests for the "one thing at a time" carriage: the same command aimed at
the same target must only reach the wire once per interval, while everything else passes.

跑法：python3 外挂/测手上一件事.py
"""

import importlib.util
import json
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
    """照主链的形状：`发` 是**实例属性**（`bridge.py:1378` `self.发 = 发命令`）✓"""

    def __init__(self):
        self.发的 = []
        self.发 = self._真发

    def _真发(self, obj):
        self.发的.append(obj)
        return True


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


def 造环境():
    b = 假bridge()
    类 = type("栈类", (), dict(vars(假任务栈)))
    b.任务栈 = 类
    return b, 类


def 主():
    sys.path.insert(0, 外挂根)
    sys.path.insert(0, ROOT)
    b, 类 = 造环境()

    r = 车.装上(b) if False else None      # 占位：下面用直接用 补丁.装上（不经车钩）
    常 = 载("手上一件事")

    print("── A 组：装上 / 卸下 ──")
    r装 = 常.装上(b)
    试("A1 装上了", bool(r装.get("好")), str(r装))
    栈 = 类()                              # ★ 造在装**之后**（主链就是这个顺序 ✓）
    试("A2 ★★ 新造出来的栈，发出口上有闸（`发` 是实例属性，靠包 __init__ 盖上 ✓）",
       getattr(栈.发, "__name__", "") == "发", str(getattr(栈.发, "__name__", "?")))
    r又 = 常.装上(b)
    试("A3 ★★ 再装一次是幂等的（不许套两层 ✓）", bool(r又.get("好")), str(r又))

    print("── B 组：核心 —— 同一条命令 + 同一个目标，短时间只准上一次线 ──")
    栈.发的 = []
    丢 = [栈.发({"cmd": "goto", "p": [-143.0, 79.0, 149.0]}) for _ in range(5)]
    试("B1 ★★★ 同一条 goto 连喊 5 次 → **只有 1 次真的上了线**"
       "（实机 63 秒 310 次就是这儿漏的 ✗）",
       # ★ 铁律：同一条命令**只准上线一次** ✓
       #   而"被拦下要回 False"（= 没发出去 ✓ 主链靠它记"卡住"✓）——
       #   我一度改成 True ✗，靠一个错的判断（见 补丁.py 里那段说明）⇒ 已按证据撤回 ✓
       len(栈.发的) == 1 and 丢[0] is True and 丢[1] is False,
       f"上线 {len(栈.发的)} 条 / 返回 {丢}")

    栈.发的 = []
    for _ in range(3):
        栈.发({"cmd": "dig", "p": [-131.0, 76.0, 155.0]})
    试("B2 ★★★ 同一个 dig 连喊 3 次 → 只上线 1 次（挥镐子不用每 0.2 秒重来 ✓）",
       len(栈.发的) == 1, str(len(栈.发的)))

    print("── C 组：别误伤 —— 换目标 / 说话 / 不认识的命令 ──")
    栈.发的 = []
    栈.发({"cmd": "goto", "p": [10.0, 60.0, 10.0]})
    栈.发({"cmd": "goto", "p": [11.0, 60.0, 10.0]})
    栈.发({"cmd": "goto", "p": [12.0, 60.0, 10.0]})
    试("C1 ★★★ 换个坐标照发 ✓（只拦「同一个目标」的重复 ✗ 不误伤正常走位）",
       len(栈.发的) == 3, str(len(栈.发的)))

    栈.发的 = []
    for i in range(4):
        栈.发({"cmd": "say", "text": f"第 {i} 句"})
    试("C2 ★★★ 说话**一律不拦** ✗ —— 那是主人等的话，不是手在做的事 ✓",
       len(栈.发的) == 4, str(len(栈.发的)))

    栈.发的 = []
    for _ in range(4):
        栈.发({"cmd": "某个我不认识的命令", "p": [1, 2, 3]})
    试("C3 ★★★ 认不出来的命令**一律放行** ✓（fail-open：宁可多问一句，"
       "也不要因为不认识就把动作闷死 ✗）",
       len(栈.发的) == 4, str(len(栈.发的)))

    # ⚠ 用**没发过的坐标** ✓ —— 不然上一组刚发的那个还在间隔里 ✗（我第一版就栽在这儿）
    栈.发的 = []
    栈.发({"act": "goto", "p": [31.0, 60.0, 31.0]})
    栈.发({"act": "goto", "p": [31.0, 60.0, 31.0]})
    试("C4 ★★ 手侧两种写法都要认（`cmd` 和 `act` ✓ 主链发 goto 用的是 `act` ✓）",
       len(栈.发的) == 1, str(len(栈.发的)))

    print("── D 组：过一阵子就该放行（别把动作闷死 ✗）──")
    栈.发的 = []
    常._上次.clear()
    栈.发({"cmd": "dig", "p": [-131.0, 76.0, 155.0]})
    常._上次[("dig", (-131.0, 76.0, 155.0))] = time.time() - 99.0
    栈.发({"cmd": "dig", "p": [-131.0, 76.0, 155.0]})
    试("D1 ★★ 过了间隔就放行 ✓（闸是「别重复喊」，不是「不许干」✓）",
       len(栈.发的) == 2, str(len(栈.发的)))

    print("── E 组：卸下要还原（留在实例上的闸也得拆掉 ✓）──")
    常.卸下(b)
    栈2 = 类()
    栈2.发的 = []
    for _ in range(3):
        栈2.发({"cmd": "goto", "p": [20.0, 60.0, 20.0]})
    试("E1 ★★★ 卸下以后**一字不差还原**：新造的栈没有闸 ✓",
       len(栈2.发的) == 3, str(len(栈2.发的)))
    栈3 = 栈                                  # 卸下之前就活着的那个 ✓
    栈3.发的 = []
    for _ in range(3):
        栈3.发({"cmd": "goto", "p": [21.0, 60.0, 21.0]})
    试("E2 ★★★ **卸下之前活着的**栈也还原了 ✓（实例上的闸得逐个摘 ✗ 忘一个就是漏一个 ✗）",
       len(栈3.发的) == 3, str(len(栈3.发的)))

    print(f"\n{'═' * 62}")
    print(f"手上一件事车厢：{len(通过)} 过 / {len(失败)} 失败")
    for x in 通过:
        print(f"  ✅ {x}")
    for x in 失败:
        print(f"  ❌ {x['名']} —— {x['为啥']}")
    print("═" * 62)
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
