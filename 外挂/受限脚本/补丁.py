#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""受限脚本·车厢本体 —— 让「剧本」这条路接进主链（**主链零改动**）。

┌───────────────────────────────────────────────────────────────────┐
│ 它只干两件事，但都挂在别人的函数外面（包壳，不是替换）            │
└───────────────────────────────────────────────────────────────────┘
  ① `任务栈.接()`     ← 如果来的活是「一段剧本」而不是「一串步骤」，
                          先**静态展开**成步骤表，再交给里面那层去审。
  ② `翻译器.组Prompt()` ← 在原有 prompt 后面**补一段剧本语法说明**，
                          让模型知道它可以这么写。

★ 「包壳」是车厢机制的规矩，不是随便写的：
  我们保存 `原函数` 然后在里面调它。所以车上如果还有动作面，
  动作面那层闸（危险物品 / 参数完整性）**照样会过**，一道都不会少。
  车钩是**后挂的先执行**（栈），所以本车厢顺序=20，排在动作面(10)后面，
  它就成了最外层 —— 剧本先展开、展开完的步骤再往下过动作面的闸。

┌───────────────────────────────────────────────────────────────────┐
│ ⚠ 新攻击面：剧本这条路**不经过翻译器**                            │
└───────────────────────────────────────────────────────────────────┘
主链的 `任务栈.接()` 只查「动作在不在 `允许动作` 里」，而「打」**就在
允许动作里**（bridge.py:1372）。平时拦住「打」的是它上游的翻译器
（`翻译器.禁止步骤 = {"打"}`）。剧本直接进 接()，等于把翻译器那道闸绕开了。

所以本文件在展开时**自己把这道闸补上**：
    禁止动作 = 翻译器.禁止步骤 ∪ 翻译器.攻击类
一个字都不许出现在剧本里。见 `_禁止集()`。
（`剧本.py` 的 B1/B2 用例专门打这个后门。）

┌───────────────────────────────────────────────────────────────────┐
│ 顺手修掉一个老毛病                                               │
└───────────────────────────────────────────────────────────────────┘
★ 已知缺陷：模型常常把「步骤」写成**字符串数组**（`["走到 1 2 3", …]`），
  主链会回一句「第 1 步不是个对象」然后拒单。这是 M7b 冻结时留着的。
  既然剧本本来就是一行一件事的文本，那**一串字符串正好就是一段剧本** ——
  这里试着拼起来当剧本展开；展开不成功就**原样交回**给里面那层，
  行为跟以前一模一样（不会因为修 bug 把原来的拒绝路径搞丢）。
"""

import os
import sys
import time

自己目录 = os.path.dirname(os.path.abspath(__file__))
if 自己目录 not in sys.path:
    sys.path.insert(0, 自己目录)

import 剧本 as 剧本模块          # noqa: E402

_原 = {}
_已装 = False
_主链 = None
_车钩 = None
_记 = None
统计 = {"接到剧本": 0, "展开成功": 0, "展开被拒": 0, "字符串数组救回": 0}


def _说(文本):
    if _记:
        _记(文本, 屏幕=False)


def _禁止集(bridge):
    """★ 这是本车厢补的那道闸。翻成白话：**翻译器不许模型干的事，
    剧本这条路也不许。**"""
    译 = getattr(bridge, "翻译器", None)
    禁 = set(getattr(译, "禁止步骤", ()) or ())
    禁 |= set(getattr(译, "攻击类", ()) or ())
    # 兜底：翻译器要是被人拆了，这两样也得拦住
    禁 |= {"打", "attack", "jumpattack", "strike", "打击"}
    return frozenset(禁)


def _危险集(bridge):
    """危险物品名单。**拿不到就返回空集，并且说实话**（不假装有闸）。"""
    栈 = getattr(bridge, "任务栈", None)
    有 = getattr(栈, "危险物品", None)
    if 有:
        return frozenset(有)
    # 动作面没挂上时，直接从数据.py 拿（拿不到就算了，动作面那层还会拦）
    try:
        import importlib
        数 = importlib.import_module("数据").载入()
        return frozenset(数.get("危险物品") or ())
    except Exception:
        _说("⚠ 危险物品名单没拿到（动作面没挂、数据.py 也读不到）—— "
            "剧本这一层的危险物品闸这次是空的（主链那层还有一道）")
        return frozenset()


def _是字符串数组(步骤):
    """模型把步骤写成 `["走到 1 2 3", "挖 1 2 3"]` —— 已知的老毛病。"""
    return (isinstance(步骤, (list, tuple)) and len(步骤) > 0
            and all(isinstance(x, str) for x in 步骤))


def _取剧本(步骤):
    """从各种来料形态里认出「这是一段剧本」。不是剧本就返回 None。"""
    if isinstance(步骤, str):
        return 步骤, "整段字符串"
    if isinstance(步骤, dict):
        for 键 in ("脚本", "剧本"):
            if isinstance(步骤.get(键), str):
                return 步骤[键], f"任务书里的「{键}」字段"
    if isinstance(步骤, (list, tuple)) and len(步骤) == 1 and isinstance(步骤[0], dict):
        for 键 in ("脚本", "剧本"):
            if isinstance(步骤[0].get(键), str):
                return 步骤[0][键], f"单元素任务书里的「{键}」"
    return None, ""


def _展开(文, bridge, 出处):
    """展开 + 报话。返回 (步骤表 or None, 拒绝理由)。"""
    允许 = frozenset(getattr(bridge.任务栈, "允许动作", ()) or ())
    r = 剧本模块.展开(文, 允许动作=允许,
                     禁止动作=_禁止集(bridge),
                     危险物品=_危险集(bridge))
    if not r["好"]:
        统计["展开被拒"] += 1
        _说(f"剧本被拒（{出处}）：{r['为什么']}")
        return None, r["为什么"]
    统计["展开成功"] += 1
    _说(f"剧本展开成功（{出处}）：{len(r['步骤'])} 步，"
        f"统计 {r['统计']}")
    return r["步骤"], ""


def _换接(bridge):
    栈 = bridge.任务栈
    原 = _原["接"]

    def 新接(self, 名字, 步骤, s):
        # ── 甲：明确是剧本（整段字符串 / 任务书里的脚本字段）──
        文, 出处 = _取剧本(步骤)
        if 文 is not None:
            统计["接到剧本"] += 1
            好, 为啥 = _展开(文, bridge, 出处)
            if 好 is None:
                try:
                    self.说(f"[{time.strftime('%H:%M:%S')}] 这段剧本我没法干：{为啥}。",
                            紧急=True)
                    self._记("拒单", 原因="剧本不合格", 说明=为啥)
                except Exception:
                    pass
                return False
            步骤 = 好
        # ── 乙：字符串数组（老毛病）—— 当成一段剧本试着救回来 ──
        elif _是字符串数组(步骤):
            文 = "\n".join(步骤)
            好, 为啥 = _展开(文, bridge, "字符串数组")
            if 好 is None:
                # ★ 救不回来就**原样交回**给里面那层 —— 拒绝路径不变，
                #   不会因为"修 bug"把原来的行为改了。
                _说("字符串数组当剧本也没展开成功，原样交回里面那层")
            else:
                统计["字符串数组救回"] += 1
                步骤 = 好
        # ── 丙：普通步骤表 —— 一个字都不动，直接往下走 ──
        return 原(self, 名字, 步骤, s)

    栈.接 = 新接
    return "任务栈.接()  ← 剧本静态展开（含字符串数组救回）；展开前先查禁止动作"


def _换prompt(bridge):
    译 = getattr(bridge, "翻译器", None)
    if 译 is None or not callable(getattr(译, "组Prompt", None)):
        return None
    原 = _原["组Prompt"] = getattr(译, "组Prompt")

    def 新组Prompt(self, s, 用途="翻译", 任务状况="没有任务", 说话人=None, 原话=None):
        文 = 原(self, s, 用途=用途, 任务状况=任务状况,
                说话人=说话人, 原话=原话)
        if not isinstance(文, str):
            return 文
        可用 = None
        try:
            可用 = frozenset(getattr(bridge.任务栈, "允许动作", ()) or ())
        except Exception:
            pass
        return 文 + "\n\n" + 剧本模块.说明书(可用)

    译.组Prompt = 新组Prompt
    return "翻译器.组Prompt()  ← 追加剧本语法说明（包壳，先调里面那层）"


# ══════════════════════════ 装上 / 卸下 ══════════════════════════

def 装上(bridge, 开关=True, 车钩=None, 日志=None):
    global _已装, _主链, _车钩, _记
    if not 开关:
        return {"好": False, "打了": [],
                "为什么": "开关关着 —— 一个补丁都不打（行为与基线逐字节相同）"}
    if _已装 or getattr(bridge, "_受限脚本外挂", None):
        return {"好": False, "打了": [], "为什么": "已经打过了，不重复打"}
    _主链, _车钩, _记 = bridge, 车钩, 日志

    栈 = bridge.任务栈
    if not callable(getattr(栈, "接", None)):
        return {"好": False, "打了": [], "为什么": "主链上没有 任务栈.接() —— 拒绝打补丁"}
    _原["接"] = 栈.接

    打的 = [_换接(bridge)]
    p = _换prompt(bridge)
    if p:
        打的.append(p)
    else:
        打的.append("翻译器.组Prompt() —— 没找到，跳过（剧本还是能用，"
                  "只是模型不知道可以这么写）")

    bridge._受限脚本外挂 = True
    _已装 = True
    return {"好": True, "为什么": "", "打了": 打的}


def 卸下(bridge):
    global _已装
    if not _已装:
        return False
    栈 = getattr(bridge, "任务栈", None)
    译 = getattr(bridge, "翻译器", None)
    if 栈 is not None and "接" in _原:
        栈.接 = _原["接"]
    if 译 is not None and "组Prompt" in _原:
        译.组Prompt = _原["组Prompt"]
    _原.clear()
    if hasattr(bridge, "_受限脚本外挂"):
        del bridge._受限脚本外挂
    _已装 = False
    return True


def 报个话(bridge):
    return {"装上": _已装,
            "统计": dict(统计),
            "记号": bool(getattr(bridge, "_受限脚本外挂", None))}
