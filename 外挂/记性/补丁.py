#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""记性 —— 自己放下的东西，自己记得放在哪儿。

English: Memory for placed blocks. When a plan says "place X at p", remember X→p; when a
later plan wants to craft a crafting_table, walk back to the remembered one instead.

★ 为什么要有这一节（主人 2026-10-09 原话）
==========================================
    「还有补上他的记忆，他日志都报『**找不到工作台了，4格以内**』，
      ……你想想啊，**自己放的东西肯定要记得自己放哪儿的啊**，不管在哪儿，
      总不能又退回说重做工作台吧」

根子（手侧，不是脑侧）
----------------------
`node/plugins/body/proto_body.js:586`：

    工作台 = bot.findBlock({ matching: ..., maxDistance: 4 });
    if (!工作台) return { ok: false, why: `合成「${名}」要工作台，可我附近 4 格内没找到` };

**只在脚边 4 格瞎找** ✗ —— 它不是"忘了放哪儿"，是**从来没记过** ✗
而脑这边（`求解器`）下一次又照样排「合成 crafting_table → 放 crafting_table」✗
→ **每用一次工作台就重做一个** ✗

本车厢干两件事
--------------
 ① **记**：计划里凡有「放 X @p」，接单那一刻把 `X → p` 记下来 ✓
    （位置就是它自己写进计划的那个坐标 ✓ **不是猜的** ✓）
 ② **用**：计划里再出现「合成 crafting_table」而账上记得有一个 →
    **把那一步换成「走到记住的坐标」** ✓
    并且把它**后面紧跟的**「放 crafting_table」删掉 ✓（不用重做 ✗）

⚠ 账落盘在 `logs/记性.json` ✓ —— 脑重启很频繁 ✓ 不落盘就等于没记 ✓
"""

import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
账本路径 = os.path.join(ROOT, "logs", "记性.json")
上限 = 64

_原 = {}
_日志 = None
_账 = {}          # 方块名 -> {"p": [x,y,z], "t": 时刻}
_用了几次 = {"记": 0, "用": 0}


def _说(文):
    if _日志:
        try:
            _日志(文)
            return
        except Exception:
            pass
    print(文, flush=True)


def _坐标(v):
    if isinstance(v, (list, tuple)) and len(v) >= 3:
        try:
            return [int(float(v[0]) // 1), int(float(v[1]) // 1), int(float(v[2]) // 1)]
        except Exception:
            return None
    return None


def _读盘():
    try:
        with open(账本路径, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, dict) and _坐标(v.get("p")):
                    _账[str(k)] = {"p": _坐标(v["p"]), "t": float(v.get("t") or 0)}
    except Exception:
        pass


def _写盘():
    try:
        os.makedirs(os.path.dirname(账本路径), exist_ok=True)
        with open(账本路径, "w", encoding="utf-8") as f:
            json.dump(_账, f, ensure_ascii=False, indent=1)
    except Exception:
        pass          # ★ 写不了就只在内存里记 ✓ 不为难主链 ✓


def _淘汰():
    if len(_账) <= 上限:
        return
    for k, _ in sorted(_账.items(), key=lambda kv: kv[1].get("t") or 0)[: len(_账) - 上限]:
        _账.pop(k, None)


def 记(方块名, p, 什么时候=None):
    """记下「自己把 X 放在 p 了」✓"""
    位 = _坐标(p)
    if not 方块名 or 位 is None:
        return False
    _账[str(方块名)] = {"p": 位, "t": float(什么时候 or time.time())}
    _用了几次["记"] += 1
    _淘汰()
    _写盘()
    return True


def 想起(方块名):
    """账上还有这个方块吗 → 坐标或 None ✓"""
    v = _账.get(str(方块名))
    return list(v["p"]) if isinstance(v, dict) and _坐标(v.get("p")) else None


def 改计划(步骤, 名字=""):
    """③ 用：把「合成 crafting_table」换成「走到记住的坐标」✓ 返回 (新步骤, 说明列表) ✓"""
    出, 说明 = [], []
    步表 = list(步骤 or [])
    i = 0
    while i < len(步表):
        步 = 步表[i]
        if not isinstance(步, dict):
            出.append(步)
            i += 1
            continue
        if 步.get("动作") == "合成" and str(步.get("物品") or "") == "crafting_table":
            位 = 想起("crafting_table")
            if 位 is not None:
                # 后面紧跟的「放 crafting_table」也一起跳掉 ✓（不用重做 ✗）
                跳 = 1
                if i + 1 < len(步表) and isinstance(步表[i + 1], dict) \
                        and 步表[i + 1].get("动作") == "放" \
                        and str(步表[i + 1].get("方块") or "") == "crafting_table":
                    跳 = 2
                出.append({"动作": "走到", "p": list(位), "到点": 3.0})
                说明.append(f"账上记得工作台在 {位} ✓ —— 这一步不重做了，走过去用它 ✓")
                _用了几次["用"] += 1
                i += 跳
                continue
        out = 步
        出.append(out)
        i += 1
    return 出, 说明


def 记计划(步骤):
    """① 记：计划里凡有「放 X @p」→ 记下来 ✓（位置是它自己写的 ✓）"""
    记了 = []
    for 步 in (步骤 or []):
        if not isinstance(步, dict):
            continue
        if 步.get("动作") == "放":
            名 = str(步.get("方块") or "")
            if 名 and _坐标(步.get("p")):
                记(名, 步.get("p"))
                记了.append((名, _坐标(步.get("p"))))
    return 记了


def 装上(bridge, 日志=None, **kw):
    global _日志
    _日志 = 日志
    栈类 = getattr(bridge, "任务栈", None)
    if 栈类 is None:
        return {"好": False, "为什么": "找不到 任务栈 类", "打了": []}
    if getattr(栈类, "_记性装了", False):
        return {"好": True, "为什么": "已经装过了（幂等）", "打了": []}
    原接 = getattr(栈类, "接", None)
    if not callable(原接):
        return {"好": False, "为什么": "任务栈.接 不是函数", "打了": []}
    _读盘()
    _原[id(栈类)] = 原接

    def 接(self, 名字, 步骤, s):
        try:
            # ★★★ 顺序是**先用后记** ✓ —— 我第一版写反了，当场被 C1 抓住 ✗
            #   写反的后果：计划里「放 crafting_table @新的地方」先被记下来 ✓
            #   → 把**要用的那条旧账盖掉了** ✗ → 于是又走回新地方重做 ✗
            #   一句话：**先拿本子查，再把新事记上** ✓（不能拿今天盖掉昨天 ✓）
            新步骤, 说明 = 改计划(步骤, 名字)
            for x in 说明:
                _说(f"[记性] {x}")
            记了 = 记计划(新步骤)
            for 名, 位 in 记了:
                _说(f"[记性] 记下了：自己把「{名}」放在 {位} ✓（下次要用就直接过去 ✓）")
            if 说明:
                return 原接(self, 名字, 新步骤, s)
        except Exception as e:
            print(f"[记性] 出岔子（不影响主链，按原样接单）：{e}", flush=True)
        return 原接(self, 名字, 步骤, s)

    栈类.接 = 接
    栈类._记性装了 = True
    return {"好": True, "为什么": "", "打了": [
        "任务栈.接()  ← 接单那一刻：① 把计划里的「放 X @p」记进本子 ✓ "
        "② 计划里再要「合成 crafting_table」而账上有 → 换成「走到记住的坐标」✓",
        f"（账本 {账本路径} ｜ 现在记得 {len(_账)} 样东西）",
    ]}


def 卸下(bridge):
    global _日志
    栈类 = getattr(bridge, "任务栈", None)
    原 = _原.pop(id(栈类), None) if 栈类 is not None else None
    if not 原:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    栈类.接 = 原
    try:
        del 栈类._记性装了
    except Exception:
        pass
    _日志 = None
    return {"好": True, "为什么": "", "打了": ["还原 任务栈.接()"]}


def 同步实例(bridge, 日志=None, 车钩=None):
    try:
        if 日志:
            日志(f"记性：记得 {len(_账)} 样自己放下的东西 ｜ "
                 f"记了 {_用了几次['记']} 次、走过去用过 {_用了几次['用']} 次")
    except Exception:
        pass
    return {"好": True, "为什么": "账在文件里，拔了也不丢", "打了": []}
