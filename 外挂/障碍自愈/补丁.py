#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""障碍自愈车厢 —— 手侧说「挡着什么」，就**当场去把它挖掉**。

主人 2026-10-09 看日志时指出的
==============================
    [10:07] 「dig」没做成：「oak_log」前面挡着「oak_leaves」，我得先把那一块挖掉
    [10:08] 「dig」没做成：「oak_log」前面挡着「oak_leaves」，我得先把那一块挖掉
主人原话：「那怎么不自己把挡住的方块挖了啊？雷达、挖的动作不是都有吗？」

他说得对 ✓ 手侧**早就把解法说出来了** ✓ —— 而且我还专门让它多返回一个字段：

    { ok: false, 未暴露: true, 挡着: [...], 先挖: [x, y, z],
      why: '「oak_log」前面挡着「oak_leaves」，我得先把那一块挖掉' }

**可从没有任何代码读 `先挖`** ✗ —— 于是它就一直重说同一句、什么都不做 ✓

这节车厢做的就是那一环：**把"理由"变成"下一步"** ✓
  · 包 `叙事者.看回执` —— 回执里带 `先挖` 坐标时 →
  · **立刻**把「走过去 → 挖掉它」当成一个短活交给任务栈 ✓
  · 挖完，主链下一拍自然会重新排原来的活 ✓（"先把挡着的挖掉"就是这个意思 ✓）

规矩
====
1. **同一块 3 秒内只派一次** ✓（手侧每 200ms 就回一次同样的拒绝 ✗ 不去重会疯 ✗）
2. **只在有坐标时动手** ✓（没有 `先挖` 就什么都不做 ✓ 交回主链 ✓）
3. 派活失败（任务栈拒单）就**照实说** ✓，不许静默 ✗
4. 卸下一字不差还原 ✓
"""

import os
import time

_日志 = None
_原件 = {}
_上次 = {}          # 坐标 -> 上次派活的时刻（去重用）
_派了几次 = 0


def _说(文):
    if _日志:
        try:
            _日志(文)
            return
        except Exception:
            pass
    print(文, flush=True)


def _活实例(bridge, 类名):
    try:
        类 = getattr(bridge, 类名, None)
        活 = list(getattr(类, "车钩活着的实例", []) or [])
        return 活[-1] if 活 else None
    except Exception:
        return None


def 处理回执(bridge, 状态=None, e=None):
    """回执里带 `先挖` → 派一个短活：走过去把它挖掉。返回说明或 None。"""
    global _派了几次
    try:
        位 = (e or {}).get("先挖") or (e or {}).get("先挖掉")
        if not (isinstance(位, (list, tuple)) and len(位) >= 3):
            return None
        键 = tuple(int(v) for v in 位[:3])
        现在 = time.time()
        if 现在 - _上次.get(键, -999.0) < 3.0:
            return None                     # 同一块 3 秒内只派一次 ✓
        _上次[键] = 现在
        挡名 = ""
        try:
            挡着 = (e or {}).get("挡着") or []
            # ★★★ 2026-10-09：名字要**对着「先挖」那一格**找 ✗
            #   原来直接拿 `挡着[0]` ✓ —— 可"被整个埋住"那一支给的是一整张挡路表 ✓
            #   而 `先挖` 是从里面**挑出来的那一块** ✗
            #   俩不一致的后果很隐蔽：派活时写「挖 oak_log」、
            #   可坐标指的是**那片叶子** → 挖空守卫的"陈坐标"判据当场把它拦下 ✗
            #   （判据是"我要的方块 ≠ 那一格初见的方块" ✓ 它拦得对，是我名字给错了 ✓）
            for 条 in 挡着:
                if not isinstance(条, dict):
                    continue
                q = 条.get("p")
                if (isinstance(q, (list, tuple)) and len(q) >= 3
                        and all(abs(float(q[i]) - 键[i]) < 0.5 for i in range(3))):
                    挡名 = str(条.get("name") or "")
                    break
            if not 挡名 and 挡着 and isinstance(挡着[0], dict):
                挡名 = str(挡着[0].get("name") or "")     # 兜底：老样子 ✓
        except Exception:
            pass
        栈 = _活实例(bridge, "任务栈")
        if 栈 is None:
            return f"看到挡着「{挡名 or '?'}」@{list(键)}，可找不到活的任务栈 ✗"
        if 状态 is None:
            # 没有当帧状态就先不做 —— 不许拿一个不知道的坐标去挖 ✗
            return f"看到挡着「{挡名 or '?'}」，可这一拍没拿到扫描帧，等下拍"
        步骤 = [{"动作": "走到", "p": list(键), "到点": 3.0},
                {"动作": "挖", "p": list(键)}]
        if 挡名:
            步骤[1]["方块"] = 挡名
        好 = 栈.接(f"先把挡着的「{挡名 or '那个'}」挖掉", 步骤, 状态)
        _派了几次 += 1
        if 好:
            return (f"★ 障碍自愈：挡着「{挡名 or '那个'}」@{list(键)} —— "
                    f"我先去把它挖掉（第 {_派了几次} 次）")
        return f"想先挖掉挡着「{挡名 or '?'}」@{list(键)}，可任务栈不接这个活 ✗"
    except Exception as ex:
        print(f"[障碍自愈] 处理回执出岔子（不影响主链）：{ex}", flush=True)
        return None


def 装上(bridge, 日志=None, **kw):
    global _日志
    _日志 = 日志
    叙类 = getattr(bridge, "叙事者", None)
    if 叙类 is None:
        return {"好": False, "为什么": "找不到 叙事者 类", "打了": []}
    if getattr(叙类, "_障碍自愈装了", False):
        return {"好": True, "为什么": "已经装过了（幂等）", "打了": []}
    原 = getattr(叙类, "看回执", None)
    if not callable(原):
        return {"好": False, "为什么": "叙事者.看回执 不是函数", "打了": []}
    _原件[id(叙类)] = 原

    def 看回执(self, e):
        原(self, e)                      # 原来那条路一个字不改 ✓
        try:
            说明 = 处理回执(bridge, getattr(self, "最后状态", None), e)
            if 说明:
                _说(f"[障碍自愈] {说明}")
                try:
                    self.说(f"[{time.strftime('%H:%M')}] {说明}", 紧急=True)
                except Exception:
                    pass
        except Exception as ex:
            print(f"[障碍自愈] 出岔子（不影响主链）：{ex}", flush=True)

    叙类.看回执 = 看回执
    叙类._障碍自愈装了 = True
    return {"好": True, "为什么": "", "打了": [
        "叙事者.看回执()  ← 读到「先挖」就把挡着的那块派成短活（原来那条路一个字不改）"]}


def 卸下(bridge):
    global _日志
    叙类 = getattr(bridge, "叙事者", None)
    原 = _原件.pop(id(叙类), None) if 叙类 is not None else None
    if not 原:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    叙类.看回执 = 原
    try:
        del 叙类._障碍自愈装了
    except AttributeError:
        pass
    _日志 = None
    return {"好": True, "为什么": "", "打了": ["还原 叙事者.看回执()"]}
