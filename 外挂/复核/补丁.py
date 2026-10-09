#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""复核 —— 每拍拿「手」的实时数据，把当前这一步的账摊开来说。

English: The missing middle layer. Every tick, re-read the live frame against the step
being executed and *say the account out loud* — expected seconds vs elapsed, and whether
the world still matches what the plan assumed.

★ 谁要它（主人 2026-10-09 原话）
================================
    「**要不然手的实时数据反馈给脑思考然后思考下一步？**」
    然后一句：「**上牙**」✓

手**早就在**每 200ms 喂状态帧了 ✓ —— 问题不是"没反馈" ✗，是**脑没嚼** ✗：
那些帧只被用来画一句【视觉】播报 ✓ 和判「当前这步完成了没」✓，**90% 是扔掉的** ✓

而今天所有的卡壳，**全都卡在"计划"和"手"中间那条缝里** ✗：

    放@10.7 格外 ✓ ｜ 拾 oak_log 背包 0 ✓ ｜ 挖 y=79 是土 ✓
    去找黑石 ✓ ｜ 掐表 6 秒挖黑曜石 ✓        —— **5 / 5**

原因都一样：**计划是"排的那一瞬间"算出来的** ✗ 可世界在动 ✓
本车厢就是补这层：**每拍**拿这一帧复核当前那一步 ✓

⚠ 它**不抢别人的活** ✗（今天栽过"同一个判断抄两遍就会漏一处"✗）
    坐标改写 → 「挖空守卫」✓
    够不着的插步 → 「够不着自愈」✓
    危险 / 落差 → 「物理体检」✓
    **本车厢只算账、只出声** ✓

⚠ 它**也不掐表** ✗（主人：「我自己挖石头都要赌一下多久才能挖到」✓）
    超预算**只报告不杀** ✓ —— 杀活儿是错的 ✗，不出声也是错的 ✗
"""

import json
import os
import time
import weakref

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
账本 = os.path.join(ROOT, "logs", "复核.jsonl")

_原 = weakref.WeakKeyDictionary()
_日志 = None
_次数 = {"看": 0, "报账": 0, "报现状": 0}
# ★ 同一步只说一次 ✗ —— 不然每拍刷屏 ✓ 那也是另一种静默 ✓
_说过 = set()


def _说(文):
    if _日志:
        try:
            _日志(文)
            return
        except Exception:
            pass
    print(文, flush=True)


def _落账(条):
    try:
        os.makedirs(os.path.dirname(账本), exist_ok=True)
        with open(账本, "a", encoding="utf-8") as f:
            f.write(json.dumps(条, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _代价():
    """拿代价函数 ✓ —— **懒加载** ✓（装在模块顶上会在测试环境里拿不到 ✓ 今天栽过 ✗）"""
    try:
        import sys
        d = os.path.join(ROOT, "外挂", "生存常识")
        if d not in sys.path:
            sys.path.insert(0, d)
        import 代价 as m
        return m
    except Exception:
        return None


def _那格(状态, p):
    """这一帧雷达读到的那一格是什么（没读数 → None ✓ 不知道 ≠ 没有 ✓）"""
    if not (isinstance(p, (list, tuple)) and len(p) >= 3):
        return None
    for 条 in ((状态 or {}).get("blocks") or []):
        q = 条.get("p")
        if isinstance(q, (list, tuple)) and len(q) >= 3:
            try:
                if all(abs(float(q[i]) - float(p[i])) < 0.5 for i in range(3)):
                    return str(条.get("name") or "")
            except Exception:
                continue
    return None


def _距(我, p):
    try:
        return (((float(p[0]) - float(我[0])) ** 2 + (float(p[1]) - float(我[1])) ** 2
                 + (float(p[2]) - float(我[2])) ** 2) ** 0.5)
    except Exception:
        return None


def 这一步账(步, 状态, 背包=None):
    """给这一步估个时间账（秒）✓ —— **全部走代价函数那一份实现** ✓

    返回 (秒 或 None, 账的说明)
    """
    D = _代价()
    动 = (步 or {}).get("动作")
    if D is None:
        return None, "（★ 拿不到代价函数，这一步的账算不出来 ✗ —— 不是「很快」✗）"
    try:
        if 动 == "挖":
            名 = 步.get("方块") or _那格(状态, 步.get("p")) or ""
            单 = D.挖(名, 背包 or {})
            if 单 == D.无穷:
                return None, f"（★ 挖「{名}」**不能干** ✗ 红线/危险/没工具 —— 它不该干这个 ✗）"
            高 = 1
            try:
                import sys
                d = os.path.join(ROOT, "外挂", "生存常识")
                if d not in sys.path:
                    sys.path.insert(0, d)
                import 补丁 as 常
                高 = int(常.骨架高())
            except Exception:
                高 = 1
            return 单 * max(1, 高), f"挖「{名}」×{高} 格 ≈ {D.说(单 * max(1, 高))}"
        if 动 == "走到":
            我 = (状态 or {}).get("pos")
            位 = 步.get("p")
            远 = _距(我, 位) if (我 and 位) else None
            if 远 is None:
                return None, "（不知道我离它多远，走路的账算不出来）"
            return D.走(远), f"走 {远:.1f} 格 ≈ {D.说(D.走(远))}"
        if 动 == "放":
            return D.放(背包), f"放一格 ≈ {D.说(D.放(背包))}"
        if 动 == "合成":
            return D.合成(int(步.get("数量") or 1)), f"合成 ≈ {D.说(D.合成(int(步.get('数量') or 1)))}"
        if 动 in ("拾", "熔炉取成品"):
            return D.拾(int(步.get("数量") or 1)), f"拾 ≈ {D.说(D.拾(int(步.get('数量') or 1)))}"
        if 动 in ("说", "等", "wait_until"):
            return None, "（说话/等待没有「干活」的账 ✓）"
        return None, f"（「{动}」这类动作的账还没标定 ✗ —— 不是「很快」✗）"
    except Exception as e:
        return None, f"（算账时出岔子：{e}）"


def 现状(步, 状态):
    """这一步的**假设**和**这一帧的现实**对得上吗 ✓（只读 ✓ 不改 ✗）

    返回 (对得上吗 或 None 不知道, 人话)
    """
    动 = (步 or {}).get("动作")
    我 = (状态 or {}).get("pos")
    p = 步.get("p")
    if 动 == "挖":
        想 = str(步.get("方块") or "")
        见 = _那格(状态, p)
        if 见 is None:
            return None, f"那格现在**没有读数**（雷达没报它 ✓ 不知道是什么）"
        if 见 in ("air", "cave_air", "void_air"):
            return True, f"那格已经是空气了 ✓（挖掉了就是空气 ✓）"
        if 想 and 见 != 想:
            return False, f"**那一格我读到的是「{见}」，可我要挖「{想}」** ✗（坐标是陈的 ✗）"
        return True, f"那一格还是「{见}」✓ 对得上"
    # ★★★ 2026-10-09 实机第一拍就抓到我自己的**误报** ✗：
    #   我原来把「走到」也套上了「手最多伸 4.5 格」✗ —— **尺子拿错了** ✗
    #   「4.5 格」那是**挖/放**的规矩 ✓（手的交互距离 ✓）
    #   **「走到」本来就以"离得远"为前提** ✓ 拿 4.5 去量它，它每一步都会被判"对不上" ✗
    #   （实机原话：「第 1 步「走到 [-138,77,157]」—— 现状对不上 ✗ 它离我 9.3 格」✗）
    #   ⇒ **每把尺子只量它该量的东西** ✓ —— 这跟 T4 那条教训是同一个 ✓
    #      「判据要用在它真正管的地方」✗（今天第 N 次 ✓）
    if 动 == "放":
        if 我 and p:
            远 = _距(我, p)
            if 远 is not None and 远 > 4.5:
                return False, f"它离我 **{远:.1f} 格** ✗（手最多伸 4.5 格 —— 得先走近 ✓）"
            if 远 is not None:
                return True, f"离我 {远:.1f} 格 ✓ 够得着"
        return None, "（不知道我离它多远）"
    if 动 == "走到":
        # ★ 走到该量的尺子是**落差**，不是距离 ✓
        #   （`常识库/物理引擎规则.json`：一步只上 0.6 格、跳只上 1.1 格；
        #     落差 > 3 格往下走会摔伤 ✓ —— 这两条跟物理体检 T4 是同一份依据 ✓）
        if 我 and p:
            try:
                落差 = float(我[1]) - float(p[1])
            except Exception:
                落差 = None
            if 落差 is not None and 落差 >= 4:
                return False, (f"它比我现在**低 {落差:.0f} 格** ✗（落差超过 3 格会摔伤 ✓"
                               f"得绕路或先垫一格 ✓）")
            if 落差 is not None and 落差 <= -2:
                return False, (f"它比我现在**高 {-落差:.0f} 格** ✗（一步只上 0.6 格、"
                               f"跳也只上 1.1 格 ✓ 得先挖上去或搭一格 ✓）")
            远 = _距(我, p)
            return True, (f"离我 {远:.1f} 格、落差 {落差:.0f} 格 ✓（走路的本分就是走过去 ✓）"
                          if 远 is not None and 落差 is not None else "（读数不全）")
        return None, "（不知道我离它多远）"
    if 动 in ("拾", "熔炉取成品"):
        名 = str(步.get("物品") or "")
        计 = (状态 or {}).get("items")
        要 = float(步.get("数量") or 1)
        # ★★★ 判据的口径要用**手侧的真实语义** ✓ —— 我第一版写成"查不到就是不知道" ✗
        #   那是错的 ✓：手侧的 `items` 是**全量背包清单** ✓
        #     （`外挂/测生存常识.py` 里有一条断言就是这么写的：
        #      「看不见（压根没这个键）时车厢会拒绝规划」✗
        #      ⇒ **键在 = 清单是全的** ✓ 那么"清单里没有它" = **0 个** ✓ 不是"不知道" ✗）
        #   这条口径错得很有代表性 ✓：**"不知道"和"没有"是两回事** ✗
        #     这里恰恰是"清单是全的 → 没有就是 0" ✓
        #   实机 14:28 那一幕就是这样：原木在第 6 步变成了木板 ✓
        #     背包里 oak_log = 0 ✓ 而脑去「拾 oak_log」→ 干等 60 秒 × 3 ✗
        if not isinstance(计, dict):
            return None, f"这一帧**没有背包清单**（不是「没有那个东西」✗ 是整份清单都没给 ✓）"
        有 = 计.get(名)
        有 = float(有) if isinstance(有, (int, float)) else 0.0
        if 有 >= 要:
            return True, f"背包里已经有 {有:.0f} 个「{名}」✓（够了 ✓）"
        return False, (f"背包里「{名}」是 **{有:.0f} 个**，可这一步要 {要:.0f} 个 ✗"
                       f"（清单是全的 ✓ 所以这是「确实没有」✗ 不是「不知道」✓）")
    return None, f"（「{动}」这类动作的现状还没写判据 ✗）"


def 装上(bridge, 日志=None, 数=None, **kw):
    global _日志
    _日志 = 日志
    # ★ config 值要用车钩给的 `数` 读 ✓（自己发明参数名 = 死代码 ✓ 今天栽过 ✗）
    慢几倍, 至少几秒 = 3.0, 20.0
    if callable(数):
        try:
            慢几倍 = float(数("慢几倍", 慢几倍))
            至少几秒 = float(数("至少几秒", 至少几秒))
        except Exception:
            pass

    栈类 = getattr(bridge, "任务栈", None)
    if 栈类 is None:
        return {"好": False, "为什么": "找不到 任务栈 类", "打了": []}
    if getattr(栈类, "_复核装了", False):
        return {"好": True, "为什么": "已经装过了（幂等）", "打了": []}
    原跑 = getattr(栈类, "跑", None)
    if not callable(原跑):
        return {"好": False, "为什么": "任务栈.跑 不是函数", "打了": []}
    _原[栈类] = 原跑

    def 跑(self, s):
        # ★★ 顺序讲究：**先让主链自己跑**（它要判完成、要下发 ✓）
        #   我们再拿**这一拍的结果**去算账 ✓ —— 反过来的话，我们看到的
        #   「已经过了几秒」会少一拍，而且可能跟主链的判据打架 ✗
        出 = 原跑(self, s)
        try:
            任 = getattr(self, "任务", None)
            if not isinstance(任, dict) or 任.get("状态") != "跑":
                return 出
            步骤 = 任.get("步骤") or []
            i = int(任.get("第几步") or 0)
            if not (0 <= i < len(步骤)):
                return 出
            步 = 步骤[i]
            if not isinstance(步, dict):
                return 出
            _次数["看"] += 1
            # ── ① 现状：假设 vs 这一帧的现实（只读 ✓）──
            对, 现话 = 现状(步, s)
            # ── ② 账：该花多久 vs 已经过了多久 ──
            秒, 账话 = 这一步账(步, s, (s or {}).get("items") or {})
            开 = 任.get("步骤开始")
            过了 = (time.time() - float(开)) if isinstance(开, (int, float)) else None
            # ── ③ 该出声了吗 ──
            键 = (id(任), i, str(步.get("p")), str(步.get("方块") or 步.get("物品") or ""))
            要报 = None
            if 对 is False:
                要报 = f"**现状对不上** ✗ {现话}"
                _次数["报现状"] += 1
            elif (秒 and 过了 and 过了 >= 至少几秒 and 过了 >= 秒 * 慢几倍):
                要报 = (f"**比账上慢 {过了 / max(秒, 0.1):.0f} 倍** ✗ "
                        f"（{账话} ｜ 已经过了 {过了:.0f} 秒）")
                _次数["报账"] += 1
            if 要报 and 键 not in _说过:
                _说过.add(键)
                _说(f"★ [复核] 第 {i + 1} 步「{步.get('动作')} "
                    f"{步.get('方块') or 步.get('物品') or 步.get('p')}」—— {要报}"
                    f"｜现状：{现话}")
                if len(_说过) > 500:
                    _说过.clear()
            _落账({"t": round(time.time(), 2), "第几步": i, "动作": str(步.get("动作") or ""),
                   "账秒": (round(秒, 2) if 秒 else None), "过了秒": (round(过了, 2) if 过了 else None),
                   "对得上": 对, "账": 账话, "现状": 现话, "报了": bool(要报)})
        except Exception as e:
            print(f"[复核] 出岔子（不影响主链）：{e}", flush=True)
        return 出

    栈类.跑 = 跑
    栈类._复核装了 = True
    return {"好": True, "为什么": "", "打了": [
        "任务栈.跑()  ← 每拍拿手的实时数据，把当前这一步的**账**摊开来说"
        "（该花多久 vs 已经过了多久 ＋ 计划的假设 vs 这一帧的现实）",
        f"（账本 {账本} ｜ 同一处只说一次 ✗ 不刷屏 ✓）",
    ]}


def 卸下(bridge):
    global _日志
    栈类 = getattr(bridge, "任务栈", None)
    原 = _原.pop(栈类, None) if 栈类 is not None else None
    if not 原:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    栈类.跑 = 原
    try:
        del 栈类._复核装了
    except Exception:
        pass
    _说过.clear()
    _日志 = None
    return {"好": True, "为什么": "", "打了": ["还原 任务栈.跑()"]}


def 同步实例(bridge, 日志=None, 车钩=None):
    try:
        if 日志:
            日志(f"复核：看了 {_次数['看']} 拍 ｜ 报账 {_次数['报账']} 次 ｜ "
                 f"报现状对不上 {_次数['报现状']} 次")
    except Exception:
        pass
    return {"好": True, "为什么": "无状态，随便拔", "打了": []}
