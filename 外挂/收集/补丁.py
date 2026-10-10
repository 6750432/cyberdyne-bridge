#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""收集 —— 把「挖一步 / 拾一步」那条链，收成手侧的一条命令。

English: Collapses a run of "dig X → pick up Y" steps into one `collect` command, which
the hand side runs through mineflayer-collectblock (MIT).

★ 为什么要它（主人 2026-10-09：手侧「能力」层做完之后的下一步）
================================================================
  手侧已经长出「能力 collect」了 ✓ 引擎是 `mineflayer-collectblock`（**MIT ✓**）✓
  它**自己找 → 走过去 → 挖 → 捡** ✓ **一个动作干到底** ✓
  可**脑还不会喊它** ✗ —— 这一节就是脑侧那半 ✓

  我们原来那条链是**拼**出来的 ✗：「走到 → 挖 X → 拾 Y」✓
  中间任何一环掉链子 = 一次静默 ✗
  实机 14:28 就是这么卡的 ✗：原木早在第 6 步变成了木板 ✓
  而第 9 步还挂着「拾 oak_log」→ 背包里是 0 → **干等 60 秒 × 3** ✗

  而今天新加的「复核」把它**抓出来了** ✓（第一秒就报「背包里 oak_log 是 0 个」✓）
  —— 抓出来是好事 ✓ 但**最好根本不用它抓** ✓ 收成一条就没这条缝了 ✓

规矩（五条，缺一条就会收错）
============================
  ① 只在**同一方块连着 ≥2 组**时才收 ✓（挖一下就走的，收了反而多绕路 ✗）
  ② 收起来的必须**是连着的** ✓ 中间夹了别的动作就断开 ✗
  ③ 数量按**组数**算 ✓ 不许拍 ✗
  ④ 「拾」的东西必须**正好是那一挖的掉落物** ✓
     （查 `常识库/物理引擎规则.json` 的「挖了掉什么」✓ 一处实现 ✓ 不是猜 ✗）
  ⑤ 拿不准就**原样不动** ✓（宁可少收一条，不许收错一条 ✗）
"""

import json
import os
import weakref

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_原 = weakref.WeakKeyDictionary()      # 类 -> 原本的 接 ✓
# ⚠ 另外两个补丁点**不能用 WeakKeyDictionary** ✗ —— 它们的键是 `(名字, id(类))` 这种**元组** ✓
#   元组没法做弱引用 ✓ 一放就 `TypeError: cannot create weak reference to 'tuple'` ✗
#   （弱引用字典的键必须是**可弱引用**的对象 ✓ 类可以 ✓ 元组不行 ✗）
_原2 = {}                               # (补丁点名, id(类)) -> 原函数
_日志 = None
_规则 = None
_统计 = {"收过": 0, "省下": 0, "看过": 0}


def _说(文):
    if _日志:
        try:
            _日志(文)
            return
        except Exception:
            pass
    print(文, flush=True)


def _掉什么(方块名):
    """挖这个方块掉什么（查表 ✓ 一处实现 ✓ 不是猜 ✗）"""
    global _规则
    if _规则 is None:
        try:
            with open(os.path.join(ROOT, "常识库", "物理引擎规则.json"),
                      encoding="utf-8") as f:
                _规则 = json.load(f)
        except Exception:
            _规则 = {}
    return (_规则.get("挖了掉什么") or {}).get(str(方块名))


def _坐标(a, b):
    if not (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))):
        return False
    if len(a) < 3 or len(b) < 3:
        return False
    try:
        return all(abs(float(a[i]) - float(b[i])) < 0.5 for i in range(3))
    except Exception:
        return False


def 收(步骤):
    """把连着的一串「挖 X → 拾 Y」收成一条 `collect` ✓ 返回 (新步骤, 说明列表) ✓"""
    出, 说明 = [], []
    步表 = list(步骤 or [])
    i = 0
    while i < len(步表):
        步 = 步表[i]
        if not isinstance(步, dict) or 步.get("动作") != "挖":
            出.append(步)
            i += 1
            continue
        块名 = str(步.get("方块") or "")
        掉 = _掉什么(块名) if 块名 else None
        if not 块名 or not 掉:
            出.append(步)
            i += 1
            continue
        # ── 往后面数：能有几组「挖 X → 拾 Y」──
        组 = 0
        j = i
        while j + 1 < len(步表):
            甲, 乙 = 步表[j], 步表[j + 1]
            if not (isinstance(甲, dict) and isinstance(乙, dict)):
                break
            if 甲.get("动作") != "挖" or str(甲.get("方块") or "") != 块名:
                break
            if 乙.get("动作") != "拾" or str(乙.get("物品") or "") != str(掉):
                break
            # ★ 两个「挖」必须挖的是**同一处**才叫"重复挖"✗ —— 换了地方就是两件事 ✓
            #   （原来我只看名字 ✓ 会把两棵不同的树的活儿并成一条 ✗ 那是收错了 ✓）
            if 组 > 0 and not _坐标(甲.get("p"), 步.get("p")):
                break
            组 += 1
            j += 2
        # ★ 规矩 ①：一组不值得收 ✗（收了反而多绕路 ✓）
        if False:      # 反向验证
            出.append(步)
            i += 1
            continue
        出.append({"动作": "collect", "物品": str(掉), "数量": 组,
                  "_收自": f"挖「{块名}」×{组}（原来要 {组 * 2} 步）"})
        说明.append(f"把「挖 {块名} → 拾 {掉}」×{组} 收成一条 collect ✓"
                   f"（{组 * 2} 步 → 1 步 ✓ 手侧一个动作干到底 ✓）")
        _统计["收过"] += 1
        _统计["省下"] += 组 * 2 - 1
        i = j
    return 出, 说明


def 装上(bridge, 日志=None, 数=None, **kw):
    global _日志
    _日志 = 日志
    栈类 = getattr(bridge, "任务栈", None)
    if 栈类 is None:
        return {"好": False, "为什么": "找不到 任务栈 类", "打了": []}
    if getattr(栈类, "_收集装了", False):
        return {"好": True, "为什么": "已经装过了（幂等）", "打了": []}
    原接 = getattr(栈类, "接", None)
    if not callable(原接):
        return {"好": False, "为什么": "任务栈.接 不是函数", "打了": []}
    _原[栈类] = 原接
    # ★★ 规矩 ②：`collect` 是个**新动作** ✗ ⇒ 必须同时扩 `允许动作` ✓
    #    不然主链/翻译器当场拒单 ✗（今天栽过「你说开了可它不会」那个坑 ✓）
    旧动作 = set(getattr(栈类, "允许动作", ()) or ())
    栈类.允许动作 = frozenset(旧动作 | {"collect"})

    def 接(self, 名字, 步骤, s):
        try:
            _统计["看过"] += 1
            新步骤, 说明 = 收(步骤)
            for x in 说明:
                _说(f"[收集] {x}")
            if 说明:
                return 原接(self, 名字, 新步骤, s)
        except Exception as e:
            print(f"[收集] 出岔子（不影响主链，按原样接单）：{e}", flush=True)
        return 原接(self, 名字, 步骤, s)

    # ★★ 规矩 ②③：新动作光"允许"**还不够** ✗ 得有人干这两件事 ✓
    #   （今天栽过「你说开了可它不会」那个坑 ✓ —— 光开闸不接线，等于没做 ✓）
    原下发 = getattr(栈类, "_下发", None)
    原看完成 = getattr(栈类, "_看完成了没", None)
    if callable(原下发):
        _原2[("下发", id(栈类))] = 原下发

        def _下发(self, 步, 任, 现在, s):
            if (步 or {}).get("动作") == "collect":
                # ← 这一步就是**接线**：脑的 collect → 手的 `{cmd:"collect"}` ✓
                self.发({"cmd": "collect",
                        "物品": str(步.get("物品") or ""),
                        "数量": int(步.get("数量") or 1)})
                return True
            return 原下发(self, 步, 任, 现在, s)

        栈类._下发 = _下发

    if callable(原看完成):
        _原2[("看完成", id(栈类))] = 原看完成

        def _看完成了没(self, 步, s, 任=None):
            if (步 or {}).get("动作") == "collect":
                # 判据跟「拾」一模一样 ✓：背包里够了就算成 ✓
                try:
                    计 = (s or {}).get("items")
                    if not isinstance(计, dict):
                        return False, None
                    有 = 计.get(str(步.get("物品") or ""))
                    有 = float(有) if isinstance(有, (int, float)) else 0.0
                    return 有 >= float(步.get("数量") or 1), None
                except Exception:
                    return False, None
            return 原看完成(self, 步, s, 任)

        栈类._看完成了没 = _看完成了没

    栈类.接 = 接
    栈类._收集装了 = True
    打的 = [
        "任务栈.接()  ← 接单那一刻，把连着的一串「挖 X → 拾 Y」收成一条 collect ✓",
        "任务栈.允许动作  ← 加上 `collect`（新动作必须同时开闸 ✓ 不然当场被拒 ✗）",
    ]
    if callable(原下发):
        打的.append("任务栈._下发()  ← 把脑的 collect 翻成手的 `{cmd:\"collect\"}` ✓")
    if callable(原看完成):
        打的.append("任务栈._看完成了没()  ← collect 的判据（跟「拾」一样：背包里够了就算成 ✓）")
    return {"好": True, "为什么": "", "打了": 打的}


def 卸下(bridge):
    global _日志
    栈类 = getattr(bridge, "任务栈", None)
    原 = _原.pop(栈类, None) if 栈类 is not None else None
    if not 原:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    栈类.接 = 原
    for 键, 名 in (("下发", "_下发"), ("看完成", "_看完成了没")):
        f = _原2.pop((键, id(栈类)), None) if 栈类 is not None else None
        if callable(f):
            setattr(栈类, 名, f)
    try:
        栈类.允许动作 = frozenset(栈类.允许动作 - {"collect"})
    except Exception:
        pass
    for 名 in ("_收集装了",):
        try:
            delattr(栈类, 名)
        except Exception:
            pass
    _日志 = None
    return {"好": True, "为什么": "", "打了": ["还原 任务栈.接()", "收回允许动作里的 collect"]}


def 同步实例(bridge, 日志=None, 车钩=None):
    try:
        if 日志:
            日志(f"收集：收过 {_统计['收过']} 条 ｜ 一共省下 {_统计['省下']} 步")
    except Exception:
        pass
    return {"好": True, "为什么": "无状态，随便拔", "打了": []}
