#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""常识库 · 离线测试（纯函数，毫秒级，不用起车、不用开 MC）。

★ C 组是**核心验收**：它把求解器给出的计划**真的模拟执行一遍**，
  逐条核对材料账，最后确认「石镐真的躺在背包里」。
  —— 这就是任务书里第一阶段那个「徒手撸树 → 木镐 → 石头 → 石镐」的最小闭环。

跑法：python3 外挂/常识/测常识.py
退出码：0 全过 / 1 有失败
"""

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import 数据 as 数据模块            # noqa: E402
import 挖掘矩阵                    # noqa: E402
import 求解器                      # noqa: E402

通过, 失败 = [], []


def 试(名, 条件, 为啥="条件不成立"):
    (通过 if 条件 else 失败).append(名 if 条件 else {"名": 名, "为啥": 为啥})
    return bool(条件)


def 试抛(名, 函数, 异常类, 关键词=""):
    try:
        函数()
    except 异常类 as e:
        if 关键词 and 关键词 not in str(e):
            失败.append({"名": 名, "为啥": f"拦住了但理由不对：「{e}」"})
        else:
            通过.append(名)
        return True
    except Exception as e:
        失败.append({"名": 名, "为啥": f"抛了意料之外的 {type(e).__name__}: {e}"})
        return False
    失败.append({"名": 名, "为啥": "**该拦却放过了**"})
    return False


# ══════════════════════════ 模拟执行器 ══════════════════════════

def 模拟执行(计划, 起始背包=None, 数=None):
    """把计划当真的跑一遍。返回 (最终背包, 出错说明)。

    ★ 这是全部测试里最要紧的一段：它不问「计划看起来对不对」，
      只问「**照着做，材料够不够**」。任何一步出现负库存就当场报。
    """
    数 = 数 or 数据模块.载入()
    背 = dict(起始背包 or {})
    for i, 步 in enumerate(计划, 1):
        a = 步.get("动作")
        if a == "挖":
            方块 = 步.get("目标方块")
            b = 数["方块"].get(方块)
            if not b:
                return 背, f"第 {i} 步：数据里没有方块「{方块}」"
            if not b["掉落"]:
                return 背, f"第 {i} 步：挖「{方块}」什么都不掉"
            掉 = b["掉落"][0]
            背[掉] = 背.get(掉, 0) + 1
        elif a == "合成":
            料 = 步.get("料") or {}
            if not 料:
                return 背, f"第 {i} 步：合成步骤没写用料明细（计划不自包含）"
            for m, k in 料.items():
                有 = 背.get(m, 0)
                if 有 < k:
                    return 背, f"第 {i} 步：合成「{步.get('物品')}」要 {k} 个「{m}」，" \
                              f"可背包里只有 {有} 个 —— **材料账算错了**"
                背[m] = 有 - k
            背[步["物品"]] = 背.get(步["物品"], 0) + int(步.get("数量") or 1)
        elif a == "放":
            方块 = 步.get("方块")
            if 背.get(方块, 0) < 1:
                return 背, f"第 {i} 步：要放「{方块}」，可背包里没有"
            背[方块] -= 1
        elif a == "走到":
            pass
        else:
            return 背, f"第 {i} 步：不认识的计划动作「{a}」"
    return 背, None


def 动作序(计划):
    """["挖:oak_log", "合成:oak_planks", "放:crafting_table", …]"""
    出 = []
    for 步 in 计划:
        a = 步.get("动作")
        名 = 步.get("物品") or 步.get("目标方块") or 步.get("方块")
        出.append(f"{a}:{名}" if 名 else a)
    return 出


# ══════════════════════════ A 组：数据层 ══════════════════════════

def A组():
    print("── A 组：数据层 ──")
    数 = 数据模块.载入()
    试("A1 三份数据都读进来了",
       len(数["物品"]) > 1000 and len(数["方块"]) > 1000 and len(数["产物到配方"]) > 500,
       f"物品{len(数['物品'])} 方块{len(数['方块'])} 配方{len(数['产物到配方'])}")
    试("A2 木头种类是从数据推的（11 种）", len(数据模块.木头种类()) == 11,
       f"实际 {len(数据模块.木头种类())}")
    试("A3 掉落索引建起来了", len(数["掉落索引"]) > 500)
    试("A4 载入是缓存的（第二次瞬间返回）", 数据模块.载入() is 数)


# ══════════════════════════ B 组：挖掘矩阵 ══════════════════════════

def B组():
    print("── B 组：挖掘判定矩阵 ──")
    数 = 数据模块.载入()
    for 名 in ("oak_log", "dirt", "sand", "gravel"):
        ok, _, _ = 挖掘矩阵.挖得动吗(名, [])
        试(f"B1 {名} 徒手能挖", ok)
    for 名 in ("stone", "granite", "diorite", "iron_ore", "diamond_ore",
               "obsidian", "coal_ore"):
        ok, 为, _ = 挖掘矩阵.挖得动吗(名, [])
        试(f"B2 {名} 空手挖不动", not ok, f"居然说能：{为}")

    # ★ 这三个是主链那个正则的**误报**（说需要镐子，其实不用）
    for 名 in ("redstone_torch", "glowstone", "grass_block"):
        ok, _, _ = 挖掘矩阵.挖得动吗(名, [])
        试(f"B3 ★ {名} 徒手能挖（主链正则误报成需要镐子）", ok)

    # ★ granite 是主链正则的**漏报**（说不用镐子 → 徒手挖 → 什么都不掉 → 静默失败）
    试("B4 ★ granite 被正确拦住（主链正则会放行 → 徒手挖 → 掉落为空）",
       not 挖掘矩阵.挖得动吗("granite", [])[0])

    ok, _, 用 = 挖掘矩阵.挖得动吗("stone", ["wooden_pickaxe", "stick"])
    试("B5 有木镐就能挖石头", ok and 用 == "wooden_pickaxe", f"{ok} {用}")

    ok, _, 用 = 挖掘矩阵.挖得动吗("diamond_ore", ["wooden_pickaxe"])
    试("B6 ★ 只有木镐时，钻石矿判「挖不动」（木镐不在它的工具集里）", not ok)
    ok, _, 用 = 挖掘矩阵.挖得动吗("diamond_ore", ["iron_pickaxe"])
    试("B7 铁镐能挖钻石矿", ok and 用 == "iron_pickaxe", f"{ok} {用}")

    # ★ 手侧那个排序 bug：金镐排在铁镐前面
    好 = 挖掘矩阵.最好的工具(["golden_pickaxe", "iron_pickaxe", "wooden_pickaxe"])
    试("B8 ★★ 有金镐+铁镐时挑**铁镐**（手侧写死的排序会挑金镐 → 挖不动铁矿）",
       好 == "iron_pickaxe", f"挑成了 {好}")

    档 = 挖掘矩阵.算档位("pickaxe")
    试("B9 镐子档位能从数据推出来", bool(档), "推不出来")
    if 档:
        试("B10 ★ 数据说金镐比铁镐低（手侧排序反了）",
           档.get("golden_pickaxe", 9) < 档.get("iron_pickaxe", -1),
           f"golden={档.get('golden_pickaxe')} iron={档.get('iron_pickaxe')}")
        试("B11 木镐比石镐低", 档.get("wooden_pickaxe", 9) < 档.get("stone_pickaxe", -1))

    # 拿真数据对账主链那个正则
    import re
    镐子系 = re.compile(r"(_ore|stone|deepslate|cobblestone|bricks|concrete|obsidian|"
                        r"netherrack|furnace|anvil|terracotta|sandstone|prismarine|"
                        r"basalt|blackstone|tuff|calcite|dripstone|quartz|_block$)")
    误报 = 漏报 = 0
    for 名, b in 数["方块"].items():
        正则说 = bool(镐子系.search(名))
        # ★ 口径跟 2026-10-07 那次对账脚本一致：
        #   「真·需要镐子」= 有 harvestTools **且里头全是镐**
        #   （光判「需要工具非空」会把斧头/铲子也算进来，数字对不上）
        工 = b["需要工具"]
        真 = bool(工) and all(x.endswith("_pickaxe") for x in 工)
        if 正则说 and not 真:
            误报 += 1
        if 真 and not 正则说:
            漏报 += 1
    试("B12 ★ 对账：主链正则误报 51 个", 误报 == 51, f"实际 {误报}")
    试("B13 ★ 对账：主链正则漏报 151 个", 漏报 == 151, f"实际 {漏报}")


# ══════════════════════════ C 组：最小闭环（核心验收） ══════════════════════════

最小闭环 = ["stone_pickaxe", "石镐"]


def C组():
    print("── C 组：最小闭环（核心验收）──")
    附近 = {"oak_log": [10, 70, 10], "stone": [12, 70, 10]}
    r = 求解器.求解("stone_pickaxe", 1, {}, 方块在哪=附近)
    试("C1 空手要石镐，能求出计划", r["好"], r["为什么"])
    if not r["好"]:
        return
    计 = r["计划"]
    序 = 动作序(计)

    试("C2 计划里有 挖 oak_log", "挖:oak_log" in 序)
    试("C3 计划里有 合成 oak_planks", "合成:oak_planks" in 序)
    试("C4 计划里有 合成 crafting_table", "合成:crafting_table" in 序)
    试("C5 计划里有 放 crafting_table", "放:crafting_table" in 序)
    试("C6 计划里有 挖 stone", "挖:stone" in 序)
    试("C7 ★ 计划里有 合成 wooden_pickaxe（它自己想到要先做木镐）",
       "合成:wooden_pickaxe" in 序)
    试("C8 计划最后是 合成 stone_pickaxe", 序[-1] == "合成:stone_pickaxe", 序[-1])

    # ★★ 顺序：工具必须排在挖石头之前，工作台必须排在需要它的合成之前
    试("C9 ★★ 木镐排在挖石头之前",
       序.index("合成:wooden_pickaxe") < 序.index("挖:stone"),
       f"木镐在 {序.index('合成:wooden_pickaxe')}，挖石头在 {序.index('挖:stone')}")
    试("C10 ★★ 工作台排在木镐之前（3×3 合成要台子）",
       序.index("放:crafting_table") < 序.index("合成:wooden_pickaxe"))
    试("C11 挖树排在木镐之前（没木头做不了镐）",
       序.index("挖:oak_log") < 序.index("合成:wooden_pickaxe"))

    # ★★★ 真的模拟执行一遍 —— 这才是「跑通最小闭环」
    背, 坏 = 模拟执行(计, {})
    试("C12 ★★★ 照计划执行，材料账一步都不欠", 坏 is None, str(坏))
    试("C13 ★★★ 执行完，石镐真的在背包里", 背.get("stone_pickaxe", 0) >= 1,
       f"最终背包：{背}")
    试("C14 ★★★ 而且中途真的做出来过一把木镐（不是跳步）",
       any(步.get("物品") == "wooden_pickaxe" for 步 in 计))
    试("C15 木料不浪费：用了 3 个原木（ceil(9 块木板 / 4)）",
       sum(1 for 步 in 计 if 步.get("目标方块") == "oak_log") == 3,
       f"挖了 {sum(1 for 步 in 计 if 步.get('目标方块') == 'oak_log')} 个原木")
    试("C16 挖了 3 块石头（石镐要 3 块圆石）",
       sum(1 for 步 in 计 if 步.get("目标方块") == "stone") == 3)

    # 已经有了就不要再挖
    r2 = 求解器.求解("stone_pickaxe", 1, {"stone_pickaxe": 1}, 方块在哪=附近)
    试("C17 背包里已经有石镐 → 计划是空的（不白跑一趟）",
       r2["好"] and r2["计划"] == [], str(r2["计划"]))

    # 手上已经有木镐 → 不该再去做一把
    r3 = 求解器.求解("stone_pickaxe", 1, {"wooden_pickaxe": 1}, 方块在哪=附近)
    试("C18 ★ 手上已有木镐 → 计划里不该再有 合成 wooden_pickaxe",
       r3["好"] and "合成:wooden_pickaxe" not in 动作序(r3["计划"]),
       动作序(r3["计划"]) if r3["好"] else r3["为什么"])
    if r3["好"]:
        背3, 坏3 = 模拟执行(r3["计划"], {"wooden_pickaxe": 1})
        试("C19 只带木镐出门也能跑通", 坏3 is None and 背3.get("stone_pickaxe"),
           f"{坏3} / {背3}")


# ══════════════════════════ D 组：边界与报错 ══════════════════════════

def D组():
    print("── D 组：边界与报错 ──")
    r = 求解器.求解("根本不存在的东西", 1, {})
    试("D1 不认识的东西 → 报错而不是循环", not r["好"] and "不认识" in r["为什么"])

    # 钻石：只能从钻石矿挖，而钻石矿要铁镐；铁镐要铁锭；铁锭要**熔炼**
    r = 求解器.求解("diamond_pickaxe", 1, {},
                   方块在哪={"oak_log": [1, 2, 3], "stone": [1, 2, 4],
                           "iron_ore": [1, 2, 5], "diamond_ore": [1, 2, 6]})
    试("D2 ★ 挖钻石目前做不到 —— 而且报得清清楚楚", not r["好"], r["为什么"])
    if not r["好"]:
        试("D2b ★★ 报的是**真原因**，不是「嵌套太深」那种敷衍话",
           "嵌套太深" not in r["为什么"],
           f"实际理由：{r['为什么']}")
        试("D2c ★★ 报的是主人要的那句「当前条件无法达成」",
           "当前条件无法达成" in r["为什么"], r["为什么"])
        试("D2d 点数了缺什么（镐子档位或熔炼）",
           any(k in r["为什么"] for k in ("熔炼", "这一档", "pickaxe", "iron_ingot")),
           r["为什么"])

    # 铁镐单独测：卡点应该是「铁锭要熔炼」这条
    r = 求解器.求解("iron_pickaxe", 1, {},
                   方块在哪={"oak_log": [1, 2, 3], "stone": [1, 2, 4]})
    试("D2e ★★ 铁镐报的是「iron_ingot 弄不到」—— 也就是缺熔炼",
       (not r["好"]) and "iron_ingot" in r["为什么"],
       r["为什么"])

    # 深度上限必须生效
    r = 求解器.求解("beacon", 1, {}, 最多深度=2)
    试("D3 深度上限生效（超纲就报，不展开）",
       not r["好"] and ("太深" in r["为什么"] or "弄不到" in r["为什么"]),
       r["为什么"])

    # 徒手能挖的东西，也给得出计划
    r = 求解器.求解("oak_log", 2, {}, 方块在哪={"oak_log": [1, 2, 3]})
    试("D4 要两个原木 → 两步挖", r["好"] and len(r["计划"]) == 2, str(r["计划"]))
    if r["好"]:
        背, 坏 = 模拟执行(r["计划"], {})
        试("D5 两个原木真的到手", 坏 is None and 背.get("oak_log") == 2, str(背))


# ══════════════════════════ Z 组 ══════════════════════════

def Z组():
    import hashlib
    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    路 = os.path.join(ROOT, "bridge.py")
    指纹 = hashlib.sha256(io.open(路, "rb").read()).hexdigest()
    试("Z1 主链 sha256 还是 2499f81f807431b0（常识库只在外面读数据，没碰主链）",
       指纹.startswith("2499f81f807431b0"), 指纹[:16])


def 主():
    A组()
    B组()
    C组()
    D组()
    Z组()
    print(f"\n{'═' * 62}")
    print(f"常识库测试：{len(通过)} 过 / {len(失败)} 失败")
    for x in 通过:
        print(f"  ✅ {x}")
    for x in 失败:
        print(f"  ❌ {x['名']} —— {x['为啥']}")
    print("═" * 62)
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
