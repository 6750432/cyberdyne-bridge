#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手上一件事 —— 同一条命令、同一个目标，几秒内只准上线路一次。

English: "One thing at a time" — the same command aimed at the same target may only go
out on the wire once per interval. Guards the very last hop (`任务栈.发`), so no caller
can bypass it by sending directly instead of going through `_下发`.

为什么要有这一节车厢
====================
★ 2026-10-09 实机（主人的 P0-1 那一场，主人问「怎么卡在半路了？」）

    一步「走到 [-143,79,149]」，**63 秒里 `goto` 被发了 310 次**（≈每秒 5 次）✗
    每发一次，手那边就把**正在跑的那条路掐断一次** ✓
    （手侧日志：「这条路被新命令打断了，重新算」×8、「Path was stopped before it…」）
    → 那条路**永远走不完** → 60 秒超时 → 重试 → 又超时 ✗

根子（不是"谁手抖"，是节流整条被绕过）
--------------------------------------
主链 `bridge.py:1740` 本来有节流：

    会重复 = 动 in ("走到", "挖", "放", "拾", ...)
    if 会重复 and 现在 - self.上次下发 < 重下 and not 卡住:
        return False

可 `卡住 = s["stuck_ms"] < 1500` ✓ —— `stuck_ms` 的语义是「**距上次记下"卡住"多久**」
（手侧 `node/server.js:853` 的原话）✗ 也就是说：**只要手那边还在记"卡住"，
节流就一直被绕过** ✗ 而它一边走一边记，于是**每拍都算卡住** → 节流等于没有 ✗

⚠ 这道闸挖空守卫里**已经有一份**（`走到防抖秒` 4.0）✓ 可它开在 `任务栈._下发` 那一层 ✗
  而**绕过去的路不止一条** —— 生存常识的「围圈捡东西」就是直接 `栈.发(...)` ✓
  （`外挂/生存常识/补丁.py:195` ✓）
  所以这一节开在**最后一跳** ✓：不管谁、从哪条路发出来的，都拦得住 ✓

规矩（三条，缺一条都会误伤）
----------------------------
 ① 只拦**同一个目标**的重复 ✗ —— 换个坐标 / 换个物品照发 ✓
 ② 说话（`say`）**一律不拦** ✗ —— 那是主人等的话，不是手在做的事 ✓
 ③ 认不出来的命令**一律放行** ✓（fail-open ✓：宁可多问一句，
    也不要因为不认识就把动作闷死 ✗）

⚠ 为什么靠包 `任务栈.__init__` ✗：`任务栈.发` 是**实例属性**
  （`bridge.py:1378` `self.发 = 发命令`）✗ 包类方法是**包不到**的 ✗
  —— 这个坑今天踩过一次（「实例属性会盖住类属性」）✓ 别再踩第二次 ✓
"""

import weakref

# 闸门参数：命令 → 同一目标的最短间隔（秒）
间隔表 = {
    "goto": 4.0,      # 主链自己的"重下"是 8 秒 ✓ 这里只兜住被绕过的那条路
    "dig": 1.5,       # 挥镐子不需要每 0.2 秒重来一次 ✓
    "place": 1.5,
    "craft": 1.0,
    "use": 1.5,
    "sneak": 1.5,
    "jump": 1.5,
    "jumpattack": 1.5,
    "swimdown": 1.5,
    "attack": 1.5,
    "eat": 1.5,
}
# 这些命令**只记不拦**（`say` 是主人等的话 ✓；心跳/模式类不是"手上的活" ✓）
不拦 = frozenset({"say", "ping", "mode", "stop", "move", "retreat"})

_原装 = weakref.WeakKeyDictionary()      # 造好的栈 -> 它本来那个 发
_上次 = {}                                # (命令, 目标) -> 时刻
_拦了 = {"次": 0, "最近说": 0.0}
_日志 = None
_开关 = True


def _说(文):
    if _日志:
        try:
            _日志(文)
        except Exception:
            pass
    else:
        print(文, flush=True)


def _目标(obj):
    """从一条要发出去的报文里取出「目标」 —— 同一条命令、同一个目标才算重复 ✓"""
    for k in ("p", "target", "item", "物品", "name", "名"):
        if k in obj:
            v = obj.get(k)
            if isinstance(v, (list, tuple)):
                try:
                    return tuple(round(float(x), 1) for x in v[:3])
                except Exception:
                    return tuple(str(x) for x in v[:3])
            return v
    return None


def _命令(obj):
    """一条报文是什么命令。手侧两种写法都认（`act` / `cmd`）✓"""
    if not isinstance(obj, dict):
        return None
    c = obj.get("cmd")
    if isinstance(c, str) and c:
        return c
    a = obj.get("act")
    if isinstance(a, str) and a:
        # ⚠ `act:"goto"` 走的也是 goto ✓ —— 主链 `_下发` 就是这么发的 ✓
        return a
    return None


def _闸(栈, 原本):
    """给一个任务栈实例的发出口装上闸 ✓"""
    def 发(obj):
        if not _开关:
            return 原本(obj)
        try:
            c = _命令(obj)
            if c is None or c in 不拦:
                return 原本(obj)
            隔 = 间隔表.get(c)
            if 隔 is None:
                return 原本(obj)          # ★ 不认识的命令一律放行（fail-open ✓）
            现在 = __import__("time").time()
            k = (c, _目标(obj))
            上 = _上次.get(k)
            if 上 is not None and 现在 - 上 < 隔:
                _拦了["次"] += 1
                # 每 5 秒最多念一次，别刷屏 ✓
                if 现在 - _拦了["最近说"] >= 5.0:
                    _拦了["最近说"] = 现在
                    _说(f"[手上一件事] 「{c}」{k[1]} —— {现在 - 上:.1f} 秒内重复喊了"
                       f" {_拦了['次']} 次，手一次只干得了一件 ✓ "
                       f"（上一条还在跑的时候喊第二遍，只会把正在跑的那条**掐断** ✗）")
                return False
            _上次[k] = 现在
        except Exception as e:
            print(f"[手上一件事] 闸门出岔子（照旧放行，不影响主链）：{e}", flush=True)
        return 原本(obj)

    return 发


def _包初始化(栈类, 日志=None):
    """包 `任务栈.__init__` —— 每个新造出来的栈都装上闸 ✓

    ⚠ 为什么不是包类方法 `任务栈.发` ✗：
      `bridge.py:1378` 里写的是 `self.发 = 发命令` —— **实例属性** ✓
      实例属性会**盖住**类属性 ✗ 包类方法等于白包 ✗（今天踩过的坑 ✓）
    """
    原init = 栈类.__init__
    if getattr(原init, "_手上一件事包过", False):
        return False

    def 新init(自身, *a, **k):
        原init(自身, *a, **k)
        try:
            本 = getattr(自身, "发", None)
            if callable(本):
                _原装[自身] = 本
                自身.发 = _闸(自身, 本)
        except Exception as e:
            print(f"[手上一件事] 装闸出岔子（这一个栈没闸，不影响主链）：{e}", flush=True)

    新init._手上一件事包过 = True
    新init._手上一件事原init = 原init
    栈类._手上一件事原init = 原init
    栈类.__init__ = 新init
    return True


def 装上(bridge, 日志=None, **kw):
    global _日志, _开关
    _日志 = 日志
    try:
        开关配置 = (kw or {}).get("配置") or {}
        s = 开关配置.get("手上一件事") or {}
        if isinstance(s, dict) and "启用" in s:
            _开关 = bool(s.get("启用"))
    except Exception:
        pass
    栈类 = getattr(bridge, "任务栈", None)
    if 栈类 is None:
        return {"好": False, "为什么": "找不到 任务栈 类", "打了": []}
    if getattr(栈类, "_手上一件事装了", False):
        return {"好": True, "为什么": "已经装过了（幂等）", "打了": []}
    try:
        _包初始化(栈类, 日志)
    except Exception as e:
        return {"好": False, "为什么": f"包 __init__ 失败：{e}", "打了": []}
    栈类._手上一件事装了 = True
    打的 = ["任务栈.__init__()  ← 给每个栈的发出口装上闸（`发` 是实例属性，"
            "包类方法包不到 ✗）"]
    打的.append("任务栈.发（实例）  ← 第一次拦在**最后一跳**：同一条命令 + 同一个目标"
                "在间隔内只准上线路一次（goto 4 秒 / 挖放 1.5 秒 / 合成 1 秒）✓ "
                "说话一律不拦 ✓ 认不出来的命令一律放行 ✓")
    return {"好": True, "为什么": "", "打了": 打的}


def 卸下(bridge):
    global _日志, _开关
    栈类 = getattr(bridge, "任务栈", None)
    if 栈类 is None:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    原init = getattr(栈类, "_手上一件事原init", None)
    if callable(原init):
        try:
            栈类.__init__ = 原init
        except Exception:
            pass
    活着的 = list(_原装.keys())
    for 栈 in 活着的:
        try:
            本 = _原装.get(栈)
            if callable(本):
                栈.发 = 本
        except Exception:
            pass
    _原装.clear()
    for 名 in ("_手上一件事原init", "_手上一件事装了"):
        try:
            delattr(栈类, 名)
        except Exception:
            pass
    _上次.clear()
    _日志 = None
    _开关 = True
    return {"好": True, "为什么": "", "打了": [
        "任务栈.__init()  ← 还原",
        f"活着的 {len(活着的)} 个栈的发出口  ← 还原",
    ]}


def 同步实例(bridge, 日志=None, 车钩=None):
    """给**已经活着**的栈补装闸 ✓（热挂的时候它们已经造好了 ✗）"""
    补 = 0
    try:
        for 栈 in list(getattr(bridge.任务栈, "车钩活着的实例", []) or []):
            本 = getattr(栈, "发", None)
            if callable(本) and 本 not in _原装.values():
                _原装[栈] = 本
                栈.发 = _闸(栈, 本)
                补 += 1
    except Exception as e:
        print(f"[手上一件事] 补装出岔子：{e}", flush=True)
    try:
        if 日志:
            日志(f"手上一件事：拦下重复命令 {_拦了['次']} 次"
                 f"（热挂时补装了 {补} 个活栈）")
    except Exception:
        pass
    return {"好": True, "为什么": "闸在实例上，拔掉即还原", "打了": []}
