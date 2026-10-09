#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工具查表车厢（v2）—— 离线断言。

v1 的教训：v1 换的是 **bridge._要镐子（模块顶层对象）** ✗ →
**车钩宪法当场拦住**（宪法① 不许换主链本体）→ 脑整晚起不来。
v2 改成**包类方法**（`任务栈._看完成了没`）✓ —— 所以这一版测的就是 v2：

  A 装上 / 幂等 / 卸下还原
  B ★★★ **顶层对象一个都没动**（v1 就是死在这条上 —— 这条是 v2 的命根子）
  C ★★★ 行为：挖草方块 + 没镐子 → **不再被判死**，交给物理事实判
       · 方块还在 → (False, None)  = 没完成，继续去挖 ✓
       · 方块没了 → (True, None)   = 完成 ✓
  D ★★ 真需要镐子的（石头）→ **不由我们接管**，交回主链（fail-closed ✓）
  E 表读不到 → 拒绝装

跑法：python3 外挂/测工具查表.py
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


def 载(名):
    p = os.path.join(外挂根, 名, "补丁.py")
    spec = importlib.util.spec_from_file_location(f"测_{名}", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"测_{名}"] = m
    sys.path.insert(0, os.path.join(外挂根, 名))
    spec.loader.exec_module(m)
    return m


class 假我:
    """只提供包装函数会用到的那两个方法（多余的它不许调 ✓）。"""
    def __init__(self, 名, 有镐=False, 要炸=False):
        self.名 = 名
        self.有镐 = 有镐
        self.要炸 = 要炸
        self.交回了 = False

    def _方块名(self, s, p):
        return self.名

    def _有工具(self, s, t):
        return self.有镐

    # 假的"原方法"：真被交回时会被换成它
    def 原方法(self, 步, s, 任):
        self.交回了 = True
        if self.要炸:
            raise RuntimeError("交回原方法了（说明这一步不归我们管 ✓）")
        return ("原方法的答案", None)


def 主():
    sys.path.insert(0, 外挂根)
    sys.path.insert(0, ROOT)
    import bridge
    查 = 载("工具查表")

    # ══════════ B 先记下：**顶层对象一个都不许动** ══════════
    快照 = {k: id(v) for k, v in vars(bridge).items()}
    试("B0 装之前，旧的硬规则确实认为草方块要镐子（留证 —— 这就是主人卡住的原因）",
       bridge._要镐子("grass_block") is True, str(bridge._要镐子("grass_block")))

    栈类 = bridge.任务栈
    原方法 = 栈类._看完成了没
    r = 查.装上(bridge, 日志=lambda *a, **k: None)
    试("A1 装上了", r.get("好") is True, str(r))
    试("A2 打了 1 处补丁（任务栈._看完成了没）", len(r.get("打了", [])) == 1, str(r.get("打了")))
    试("A3 类方法真的被换掉了", 栈类._看完成了没 is not 原方法)
    试("A4 幂等", 查.装上(bridge)["为什么"].find("已经装过") >= 0)

    变了 = [k for k, v in vars(bridge).items() if 快照.get(k) is not None and id(v) != 快照[k]]
    试("B1 ★★★ **顶层对象一个都没动**（v1 就是死在这条上）", not 变了, f"动了：{变了}")
    试("B2 ★★★ bridge._要镐子 还是原来那个（没被换）",
       bridge._要镐子 is not None and id(bridge._要镐子) == 快照.get("_要镐子"))

    # ══════════ C 行为 ══════════
    包 = 栈类._看完成了没
    我1 = 假我("grass_block", 有镐=False)
    s1 = {"pos": [0, 0, 0]}
    出1 = 包(我1, {"动作": "挖", "p": [1, 2, 3]}, s1, {})
    试("C1 ★★★ 挖草方块 + 没镐子 → **不再判死**（方块还在 = 没完成，继续去挖 ✓）",
       出1 == (False, None), str(出1))
    试("C2 而且**没交给主链**（主链那条硬规则会判死它 ✗）", 我1.交回了 is False)

    我2 = 假我("air", 有镐=False)
    出2 = 包(我2, {"动作": "挖", "p": [1, 2, 3]}, s1, {})
    试("C3 ★★ 方块变成空气了 → 判**完成** ✓", 出2 == (True, None), str(出2))

    我3 = 假我("oak_log", 有镐=False)
    出3 = 包(我3, {"动作": "挖", "p": [1, 2, 3]}, s1, {})
    试("C4 ★★ 原木也一样（表说不要镐子 ✓）", 出3 == (False, None), str(出3))

    # ══════════ C5 ★★★ 雷达**没读数**（名=None）≠ 挖完了 ══════════
    #   ⚠⚠ 这条用例是**补上去的** ✗ —— 2026-10-09 我改「空气名先判」时写成了
    #     `if 名 is None or str(名) in 空气名: return True` ✗
    #     → **把「雷达没读数」也当成了「挖完了」** ✓
    #     实机后果（当场抓到，任务账本原文）：
    #       13:22:41.778 步骤完成 挖  用了 **0.0 秒**   ← 那根原木还在！
    #       13:23:41.977 步骤失败 拾  等了 60 秒还没成（超时）
    #     ⚠ 而这个坑**主链的注释里早写着**：
    #       「探针没到货（None）**不算挖完** —— 只有明确读到空气才算。
    #         原来把 None 也算进去，结果接单后第一拍就"挖完了"（0.2 秒），
    #         而那一格其实还在（后面 60 秒的"拾"超时就是这么来的）。」
    #     ★ 规矩：**`None` 是「不知道」，不是「没有」** ✗
    #       「不知道」永远不许当成「好消息」（不许 fail-open ✓）
    #       —— 跟主链那 12 处 `or [0,0,0]` 是同一个病根 ✓
    我5 = 假我(None, 有镐=False, 要炸=True)      # ← 雷达对那一格**没有读数**
    抛了5 = None
    出5 = None
    try:
        出5 = 包(我5, {"动作": "挖", "p": [1, 2, 3]}, s1, {})
    except Exception as e:
        抛了5 = e
    试("C5 ★★★ 雷达**没读数**（名=None）→ **不许判完成** ✗"
       "（None 是「不知道」，不是「没有」；判成完成 = 接单第一拍就「挖完了」、「拾」干等 60 秒）",
       出5 != (True, None) and (抛了5 is not None or 出5 == (False, None)),
       f"出={出5!r} 抛={抛了5!r}")

    # ══════════ D 真需要镐子的，交回主链 ══════════
    我4 = 假我("stone", 有镐=False, 要炸=True)
    试("D1 ★★ 挖石头（表说**要镐子**）→ 不由我们接管 ✓", 查.要镐子吗("stone") is True)
    # ⚠ 交回原方法 = 真主链那个方法被调用 ✓ —— 而它需要一大堆 self 上的东西
    #   （任务 / 数 / _记 …），我的假我**故意**没有 ✗ → 它必然抛异常 ✓
    #   「抛异常」本身就是"交回出去了"的证据 ✓（真跑的时候 self 是真的，不会抛 ✓）
    抛了 = None
    try:
        包(我4, {"动作": "挖", "p": [1, 2, 3]}, s1, {})
    except Exception as e:
        抛了 = e
    试("D2 ★★ 挖石头（表说要镐子）→ **交回主链了**（所以它去调真方法、在我这个假 self 上抛了）",
       抛了 is not None and "假我" in str(抛了), f"抛了：{抛了!r}")

    # ══════════ A 卸下 ══════════
    r2 = 查.卸下(bridge)
    试("A5 卸下返回好", r2.get("好") is True, str(r2))
    试("A6 ★★ 一字不差还原（is 同一个对象）", 栈类._看完成了没 is 原方法)
    试("A7 卸干净之后再卸也不炸", 查.卸下(bridge).get("好") is True)

    # ══════════ E 表读不到 → 拒绝装 ══════════
    查._表 = {}
    r3 = 查.装上(bridge, 日志=lambda *a, **k: None)
    试("E1 ★★ 表读不到 → **拒绝装**（不装作装上了）", r3.get("好") is False, str(r3))
    试("E2 ★★ 而且没动全局状态", 栈类._看完成了没 is 原方法)
    查._表 = None

    print("\n" + "═" * 62)
    print(f"工具查表车厢：{len(通过)} 过 / {len(失败)} 失败")
    for f in 失败:
        print(f"  ❌ {f['名']} —— {f['为啥']}")
    print("═" * 62)
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
