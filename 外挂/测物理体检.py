#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""物理体检车厢 —— 离线断言。

要证明的四件事：
  A 装上 / 幂等 / 卸下（一字不差还原）
  B ★★★ **今天实机抓到的每一类 bug，它都挑得出来**（这是它的全部意义）
  C ★★★ 能改正的就**当场改正**（`拾 grass_block` → `拾 dirt`）✓
  D 干净的步子**一个字不许碰**（不误伤 ✓）

⚠ 这个车厢的数据是**自动抓**的（`tools/生成物理常识.js` → `常识库/物理引擎规则.json`）
  所以这里**不重抄**那些数字 ✓ —— 用例读的是**同一个文件** ✓
  （抄一遍数字 = 又一份会过期的真相 ✓ 今天记过这条）

跑法：python3 外挂/测物理体检.py
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
    spec = importlib.util.spec_from_file_location("测_" + 名, p)
    m = importlib.util.module_from_spec(spec)
    sys.modules["测_" + 名] = m
    sys.path.insert(0, os.path.join(外挂根, 名))
    spec.loader.exec_module(m)
    return m


def 帧(方块=None):
    """造一份状态帧：`blocks` = 雷达读数；`items` = 手里有什么"""
    return {"pos": [-138.5, 74.0, 168.7], "items": {},
            "blocks": [{"p": list(k), "name": v} for k, v in (方块 or {}).items()],
            "scan": {}}


def 主():
    sys.path.insert(0, 外挂根)
    sys.path.insert(0, ROOT)
    import bridge
    体 = 载("物理体检")

    # ══════════ A 装 / 卸 ══════════
    print("── A 组：装、卸 ──")
    原接 = bridge.任务栈.接
    r = 体.装上(bridge, 日志=lambda *a, **k: None)
    试("A1 装上了（数据在、钩子打上了）", r.get("好") is True, str(r))
    试("A2 ★★ 打了 1 处补丁（任务栈.接）", len(r.get("打了", [])) == 1, str(r.get("打了")))
    试("A3 类方法真的被换掉了", bridge.任务栈.接 is not 原接)
    试("A4 幂等（重复装上不再套壳）", 体.装上(bridge)["为什么"].find("已经装过") >= 0)
    r2 = 体.卸下(bridge)
    试("A5 ★★ 卸下以后**一字不差还原**", r2.get("好") is True and bridge.任务栈.接 is 原接, str(r2))
    试("A6 卸载幂等", 体.卸下(bridge).get("好") is True)

    # ══════════ B ★★★ 今天实机抓到的每一类，它都得挑出来 ══════════
    #   这一组就是它**存在的全部意义** ✓
    #   下面每一条都是 2026-10-09 的**真机原话**，不是编的 ✓
    print("── B 组：今天实机抓到的每一类 ──")

    # ① 「挖 air」——「生存常识：本区块：air@[-136, 77, 159]，0.7 格」→ 挖成功却不掉东西
    _, 报 = 体.体检([{"动作": "挖", "p": [-136, 77, 159], "方块": "air"}],
                  帧({(-136, 77, 159): "air"}))
    试("B1 ★★★ 挖的目标**就是空气** → 挑得出来（实机：本区块 air@…，挖成功却不掉东西 ✓）",
       any("T1" in x for x in 报), str(报))

    # ② 「挖基岩」——diggable:false
    _, 报 = 体.体检([{"动作": "挖", "p": [-155, 74, 152], "方块": "bedrock"}],
                  帧({(-155, 74, 152): "bedrock"}))
    试("B2 ★★★ 挖**挖不动的**（基岩）→ 挑得出来（数据是 diggable:false ✓）",
       any("T2" in x for x in 报), str(报))

    # ③ 「拾 grass_block」——实机：挖草方块 → 拾 grass_block → 干等 60 秒 ×3
    改, 报 = 体.体检([{"动作": "挖", "p": [-141, 75, 163], "方块": "grass_block"},
                    {"动作": "拾", "物品": "grass_block", "数量": 1}],
                  帧({(-141, 75, 163): "grass_block"}))
    试("B3 ★★★ 拾的物品 ≠ 掉落物 → 挑得出来（实机原话：挖草方块却拾 grass_block ✓）",
       any("T3" in x for x in 报), str(报))

    # ④ 「走到树叶那一格」——透明 ≠ 能穿（今天最贵的认知盲区）
    _, 报 = 体.体检([{"动作": "走到", "p": [-138, 74, 168]}], 帧({(-138, 74, 168): "oak_leaves"}))
    试("B4 ★★★ 要走到**碰撞盒非空**的一格（树叶）→ 挑得出来"
       "（★ 今天最贵的那条：**透明 ≠ 能穿** ✓ 树叶就是这样的 ✓）",
       any("T4" in x for x in 报), str(报))

    # ⑤ 「要镐子的方块、可手里没镐子」——挖了也不掉东西
    _, 报 = 体.体检([{"动作": "挖", "p": [-141, 75, 163], "方块": "stone"}],
                  帧({(-141, 75, 163): "stone"}))
    试("B5 ★★★ 要镐子的方块 + 手里没镐子 → 挑得出来（挖了也不掉东西 ✓）",
       any("T5" in x for x in 报), str(报))

    # ══════════ C ★★★ 能改正的**当场改正** ══════════
    print("── C 组：能改正的就当场改正 ──")
    改, 报 = 体.体检([{"动作": "挖", "p": [-141, 75, 163], "方块": "grass_block"},
                    {"动作": "拾", "物品": "grass_block", "数量": 1}],
                  帧({(-141, 75, 163): "grass_block"}))
    拾 = [x for x in 改 if x.get("动作") == "拾"]
    试("C1 ★★★ 「拾 grass_block」→ **当场改成「拾 dirt」** ✓（数据里 grass_block→dirt ✓）",
       bool(拾) and 拾[0].get("物品") == "dirt", str(拾))
    试("C2 ★★ 挖那一步一个字没动", 改[0].get("方块") == "grass_block", str(改[0]))
    改2, _ = 体.体检([{"动作": "挖", "p": [-141, 75, 163], "方块": "stone"},
                    {"动作": "拾", "物品": "stone", "数量": 1}],
                  帧({(-141, 75, 163): "stone"}))
    试("C3 ★★ 石头 → **cobblestone** ✓（不是 stone ✓）",
       [x for x in 改2 if x.get("动作") == "拾"][0].get("物品") == "cobblestone", str(改2))

    # ══════════ D 干净的步子一个字不许碰 ══════════
    print("── D 组：不误伤 ──")
    干净 = [{"动作": "走到", "p": [-136, 74, 170]},
           {"动作": "挖", "p": [-141, 75, 163], "方块": "oak_log"},
           {"动作": "拾", "物品": "oak_log", "数量": 1},
           {"动作": "合成", "物品": "oak_planks", "数量": 1}]
    帧净 = 帧({(-136, 74, 170): "air", (-141, 75, 163): "oak_log"})
    改3, 报3 = 体.体检(干净, 帧净)
    试("D1 ★★★ 一条干净的计划 → **一处都不挑**（体检不是找茬 ✓）", not 报3, str(报3))
    试("D2 ★★ 而且计划**原样不动**（连顺序都不许变 ✓）",
       改3 == 干净, str(改3))
    试("D3 ★★ 原木挖了掉原木 → 拾原木是对的（不误改 ✓）",
       [x for x in 改3 if x.get("动作") == "拾"][0].get("物品") == "oak_log")

    # ══════════ E 数据读不到 → 拒绝装（fail-closed）══════════
    print("── E 组：读不到常识库就不装 ──")
    存 = 体._规
    体._规 = False
    r3 = 体.装上(type("桥", (), {"任务栈": bridge.任务栈})())
    试("E1 ★★★ 读不到 常识库/物理引擎规则.json → **拒绝装**（不装作体检过了 ✓）",
       r3.get("好") is False, str(r3))
    体._规 = 存

    print()
    print("═" * 62)
    print(f"物理体检车厢：{len(通过)} 过 / {len(失败)} 失败")
    for x in 失败:
        print(f"  ❌ {x['名']} —— {x['为啥']}")
    print("═" * 62)
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
