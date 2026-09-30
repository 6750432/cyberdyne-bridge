#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M4·猎手（主动锁定）的离线回归。

为什么不用游戏实测来验：锁定这件事是**概率 + 时间 + 距离**三样东西拧在一起的，
在游戏里"打一场看看"永远说不清是哪一条没生效 —— 上一轮 M2 就吃过这个亏，
`反射层(m1, 说)` 只喂了 m1，配置**静默失效**，游戏里看着像"性格变了"。

这里用虚拟时钟（和 tools/回放.py 同一套办法）+ 手工造的状态帧，
把每一条规则单独拧出来验：该锁的锁、不该锁的不锁、该撒手的撒手、
配置真的被读到了、打完不后撤、叫停管用。

用法：
    python3 tools/测猎手.py
    python3 tools/测猎手.py -v      # 每条断言都打出来
退出码：0 = 全过；1 = 有失败。
"""
import argparse
import json
import math
import os
import sys
import time as _时间

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 虚拟时钟必须在 import bridge 之前装好（和 tools/回放.py 同一个套路）──
_虚拟 = [0.0]
_时间.time = lambda: _虚拟[0]

sys.path.insert(0, ROOT)
import bridge  # noqa: E402

CFG = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))

通过 = []
失败 = []
详细 = False


def 断言(名, 条件, 实际=None):
    行 = f"{'✅' if 条件 else '❌'} {名}" + (f"    实际：{实际}" if (实际 is not None and not 条件) else "")
    (通过 if 条件 else 失败).append(行)
    if 详细 or not 条件:
        print(行)


def 造帧(我=[0.0, 78.0, 0.0], 血=20.0, 食物=20, 猎物=None, 别的敌人=(),
         武器=(("iron_sword", 1),), 吃=(("cooked_beef", 16),), 朋友=(),
         对方血=None, 重生=False, 死数=0, 打我=None, 猎物敌对=True,
         卡住次数=0, 卡住多久=None, 有寻路=False):
    """造一帧状态。猎物 = (名字, 距离, 算不算敌人)，沿 +Z 方向摆。
    别的敌人 = ((名字, 距离), ...)，走 threats（游戏里就是僵尸那类）。"""
    players, threats, 我 = [], [], list(我)
    if 猎物:
        名, 距, 敌对 = 猎物
        players.append({"name": 名, "dist": float(距), "hostile": bool(敌对),
                        "pos": [我[0], 我[1], 我[2] + float(距)]})
        if 敌对 and 距 < CFG["m1"].get("threat_radius", 8):
            threats.append({"name": 名, "kind": "player", "dist": float(距),
                            "pos": [我[0], 我[1], 我[2] + float(距)]})
    for 名, 距 in 别的敌人:
        threats.append({"name": 名, "kind": "hostile", "dist": float(距),
                        "pos": [我[0] + float(距), 我[1], 我[2]]})
    threats.sort(key=lambda t: t["dist"])
    return {
        "type": "state", "connected": True, "t": _虚拟[0] * 1000,
        "pos": 我, "hp": float(血), "food": 食物, "onGround": True,
        "threats": threats, "players": players, "friends": list(朋友),
        "weapons": [{"name": n, "count": c} for n, c in 武器],
        "foods": [{"name": n, "count": c} for n, c in 吃],
        "drops": [], "plugins": {"pathfinder": 有寻路, "body": True},
        "watched": ({"mintstar": 对方血} if 对方血 is not None else None),
        "respawned": 重生, "acting": "idle", "held": "iron_sword",
        # M4：手那边报上来的两件事 —— 我死过几次、刚才是谁打我
        "deaths": 死数, "attacked_by": 打我,
        # M4b：手报的"卡住"两条事实
        "stuck_count": 卡住次数, "stuck_ms": 卡住多久,
        "stuck_dir": None,
        "near": [], "look": {"yaw": 0.0, "pitch": 0.0}, "msg": None,
    }


def 造反射(**调):
    """按 config 起一个反射层，允许临时改猎手参数。参数合并方式和主链一字不差。"""
    # 时钟归到 1000 秒再开跑：反射层的"掷骰冷却/锁定冷却"初值都是 0.0，
    # 从 0 秒起步的话第一拍会被冷却挡住（真实运行时时钟是 epoch 秒，不存在这问题）。
    _虚拟[0] = 1000.0
    m4 = dict(CFG["m4"])
    m4["hunt_enable"] = True      # 用例自带总开关：跑测试不受 config 里那个运行开关影响
    m4.update(调)
    说 = lambda *a, **k: None
    return bridge.反射层({**CFG["m1"], **CFG["m2"], **m4}, 说)


def 走(反射, 秒=0.2, **帧参数):
    """推进虚拟时钟并走一拍，返回 (决策, 发出去的命令)。"""
    _虚拟[0] += 秒
    帧 = 造帧(**帧参数)
    命令 = []
    决策 = 反射.决断(帧)
    反射.执行(决策, 命令.append)
    return 决策, 命令


def 撤到墙上(反射):
    """把上一拍欠的后撤步也走掉 —— 验"打完撤不撤"的时候要用。"""
    命令 = []
    反射.收尾(命令.append)
    return 命令


# ────────────────────────── 用例 ──────────────────────────
def 用例_配置真的接上了():
    反 = 造反射()
    断言("config 里的猎手参数确实进了反射层（防「静默失效」那类 bug）",
        反.m.get("hunt_chance") == CFG["m4"]["hunt_chance"]
         and 反.m.get("hunt_enable") is True and 反.m.get("hunt_step_ms") == 400,
         反.m.get("hunt_chance"))
    断言("m1 / m2 的老参数没被 m4 挤掉",
         反.m.get("counter_dist") == CFG["m2"]["counter_dist"]
         and 反.m.get("flee_dist") == CFG["m1"]["flee_dist"])


def 用例_该锁就锁():
    反 = 造反射(hunt_chance=1.0)
    决策, 命令 = 走(反, 猎物=("mintstar", 20.0, True))
    断言("20 格外掷中 → 决策是「追猎」", 决策[0] == 反.追猎, 决策[0])
    断言("追猎会真的发出 move 命令（疾跑）",
          bool(命令) and 命令[-1].get("cmd") == "move"
         and 命令[-1].get("sprint") is True, 命令)
    断言("锁定目标记下来了", 反.锁定目标 == "mintstar")
    断言("在追猎() 对外返回真（节拍器靠它切快档）", 反.在追猎() is True)
    断言("追击计数 +1（实测要看「它主动来了几次」）", 反.追击次数 == 1)
    方向 = 命令[-1]["dir"]
    断言("方向指向猎物（+Z）", abs(方向[0]) < 0.01 and 方向[1] > 0.99, 方向)
    断言("步长用的是配置里的 hunt_step_ms",
          int(命令[-1]["ms"]) == int(CFG["m4"]["hunt_step_ms"]), 命令[-1]["ms"])


def 用例_概率零就永不锁():
    反 = 造反射(hunt_chance=0.0)
    for _ in range(40):
        决策, _ = 走(反, 秒=0.3, 猎物=("mintstar", 20.0, True))
    断言("hunt_chance=0 → 40 拍一次都不锁", 反.锁定目标 is None and 反.追击次数 == 0,
         反.锁定目标)


def 用例_概率一就立刻锁():
    反 = 造反射(hunt_chance=1.0)
    决策, _ = 走(反, 猎物=("mintstar", 20.0, True))
    断言("hunt_chance=1 → 第一拍就锁", 反.锁定目标 == "mintstar")


def 用例_名单和距离():
    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 20.0, False))
    断言("players[].hostile=false 的玩家不锁（名单解释权在手的）", 反.锁定目标 is None)

    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 30.0, True))
    断言("30 格 > hunt_range(26) → 不锁", 反.锁定目标 is None)
    走(反, 猎物=("mintstar", 24.0, True))
    断言("走进 24 格 → 锁上", 反.锁定目标 == "mintstar")

    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 20.0, True), 朋友=("mintstar",))
    断言("朋友名单里的人不锁（即使 players 说他是敌人）", 反.锁定目标 is None)


def 用例_四个前提():
    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 20.0, True), 武器=())
    断言("空手不主动挑事", 反.锁定目标 is None)

    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 20.0, True), 血=12.0)
    断言("血 12 < hunt_hp_min(13) 不挑事", 反.锁定目标 is None)

    反 = 造反射(hunt_chance=1.0)
    决策, _ = 走(反, 猎物=("mintstar", 20.0, True), 别的敌人=(("zombie", 3.0),))
    断言("旁边有僵尸贴脸 → 先打眼前的，不开新战场", 反.锁定目标 is None)

    反 = 造反射(hunt_chance=1.0)
    决策, _ = 走(反, 猎物=("mintstar", 20.0, True), 血=9.0, 吃=(("cooked_beef", 2),))
    断言("血低于该吃线而且背包有吃的 → 先吃饭不追", 反.锁定目标 is None)


def 用例_进打击圈交给反击():
    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 3.4, True))          # 先锁上（3.4 在锁范围内）
    断言("3.4 格时先锁上并压过去", 反.锁定目标 == "mintstar")
    决策, _ = 走(反, 秒=0.2, 猎物=("mintstar", 2.0, True))
    断言("进 2.2 格打击圈 → 交给原来的「反击」分支", 决策[0] == 反.反击, 决策[0])
    断言("交了手也还记着在追谁（下次贴脸不用重新锁）", 反.锁定目标 == "mintstar")


def 用例_打完不后撤():
    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 3.4, True))
    决策, 命令 = 走(反, 秒=0.2, 猎物=("mintstar", 2.0, True))
    断言("追猎期间挥完不欠后撤步（hunt_press=true）", 反.待后撤 is None, 反.待后撤)
    断言("贴身这段时间才是真的打起来了，不是打完就溜", 命令[-1]["cmd"] in ("attack", "jumpattack"),
         命令)

    反 = 造反射(hunt_chance=0.0, hunt_press=False)     # 完全不锁 = 退回 M2
    _虚拟[0] += 30
    决策, 命令 = 走(反, 秒=0.2, 猎物=("mintstar", 2.0, True))
    断言("不锁定（M2 老样子）时照样「打一下就跑」", 反.待后撤 is not None, 反.待后撤)


def 用例_疼了就撒手():
    # 同样：这是"非死斗"的性格（打不过就跑）
    反 = 造反射(hunt_chance=1.0, hunt_until_death=False)
    走(反, 猎物=("mintstar", 6.0, True))
    断言("6 格外锁上并追", 反.锁定目标 == "mintstar")
    决策, _ = 走(反, 秒=0.2, 血=8.0, 猎物=("mintstar", 6.0, True))
    断言("血掉到 hunt_abort_hp(9) 以下 → 立刻撒手", 反.锁定目标 is None)
    断言("撒手之后状态回到「平静」交给后面的分支", 反.状态 in (反.平静, 反.逃跑), 反.状态)

    决策, _ = 走(反, 秒=0.2, 血=11.0, 猎物=("mintstar", 3.0, True))
    断言("贴脸而血不够还手（<=counter_hp_min 12）也不硬碰", 反.锁定目标 is None)
    断言("这种情况让原来的逃跑/迎战分支接手", 决策[0] != 反.追猎, 决策[0])


def 用例_追不上就放弃():
    # 这一组验的是"非死斗"的老规矩（hunt_until_death=false）——
    # 死斗开着的时候这些撤手条件全部不生效，见 用例_死斗_*。
    反 = 造反射(hunt_chance=1.0, hunt_until_death=False, hunt_giveup_dist=34, hunt_giveup_ms=3500)
    走(反, 猎物=("mintstar", 20.0, True))
    走(反, 秒=1.0, 猎物=("mintstar", 40.0, True))
    断言("刚超距 1 秒还不放弃（隔一堵墙不算追不上）", 反.锁定目标 == "mintstar")
    # 放弃起点是"第一次发现超距"那一刻，所以还要再走满 hunt_giveup_ms 才撒手
    for _ in range(4):
        走(反, 秒=1.0, 猎物=("mintstar", 40.0, True))
    断言("持续超距 3.5 秒以上 → 放弃", 反.锁定目标 is None)
    走(反, 秒=1.0, 猎物=("mintstar", 20.0, True))
    断言("放弃后进冷却（15 秒内不再锁）", 反.锁定目标 is None)
    for _ in range(20):
        走(反, 秒=1.0, 猎物=("mintstar", 20.0, True))
    断言("冷却过后重新掷中 → 又追上来", 反.锁定目标 == "mintstar" and 反.追击次数 == 2,
         (反.锁定目标, 反.追击次数))


def 用例_追太久收工():
    反 = 造反射(hunt_chance=1.0, hunt_until_death=False, hunt_max_ms=10000)
    走(反, 猎物=("mintstar", 20.0, True))
    for _ in range(60):
        走(反, 秒=0.2, 猎物=("mintstar", 20.0, True))
    断言("一次追击封顶 hunt_max_ms，到点收工", 反.锁定目标 is None)


def 用例_目标没了():
    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 20.0, True))
    决策, _ = 走(反, 秒=0.2, 猎物=None)      # 下线 / 死了 → players 里就没有了
    断言("目标从玩家表里消失 → 撒手（不会追着空气跑）", 反.锁定目标 is None)


def 用例_死斗_不死不休():
    """主人 2026-10-01 的要求：触发之后一直打，追着打，直到目标死或自己死。"""
    反 = 造反射(hunt_chance=1.0)          # config 里 hunt_until_death=true
    走(反, 猎物=("mintstar", 20.0, True))
    断言("死斗默认开着（config 里 hunt_until_death=true）", 反._死斗() is True)

    # ① 追到 40 格外也不放弃
    for _ in range(6):
        走(反, 秒=1.0, 猎物=("mintstar", 40.0, True))
    断言("死斗：追到 40 格还接着追（不再有 hunt_giveup_dist 这条）", 反.锁定目标 == "mintstar")

    # ② 追过 hunt_max_ms 也不收工
    for _ in range(40):
        走(反, 秒=1.0, 猎物=("mintstar", 40.0, True))
    断言("死斗：追满 45 秒也不收工（hunt_max_ms 这条失效）", 反.锁定目标 == "mintstar")

    # ③ 自己只剩 3 点血也不撒手
    决策, _ = 走(反, 秒=0.2, 血=3.0, 猎物=("mintstar", 18.0, True))
    断言("死斗：血 3/20 还在追（hunt_abort_hp 这条失效）", 决策[0] == 反.追猎, 决策[0])

    # ④ 近身血少也不交回逃跑分支，而是接着打
    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 3.4, True))
    决策, _ = 走(反, 秒=0.2, 血=5.0, 猎物=("mintstar", 2.0, True))
    断言("死斗：贴脸时血只有 5 也照样挥拳（不再退给逃跑分支）",
         决策[0] == 反.反击, 决策[0])

    # ⑤ 自己死了才算完
    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 20.0, True))
    走(反, 秒=0.2, 血=0.0, 猎物=("mintstar", 20.0, True))
    断言("死斗：自己血 0 → 收手", 反.锁定目标 is None)
    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 20.0, True))
    走(反, 秒=0.2, 死数=1, 猎物=("mintstar", 20.0, True))
    断言("死斗：死亡计数 +1（重生后血回满）也会收手", 反.锁定目标 is None)
    走(反, 秒=0.2, 血=20.0, 重生=True, 猎物=("mintstar", 20.0, True))
    断言("死斗：刚重生（respawned 那个 15 秒窗口）不会再立刻粘上去",
         反.锁定目标 is None)

    # ⑥ 目标死了才算完
    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 20.0, True))
    走(反, 秒=0.2, 对方血=0.0, 猎物=None)
    断言("死斗：目标倒下 → 收手（这才是唯一该收手的时候）", 反.锁定目标 is None)


def 用例_被打就应战():
    """主人 2026-10-01：「我打它它就直接降级成（老样子）」——
    被人先动手时不该退回 M2 的「打一下就跑」，要立刻锁、立刻死斗。"""
    # ① 概率关到 0 也照样应战（说明这条路根本不掷骰子）
    反 = 造反射(hunt_chance=0.0)
    决策, 命令 = 走(反, 猎物=("mintstar", 3.0, True), 打我="mintstar")
    断言("被打 → 立刻锁（hunt_chance=0 也锁得上）", 反.锁定目标 == "mintstar")
    断言("被打应战的那一刻就压上去", 决策[0] == 反.追猎, 决策[0])

    # ② 刚结束一次追击、还在冷却里，也一样立刻应战
    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 20.0, True))
    反.放掉追击("测试")
    走(反, 秒=0.5, 猎物=("mintstar", 6.0, True))          # 冷却中：不锁
    断言("冷却期间不会主动挑事", 反.锁定目标 is None)
    走(反, 秒=0.5, 猎物=("mintstar", 6.0, True), 打我="mintstar")
    断言("但我打它 → 冷却也挡不住，立刻应战", 反.锁定目标 == "mintstar")

    # ③ 名单解释权在手那边：不是敌人就不算"被打"
    反 = 造反射(hunt_chance=0.0)
    走(反, 猎物=("mintstar", 3.0, False), 打我="mintstar")
    断言("打我的人不在敌对名单里（hostile=false）→ 不应战", 反.锁定目标 is None)

    反 = 造反射(hunt_chance=0.0)
    走(反, 猎物=None, 打我="Stranger")
    断言("打我的人根本不在 players[] 里 → 不应战（不追空气）", 反.锁定目标 is None)

    # ④ 空手时被打：还是先跑（空手打架 = 送）
    反 = 造反射(hunt_chance=0.0)
    走(反, 猎物=("mintstar", 3.0, True), 武器=(), 打我="mintstar")
    断言("空手时被打不应战（先保命，装备齐了才谈死斗）", 反.锁定目标 is None)

    # ⑤ 锁着的时候被打，目标不变、话也不重复说
    反 = 造反射(hunt_chance=0.0)
    走(反, 猎物=("mintstar", 20.0, True), 打我="mintstar")
    次数 = 反.追击次数
    走(反, 秒=0.2, 猎物=("mintstar", 18.0, True), 打我="mintstar")
    断言("已经在追了就不会重复锁（追击计数不涨）", 反.追击次数 == 次数)



    """可连击：锁定期间两次挥击之间只等 hunt_combo_ms。"""
    反 = 造反射(hunt_chance=1.0, hunt_combo_ms=650, counter_cooldown_ms=1400)
    断言("没锁定时用老冷却 counter_cooldown_ms",
         abs(反._攻击冷却() - 1.4) < 1e-6, 反._攻击冷却())
    走(反, 猎物=("mintstar", 3.4, True))
    断言("锁定期间用 hunt_combo_ms（连击）",
         abs(反._攻击冷却() - 0.65) < 1e-6, 反._攻击冷却())

    挥 = 0
    for i in range(12):                    # 12 拍 × 0.2 秒 = 2.4 秒
        决策, 命令 = 走(反, 秒=0.2, 猎物=("mintstar", 2.0, True), 对方血=20.0)
        if 命令 and 命令[-1].get("cmd") in ("attack", "jumpattack"):
            挥 += 1
    断言("死斗 2.4 秒里挥了 3~4 下（≈650ms 一下，且快过这个数没意义）", 3 <= 挥 <= 4, 挥)




def 用例_绕路():
    """M4b：直线追不动了要会绕（有插件交给插件；没插件沿墙滑）。"""
    # ① 有插件 + 卡住 → 下发 goto，把方向盘交出去
    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 18.0, True))
    决策, 命令 = 走(反, 秒=0.2, 猎物=("mintstar", 18.0, True),
                   卡住次数=1, 卡住多久=300, 有寻路=True)
    断言("卡住 + 有寻路插件 → 决策是「绕路」", 决策[0] == 反.绕路, 决策[0])
    断言("绕路会把 goto 发下去（带目标坐标）",
         bool(命令) and 命令[-1].get("act") == "goto" and len(命令[-1].get("p", [])) == 3, 命令)

    # ② 插件走的时候，脑不抢方向盘（这一拍不下命令）
    决策, 命令 = 走(反, 秒=0.3, 猎物=("mintstar", 18.0, True),
                   卡住次数=1, 卡住多久=300, 有寻路=True)
    断言("插件正在走 → 这一拍不下命令（不跟它抢方向盘）", 命令 == [], 命令)

    # ③ 没插件 → 沿墙滑：方向相对"朝目标"转了约 detour_angle 度
    反2 = 造反射(hunt_chance=1.0, detour_angle=70)
    走(反2, 猎物=("mintstar", 18.0, True))
    决策, 命令 = 走(反2, 秒=0.2, 猎物=("mintstar", 18.0, True),
                   卡住次数=1, 卡住多久=300, 有寻路=False)
    断言("卡住 + 没插件 → 还是「追猎」，但方向被转开了", 决策[0] == 反2.追猎, 决策[0])
    if 命令:
        dx, dz = 命令[-1]["dir"]
        # 造帧里猎物摆在 +Z 方向（方位角 90°），所以量的是"和朝目标方向的夹角"
        直线 = math.degrees(math.atan2(1.0, 0.0))
        角 = abs(math.degrees(math.atan2(dz, dx)) - 直线) % 360
        角 = min(角, 360 - 角)
        断言("沿墙滑的角度 ≈ detour_angle(70°)", 60 <= 角 <= 80, round(角, 1))

    # ④ 再卡一次 → 翻到另一边
    反3 = 造反射(hunt_chance=1.0)
    走(反3, 猎物=("mintstar", 18.0, True))
    走(反3, 秒=0.2, 猎物=("mintstar", 18.0, True), 卡住次数=1, 卡住多久=300)
    一 = 反3.绕向
    走(反3, 秒=0.2, 猎物=("mintstar", 18.0, True), 卡住次数=2, 卡住多久=300)
    断言("连着卡住会翻面绕（左右换边）", 反3.绕向 == -一, (一, 反3.绕向))

    # ⑤ 不卡了 → 忘掉绕行姿势，回到直线
    决策, 命令 = 走(反3, 秒=0.2, 猎物=("mintstar", 18.0, True),
                   卡住次数=2, 卡住多久=9000)
    断言("卡住信号过期（9 秒没再卡）→ 绕行姿势清掉", 反3.绕角度 == 0.0, 反3.绕角度)

    # ⑥ 总开关关掉 → 撞墙也走直线
    反4 = 造反射(hunt_chance=1.0, detour_enable=False, detour_angle=70)
    走(反4, 猎物=("mintstar", 18.0, True))
    决策, 命令 = 走(反4, 秒=0.2, 猎物=("mintstar", 18.0, True),
                   卡住次数=1, 卡住多久=300, 有寻路=True)
    断言("detour_enable=false → 不绕路，退回纯直线",
         决策[0] == 反4.追猎 and 命令 and "act" not in 命令[-1], (决策[0], 命令))

    # ⑦ 进了打击圈就不绕了（别"绕得开心、一拳不挥"）
    反5 = 造反射(hunt_chance=1.0)
    走(反5, 猎物=("mintstar", 3.4, True))
    决策, 命令 = 走(反5, 秒=0.2, 猎物=("mintstar", 2.0, True),
                   卡住次数=1, 卡住多久=300, 有寻路=True)
    断言("已经在打击圈里 → 不绕，交给挥拳", 决策[0] != 反5.绕路, 决策[0])


def 用例_叫停():
    反 = 造反射(hunt_chance=1.0)
    走(反, 猎物=("mintstar", 20.0, True))
    好 = 反.放掉追击("主人叫停")
    断言("指令层说「停」能立刻掐掉追击", 好 is True and 反.锁定目标 is None)
    断言("叫停之后 15 秒冷却同样生效",
         (走(反, 秒=1.0, 猎物=("mintstar", 20.0, True)), 反.锁定目标 is None)[1])


def 用例_追猎强制快档():
    反 = 造反射(hunt_chance=1.0)
    节拍 = bridge.节拍器(CFG["m2"], lambda *a, **k: None)
    节拍.外部要快 = 反.在追猎
    帧 = 造帧(猎物=("mintstar", 20.0, True))
    _虚拟[0] += 60            # 让"平静档"的判定彻底过期
    断言("没追猎时是慢档", abs(节拍.想要(帧) - 节拍.慢) < 1e-6, 节拍.想要(帧))
    走(反, 猎物=("mintstar", 20.0, True))
    断言("追猎期间强制快档", abs(节拍.想要(帧) - 节拍.快) < 1e-6, 节拍.想要(帧))


def 用例_开关和确定性():
    反 = 造反射(hunt_enable=False, hunt_chance=1.0)
    走(反, 猎物=("mintstar", 20.0, True))
    断言("hunt_enable=false → 整个猎手不参与（退化成 M2.1）", 反.锁定目标 is None)

    # 同一颗随机种子 + 同一串帧 → 同一串决定。回放基准靠这条活着。
    序列 = []
    for _ in range(2):
        _虚拟[0] = 1000.0
        反 = 造反射(hunt_chance=0.5)
        一次 = []
        for i in range(12):
            决策, _ = 走(反, 秒=3.0, 猎物=("mintstar", 20.0, True))
            一次.append(决策[0])
        序列.append(一次)
    断言("固定种子 → 两遍跑出来一模一样（回放基准不会被随机打乱）", 序列[0] == 序列[1],
         序列)


def main():
    global 详细
    p = argparse.ArgumentParser()
    p.add_argument("-v", "--详细", action="store_true")
    a = p.parse_args()
    详细 = a.详细

    for 函数 in list(globals().values()):
        if callable(函数) and getattr(函数, "__name__", "").startswith("用例_"):
            函数()

    print(f"\n通过 {len(通过)} 条，失败 {len(失败)} 条。")
    if 失败:
        print("\n失败明细：")
        for 行 in 失败:
            print("  " + 行)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
