#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""声呐耳朵车厢 —— 离线断言。

要证明的四件事：
  A 装上 / 幂等 / 卸下 —— 原来那条路一个字不改
  B **不是口令的话不乱动**（正常聊天不许被当成命令）
  C ★★★ **听见口令 → 当场认出 → 当场做计划 → 当场接单**（不等心跳）
  D 元件缺失时**什么都不做**并说清为什么（耳朵听不清不许把脑弄哑）

跑法：python3 外挂/测声呐耳朵.py
"""

import importlib.util
import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
外挂根 = os.path.join(ROOT, "外挂")
通过, 失败 = [], []


def 试(名, 条件, 为啥="条件不成立"):
    (通过 if 条件 else 失败).append(名 if 条件 else {"名": 名, "为啥": 为啥})
    return bool(条件)


def 载(名, 模块名):
    p = os.path.join(外挂根, 名, "补丁.py")
    spec = importlib.util.spec_from_file_location(模块名, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[模块名] = m
    sys.path.insert(0, os.path.join(外挂根, 名))
    spec.loader.exec_module(m)
    return m


class 假叙事者:
    def __init__(self):
        self.最后状态 = {"pos": [-178, 72, 162], "scan": {"t": 0}}
        self.说的话 = []

    def 看事件(self, e):
        self.收到 = getattr(self, "收到", 0) + 1
        return "原来看事件跑完了"

    def 说(self, 文, 紧急=False):
        self.说的话.append(文)


class 假翻译器:
    def __init__(self, 任=None):
        self.任 = 任
        self.叫了几次 = 0

    def 收输出(self, 输出, 状态, 用途=None, *a, **k):
        self.叫了几次 += 1
        return "计划", self.任, None


class 假任务栈:
    def __init__(self, 好=True):
        self.好 = 好
        self.接过的 = []

    def 接(self, 名字, 步骤, s):
        self.接过的.append((名字, list(步骤 or [])))
        return self.好


class 假bridge:
    pass


def 造环境(任=None, 栈好=True):
    """搭一个"活实例"齐全的假脑。"""
    译 = 假翻译器(任)
    栈 = 假任务栈(栈好)
    译类 = type("译类", (), {"车钩活着的实例": [译]})
    栈类 = type("栈类", (), {"车钩活着的实例": [栈]})
    叙类 = 假叙事者
    b = 假bridge()
    b.翻译器, b.任务栈, b.叙事者 = 译类, 栈类, 叙类
    return b, 译, 栈


def 假生存常识(结果="stone_pickaxe"):
    m = types.ModuleType("假生存常识")
    m._上次原话 = {"原话": "", "时刻": 0.0, "说话人": None}
    def 认口令(最久前=90.0):
        # 照真车厢的语义：**有"命令动词"才认**（闲聊不算）✓
        原 = str(m._上次原话.get("原话") or "").lower()
        词 = ("gei", "zuo", "bang", "yao", "给", "做", "帮", "要", "造")
        return 结果 if (原 and any(w in 原 for w in 词)) else None
    m.认口令 = 认口令
    sys.modules["假生存常识"] = m
    return m


def 主():
    sys.path.insert(0, 外挂根)
    耳 = 载("声呐耳朵", "测_声呐耳朵")
    常 = 假生存常识()

    # ══════════ A 装卸 ══════════
    print("── A 组：装上 / 幂等 / 卸下 ──")
    b, 译, 栈 = 造环境(任={"名字": "常识：造石镐", "步骤": [{"动作": "走到", "p": [1, 2, 3]}]})
    原 = 假叙事者.看事件          # ★ 必须**装上之前**抓（抓晚了抓到的是壳 ✗）
    r = 耳.装上(b, 日志=lambda *a, **k: None)
    试("A1 装上了", r.get("好") is True, str(r))
    试("A2 看事件被换掉了", 假叙事者.看事件 is not 原)
    试("A3 幂等", 耳.装上(b)["为什么"].find("已经装过") >= 0)
    试("A4 卸下能还原（一字不差）",
       耳.卸下(b)["好"] is True and 假叙事者.看事件 is 原)

    # ══════════ B 不是口令不乱动 ══════════
    print("── B 组：不是口令就不管 ──")
    耳.装上(b, 日志=lambda *a, **k: None)
    叙 = 假叙事者()
    常._上次原话["原话"] = ""
    得 = 耳.接单(b, 叙, {"kind": "chat", "from": "mintstar", "text": "今天天气不错"})
    试("B1 ★★ 闲聊不算命令（返回 None，什么都不做）", 得 is None, str(得))
    试("B2 而且没去打扰翻译器", 译.叫了几次 == 0, str(译.叫了几次))
    试("B3 原来看事件照常跑完（行为一个字不改）",
       叙.看事件({"kind": "chat", "from": "mintstar", "text": "闲聊"}) == "原来看事件跑完了")

    # ══════════ C 听见口令 → 当场接单 ══════════
    print("── C 组：听见口令当场动身 ──")
    b2, 译2, 栈2 = 造环境(任={"名字": "常识：造石镐",
                             "步骤": [{"动作": "走到", "p": [1, 2, 3]},
                                    {"动作": "挖", "p": [4, 5, 6], "方块": "oak_log"}]})
    耳.装在 = None
    耳.卸下(b)
    耳.装上(b2, 日志=lambda *a, **k: None)
    叙2 = 假叙事者()
    # 只走**包装过的那条路**（直调 + 再走一次 = 接了两单 ✗ 上一版就是这么挂的）
    叙2.看事件({"kind": "chat", "from": "mintstar",
              "text": "ni bang wo zuo yi ge shi gao"})
    得2 = "；".join(叙2.说的话)
    试("C1 ★★★ 认出口令并当场接单（不等心跳）", "耳朵接单 ✓" in str(得2), str(得2))
    试("C2 ★★★ **任务栈真的收到活了**（名字 + 两步）",
       len(栈2.接过的) == 1 and 栈2.接过的[0][0] == "常识：造石镐"
       and len(栈2.接过的[0][1]) == 2, str(栈2.接过的))
    试("C3 ★★ 计划是**当场**推的（翻译器被叫了一次）", 译2.叫了几次 == 1, str(译2.叫了几次))
    试("C4 ★★ 原话被记进了「上次原话」（认口令靠它 + 90 秒时效）",
       "ni bang wo" in str(常._上次原话.get("原话")), str(常._上次原话))
    试("C5 ★★ 还会开口说一声（主人看得见它听见了）",
       any("接单" in t for t in 叙2.说的话), str(叙2.说的话))

    # ══════════ D 元件缺失不装死 ══════════
    print("── D 组：元件缺失 → 说清为什么，不装死 ──")
    b3, _, 栈3 = 造环境()
    b3.翻译器 = type("空译", (), {"车钩活着的实例": []})       # 没有活翻译器
    得3 = 耳.接单(b3, 假叙事者(), {"kind": "chat", "from": "m", "text": "gei wo ge shi gao"})
    试("D1 ★★ 找不到翻译器 → 说清为什么（不是静默失败）",
       "翻译器" in str(得3), str(得3))
    b4, _, _ = 造环境(任={"名字": "常识：造石镐", "步骤": [{"动作": "走到", "p": [1, 2, 3]}]}, 栈好=False)
    得4 = 耳.接单(b4, 假叙事者(), {"kind": "chat", "from": "m", "text": "gei wo ge shi gao"})
    试("D2 ★★ 任务栈拒单 → 照实转达", "被拒" in str(得4), str(得4))
    无状态 = 假叙事者(); 无状态.最后状态 = None
    得5 = 耳.接单(b4, 无状态, {"kind": "chat", "from": "m", "text": "gei wo ge shi gao"})
    试("D3 ★★ 还没有扫描帧 → 说清「等下一拍」，不瞎接", "等下一拍" in str(得5), str(得5))

    print("\n" + "═" * 62)
    print(f"声呐耳朵车厢：{len(通过)} 过 / {len(失败)} 失败")
    for f in 失败:
        print(f"  ❌ {f['名']} —— {f['为啥']}")
    print("═" * 62)
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
