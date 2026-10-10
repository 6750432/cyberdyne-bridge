#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分饭车厢 —— 离线测试。

★ 最重要的一组是 E 组：它把主人那句「**前提是自己够吃**」钉成了断言 ——
  哪怕只剩 1 份，它也**不许**分出去，而且要说清楚为什么。

跑法：python3 外挂/测分饭.py
"""

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
外挂根 = os.path.join(ROOT, "外挂")
通过, 失败 = [], []


def 试(名, 条件, 为啥="条件不成立"):
    (通过 if 条件 else 失败).append(名 if 条件 else {"名": 名, "为啥": 为啥})
    return bool(条件)


class 假栈:
    # ★ 主链的「允许动作」是**类属性**（动作面车厢也打在类上），照它来
    允许动作 = frozenset({"走到", "挖", "放", "说", "合成"})

    def __init__(self):
        self.发的 = []
        self.任务 = None
        self.说过 = []

    def 发(self, m):
        self.发的.append(m)

    def 说(self, 文, **kw):
        self.说过.append(str(文))

    @staticmethod
    def _物品数量(s, 名):
        return float((s or {}).get("items", {}).get(名, 0))

    def _挂探针(self, 步骤, s):
        return "原装-挂"

    def _下发(self, 步, 任, 现在, s):
        return "原装-下发"

    def _看完成了没(self, 步, s, 任=None):
        return False, None


class 假指令层:
    def __init__(self):
        self.喊过 = []

    def 解析(self, 说话人, 原文=""):
        self.喊过.append((说话人, 原文))
        return {"act": "chat", "文本": "原装-闲聊"}

    def 说(self, 文):
        self.喊过.append(("说", 文))


class 假桥:
    def __init__(self):
        self.任务栈 = 假栈
        self.指令层 = 假指令层          # 类：车厢往类上打补丁
        self.栈 = 假栈()                # 实例：测试要调方法，得带 self
        self.指 = 假指令层()            # 同上


def 帧(items=None):
    return {"items": dict(items or {})}


def 主():
    sys.path.insert(0, 外挂根)
    sys.path.insert(0, ROOT)
    import bridge
    spec = importlib.util.spec_from_file_location(
        "测_分饭", os.path.join(外挂根, "分饭", "补丁.py"))
    饭 = importlib.util.module_from_spec(spec)
    sys.modules["测_分饭"] = 饭
    spec.loader.exec_module(饭)

    # ══════════ A 组：装 / 卸 ══════════
    print("── A 组：装、卸、钩子点 ──")
    试("A1 ★★ 主链上真有这四个钩子（不然装了等于没装）",
       all(hasattr(bridge.任务栈, n) for n in ("_挂探针", "_下发", "_看完成了没"))
       and hasattr(bridge.指令层, "解析"))
    原类看 = 假栈._看完成了没
    桥 = 假桥()
    r = 饭.装上(桥)
    试("A2 ★★ 装上了，报了 5 个钩子", r["好"] and len(r["打了"]) == 5, str(r))
    试("A3 ★★★ 允许动作里多了「给」", "给" in 假栈.允许动作, str(sorted(假栈.允许动作)))
    试("A4 ★★ 三个钩子真的被换掉了", 假栈._看完成了没 is not 原类看)
    试("A5 ★★★ 重复装上不会套两层壳", 饭.装上(桥)["打了"] == [])
    试("A6 ★★ 卸下以后允许动作和钩子都还回原样",
       饭.卸下(桥)["好"] and 假栈._看完成了没 is 原类看 and "给" not in 假栈.允许动作)
    试("A7 ★ 钩子对不上就拒绝上岗（不是装作没看见）",
       饭.装上(type("坏桥", (), {"任务栈": type("空", (), {})(), "指令层": type("空2", (), {})()})())["好"] is False)

    # ══════════ B 组：够吃才分 ══════════
    print("── B 组：算账（够吃才分）──")
    栈 = 假栈()
    名, 数 = 饭.算分多少(栈, 帧({"cooked_beef": 10}), 保留=4, 一次=3)
    试("B1 ★★ 10 份、留 4 份 → 分 3 份出去", (名, 数) == ("cooked_beef", 3), f"{名}×{数}")

    名, 数 = 饭.算分多少(栈, 帧({"cooked_beef": 5}), 保留=4, 一次=3)
    试("B2 ★★★ **只剩 1 份富余就只分 1 份**，绝不超额（这是「自己够吃」的底线）",
       (名, 数) == ("cooked_beef", 1), f"{名}×{数}")

    名, 数 = 饭.算分多少(栈, 帧({"bread": 2, "cooked_beef": 1}), 保留=4, 一次=3)
    试("B3 ★★★ 总共才 3 份、要留 4 份 → **一口都不分**，而且给出理由",
       名 is None and "不够分" in str(数), f"{名} / {数}")

    名, 数 = 饭.算分多少(栈, 帧({}), 保留=4, 一次=3)
    试("B4 ★★ 一口吃的都没有 → 说清楚，而不是硬塞空气",
       名 is None and "一口吃的都没有" in str(数), str(数))

    # ══════════ C 组：可着最富余的分 ══════════
    print("── C 组：分哪一种 ──")
    名, 数 = 饭.算分多少(栈, 帧({"cooked_beef": 3, "bread": 12}), 保留=4, 一次=3)
    试("C1 ★★ 两种都有 → 挑**最富余**的那种（bread 12 > cooked_beef 3），别把少的分光",
       (名, 数) == ("bread", 3), f"{名}×{数}")

    名, 数 = 饭.算分多少(栈, 帧({"cooked_beef": 9, "bread": 2}), 保留=4, 一次=3)
    试("C2 ★★ 反过来也成立（cooked_beef 9 更富余）", (名, 数) == ("cooked_beef", 3), f"{名}×{数}")

    名, 数 = 饭.算分多少(栈, 帧({"cookie": 64}), 保留=4, 一次=100)
    试("C3 ★ 一次要 100 份也最多给 64（一叠的上限）", (名, 数) == ("cookie", 60), f"{名}×{数}")

    # ══════════ D 组：口令走本地，不问大模型 ══════════
    print("── D 组：口令「分我点吃的」──")
    桥 = 假桥()
    饭.装上(桥)
    指 = 桥.指
    任务 = 桥.指.解析("mintstar", "分我点吃的")
    试("D1 ★★★ 认得出「分我点吃的」，而且**一次都没往下传**（大模型压根没被请示）",
       len(指.喊过) == 0, f"往下传了 {len(指.喊过)} 次：{指.喊过}")
    试("D2 ★★★ 直接变成一条任务书：一步「给」",
       任务["act"] == "task" and 任务["步骤"][0]["动作"] == "给", str(任务))
    试("D3 ★★ 任务书里记着是谁要的（谁 = mintstar）", 任务["步骤"][0]["谁"] == "mintstar")
    试("D4 ★★★ 任务书里**没有「物品」字段** —— 分什么得等下发时看着背包现算",
       "物品" not in 任务["步骤"][0], str(任务["步骤"][0]))

    试("D5 ★★ 「我饿了」也认", 桥.指.解析("mintstar", "我饿了")["act"] == "task")
    试("D6 ★★ 听不懂的话照旧往下传（别把主链的解析吃掉）",
       桥.指.解析("mintstar", "你是条啥鱼")["act"] == "chat")
    饭.卸下(桥)

    # ══════════ E 组：下发时才算账（指令层没有状态帧）══════════
    print("── E 组：下发时当场算账 ──")
    桥 = 假桥()
    饭.装上(桥)
    桥.栈.任务 = {"分饭_之前": None}
    桥.栈.任务 = {}
    步 = {"动作": "给", "数量": 3, "谁": "mintstar"}
    桥.栈._下发(步, None, 1000.0, 帧({"cooked_beef": 10}))
    递的 = [m for m in 桥.栈.发的 if m.get("cmd") == "递"]
    试("E1 ★★★ 下发时真的发了「递」给手侧", len(递的) == 1, str(桥.栈.发的))
    试("E2 ★★★ 现算出「分什么、分几份」并写回步骤",
       步.get("物品") == "cooked_beef" and 步.get("数量") == 3, str(步))
    试("E3 ★★ 递的时候点名给谁", 递的 and 递的[0].get("谁") == "mintstar", str(递的))

    桥 = 假桥()
    饭.装上(桥)
    桥.栈.任务 = {}
    步2 = {"动作": "给", "数量": 3, "谁": "mintstar"}
    r2 = 桥.栈._下发(步2, 桥.栈.任务, 1000.0, 帧({"cooked_beef": 2}))
    试("E4 ★★★ **自己不够吃就不发「递」**（一份都不许动）",
       r2 is False and not [m for m in 桥.栈.发的 if m.get("cmd") == "递"],
       str(桥.栈.发的))
    试("E5 ★★★ 而且**当着主人的面说明了理由**（不是默默拒绝）",
       桥.栈.任务.get("分饭_回绝") and "不够分" in str(桥.栈.任务.get("分饭_回绝"))
       and any("不够分" in x for x in 桥.栈.说过),
       f"记下={桥.栈.任务.get('分饭_回绝')!r} 说过={桥.栈.说过}")
    好, _ = 桥.栈._看完成了没(步2, 帧({"cooked_beef": 2}), 桥.栈.任务)
    试("E6 ★★ 回绝过的那一步**算完成** —— 不能卡在那儿死等", 好 is True)

    桥 = 假桥()
    饭.装上(桥)
    桥.栈.任务 = {}
    步5 = {"动作": "给", "数量": 3, "谁": "mintstar"}
    r5 = 桥.栈._下发(步5, 桥.栈.任务, 1000.0, {"items": {}})
    试("E7 ★★★ 看不见背包（items 空）时**不许回绝** —— 宁可晚一拍，也不能冤枉自己有饭不给",
       r5 is False and not 桥.栈.任务.get("分饭_回绝")
       and any(m.get("list") == ["*"] for m in 桥.栈.发的 if m.get("cmd") == "watch_items"),
       f"回了={r5} 回绝={桥.栈.任务.get('分饭_回绝')} 发过={桥.栈.发的}")

    # ══════════ F 组：完成判据 ══════════
    print("── F 组：怎么算分完了 ──")
    桥 = 假桥()
    饭.装上(桥)
    任 = {}
    步3 = {"动作": "给", "物品": "cooked_beef", "数量": 3, "谁": "mintstar"}
    好, _ = 桥.栈._看完成了没(步3, 帧({"cooked_beef": 10}), 任)
    试("F1 ★★ 第一拍先记基准，不急着算完", 好 is False and 任.get("分饭_之前") == 10.0, str(任))
    好, _ = 桥.栈._看完成了没(步3, 帧({"cooked_beef": 7}), 任)
    试("F2 ★★★ 背包真少了 3 个 → 这一步算完成", 好 is True)
    好, _ = 桥.栈._看完成了没(步3, 帧({"cooked_beef": 9}), 任)
    试("F3 ★★ 只少了 1 个 → 还不算完（别提前收工）", 好 is False)

    桥 = 假桥()
    饭.装上(桥)
    试("F4 ★★ 别的动作照旧交给主链，不越权",
       桥.栈._看完成了没({"动作": "挖", "p": [1, 2, 3]}, 帧(), None) == (False, None))

    # ══════════ G 组：红线 ══════════
    print("── G 组：红线 ──")
    import hashlib
    with open(os.path.join(ROOT, "bridge.py"), "rb") as f:
        哈 = hashlib.sha256(f.read()).hexdigest()
    试("G1 ★★★ 主链 bridge.py 一个字节都没动", 哈.startswith("a649665c970d84ba"), 哈[:16])
    手 = os.path.join(ROOT, "node", "plugins", "body", "proto_body.js")
    js = open(手, encoding="utf-8").read()
    试("G2 ★★★ 手侧身体插件里**真有「递」**这个能力（不然分饭发出去也是白搭）",
       "'递'" in js and "递东西" in js)
    试("G3 ★★ 「递」是加在插件里的，没往主链动词表里塞（符合 M4 规矩）",
       "递" not in open(os.path.join(ROOT, "bridge.py"), encoding="utf-8").read())

    print("\n" + "═" * 62)
    print(f"分饭车厢：{len(通过)} 过 / {len(失败)} 失败")
    for f in 失败:
        print(f"  ❌ {f['名']} —— {f['为啥']}")
    print("═" * 62)
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
