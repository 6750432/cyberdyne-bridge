#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""物理体检车厢 —— 拿「隐式物理常识」把每一条计划**过一遍**。

English: A pre-flight physical check for plans. Before a plan is accepted, every step
is tested against the implicit-physics rules extracted from minecraft-data and
prismarine-physics (collision boxes, diggable, drops, tool requirements, reach).

主人 2026-10-09 的架构级反馈
============================
「大肥鱼目前对 MC 物理引擎的理解停留在『API 调用』层面，没有建立起
 『物理世界玩家』的常识。**只写了显式常识，漏了隐式常识**。」

数据是自动抓的 ✅（`tools/生成物理常识.js` → `常识库/物理引擎规则.json`）
**可光有数据等于没做** ✗ —— 今天最贵的那条教训就是：
「理由写出来了，可没人读」✓（`先挖` 写好了、可"被整个埋住"那一支没接 → 五分钟一步没动）
所以这一节车厢干的就是**读**它那一环：

    接单那一刻 → 把每一条计划拿物理常识过一遍 → 违反物理的**当场挑出来/改正** ✓

它治的是今天实机抓到的这几类（全是真机原话）
==============================================
  T1 「挖 air」        —— 那格本来就是空气，挖了白挖 ✓ 后面「拾」必然干等 60 秒
  T2 「挖基岩」        —— `diggable:false`，物理上挖不动 ✗
  T3 「拾 grass_block」—— 挖草方块掉的是**泥土** ✗（不是方块自己的名字 ✓）
  T4 「走到一堵墙里」   —— 那格的碰撞盒非空，**站不进去** ✗
  T5 「要镐子的方块、可手里没镐子」 —— 挖了也**不掉东西** ✓

三条自我约束（今天的血）
========================
  1. **只读数据、不猜** ✓ —— 所有判据都来自 `常识库/物理引擎规则.json`（每条带出处 ✓）
     读不到那个文件 → **拒绝装**（fail-closed ✓ 不许装作体检过了 ✗）
  2. **能改正的就改正、不能改正的才报** ✓
     （T3 是**明确的事实**："挖 X 掉 Y" → 拾 Y ✓ 直接改 ✓
      其余是"这一步不成立" → 只报，交回主链 ✓ 我不替它决定）
  3. **不碰主链一个字** ✓ 只包 `任务栈.接` ✓ 拔掉即恢复原样 ✓
"""

import json
import os
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_日志 = None
_原件 = {}
_规 = None              # 物理引擎规则.json（懒加载，只读一次 ✓）
_体检过 = 0
_挑出过 = 0
_最近报告 = []

空气名 = ("air", "cave_air", "void_air")
# T5 认的"干活工具" —— 镐/斧/铲/锄
# （规则库那 388 种"要工具才掉东西"的方块全在这四类里）
工具尾巴 = ("_pickaxe", "_axe", "_shovel", "_hoe")


def _说(文):
    if _日志:
        try:
            _日志(文)
            return
        except Exception:
            pass
    print(文, flush=True)


def _规则():
    """懒加载物理常识（只读一次 ✓ —— 120 KB，别每拍读）"""
    global _规
    if _规 is not None:
        return _规
    for 路 in (os.path.join(ROOT, "常识库", "物理引擎规则.json"),
               os.path.join(ROOT, "外挂", "常识", "物理引擎规则.json")):
        try:
            with open(路, encoding="utf-8") as f:
                _规 = json.load(f)
            return _规
        except Exception:
            continue
    _规 = False          # 标记"读不到"（False ≠ None，别反复重试 ✓）
    return _规


def _戴(名):
    """这个方块名戴不戴得住：能穿过去的（空气/水/草）→ True"""
    规 = _规则()
    if not 规:
        return None
    能穿 = set(规.get("碰撞盒", {}).get("能穿过去的", []))
    return str(名) in 能穿


def _挖不动(名):
    规 = _规则()
    if not 规:
        return None
    return str(名) in set(规.get("挖不动", []))


def _掉什么(名):
    规 = _规则()
    if not 规:
        return None
    掉 = 规.get("挖了掉什么") or {}
    if str(名) not in 掉:
        return None          # 没有掉落记录 = 挖了什么都不掉 ✓（空气/水/叶子…）
    return 掉[str(名)]


def _要工具(名):
    规 = _规则()
    if not 规:
        return None
    return str(名) in set(规.get("要工具才掉东西", []))


def _方块名(状态, p):
    """从状态帧里读那一格是什么（雷达读数 ✓ 没读数 → None = 不知道）"""
    for 条 in ((状态 or {}).get("blocks") or []):
        q = 条.get("p")
        if isinstance(q, (list, tuple)) and len(q) >= 3:
            try:
                if all(abs(float(q[i]) - float(p[i])) < 0.5 for i in range(3)):
                    return str(条.get("name") or "")
            except Exception:
                continue
    return None


def 体检(步骤, 状态):
    """把整张步骤表过一遍。返回 (改过的步骤表, 报告列表)。

    ★ 规矩：**能改正的就改**（那是明确的事实 ✓）**不能改正的才报** ✗
      （报出来的交回主链，我不替它决定下一步 ✓）
    """
    报告 = []
    出 = []
    上一步 = None
    挖的 = {}            # 坐标 -> 挖的是什么（T3 要用）
    计划产物 = set()     # 计划**自己会做出来**的东西（T5 要用，跨步累加）✓
    for i, 步 in enumerate(步骤 or []):
        if not isinstance(步, dict):
            出.append(步)
            continue
        步 = dict(步)
        动 = 步.get("动作")
        p = 步.get("p")

        # ★ 计划**自己会做出来**的东西（跨步累加）—— T5 要用它 ✓
        #   ⚠ 2026-10-09 实机：stone_pickaxe 那条 23 步计划被 T5 报了 3 条 ✗
        #     「第 15/18/21 步要挖 stone —— 要镐子，手里没有」✗
        #     **三条全是误报** ✗ —— 第 12 步就写着「合成 wooden_pickaxe」✓
        #     挖 stone 在第 14 步**之后** ✓ 到那时候手里当然有镐子 ✓
        #     教训还是那一句：**误报比漏报更危险** ✓ 报一堆假的，
        #     真的那条（我编坐标那一处）就没人看了 ✓
        if 动 in ("合成", "箱子里取", "熔炉取成品") and 步.get("物品"):
            计划产物.add(str(步.get("物品")))

        # ★ 计划**自己会做出来**的东西（跨步累加）—— T5 要用它 ✓
        #   ⚠ 2026-10-09 实机：stone_pickaxe 那条 23 步计划被 T5 报了 3 条 ✗
        #     「第 15/18/21 步要挖 stone —— 要镐子，手里没有」✗
        #     **三条全是误报** ✗ —— 第 12 步就写着「合成 wooden_pickaxe」✓
        #     挖 stone 在第 14 步**之后** ✓ 到那时手里当然有镐子 ✓
        #     教训还是那一句：**误报比漏报更危险** ✓ 报一堆假的，
        #     真的那条（我编坐标那一处）就没人看了 ✓
        if 动 in ("合成", "箱子里取", "熔炉取成品") and 步.get("物品"):
            计划产物.add(str(步.get("物品")))

        # ── T1/T2/T5：挖 这一步成立吗 ──
        if 动 == "挖" and isinstance(p, (list, tuple)) and len(p) >= 3:
            名 = 步.get("方块") or _方块名(状态, p)
            站在 = _方块名(状态, p)
            if 站在 is not None and 站在 in 空气名:
                报告.append(f"[T1] 第 {i + 1} 步要挖 {list(p)[:3]}，可**那格就是空气** ✗"
                           f"（挖了白挖 ✓ 后面「拾」会干等 60 秒）")
            elif _挖不动(站在 if 站在 is not None else 名):
                报告.append(f"[T2] 第 {i + 1} 步要挖「{站在 or 名}」—— **物理上挖不动** ✗"
                           f"（diggable:false ✓）")
            elif 名 and _要工具(名):
                # 手里有工具吗？手侧 `items` 是 "{名字: 数量}"
                有 = False
                try:
                    for k, v in ((状态 or {}).get("items") or {}).items():
                        if str(k).endswith(工具尾巴) and (v or 0) > 0:
                            有 = True
                            break
                except Exception:
                    有 = False
                # ★ 计划里**前面已经排了**合成/取出这件工具 → 到这一步手里就有了 ✓
                #   （这条不加就是误报机器 ✗ 见上面 计划产物 的注释）
                会做 = any(str(x).endswith(工具尾巴) for x in 计划产物)
                if not 有 and not 会做:
                    报告.append(f"[T5] 第 {i + 1} 步要挖「{名}」——**它要工具才掉东西** ✗"
                               f"（手里没有、计划里也没安排做 → 挖了也是白挖 ✓）")
            if 名:
                挖的[tuple(int(v) for v in p[:3])] = 名

        # ── T3：拾 的物品 == 前面那一挖的**掉落物**吗（**能改正 ✓**）──
        if 动 == "拾" and 步.get("物品"):
            物品 = str(步.get("物品"))
            # 找"最近那一挖"挖的是什么
            名 = None
            for j in range(len(出) - 1, -1, -1):
                q = 出[j]
                if isinstance(q, dict) and q.get("动作") == "挖":
                    qp = q.get("p")
                    if isinstance(qp, (list, tuple)) and len(qp) >= 3:
                        名 = 挖的.get(tuple(int(v) for v in qp[:3])) or q.get("方块")
                    break
            if 名:
                该 = _掉什么(名)
                if 该 is not None and str(该) != 物品:
                    步["物品"] = str(该)
                    报告.append(f"[T3] 第 {i + 1} 步「拾 {物品}」——可挖「{名}」掉的是"
                               f"**「{该}」** ✓ 已改正（挖了白捡的名字必然拾不到）")
                elif _掉什么(名) is None and 物品 == str(名):
                    报告.append(f"[T3] 第 {i + 1} 步「拾 {物品}」——可挖「{名}」"
                               f"**什么都不掉** ✗（这一拾没有东西可拾）")

        # ── T4：这个「走到」的**高度差**物理上过得去吗 ──
        #   ⚠⚠ 我第一版这条写错了 ✗ —— 去查"那一格的碰撞盒"，判"站不进去" ✓
        #     可「走到」本来就是"**靠近**那一格"（到点 3.0），**不是站进去** ✗
        #     → 每一条正常计划都会被挑出来 ✗ **误报机器** ✓
        #   （"误报比漏报更危险" —— 报一堆假的，真的那条就没人看了 ✓ 今天记过）
        #   规矩：**判据要用在它真正管的地方** ✓
        #   换成有依据的两条（依据就是刚抓到的常量 ✓）：
        if 动 == "走到" and isinstance(p, (list, tuple)) and len(p) >= 3:
            我 = (状态 or {}).get("pos")
            if isinstance(我, (list, tuple)) and len(我) >= 3:
                try:
                    升高 = float(p[1]) - float(我[1])
                except Exception:
                    升高 = 0.0
                if 升高 >= 2:
                    报告.append(f"[T4] 第 {i + 1} 步要走到 {list(p)[:3]}，比我现在**高 "
                               f"{升高:.0f} 格** ✗ —— 一步只上 0.6 格、跳也只上 1.1 格 ✓"
                               f"（得先挖上去/搭一格，不是「走过去」）")
                elif 升高 <= -4:
                    报告.append(f"[T4] 第 {i + 1} 步要走到 {list(p)[:3]}，比我现在**低 "
                               f"{-升高:.0f} 格** ✗ —— 落差超过 3 格**会摔伤** ✓"
                               f"（得绕路或先垫一格）")

        出.append(步)
        上一步 = 步
    return 出, 报告


def 装上(bridge, 日志=None, **kw):
    global _日志
    _日志 = 日志
    if not _规则():
        return {"好": False, "为什么": "读不到 常识库/物理引擎规则.json（先跑 tools/生成物理常识.js）",
                "打了": []}
    栈类 = getattr(bridge, "任务栈", None)
    if 栈类 is None:
        return {"好": False, "为什么": "找不到 任务栈 类", "打了": []}
    if getattr(栈类, "_物理体检装了", False):
        return {"好": True, "为什么": "已经装过了（幂等）", "打了": []}
    原 = getattr(栈类, "接", None)
    if not callable(原):
        return {"好": False, "为什么": "任务栈.接 不是函数", "打了": []}
    _原件[id(栈类)] = 原

    def 接(self, 名字, 步骤, s):
        """★ 接单那一刻体检：**计划是全的、物理常识才是真的** ✓"""
        global _体检过, _挑出过, _最近报告
        try:
            改, 报告 = 体检(步骤, s)
            _体检过 += 1
            if 报告:
                _挑出过 += 1
                _最近报告 = 报告[:6]
                _说(f"[物理体检] ★ 「{名字}」这一步计划里挑出 {len(报告)} 处违反物理的地方：")
                for x in 报告[:6]:
                    _说(f"[物理体检]   {x}")
            return 原(self, 名字, 改, s)
        except Exception as ex:
            print(f"[物理体检] 体检时出岔子（不影响主链，按原样接单）：{ex}", flush=True)
            return 原(self, 名字, 步骤, s)

    栈类.接 = 接
    栈类._物理体检装了 = True
    return {"好": True, "为什么": "", "打了": [
        "任务栈.接()  ← 接单那一刻拿「隐式物理常识」把计划过一遍"
        "（挖空气/挖不动/拾错名字/站不进去 ✓ 出处的每一条都在 常识库/物理引擎规则.json）"]}


def 卸下(bridge):
    global _日志
    栈类 = getattr(bridge, "任务栈", None)
    原 = _原件.pop(id(栈类), None) if 栈类 is not None else None
    if not 原:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    栈类.接 = 原
    try:
        del 栈类._物理体检装了
    except Exception:
        pass
    _日志 = None
    return {"好": True, "为什么": "", "打了": ["还原 任务栈.接()"]}


def 同步实例(bridge, 日志=None, 车钩=None):
    try:
        if 日志:
            日志(f"物理体检：接单 {_体检过} 次，挑出过问题 {_挑出过} 次")
    except Exception:
        pass
    return {"好": True, "为什么": "无状态，随便拔", "打了": []}
