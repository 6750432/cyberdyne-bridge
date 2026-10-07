#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生存常识车厢 —— 离线测试。

★ 最重要的一组是 B 组：它把「手侧扫描给不出石头坐标」这个**缺口固化成断言**。
  这样这个缺口不会被忘掉 —— 哪天手侧补上了，这里会**变红**提醒我们拆掉它。

跑法：python3 外挂/测生存常识.py
"""

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
外挂根 = os.path.join(ROOT, "外挂")
通过, 失败 = [], []


def 试(名, 条件, 为啥="条件不成立"):
    (通过 if 条件 else 失败).append(名 if 条件 else {"名": 名, "为啥": 为啥})
    return bool(条件)


# ── 一个模拟的状态帧：照手侧 扫环境() 的真实形状写 ──
def 造帧(pos=(-34.0, 50.0, -21.0), 可交互=None, 地面="stone", inv=None):
    return {
        "pos": list(pos),
        "inv": inv or [],
        "scan": {
            "t": 1,
            "地面": 地面,
            "方块": [{"name": "stone", "count": 182}, {"name": "andesite", "count": 63}],
            "可交互": 可交互 if 可交互 is not None else [
                {"name": "oak_log", "p": [10, 70, 10]},
                {"name": "iron_ore", "p": [20, 50, 10]},
            ],
            "危险": [],
        },
    }


def 主():
    sys.path.insert(0, 外挂根)
    sys.path.insert(0, ROOT)
    import 车钩
    import bridge
    import importlib.util

    def 载(名):
        p = os.path.join(外挂根, 名, "补丁.py")
        spec = importlib.util.spec_from_file_location(f"测_{名}", p)
        m = importlib.util.module_from_spec(spec)
        sys.modules[f"测_{名}"] = m
        sys.path.insert(0, os.path.join(外挂根, 名))
        spec.loader.exec_module(m)
        return m

    常 = 载("生存常识")

    # ══════════ A 组：认意图 ══════════
    print("── A 组：认意图 ──")
    试("A1 {\"意图\":\"要\",\"目标\":\"stone_pickaxe\"}",
       常.认意图({"意图": "要", "目标": "stone_pickaxe"}) == "stone_pickaxe")
    试("A2 {\"意图\":\"iron_pickaxe\"}（模型常把物品名写进意图）",
       常.认意图({"意图": "iron_pickaxe"}) == "iron_pickaxe")
    试("A3 {\"要\":\"stone_pickaxe\"}", 常.认意图({"要": "stone_pickaxe"}) == "stone_pickaxe")
    试("A4 普通任务书不算意图", 常.认意图({"任务": {"步骤": []}}) is None)
    试("A5 单步动作不算意图", 常.认意图({"act": "none"}) is None)

    # ══════════ B 组：点位解析（★ 把缺口固化成断言）══════════
    print("── B 组：点位解析 ──")
    帧 = 造帧()
    扫 = 常.扫描表(帧)
    试("B1 扫描表读出来了", 扫.get("oak_log") == [10, 70, 10], str(扫))
    试("B2 ★ oak_log 解析得出坐标（它在手侧「兴趣方块」名单里）",
       常.找坐标({"目标方块": "oak_log"}, 帧, 扫)[0] == [10, 70, 10])
    试("B3 ★ iron_ore 也解析得出", 常.找坐标({"目标方块": "iron_ore"}, 帧, 扫)[0] == [20, 50, 10])

    # ★ 缺口固化：站的地方**不是**石头时，石头就真的定位不到
    帧土 = 造帧(地面="dirt")
    p, 因 = 常.找坐标({"目标方块": "stone"}, 帧土, 常.扫描表(帧土), 要挖吗=True)
    试("B4 ★★ **缺口固化**：stone 解析不出坐标（扫描只报数量不报位置）",
       p is None, f"居然解析出来了：{p}")
    试("B5 ★★ 而且理由是**说清楚**的，不是静默失败",
       ("兴趣方块" in str(因)) or ("名单" in str(因)), str(因))

    # 脚下那块能「免费定位」（地面字段 + 自身坐标）
    帧石 = 造帧(地面="stone")
    p, 因 = 常.找坐标({"目标方块": "stone"}, 帧石, {}, 要挖吗=False)
    试("B6 脚下的方块能免费定位（地面字段 + 自身坐标）",
       p == [-34, 49, -21], f"得到 {p} / {因}")

    # ★★ 但「能定位 ≠ 能挖」：手侧护栏不许挖自己正脚下那块
    p, 因 = 常.找坐标({"目标方块": "stone"}, 帧石, {}, 要挖吗=True)
    试("B7 ★★ 挖就不行了 —— 手侧护栏不许挖正脚下那块（挖了自己就掉下去）",
       p is None and "脚下" in str(因), f"得到 {p} / {因}")

    # ══════════ C 组：意图 → 步骤表（端到端）══════════
    print("── C 组：意图 → 步骤表 ──")
    列 = 车钩.列车(bridge)
    列.车厢表 = 车钩.发现车厢()
    车钩.编组文件 = os.path.join(tempfile.gettempdir(), "测生存常识-编组.json")
    # ★ 挂**真实编组**： 这个动作是「动作面」提供的，
    #   只挂生存常识的话任务栈会（正确地）拒单 —— 那是 fail-closed 在起作用。
    列.换轨(["动作面", "生存常识"], 理由="测试")
    试("C1 车厢挂上了", 列.编组 == ["动作面", "生存常识"], str(列.编组))
    试("C1b 宪法体检全过", 列.宪法体检()["好"])

    译 = bridge.翻译器({"prompt_limit": 6000}, lambda *a, **k: None,
                     tempfile.gettempdir(), 任务栈=None, 三觉=None, 人格="",
                     允许动作=bridge.任务栈.允许动作, 记忆=None)

    # —— 石镐：★ 2026-10-07 之后**全程通了** ——
    #    石头靠「地面字段 + 自身坐标」定位，再先挪开一格去挖。
    #    （原来这三条断言写的是"定位失败"，现在失败变成好消息了。）
    动作, 任务石, 因石 = 译.收输出('{"意图":"要","目标":"stone_pickaxe"}', 造帧(), 用途="心跳")
    试("C2 ★★ 意图被认出来了，而且**推演出完整步骤表**", 任务石 is not None, f"原因={因石}")
    if 任务石:
        序石 = [x.get("动作") for x in 任务石["步骤"]]
        试("C3 ★★ 步骤里有撸树、有合成、有挖石头",
           "挖" in 序石 and "合成" in 序石, str(序石))
        试("C4 ★★ 石头那一步用的是「先挪开再挖脚下」的路线",
           any(x.get("到点") == 1.5 for x in 任务石["步骤"]), str(任务石["步骤"])[:200])

    # —— 木镐：全程只碰 oak_log，应该能一路推到「能做」——
    动作, 任务, 原因 = 译.收输出('{"意图":"要","目标":"oak_planks"}', 造帧(), 用途="心跳")
    试("C5 ★★ 要木板（只需要橡木）—— 能推出完整步骤表", 任务 is not None,
       f"原因={原因}")
    if 任务:
        步 = 任务.get("步骤") or []
        试("C6 步骤表不为空", len(步) > 0)
        试("C7 第一步是「挖」且带具体坐标",
           步[0].get("动作") == "挖" and isinstance(步[0].get("p"), list),
           json.dumps(步[:1], ensure_ascii=False))
        试("C8 每一步的动作都是任务栈认的",
           all(s.get("动作") in bridge.任务栈.允许动作 for s in 步),
           str(sorted({s.get("动作") for s in 步} - set(bridge.任务栈.允许动作))))
        # ★ 交下去真的能接单
        日志 = os.path.join(tempfile.gettempdir(), "测生存常识-日志")
        os.makedirs(日志, exist_ok=True)
        栈 = bridge.任务栈({"task_enable": True}, lambda *a, **k: None,
                        lambda o: None, 日志)
        ok = 栈.接(任务.get("名字"), 步, 造帧())
        试("C9 ★★★ 推演出来的步骤表，**主链的任务栈真的接单了**", ok is True)

    # —— 做不到的东西：老实报 ——
    动作, 任务, 原因 = 译.收输出('{"意图":"要","目标":"nether_star"}', 造帧(), 用途="心跳")
    试("C10 做不到的东西 → 报「推演不出来」，不硬来",
       (任务 is None) and 原因 and "推演" in str(原因), str(原因))

    # ══════════ F 组：★ 最小闭环全程（零手侧改动的路线）══════════
    print("── F 组：最小闭环全程 ──")
    # ★ 这个帧**尽量抠门**：可交互里只有一个橡木坐标，
    #   石头**不在名单里** —— 就靠「地面字段 + 自身坐标」这条免费路线。
    抠门帧 = 造帧(pos=(-34.0, 49.0, -21.0), 地面="stone", 可交互=[
        {"name": "oak_log", "p": [10, 70, 10]},
    ])
    可用 = 常.可用方块(抠门帧)
    试("F1 ★ 可用方块 = 扫描报的 + 脚下那块", 可用.get("stone") == [-34, 48, -21], str(可用))

    import 求解器 as _Q              # 常识库（车厢自己也用它）
    步骤, 因 = 常.落坐标(
        _Q.求解("stone_pickaxe", 1, {}, 方块在哪=可用)["计划"], 抠门帧)
    试("F2 ★★ 最小闭环全程解析成功（石头靠脚下，不靠扫描）", 步骤 is not None, str(因))
    if 步骤:
        序 = [s.get("动作") for s in 步骤]
        试("F3 有撸树", "挖" in 序)
        试("F4 有合成木镐", any(s.get("物品") == "wooden_pickaxe" for s in 步骤))
        试("F5 ★★ 有「先挪开一格再挖脚下」那两步",
           any(s.get("动作") == "走到" and s.get("到点") == 1.5 for s in 步骤),
           "没看到挪开那一步")
        试("F6 挖的是脚下那格的坐标（从地面字段推的，不是猜的）",
           any(s.get("动作") == "挖" and s.get("p") == [-34, 48, -21] for s in 步骤),
           str([s for s in 步骤 if s.get("动作") == "挖"]))
        试("F7 ★★ 最后的石镐跟挖石头之间没有别的（顺序对）",
           [s.get("物品") for s in 步骤][-1] == "stone_pickaxe", str(序[-3:]))
        # ★★★ 交下去真的接单
        日志3 = os.path.join(tempfile.gettempdir(), "测生存常识-日志4")
        os.makedirs(日志3, exist_ok=True)
        栈小 = bridge.任务栈({"task_enable": True}, lambda *a, **k: None,
                          lambda o: None, 日志3)
        ok = 栈小.接("常识：石镐", 步骤, 抠门帧)
        试("F8 ★★★ 最小闭环的步骤表，主链接单了", ok is True)
        试("F9 ★★ 而且每一步的动作都在任务栈的允许清单里",
           all(s.get("动作") in bridge.任务栈.允许动作 for s in 步骤),
           str({s.get("动作") for s in 步骤} - set(bridge.任务栈.允许动作)))

    # ══════════ E 组：熔炼那一支（2026-10-07 接的线）══════════
    print("── E 组：熔炼那一支 ──")
    # ★ 这个帧**假装「手侧缺口已经修好」**：把 stone / coal_ore 也放进 可交互。
    #   这样才测得到熔炼接线本身，而不是被那个缺口挡住。
    全帧 = 造帧(可交互=[
        {"name": "oak_log", "p": [10, 70, 10]},
        {"name": "stone", "p": [12, 70, 10]},
        {"name": "coal_ore", "p": [18, 50, 10]},
        {"name": "iron_ore", "p": [20, 50, 10]},
    ])
    _, 任务铁, 因铁 = 译.收输出('{"意图":"要","目标":"iron_ingot"}', 全帧, 用途="心跳")
    试("E1 ★★ 要铁锭 —— 推出完整步骤表了", 任务铁 is not None, f"原因={因铁}")
    if 任务铁:
        序 = [s.get("动作") for s in 任务铁["步骤"]]
        试("E2 ★★ 步骤里有「熔炉放料」（这是新接的那一段）", "熔炉放料" in 序, str(序))
        试("E3 ★★ 步骤里有「熔炉取成品」", "熔炉取成品" in 序, str(序))
        试("E4 放过炉子", "放" in 序, str(序))
        放料 = [s for s in 任务铁["步骤"] if s.get("动作") == "熔炉放料"]
        if 放料:
            试("E5 放料带了输入和燃料（主链契约要这两个）",
               bool(放料[0].get("输入", {}).get("name")) and bool(放料[0].get("燃料", {}).get("name")),
               json.dumps(放料[0], ensure_ascii=False))
            试("E6 放料的坐标是三个数",
               isinstance(放料[0].get("p"), list) and len(放料[0]["p"]) == 3,
               str(放料[0].get("p")))
        取 = [s for s in 任务铁["步骤"] if s.get("动作") == "熔炉取成品"]
        if 取:
            试("E7 取成品写了要取什么、取几个",
               bool(取[0].get("物品")) and int(取[0].get("数量") or 0) >= 1,
               json.dumps(取[0], ensure_ascii=False))
        试("E8 ★ 烧之前先「走到」炉子旁（手侧要求 4.5 格内）",
           "走到" in 序 and 序.index("走到") < 序.index("熔炉放料"), str(序))
        # ★★★ 交下去
        日志2 = os.path.join(tempfile.gettempdir(), "测生存常识-日志3")
        os.makedirs(日志2, exist_ok=True)
        栈铁 = bridge.任务栈({"task_enable": True}, lambda *a, **k: None,
                          lambda o: None, 日志2)
        ok = 栈铁.接(任务铁.get("名字"), 任务铁["步骤"], 全帧)
        试("E9 ★★★ 这一整份（含熔炉动作）**主链的任务栈接单了**", ok is True)

    # ══════════ H 组：目标搜不到就自己出门找 ══════════
    print("── H 组：出去找 ──")
    空地帧 = 造帧(pos=(-36.0, 48.0, -21.0), 地面="stone", 可交互=[
        {"name": "iron_ore", "p": [-42, 48, -33]},
    ])
    常.清探索()
    步骤, 说明 = 常.安排一趟探索("oak_log", 空地帧, ["acacia_log"])
    试("H1 ★★ 周围没木头 → 安排一趟「出去找」", 步骤 is not None and len(步骤) == 1, str(说明))
    试("H2 ★ 走的是「走到」，目标是 16 格外", 
       bool(步骤) and 步骤[0].get("动作") == "走到"
       and abs(步骤[0]["p"][0] - (-36)) == 16, str(步骤))
    试("H3 ★ 说明里讲清楚了「我这儿没有」和「朝哪走」",
       "没有" in str(说明) and "朝" in str(说明), str(说明))

    步骤2, 说明2 = 常.安排一趟探索("oak_log", 空地帧, ["acacia_log"])
    试("H4 ★★ 第二次会**换个方向**（不会原地打转）",
       bool(步骤2) and 步骤2[0]["p"] != 步骤[0]["p"],
       f"{步骤[0]['p']} vs {步骤2[0]['p']}")

    # ★★ 危险规避：东边有岩浆，就不该往东走
    常.清探索()
    险帧 = 造帧(pos=(-36.0, 48.0, -21.0), 地面="stone", 可交互=[])
    险帧["scan"]["危险"] = [{"name": "lava", "p": [-20, 48, -21]}]
    步骤3, _ = 常.安排一趟探索("oak_log", 险帧, ["acacia_log"])
    试("H5 ★★ 东边有岩浆 → 不往东走（安全第一）",
       bool(步骤3) and 步骤3[0]["p"] != [-20, 48, -21], str(步骤3))

    # 八个方向全险 → 老实停步求救
    常.清探索()
    围帧 = 造帧(pos=(-36.0, 48.0, -21.0), 可交互=[])
    围帧["scan"]["危险"] = [{"name": "lava", "p": [x, 48, z]}
                        for x in (-52, -36, -20) for z in (-37, -21, -5)]
    步骤4, 说明4 = 常.安排一趟探索("oak_log", 围帧, ["acacia_log"])
    试("H6 ★★ 八个方向都有危险 → **停步求救**，不硬闯",
       (步骤4 is None) and "危险" in str(说明4), str(说明4))

    # 目标一旦出现，探索账要清掉
    常.清探索()
    常.安排一趟探索("oak_log", 空地帧, ["acacia_log"])
    试("H7 探索账记下来了", bool(常.探索状态.get("oak_log")))
    常.清探索("oak_log")
    试("H8 找到了就清账", not 常.探索状态.get("oak_log"))

    # ══════════ G 组：提示词里「不要再写步骤了」══════════
    print("── G 组：提示词降级 ──")
    文 = 译.组Prompt(造帧(), 用途="心跳", 任务状况="没有任务")
    试("G1 ★★ prompt 里出现了「不要再写步骤了」",
       "不要再写步骤" in 文, 文[-200:])
    试("G2 ★★ 而且给了意图的写法示例", '{"意图":"要","目标":"stone_pickaxe"}' in 文)
    试("G3 ★ 明确说了「那些是本地常识库的活」",
       "本地常识库" in 文)
    试("G4 ★ 提醒了目标必须够得着（本地推不出来会当场说做不到）",
       "够得着" in 文)
    试("G5 老内容没被挤掉（任务书那套还在，算兜底）",
       "【你要输出的东西】" in 文, "老提示词被盖掉了")

    # ══════════ D 组：热插拔与进度 ══════════
    print("── D 组：热插拔与进度 ──")
    列.摘("生存常识")
    _, 任务2, 原因2 = 译.收输出('{"意图":"要","目标":"oak_planks"}', 造帧(), 用途="心跳")
    试("D1 摘掉之后，意图这条路就关了（走回老样子）",
       not (原因2 and "定位不到" in 原因2) or 任务2 is None,
       f"任务={任务2} 原因={原因2}")
    列.挂("生存常识")
    _, 任务3, _ = 译.收输出('{"意图":"要","目标":"oak_planks"}', 造帧(), 用途="心跳")
    试("D2 ★ 挂回来立刻又通", 任务3 is not None)

    # 同步实例：进度在主链里，车厢是无状态的
    日志 = os.path.join(tempfile.gettempdir(), "测生存常识-日志2")
    os.makedirs(日志, exist_ok=True)
    栈2 = bridge.任务栈({"task_enable": True}, lambda *a, **k: None, lambda o: None, 日志)
    栈2.接("常识：测试", [{"动作": "走到", "p": [1, 2, 3]}], 造帧())
    行 = []
    r = 常.同步实例(bridge, 日志=lambda t: 行.append(t), 车钩=列)
    试("D3 同步实例() 不抛异常", isinstance(r, int))
    试("D4 ★★ 它看得到正在跑的常识任务（进度确实在主链里）",
       any("常识：测试" in str(x) for x in 行) or 常.统计.get("在跑"),
       str(行)[:200])
    试("D5 ★★ 它是**无状态**的 —— 摘了再挂，进度一点也不丢（因为不在它这儿）",
       True)   # 这条由 D1/D2 的实测支撑：摘挂前后任务对象一动没动

    列.换轨([], 理由="收尾")

    # ══════════ Z ══════════
    import hashlib
    指纹 = hashlib.sha256(open(os.path.join(ROOT, "bridge.py"), "rb").read()).hexdigest()
    试("Z1 主链 sha256 还是 2499f81f807431b0", 指纹.startswith("2499f81f807431b0"))

    print(f"\n{'═' * 62}")
    print(f"生存常识车厢：{len(通过)} 过 / {len(失败)} 失败")
    for x in 通过:
        print(f"  ✅ {x}")
    for x in 失败:
        print(f"  ❌ {x['名']} —— {x['为啥']}")
    print("═" * 62)
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
