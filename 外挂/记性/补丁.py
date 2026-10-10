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
import sys
import time

# ⚠ 三层 dirname ✗ —— 我第一版只写了两层，账本落到 `外挂/logs/记性.json` 去了 ✗
#   （实机 15:12 记下了，可 `logs/记性.json` 是空的 ✓ 一查就露馅 ✓）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
账本路径 = os.path.join(ROOT, "logs", "记性.json")
上限 = 64

_原 = {}
_最近状态 = [None]
_待接手 = [None]        # (品, 计划) —— 空状态不交 ✗ 等一帧真状态到手再交 ✓      # ★ 最近一帧真状态 ✓ 接手任务**必须**用它 ✗（空状态接不住 ✓）
_原下发 = {}
# ★ 甲/乙 用的小本子（2026-10-09）：拾/goto 的节流 + 上次发过的坐标 ✓
_拾过 = {}
# ★★★ 2026-10-09：**任务栈自己发的那一镐 craft 要放行** ✓
#   现场：接线闸把「光杆 craft」改成任务 ✗ —— 可**任务栈派下来的 craft 长得一模一样** ✓
#   ⇒ 闸门把自己人的命令也拦了 ✗ ⇒ 又拆一次任务 ⇒ 又拦 ⇒ **自己拦自己** ✓
#   ⇒ 手侧一条 craft 都收不到 ✓（主人看到的「回执丢了：craft 8 秒没回音」✓）
_放行合成 = [False]
# ★ 拾的"空手喊话"限流（不许每拍刷屏 ✗ —— 但**必须喊** ✓ 不然就是静默 ✗）
_拾空喊过 = {"t": 0.0}
# ★ 换树种那次喊话的限流（2026-10-10 半夜：计划要挖 birch_log，那一格却是 oak_log ✓）
_换树说过 = {"t": 0.0}
# ★ 「要跑合成工作台时报一句」的限流（2026-10-10：有台子却又要重做一个 ✗）
_台子说过 = {"t": 0.0}
# ★ 「合成前补料」的限流（2026-10-10：石镐要 3 块圆石，可计划里只挖一镐 ✗）
_补料说过 = {"t": 0.0}
# ★ 挖账那两句的限流（挖过跳过 / 挖了没多出东西 ✓）
_挖账说过 = {"t": 0.0, "t2": 0.0, "t3": 0.0, "t4": 0.0}
# ★ "允许挖脚下"这面旗子（本拍立、下一拍那条 dig 用掉就摘 ✓）
_允许脚下 = [False]
_原发3 = {}
_原发 = {}
_原看完了 = {}
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


挖过路径 = os.path.join(ROOT, "logs", "挖过.json")
_挖过 = {}          # "x,y,z" -> 挖掉的时刻 ✓（主人要求①：挖矿前先问这个 ✓）


def _挖键(位):
    try:
        return "%d,%d,%d" % (int(float(位[0]) // 1), int(float(位[1]) // 1),
                            int(float(位[2]) // 1))
    except Exception:
        return None


def 挖过吗(位):
    """这个坐标**挖过吗** ✓ —— 主人 2026-10-10 的原话：
    「**1. 挖矿前先读账本：询问「记性」："这个坐标被我挖过吗？"如果挖过，跳过。**」✓

    ★ 为什么非要它：同一个坐标被计划挖第二次 = 挖空气 ✗（挖空守卫早就在喊"陈坐标"✓）
      可那是**事后**拦 ✗ —— 事前就该跳过 ✓（省一趟空活 + 省一次失败重试 ✓）
    """
    键 = _挖键(位)
    return bool(键 and 键 in _挖过)


def 记挖过(位):
    """记下"这一格我挖掉了" ✓（落盘 ✓ 脑重启也不丢 ✓）"""
    键 = _挖键(位)
    if not 键:
        return False
    _挖过[键] = time.time()
    if len(_挖过) > 4000:                      # 别涨成内存洞 ✗（丢最老的那批 ✓）
        for k in sorted(_挖过, key=lambda x: _挖过[x])[:1000]:
            _挖过.pop(k, None)
    _写挖过盘()
    return True


def _写挖过盘():
    try:
        with open(挖过路径, "w", encoding="utf-8") as f:
            json.dump(_挖过, f, ensure_ascii=False)
    except Exception as e:
        _说(f"[记性·挖账] 落盘出岔子（{type(e).__name__}: {e}）✗ 出声 ✓")


def _读挖过盘():
    try:
        with open(挖过路径, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict):
            for k, v in d.items():
                try:
                    _挖过[str(k)] = float(v)
                except Exception:
                    continue
        _说(f"[记性·挖账] 读回 {len(_挖过)} 个挖过的格子 ✓（重启不丢 ✓）")
    except Exception:
        pass


_预热过 = [False]


def 预热(状态):
    """★ 主人要求③（2026-10-10）：「**重启预热：监工拉起脑的时候，必须先拉取一份
    「过去 5 分钟的方块变化记录」，而不是直接空白开局**」✓

    手侧现在会在状态帧里带 `变了`（过去 5 分钟里**消失**的方块 ✓ 见 node/server.js ✓）。
    脑一开机就把它读进来 ✓ 做两件事：
      ① 那些格子统统记进「挖过账」✓ ⇒ **不会再去挖空气** ✓（要求①的账这下开局就是满的 ✓）
      ② 出声报一句「读回几格」✓ ⇒ 主人看得见它不是空白开局 ✓

    ⚠ 只认**手真报回来的** ✓ —— 没拿到就**下一拍再看** ✓（绝不自己编一段历史 ✗）
    """
    global _预热过
    if _预热过[0] or not isinstance(状态, dict):
        return 0
    变 = 状态.get("变了")
    if not isinstance(变, list):
        扫 = (状态.get("scan") or {})
        变 = 扫.get("变了") if isinstance(扫, dict) else None
    if not isinstance(变, list) or not 变:
        return 0                      # 还没有 ⇒ 下一拍再看 ✓（别当成"没有变化"✗）
    _预热过[0] = True
    n = 0
    for x in 变:
        try:
            p = (x or {}).get("p")
            if isinstance(p, (list, tuple)) and len(p) >= 3 and 记挖过(p):
                n += 1
        except Exception:
            continue
    _说(f"[记性·预热] 开局读回**过去 5 分钟里消失的 {n} 格** ✓ ⇒ 全记进挖过账 ✓"
        f"（这些格子**不会再挖一遍** ✓ 不是空白开局 ✓ 主人要求③ ✓）")
    return n


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


def 忘记(方块名):
    """把账上这一条**删掉** ✓ 返回 True/False ✓

    ★★★ 2026-10-09 深夜（主人：「他是不是做出来了？！」那一场）：
      现场：账上记着工作台在 `[2341,63,2249]` ✓ 可它**实际不在那儿了** ✗
        ⇒ 计划被换成「走过去用账上那个」✗ ⇒ 走到那儿**啥也没有** ✗
        ⇒ 手报「合成 stone_pickaxe 要工作台，可我 32 格内都没找到」✗
        ⇒ 又开始重做一遍计划 → 又走回那个空地方 → **死循环** ✓
      规矩：**错账必须能忘** ✗ —— 记忆是资产 ✓ 但**验不过的记忆是包袱** ✗
        （跟「记忆体力上限 200 格」同一条思路 ✓：记忆得能被现实否掉 ✓）
      ⚠ 忘掉要**出声** ✓（主人得看得见"它为什么不再去那本子上记的地方了"✓）
    """
    名 = str(方块名)
    try:
        if 名 in _账:
            旧 = _账.pop(名)
            _写盘()
            _说(f"[记性·忘] 账上「{名}」@{list((旧 or {}).get('p') or [])} "
                f"这条**删了** ✓ —— 现实说那儿没有 ✓（不能拿错账接着坑自己 ✗）")
            return True
        _说(f"[记性·忘] 账上本来就没有「{名}」（不用删 ✓）")
        return False
    except Exception as e:
        _说(f"[记性·忘] 删账出岔子（{type(e).__name__}: {e}）⇒ 出声 ✗ 不静默 ✓")
        return False


def _有原木(状态, 族, 任=None):
    """手里（或这一趟计划要挖的）有没有这个族的木头 → True/False ✓

    ★ 2026-10-10 主人：「不同树种的木板也能合成工作台跟木棍和木镐」✓
      所以判据是**我到底拿得到哪种木头** ✓ —— 不是"计划里写的是哪种" ✗
    """
    想要 = {f"{族}_log", f"{族}_stem", f"{族}_wood", f"{族}_hyphae"}
    try:
        背包 = dict(((状态 or {}).get("items") or {}))
    except Exception:
        背包 = {}
    for 名 in 想要:
        try:
            if float(背包.get(名) or 0) >= 1:
                return True
        except Exception:
            continue
    # 这一趟计划里本来就有一镐是挖这种木头的 ⇒ 也算"拿得到" ✓
    for 步 in list((任 or {}).get("步骤") or []):
        try:
            if isinstance(步, dict) and 步.get("动作") == "挖" \
                    and str(步.get("方块") or 步.get("目标方块") or "") in 想要:
                return True
        except Exception:
            continue
    return False


def _能做的木板(状态, 任=None):
    """我**真能做出**哪种木板 → 名字或 None ✓（拿不到原木的一律不算 ✗）

    ⚠ 顺序：先看手里现成的木板 ✓（已经有了就不用再做 ✓），再看有哪种原木 ✓
    """
    候选 = ("oak", "birch", "spruce", "jungle", "acacia", "dark_oak",
           "mangrove", "cherry", "pale_oak", "bamboo", "crimson", "warped")
    try:
        背包 = dict(((状态 or {}).get("items") or {}))
    except Exception:
        背包 = {}
    for b in 候选:
        try:
            if float(背包.get(f"{b}_planks") or 0) >= 1:
                return f"{b}_planks"
        except Exception:
            continue
    for b in 候选:
        if _有原木(状态, b, 任):
            return f"{b}_planks"
    return None


def _那格是什么(状态, 位):
    """状态帧里**那一格**是什么方块 → 名字或 None ✓（只读读数 ✓ 不猜 ✗）

    ★ 2026-10-10 半夜：计划要挖 `birch_log` ✗ 可那一格雷达读到的是 `oak_log` ✓
      手侧一共三处会报方块：`blocks`（雷达盯的那几格 ✓）、`scan.可交互`、`scan.找` ✓
      按坐标认领 ✓ 认不到就返回 None ✓（**绝不编一个名字** ✗ —— 编了就是静默骗自己 ✓）
    """
    try:
        if not (isinstance(位, (list, tuple)) and len(位) >= 3):
            return None
        键 = (int(float(位[0]) // 1), int(float(位[1]) // 1), int(float(位[2]) // 1))
    except Exception:
        return None
    扫 = (状态 or {}).get("scan") or {}
    堆 = list((状态 or {}).get("blocks") or [])
    for 名 in ("可交互", "找", "方块"):
        v = 扫.get(名)
        if isinstance(v, list):
            堆 += [x for x in v if isinstance(x, dict)]
    for 条 in 堆:
        try:
            q = 条.get("p")
            if not (isinstance(q, (list, tuple)) and len(q) >= 3):
                continue
            if (int(float(q[0]) // 1), int(float(q[1]) // 1), int(float(q[2]) // 1)) == 键:
                名 = str(条.get("name") or "")
                if 名:
                    return 名
        except Exception:
            continue
    return None


def _找生存常识():
    """★ 改成**查「车厢能力」册子** ✓ —— 不再手写"哪个车厢有哪个函数" ✗

    主人 2026-10-09 晚上的原话：
      「我什么东西都写得大差不差了，是不是你在给我重复造轮子啊？
        **他脑子都不思考一下每个车厢能干啥然后自己去调用吗？自动化啊**」

    我原来这一小块是**手写的** ✗：
      `sys.modules.get("车厢_生存常识_入口")` —— 名字写死 ✓ 换一节车厢就不认了 ✓
      更糟的是：**手接一次没事 ✓ 手接两次开始抄 ✓ 手接三次必抄第二遍** ✗
      （今晚我就抄了三遍 ✓ 而每一样**主人都早就写好了** ✓）

    ⇒ 现在只做一件事：**问册子**「谁会 `安排一趟挖到`」✓
      册子自己扫已经挂上车的车厢 ✓ 谁有就谁用 ✓ 要不到就**出声** ✗ 绝不自己造 ✓
    """
    try:
        import os as _o, sys as _s
        厢 = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
        if 厢 not in _s.path:
            _s.path.insert(0, 厢)
        import 车厢能力
        return 车厢能力.要("安排一趟挖到", 出声=lambda 文: _说(文))
    except Exception as e:
        _说(f"[记性] ✗ 车厢能力册子打不开（{type(e).__name__}: {e}）"
            f" ⇒ 这趟路**不敢自己乱挖** ✓（主人点过：别抄第二遍 ✗）")
        return None


def 铺路向下(我y, 目标, 状态=None):
    """★ 下不去的「走到」⇒ **交回唯一那一份实现** ✓（`生存常识.安排一趟挖到` ✓）

    ★★★ 主人在 2026-10-09 晚上**连点我三次**，这是第三次，也是最狠的一次：
        「另外，我教的黄金模型挖矿法怎么不用」
        「等等，我发现问题了，他**只读坐标**来确认能不能过去，怎么？**雷达是摆设吗？**」
      我犯的错（三件事其实是同一件）：
        ① 自己写了一套「挖脚下直着往下」的**竖井** ✗ —— 主人的模型是
           **1 宽 / 2 高 / 45° 斜巷** ✓（`常识库/通道骨架.json` ✓）
        ② 判断「能不能过去」时**瞎猜了一个字典形状** ✗（`看到.get("x,y,z")` ✓）
           真实的状态帧里根本没有那个键 ⇒ 永远返回 None ⇒ **雷达等于没读** ✓
        ③ 而 `生存常识.安排一趟挖到()` **早就把这件事做完了** ✓
           它的注释原话：「**只做这一份实现 ✓ 谁要谁调 ✓ 别抄第二遍**
                          —— 抄第二遍就一定会漏一处 ✓」
           还写着「**一格下一格** ✓ 45° 阶梯 ✓ **直下会把自己埋进竖井** ✗」
           以及那条硬推论：「**横向步数必须 ≥ 落差** ✗」

    ⇒ 现在这里**只做一件事**：把目标交给那一份实现 ✓ 拿回它排的步 ✓
      摸不到那节车厢 ⇒ **什么都不做**（不动计划 ✓）并**出声** ✗
        —— 让物理体检去拦（它会说清"落差多少、会摔伤"✓）
           这比我自作聪明再挖一条竖井强得多 ✓
    """
def 铺路向下(我y, 目标, 状态=None):
    """★ 下不去的「走到」⇒ 写一个**通用的「调」步骤** ✓（谁有那本事谁干 ✓）

    主人 2026-10-09 晚上问的原话：
      「？还是卡？**没给他调用车厢工具的能力吗**」

    他说对了 ✓ —— 原来这块是我在**计划期**手接一次（`_找生存常识()` ✗）：
      · 计划里根本不出现"我要用某节车厢"这件事 ✗
      · 换一节车厢、换一个本事，就得再手接一次 ✗（＝抄第二遍的起点 ✓）
    ⇒ 现在改成**计划里写一句话** ✓：
        {"动作": "调", "要": "安排一趟挖到", "p": [x, Y, z]}
      由执行期（`_下发`）去**册子里查**谁有这本事 ✓ 查到就让它排路 ✓
      排好的步**就地插进计划** ✓ 查不到 ⇒ **出声且什么都不做** ✗
    —— 这就是"**给他调用车厢工具的能力**" ✓ 任何一节车厢的本事都能这样点名 ✓
    """
    x, Y, z = 目标[0], 目标[1], 目标[2]
    if int(我y) - int(Y) <= 3:
        # ★★★ 2026-10-09：**这里是"不用铺路"，不是失败** ✓ ——
        #   从前返回裸 `None` ✗ → 上面 `路, 为啥 = 铺路向下(...)` 一解包就炸 ✓
        #   主人截图里的「cannot unpack non-iterable NoneType object」就是它 ✓
        #   规矩：**返回形状永远是 2 元组** ✓（调用方要能不加判断地解 ✓）
        return None, "落差在 3 格以内，不用铺路 ✓"
    return ([{"动作": "走到", "p": [x, int(我y), z], "到点": 3.0},
             {"动作": "调", "要": "安排一趟挖到", "p": [x, int(Y), z]}],
            f"下不去 {[x, int(Y), z]}（落差 {int(我y) - int(Y)} 格 ✗ 会摔伤 ✓）"
            f"⇒ 写一个**「调」步骤**交给车厢册子 ✓（谁有「安排一趟挖到」谁就干 ✓"
            f" 我**不自己挖** ✗ —— 主人问过：「没给他调用车厢工具的能力吗」✓）")


def _光杆craft要拆料(命令):
    """命令是 `craft X` 且**拆得出 >1 步** ⇒ 返回 (X, 求解器的计划) ✓ 否则 None ✓

    ★★★ 2026-10-09 主人：「**又挖了一个白桦木又发呆了**」那一晚查出来的第二个病 ✓
      现场：重排时喂给求解器的是 **`背包={}` + 根本没有方块表** ✗
        ⇒ 它以为这世上什么都没有 ✓ ⇒ 于是
          · 按配方默认挑一种木头（实机挑过 `acacia_log` ✓ 可那片林子只有橡木/白桦 ✗）
          · 或者给一个**埋在地下、谁也看不见**的落点 ✗（实机：stone ✓
            → 手挖上来的是 dirt ✓ → 接着「拾 cobblestone」**0 秒"过"** ✓
            → 再「合成 stone_pickaxe」空转 ✓ → 整条链白跑 ✓）
      规矩：**重排必须用"我现在这一帧的真情报"** ✓
        · 背包：`_最近状态[0]["items"]` ✓（手侧每拍都报 ✓）
        · 方块表：`生存常识.可用方块(状态)` ✓ —— **同一处实现** ✓
          它已经把「整个被埋住」的踢掉了 ✓（反矿透那条红线 ✓）我绝不自己再算一遍 ✗
      ⚠ 拿不到状态就**照旧**（fail-open ✓）：宁可像以前那样按空背包重排一次 ✓
        也不要因为拿不到读数就什么都不做 ✗
    """
    if not (isinstance(命令, dict) and 命令.get("cmd") == "craft" and 命令.get("item")):
        return None
    品 = str(命令["item"])
    求 = _求解器()
    if 求 is None:
        return None
    背, 表 = {}, None
    try:
        s = _最近状态[0]
        if isinstance(s, dict) and s:
            背 = dict(s.get("items") or {})
            常 = _找生存常识()
            if 常 is not None and callable(getattr(常, "可用方块", None)):
                表 = 常.可用方块(s)
                _说(f"[记性·目标] 重排用**这一帧的真情报** ✓ 背包 {len(背)} 样 ｜ "
                    f"看得见的方块 {len(表 or {})} 种 ✓（不再假装一无所有 ✗）")
    except Exception as e:
        _说(f"[记性·目标] 取当前状态出岔子（{type(e).__name__}: {e}）⇒ 按老办法重排 ✓")
    计 = 求.求解(品, 1, 背包=背, 方块在哪=表) or {}
    if 计.get("好") and len(计.get("计划") or []) > 1:
        return 品, 计
    return None


def _活着任务栈():
    """摸一个活着的任务栈实例 ✓（摸不到就 None ✓ 出声交给上游 ✗）"""
    try:
        for _, 值 in list(globals().items()):
            pass
    except Exception:
        pass
    try:
        br = _主链模块()
        for 名 in ("任务栈", "任务"):
            v = getattr(br, 名, None)
            if isinstance(v, type):          # 是**类** ⇒ 去它的实例表里找 ✓
                for 实 in list(getattr(v, "车钩活着的实例", []) or []):
                    return 实
            elif v is not None:
                return v
    except Exception:
        pass
    return None


def _主链模块():
    import sys as _s
    for 名 in ("bridge",):
        m = _s.modules.get(名)
        if m is not None:
            return m
    for k, m in list(_s.modules.items()):
        if str(k).endswith("bridge") and hasattr(m, "任务栈"):
            return m
    raise RuntimeError("摸不到主链模块 bridge")


def _求解器():
    """把依赖求解器摸出来 ✓（`外挂/常识/求解器.py` ✓ 纯标准库 ✓）摸不到**出声** ✗"""
    try:
        import os as _o, sys as _s
        常 = _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.abspath(__file__))), "常识")
        if 常 not in _s.path:
            _s.path.insert(0, 常)
        import 求解器
        return 求解器
    except Exception as e:
        _说(f"[记性·目标] ✗ 求解器打不开（{type(e).__name__}: {e}）⇒ 不敢自己拼料 ✓ 出声 ✗")
        return None


def 是孤零零一个合成(步骤):
    """★ 整条计划只有**一个「合成 X」** ⇒ 那是个**目标**，不是计划 ✗

    主人 2026-10-09 实机截图（20:11）：
      「[声呐耳朵] 认出口令「stone_pickaxe」，可这一拍推不出步骤…」
      「「craft」没做成：合成「stone_pickaxe」要工作台，可我 32 格内都没找到」
    ⇒ 大模型层只回了一个**单一动作**（craft ✗）⇒ 于是它去"直接合成" ✗
      而**依赖拆解**（撸树→木板→工作台→木镐→挖石头→石镐 ✓）**在求解器里** ✓
      **没有任何一条路把"我要 X"交给求解器** ✗✓ —— 这就是病根 ✓
    规矩：**孤零零一个合成 = 那是个目标** ✓ ⇒ 交给求解器 ✓（它会自己拆 ✓）
    """
    有 = [x for x in (步骤 or []) if isinstance(x, dict)]
    if len(有) != 1:
        return None
    x = 有[0]
    if x.get("动作") != "合成":
        return None
    return str(x.get("物品") or "") or None


def 铺路向上(我y, 目标, 状态=None):
    """★ 目标比现在**高**太多 ⇒ 同样写一个「调」步骤 ✓（交给人家的"挖上去" ✓）

    主人 2026-10-10 实机抓的第二例：
      [复核] 第 5 步「走到 [2626,72,2264]」—— **现状对不上** ✗ 它比我现在**高 2 格** ✗
             （一步只上 0.6 格、跳也只上 1.1 格 ✓ 得先挖上去或搭一格 ✓）
      我原来**只给"往下去"接了执行器** ✗ ⇒ 往上这条路**没人管** ⇒ 卡死 ✓
      ⇒ 对称地接上：`生存常识.安排一趟挖上去` ✓（骨架文件里写着它是读骨架的那几处之一 ✓）
    ⚠ 各个本事的**长参不一样** ✗（"挖到"收 (状态,目标,…) ✓ "挖上去"收 (状态,背包,目标层=…) ✓）
      ⇒ 执行器统一**试几种叫法** ✓ 试不出来就**出声** ✗（不猜、不硬凑 ✓）
    """
    x, Y, z = 目标[0], 目标[1], 目标[2]
    if int(Y) - int(我y) < 2:
        return None, "落差不到 2 格，不用铺路 ✓"     # ★ 同上：形状永远是 2 元组 ✓
    return ([{"动作": "调", "要": "安排一趟挖上去", "p": [x, int(Y), z]}],
            f"要上去 {[x, int(Y), z]}（比我高 {int(Y) - int(我y)} 格 ✗ 一步只上 0.6、跳也只 1.1 ✓）"
            f"⇒ **调「安排一趟挖上去」** ✓（照主人的 45° 骨架 ✓ 我不自己修阶梯 ✗）")


def 调完了(步, 果, 任, 说):
    """把「调」的结果**就地插进计划** ✓ —— 抽出来是为了好单测 ✓"""
    排 = 果[0] if isinstance(果, tuple) else 果
    因 = 果[1] if isinstance(果, tuple) and len(果) > 1 else ""
    if not 排:
        # ★★★ 2026-10-09 主人一针见血：「**木稿都不做怎么挖**？」✓
        #   现场：计划里有一步「调 · 安排一趟挖上去」✗ —— 挖阶梯**要镐子** ✗
        #     而镐子正是它正在做的东西 ✓ ⇒ 排不出路 ✓
        #   旧代码只说一句"跳过"、**返回 False** ✗ ⇒ 任务栈认为"没做完" ⇒
        #     **每 0.1 秒重试一遍** ✗ 死锁 + 刷屏 ✓✓
        #   规矩（就是主人那句）：**排不出来就真把它摘掉** ✓ 让计划**往下走** ✗
        #     （走路爬坡本来就是**手侧寻路**的活 ✓ 不必先挖一条阶梯 ✗）
        说(f"[记性·调] ✗「{步.get('要')}」没排出路（{因 or '没说来由'}）"
           f"⇒ **把它从计划里摘掉** ✓ 让后面那步照常跑 ✓（不再无限重试 ✗）")
        try:
            步表0 = list(任.get("步骤") or [])
            号0 = int(任.get("第几步") or 0)
            if 0 <= 号0 < len(步表0):
                步表0[号0:号0 + 1] = []
                任["步骤"] = 步表0
        except Exception:
            pass
        return True          # ★ 当作"这一步完了"✓ —— 下拍就走下一步 ✓
    步表 = list(任.get("步骤") or [])
    号 = int(任.get("第几步") or 0)
    if not (0 <= 号 < len(步表)):
        说(f"[记性·调] ✗ 找不到当前第几步（第几步={号}）⇒ 不动 ✓")
        return False
    步表[号:号 + 1] = list(排)
    任["步骤"] = 步表
    说(f"[记性·调] ✓「{步.get('要')}」排出 {len(排)} 步，**就地插进计划** ✓（{str(因)[:56]}）")
    return True


def _册子要(能力):
    """★ 走**能力册** ✓ —— 不写死名单 ✗（主人：自动化啊 ✓）"""
    try:
        import os as _o, sys as _s
        厢 = _o.path.dirname(_o.path.dirname(_o.path.abspath(__file__)))
        if 厢 not in _s.path:
            _s.path.insert(0, 厢)
        import 车厢能力
        return 车厢能力.要(能力, 出声=lambda 文: _说(文))
    except Exception as e:
        _说(f"[记性·调] ✗ 册子打不开（{type(e).__name__}: {e}）⇒ 这一步跳过 ✓")
        return None


def _标记做完(任):
    """把当前这一步标成做完（就地往下一步）—— 失败也**出声** ✗"""
    try:
        任["第几步"] = int(任.get("第几步") or 0) + 1
        任["下发过"] = False
        return True
    except Exception as e:
        _说(f"[记性·调] ✗ 标不动「第几步」（{e}）⇒ 可能卡住 ✓ 出声 ✗")
        return False


def 改计划(步骤, 名字="", 状态=None):
    """③ 用：把「合成 crafting_table」换成「走到记住的坐标」✓ 返回 (新步骤, 说明列表) ✓

    ★★★ 2026-10-09 加的一道护栏（实机撞出来的）：
      账上那个工作台在 [-147,74,156]，比我**低 7 格** ✗（在一个坑里）
      落差 > 3 会摔伤 ⇒ 物理体检 T4 会把这条「走到」**拦下来** ✓（它拦得对 ✓）
      可我原来的做法是**照样生成那条走到** ✗ ⇒ 计划卡死在第一步、原地站着 ✓
      （实机日志：物理体检拦一次 ✓ 复核又独立复核一次 ✓ 然后它就不动了 ✓）

      ⇒ 现在：**太深就别去 ✓ 就地重做一个** ✓
        工作台 = **4 块木板** ✓ 而手里本来就有 planks ✓
        —— 比"挖一条斜坡下去"**又快又安全** ✓ 而且用的全是现成动作 ✓
      ⚠ 一定要**出声** ✗（为什么没去那本子上记的地方，主人得看得见 ✓）
    """
    出, 说明 = [], []
    步表 = list(步骤 or [])
    # ★★★ 孤零零一个「合成 X」⇒ 那是**目标**不是计划 ✗ ⇒ 交给求解器（它会自己拆料 ✓）
    孤单 = 是孤零零一个合成(步表)
    if 孤单:
        求 = _求解器()
        背 = None
        if isinstance(状态, dict):
            背 = 状态.get("items") or 状态.get("背包")
        # ★★★ 同一条规矩（上面 `_光杆craft要拆料` 那一大段 ✓）：**方块表也要喂** ✓
        #   少了它，求解器会把"埋在地下、谁都看不见"的落点排进来 ✗
        #   （实机：stone 埋在 dirt 下面 → 手挖上来的是 dirt → 后面整条链空转 ✓）
        表 = None
        try:
            常 = _找生存常识()
            if isinstance(状态, dict) and 常 is not None \
                    and callable(getattr(常, "可用方块", None)):
                表 = 常.可用方块(状态)
        except Exception as e:
            _说(f"[记性·目标] 取方块表出岔子（{type(e).__name__}: {e}）⇒ 照旧只给背包 ✓")
        计 = 求.求解(孤单, 1, 背包=dict(背 or {}), 方块在哪=表) if 求 else None
        if 计 and 计.get("好") and 计.get("计划"):
            步表 = list(计["计划"])
            说明.append(f"「合成 {孤单}」只是一句**目标** ✗ ⇒ 交给**求解器**拆开 ✓"
                       f"（它给了 {len(步表)} 步："
                       f"{' → '.join(str(x.get('动作')) + str(x.get('物品') or x.get('方块') or x.get('目标方块') or '') for x in 步表[:4])} …）")
        elif 求:
            说明.append(f"「合成 {孤单}」求解器也拆不出来：{str((计 or {}).get('为什么'))[:120]}")
        else:
            说明.append(f"「合成 {孤单}」要拆料，可**求解器打不开** ✗ ⇒ 按原样接 ✓（会出声 ✗）")
    i = 0
    while i < len(步表):
        步 = 步表[i]
        if not isinstance(步, dict):
            出.append(步)
            i += 1
            continue
        if 步.get("动作") == "合成" and str(步.get("物品") or "") == "crafting_table":
            位 = 想起("crafting_table")
            我 = (状态 or {}).get("pos") if isinstance(状态, dict) else None
            落差 = None
            if 位 is not None and 我 and len(我) >= 3:
                落差 = float(我[1]) - float(位[1])        # 正数 = 它在下面 ✓
            太深 = (落差 is not None and 落差 > 3)
            # ★★★ 2026-10-09 主人当场看到的（「看他跑了老远…」）：
            #   账本记着**老家**的工作台 ✓ 可它已经离家 **2400+ 格** ✗
            #   ⇒ 计划被改成"走回去用那个工作台" ✗✗（物理体检：要走到 [-131,81,141] ✓）
            #   规矩：**记忆有体力上限** ✗ —— 太远的旧坐标不是资产 ✓ 是包袱 ✗
            #     （⚠ 主人 2026-10-09 当场把阈值定成 **200 格** ✓——
            #       「超 200 格吧」✓：一个工作台值得多走点路 ✓ 但别横穿半个世界 ✗）
            _我 = (状态 or {}).get("pos") if isinstance(状态, dict) else None
            _太远 = False
            if 位 is not None and isinstance(_我, (list, tuple)) and len(_我) >= 3:
                try:
                    _太远 = ((float(位[0]) - float(_我[0])) ** 2
                           + (float(位[2]) - float(_我[2])) ** 2) ** 0.5 > 200
                except Exception:
                    _太远 = False
            if 位 is not None and (太深 or _太远):
                说明.append(
                    (f"账上那个工作台在 {位}，比我现在低 {落差:.0f} 格 ✗"
                     f"（落差 > 3 会摔伤 ✓ 物理体检拦得对 ✓）⇒ **就地重做一个** ✓（4 块木板的事 ✓）")
                    if 太深 else
                    (f"账上那个工作台在 {位}，可我离家太远了 ✗（超过 200 格 ✓）"
                     f"⇒ **记忆有体力上限** ✓ **就地重做一个** ✓（4 块木板的事 ✓）"))
                _用了几次["太深没去"] = _用了几次.get("太深没去", 0) + 1
            if 位 is not None and not 太深:
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
        # ★★★ 第二道护栏：**任何**「走到」下不去（落差 > 3）都在这儿铺路 ✗
        #   （不只是工作台那一条 ✓ 挖石头的落点也一样会碰上 ✓）
        if 步.get("动作") == "走到" and isinstance(步.get("p"), (list, tuple)) \
                and len(步["p"]) >= 3:
            我 = (状态 or {}).get("pos") if isinstance(状态, dict) else None
            if 我 and len(我) >= 3:
                # ★ 两个方向都要接 ✗（我原来只接了"往下去" ⇒ 往上那条没人管 ✓ 实机卡死 ✓）
                # ⚠ 兜一层形状闸 ✓（2026-10-09：裸 None 炸过一次 ✓ 主人截图就是它）
                #   规矩：**解包之前先保证形状** ✓ —— 修了源头也要留这道 ✓
                _r = 铺路向下(我[1], 步["p"], 状态)
                路, 为啥 = (_r if isinstance(_r, tuple) and len(_r) == 2 else (None, ""))
                if not 路:
                    _r2 = 铺路向上(我[1], 步["p"], 状态)
                    路, 为啥 = (_r2 if isinstance(_r2, tuple) and len(_r2) == 2 else (None, ""))
                if 路:
                    出.extend(路)
                    说明.append(为啥)
                    _用了几次["铺路向下"] = _用了几次.get("铺路向下", 0) + 1
                    i += 1
                    continue
                else:
                    说明.append(f"要去 {list(步['p'])}：{为啥}")
                    _用了几次["铺路向下"] = _用了几次.get("铺路向下", 0) + 1
                    i += 1
                    continue
        出.append(步)
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
    _读挖过盘()          # ★ 主人要求①：挖过账也要**读回来** ✓（重启不丢 ✓）
    _原[id(栈类)] = 原接

    # ★ 「调」是新的步骤动词 ⇒ **得先过白名单那道闸** ✗（不然会被当"野的"拦下 ✓）
    #   照 `收集` 那节车厢加 `collect` 的**同一个写法** ✓（同一件事同一个做法 ✓）
    try:
        原允许 = getattr(栈类, "允许动作", None)
        if isinstance(原允许, (set, frozenset)):
            if "调" not in 原允许:
                栈类.允许动作 = frozenset(set(原允许) | {"调"})
                _说("[记性] 白名单加了「调」✓ —— 脑点名调车厢本事的那个动词 ✓")
        else:
            _说(f"[记性] ⚠ 任务栈 上没有「允许动作」清单（拿到 {type(原允许).__name__}）"
                f" ⇒ 「调」可能被当野的拦下 ✓ 出声 ✗")
    except Exception as e:
        _说(f"[记性] ✗ 白名单加不上「调」（{e}）⇒ 调步骤会被拦 ✓ 出声 ✗")

    # ══════ ★★★★ **真正的最后一跳**：`接线口.发` ══════
    #   主人 20:25 的第三张截图（我闸门上线之后还是一样 ✗）逼我查出了这个：
    #     bridge.py:3749  `任务.发 = iface.发`
    #     bridge.py:3751  `指令 = 指令层(cfg…, iface.发, …)`  ★ 指令层拿的是 **iface.发** ✗
    #   ⇒ **指令层根本不走我包的那个 `任务栈.发`** ✗✓ —— 闸门形同虚设 ✓
    #   ⇒ 而且 `接线口` 是**每次重连都新建**的（主循环里 `iface = 接线口(cfg, 说)` ✓）
    #     ⇒ 只能拦**类** ✓（拦实例会被下一次重连绕过去 ✗）
    #   ★ `接线口.发` 才是**真正的最后一跳** ✓ —— 任务栈 / 指令层 / 三觉层 全从这儿出去 ✓
    口类 = getattr(bridge, "接线口", None)
    if isinstance(口类, type) and callable(getattr(口类, "发", None)) \
            and not getattr(口类, "_记性口闸包过", False):
        原口发 = 口类.发

        def 口发(self, obj, _原=原口发):
            try:
                # ★ 任务栈**自己派下来**的那一镐合成 → **放行** ✓（不许自己拦自己 ✗）
                #   标记由 `_下发` 包壳在调原函数前立起、调完就收 ✓
                if _放行合成[0]:
                    return _原(self, obj)
                拦 = _光杆craft要拆料(obj)
                if 拦 is not None:
                    品, 计 = 拦
                    _说(f"[记性·接线闸] ★「直接合成 {品}」是一句**目标** ✗ ⇒ **不发** ✓"
                        f" 改成接手任务：求解器拆了 {len(计['计划'])} 步 ✓"
                        f"（拦在最后一跳 接线口.发 ✓ 指令层也走这儿 ✓）")
                    栈 = _活着任务栈()
                    真状态 = _最近状态[0] or {}
                    if 栈 is not None:
                        # ★ 必须用**最近一帧真状态** ✗ —— 我第一版喂了个 `{}` ✓
                        #   结果：任务"接住了"但**坐标/背包全空** ⇒ 一步都起不来 ✗
                        #   而且外面看着就是"拦住了、然后什么都没发生" ✓（主人「？？？」那张 ✓）
                        了 = 栈.接(f"常识：{品}", list(计["计划"]), 真状态)
                        _说(f"[记性·接线闸] 接手结果：{了} ✓（用的是最近一帧真状态 ✓）")
                        return False
                    if 栈 is not None and not 真状态:
                        _待接手[0] = (品, list(计["计划"]))
                        _说("[记性·接线闸] 手上还没有**真状态**（雷达没进来 ✓）⇒ **先不交** ✗"
                            " 记下欠账，等下一帧到手再交 ✓（空状态交出去 = 计划没坐标 = 空跑 ✓）")
                        return False
                    _说("[记性·接线闸] ✗ 摸不到活的任务栈 ⇒ **照发** ✓（出声 ✗ 不装作没事 ✓）")
            except Exception as e:
                _说(f"[记性·接线闸] 出岔子（照发 ✓）：{type(e).__name__}: {e}")
            return _原(self, obj)

        口类.发 = 口发
        口类._记性口闸包过 = True
        _说("[记性] **接线口闸装上了** ✓（真正的最后一跳 ✓ 光杆 craft 到不了手 ✗）")

    # ══════ ★★★ 最后一道闸：**光杆 craft 不许直接发给手** ══════
    #   主人 2026-10-09 的两张截图都是这一条：
    #     「认出口令「stone_pickaxe」，可这一拍推不出步骤」
    #     「「craft」没做成：合成「stone_pickaxe」要工作台，可我 32 格内都没找到」
    #   真因（我一开始还以为是 LLM ✗）：**主链指令层** bridge.py:3302 直接
    #     `self.发({"cmd": "craft", "item": …})` ✗ —— **绕过了 `任务栈.接`** ✓
    #     ⇒ 我上一轮那条"孤零零一个合成 ⇒ 交给求解器"的规矩**碰不到它** ✗✓
    #   ⇒ 闸开在**最后一跳 `发`** 上 ✓：光杆 craft（手里又没料）⇒
    #     **不发** ✗ 改成**接手一个任务**（把求解器拆好的链子交给任务栈 ✓）
    #   ⚠ 舱位说明：`发` 是**实例属性**（bridge.py:1378 `self.发 = 发命令`）
    #     ⇒ 得按实例包 ✓（跟 `手上一件事` 同一个写法 ✓ 包类方法等于白包 ✗）
    原init2 = getattr(栈类, "__init__", None)
    if callable(原init2) and not getattr(原init2, "_记性发闸包过", False):
        def 新init(自身, *a, **k):
            原init2(自身, *a, **k)
            try:
                本 = getattr(自身, "发", None)
                if callable(本):
                    _原发[id(自身)] = 本

                    def 带闸(命令, _本=本, _自身=自身):
                        try:
                            if isinstance(命令, dict) and 命令.get("cmd") == "craft" \
                                    and 命令.get("item"):
                                品 = str(命令["item"])
                                求 = _求解器()
                                计 = 求.求解(品, 1, 背包={}) if 求 else None
                                计 = 计 or {}
                                if 计.get("好") and len(计.get("计划") or []) > 1:
                                    _说(f"[记性·发闸] 「直接合成 {品}」其实是一句**目标** ✗"
                                        f" ⇒ **不发给手** ✓ 改成接手一个任务："
                                        f"求解器拆了 {len(计['计划'])} 步 ✓")
                                    自身.接(f"常识：{品}", list(计["计划"]), {})
                                    return False
                                if not 求:
                                    _说(f"[记性·发闸] ⚠ 求解器打不开 ⇒ 这条 craft 照发 ✓"
                                        f"（会出声 ✗ 不装作没事 ✓）")
                        except Exception as e:
                            _说(f"[记性·发闸] 出岔子（照发 ✓）：{type(e).__name__}: {e}")
                        return _本(命令)

                    自身.发 = 带闸
            except Exception as e:
                _说(f"[记性·发闸] 装不上（这个栈没有闸 ✓）：{type(e).__name__}: {e}")

        新init._记性发闸包过 = True
        新init._记性发闸原init = 原init2
        栈类.__init__ = 新init
        _说("[记性] 发闸装上了 ✓（光杆 craft 会被改成任务 ✓ 不再一头撞死 ✗）")

    # ══════ 降层闭环（主人 2026-10-09 亲自定的形状 ✓）══════
    #   挂在**下发**和**完成判据**上 ⇒ 一拍一判 ✓ 不是固定序列 ✓
    #     ① 已经在 Y 层 ⇒ 完成 ✓（不发任何命令）
    #     ② 掉偏了 ⇒ 补一条「走到」校正坐标 ✓
    #     ③ 否则 ⇒ 挖脚下那一格 ✓（掉不掉由它自己决定 ✓ 下一拍再看 ✓）
    #   ⚠ 间隔 1.5 秒：**别每拍重发** ✗ —— 重发会把正在跑的那条路掐断 ✓（老坑 ✓）
    #   ⚠ 判据走**单调钟** ✓（老祖课第五课：墙钟会被拽 ✓）
    原下发 = getattr(栈类, "_下发", None)
    原看完了 = getattr(栈类, "_看完成了没", None)
    if not (callable(原下发) and callable(原看完了)):
        # ★ 2026-10-09：装不上**也得说一声** ✗（主人：「不许静默」）
        #   这一块里装的是两道闸：① 降层闭环 ② **拾要到货** ✓
        #   悄悄装不上 = 后面"空手算成功"那种病又回来了 ✓ 而没人知道为什么 ✗
        _说(f"[记性] ⚠ 任务栈上没有 `_下发`/`_看完成了没`"
            f"（_下发={callable(原下发)} ｜ _看完成了没={callable(原看完了)}）"
            f"⇒ **降层闭环 + 拾到货这两道闸都没装上** ✗ 出声 ✗ 别静默")
    if callable(原下发) and callable(原看完了):
        _原下发[id(栈类)] = 原下发
        _原看完了[id(栈类)] = 原看完了

        def 看完成了没(self, 步, s, 任=None):
            try:
                if isinstance(s, dict) and s:
                    _最近状态[0] = s
                    预热(s)          # ★ 要求③：开机预热（拿真记录 ✓ 不空白开局 ✓）
                    if _待接手[0] is not None and s.get("pos"):
                        品, 计划 = _待接手[0]
                        _待接手[0] = None
                        栈 = _活着任务栈()
                        if 栈 is not None:
                            了 = 栈.接(f"常识：{品}", list(计划), s)
                            _说(f"[记性·接线闸] 真状态到手 ✓ 现在交「常识：{品}」"
                                f"（{len(计划)} 步）⇒ 结果 {了} ✓（用的是刚到手那一帧 ✓）")
                            return False          # ★ 存最近一帧真状态 ✓（接任务要用 ✓）
                if isinstance(步, dict) and 步.get("动作") == "降到":
                    我 = (s or {}).get("pos") or [0, 0, 0]
                    if int(我[1]) <= int((步.get("p") or [0, 0, 0])[1]):
                        return True, None        # ★ **到层了** = 这一步完 ✓（目标点导向 ✓）
                    return False, None
                # ══════ ★★★ 拾：**背包里没到货就不算完** ✗ ══════
                #   2026-10-09 主人：「又挖了一个白桦木又发呆了」那一晚的第三个病 ✓
                #   现场：`挖 stone` 那一镐**挖上来的是 dirt** ✗
                #     → 下一步「拾 cobblestone」**0 秒"过"** ✗（甲把拾换成了"走过去"✓
                #        走过去当然会"完成" ✓ 可**背包里一块圆石都没有** ✗）
                #     → 再「合成 stone_pickaxe」空转 → 3 分钟判失败 → 重排 → 死循环 ✓
                #   规矩（跟「不许静默」「Fail-Closed」同一条 ✓）：
                #     **拾 = 背包里真多了那个东西** ✓
                #       没到货 ⇒ 这一步**不算完** ✓ 让主链的超时/重试照常判失败 ✓
                #       （宁可如实失败 ✓ 也不许"空手算成功"✗ —— 那会把整条链带到坑里 ✓）
                # ══════ ★★★ 主人要求②（2026-10-10）：「**「挖」的闭环必须绑定「拾」**」══════
                #   「把动作改成 挖并拾取。**如果背包物品数量没增加，这一步就判定为"未完成"**，
                #     一直重试（带超时熔断）。」✓
                #   ⇒ 判据：背包里那个掉落物 **比挖之前多** ✓ 才叫完 ✓
                #     （多不出来 ⇒ 不算完 ✓ 让主链的超时/重试照常兜着 = 熔断 ✓）
                if isinstance(步, dict) and 步.get("动作") == "挖":
                    好了5, 余5 = 原看完了(self, 步, s, 任)
                    if 好了5:
                        _掉6 = str(步.get("_挖掉啥") or "")
                        _基6 = 步.get("_挖前")
                        if _掉6 and _基6 is not None:
                            有6 = 0.0
                            try:
                                有6 = float(((s or {}).get("items") or {}).get(_掉6) or 0)
                            except Exception:
                                有6 = 0.0
                            if 有6 < float(_基6) + 1:
                                if (time.monotonic() - float(_挖账说过.get("t2") or 0)) > 5.0:
                                    _挖账说过["t2"] = time.monotonic()
                                    _说(f"[记性·挖并拾] ✗ 挖了「{步.get('方块')}」可背包里的"
                                        f"「{_掉6}」**没多**（{有6:g} 个，挖之前 {float(_基6):g} 个）"
                                        f"⇒ **这一步不算完** ✓ 重试（超时了就熔断判失败 ✓）"
                                        f"—— 主人要求② ✓")
                                return False, 余5
                        记挖过(步.get("p"))      # ★ 完成了才记账 ✓（账本要准 ✓）
                    return 好了5, 余5
                if isinstance(步, dict) and 步.get("动作") == "拾" and 步.get("物品"):
                    好了, 余 = 原看完了(self, 步, s, 任)
                    if 好了:
                        try:
                            要 = float(步.get("数量") or 1)
                        except Exception:
                            要 = 1.0
                        有 = 0.0
                        try:
                            有 = float(((s or {}).get("items") or {}).get(str(步["物品"])) or 0)
                        except Exception:
                            有 = 0.0
                        if 有 < 要:
                            现在 = time.monotonic()
                            if 现在 - float(_拾空喊过.get("t") or 0) > 5.0:
                                _拾空喊过["t"] = 现在
                                _说(f"[记性·拾] ✗「{步['物品']}」背包里只有 {有:g} 个"
                                    f"（要 {要:g} 个）—— **这一步不算完** ✗"
                                    f"（空手算成功会把后面全带坑里 ✓ 让主链判失败重排 ✓）")
                            return False, None
                    return 好了, 余
            except Exception as e:
                _说(f"[记性·降层] 完成判据出岔子（按原样走 ✓）：{e}")
            return 原看完了(self, 步, s, 任)

        def 下发(self, 步, 任, 现在, s):
            try:
                if isinstance(s, dict) and s:
                    _最近状态[0] = s
                    预热(s)          # ★ 要求③：两条路都预热 ✓（谁先来都行 ✓）
                # ══════ ★★★ 换树种：计划要挖的和那一格**实际**的，同族就换 ══════
                #   2026-10-10 半夜（主人：「让他接着跑」之后我盯到的现场）：
                #     计划要「挖 birch_log」✗ 可那一格雷达读到的是「oak_log」✓
                #       ⇒ 「拾 birch_log」永远是 **0 个** ✗（复核连着两拍点名 ✗）
                #       ⇒ 60 秒 ×3 判失败 → 重排 → 又排 birch → **死循环** ✓
                #   规矩（老规矩了）：**同族就换** ✓ —— 判据只有一份实现
                #     （`生存常识._同族吗` / `_族名` ✓ 我绝不自己再写一遍 ✗）
                #   ⚠ 只换「挖」这一步 + 后面配对的「拾」 ✓ 别的步骤一个字不动 ✗
                # ══════ ★★★ 合成木板：**用手上真拿得到的那种木头** ══════
                #   2026-10-10 主人原话：
                #     「**其实不同树种的木板也能合成工作台跟木棍和木镐**」✓
                #   现场：计划第一步挖的是**橡木**（落坐标按同族改对了 ✓）
                #     可第二步要「合成 **acacia**_planks」✗ —— 手里 0 根金合欢原木 ✗
                #     ⇒ 合成永远差料 ⇒ 空转 ✓（手那句诊断：「配方要：acacia_log 0/1」✓）
                #   规矩：**要哪种木板，看手里/这一趟真能拿到的木头** ✓
                #     ① 这一步要的木板、其原木我拿得到 ⇒ 一个字不动 ✓
                #     ② 拿不到、可我**有别的木头** ⇒ 换成那种木板 ✓
                #        （原版 `#planks` 标签通用 ✓ —— 主人点名的事实 ✓）
                #     ③ 什么都没有 ⇒ 不动 ✗（交给主链按缺料处理 ✓ 不瞎换 ✓）
                if isinstance(步, dict) and 步.get("动作") == "合成":
                    物 = str(步.get("物品") or "")
                    if 物.endswith("_planks"):
                        族 = 物[:-len("_planks")]
                        好木头 = _有原木(s, 族, 任)
                        # ⚠ 判据也要**出声** ✗（2026-10-10：实机明明有 4 块橡木板 ✓
                        #   却还在要 acacia ✗ 而日志里一个字都没有 ⇒ 我根本不知道它判成了啥 ✗）
                        if (time.monotonic() - float(_换树说过.get("判") or 0)) > 5.0 \
                                and not 好木头:
                            _换树说过["判"] = time.monotonic()
                            try:
                                背 = dict((s or {}).get("items") or {})
                            except Exception:
                                背 = {}
                            _说(f"[记性·换木判] 这一步要「{物}」｜ 族={族} ｜ 有原木吗={好木头} ｜ "
                                f"能做的木板={_能做的木板(s, 任)} ｜ 背包里的木板="
                                f"{ {k: v for k, v in 背.items() if str(k).endswith('_planks')} }")
                        if not 好木头:
                            换 = _能做的木板(s, 任)
                            if 换 and 换 != 物 and (time.monotonic() - float(_换树说过.get("t") or 0)) > 5.0:
                                _换树说过["t"] = time.monotonic()
                                _说(f"[记性·换木] 这一步要「{物}」✗ 可我没有「{族}」的原木 ✓"
                                    f"—— **换成手上真有的「{换}」** ✓"
                                    f"（主人点名的事实：不同树种木板都能做工作台/木棍/木镐 ✓）")
                                旧物 = 物
                                步["物品"] = 换
                                if isinstance(步.get("料"), dict) and 旧物 in 步["料"]:
                                    步["料"][换] = 步["料"].pop(旧物)
                                # 后面几步的「料」里可能还点着旧木板名 ⇒ 一并换 ✓（只换这一个键 ✗）
                                for _后 in list((任 or {}).get("步骤") or []):
                                    try:
                                        if isinstance(_后, dict) and isinstance(_后.get("料"), dict) \
                                                and 旧物 in _后["料"]:
                                            _后["料"][换] = _后["料"].pop(旧物)
                                    except Exception:
                                        continue
                # ══════ ★★★ 要跑「合成工作台」之前：**先看账上那个还在不在** ══════
                #   2026-10-10 半夜（主人当场发火：「**他有工作台为啥又要重做一个**」✓）
                #   病根：那条「合成工作台 → 改成走过去用账上那个」的规矩
                #     **只在「接单那一刻」跑** ✗（在 `改计划` 里 ✓）
                #     而今天新加的自愈（障碍 / 够不着 / 调 ✓）是**直接插进任务里**的 ✗
                #     ⇒ 插进来的「合成工作台」**没人管** ⇒ 它照做 ⇒ 又搭一个新台子 ✗
                #   规矩：**同一条判据，补到"要跑的那一刻"** ✓
                #     记得、且 ≤200 格、落差 ≤3 ⇒ **当场把这一步换成「走到那儿」** ✓
                #     后面紧跟的「放工作台」也一并跳掉 ✓（走过去用现成的 ✓ 不用再放 ✗）
                #   ⚠ 判据（200 格 / 落差 3 / 先查本子）**不重写** ✓ —— 跟 `改计划` 里那份一字不差 ✓
                if isinstance(步, dict) and 步.get("动作") == "合成" \
                        and str(步.get("物品") or "") == "crafting_table":
                    位 = 想起("crafting_table")
                    我 = (s or {}).get("pos")
                    该用 = False
                    if isinstance(位, (list, tuple)) and len(位) >= 3 \
                            and isinstance(我, (list, tuple)) and len(我) >= 3:
                        try:
                            距 = ((float(位[0]) - float(我[0])) ** 2
                                 + (float(位[2]) - float(我[2])) ** 2) ** 0.5
                            落差 = float(我[1]) - float(位[1])
                            该用 = (距 <= 200 and 落差 <= 3)
                        except Exception:
                            该用 = False
                    if 该用:
                        任2 = 任 if isinstance(任, dict) else getattr(self, "任务", None)
                        步表2 = list((任2 or {}).get("步骤") or [])
                        try:
                            号2 = int((任2 or {}).get("第几步") or 0)
                        except Exception:
                            号2 = 0
                        if 0 <= 号2 < len(步表2):
                            去掉放 = False
                            if 号2 + 1 < len(步表2) and isinstance(步表2[号2 + 1], dict) \
                                    and 步表2[号2 + 1].get("动作") == "放" \
                                    and str(步表2[号2 + 1].get("方块") or "") == "crafting_table":
                                步表2.pop(号2 + 1)
                                去掉放 = True
                            新步 = {"动作": "走到", "p": list(位), "到点": 2.5}
                            步表2[号2:号2 + 1] = [新步]
                            任2["步骤"] = 步表2
                            任2["重试"] = 0
                            任2["重试到"] = 0.0
                            任2["下发过"] = False
                            if (time.monotonic() - float(_台子说过.get("t") or 0)) > 5.0:
                                _台子说过["t"] = time.monotonic()
                                _说(f"[记性·台子] 这一步要「合成工作台」✗ 可账上记着"
                                    f" @{list(位)}（{距:.1f} 格 ✓ ≤200 ✓ 落差 {落差:.0f} ✓）"
                                    f" ⇒ **换成走过去用现成的** ✓（{'连「放」也跳掉 ✓' if 去掉放 else ''}"
                                    f"**绝不再多搭一个** ✗）")
                            return 原下发(self, 新步, 任2, 现在, s)
                # ══════ ★★★ 合成前先核对：**配方要几块、我挖了几块** ══════
                #   2026-10-10 深夜（主人：「**让他直接挖完配方需要的数量**然后回工作台」✓）
                #   现场：石镐要 3 块圆石 ✓ 可计划里只有**一镐** ✗ ⇒ 拾到 1 块就去合成 ✗
                #     ⇒ 手回「配方要：cobbled_deepslate 0/3」✗ ⇒ 空转 → 3 分钟失败 → 重排 → 又只挖一镐 ✓
                #   规矩：**要几块就挖几块** ✓ —— 而且"要几块"这件事**问求解器** ✓
                #     （它本来就管算料 ✓ 我不另抄一份配方表 ✗）
                if isinstance(步, dict) and 步.get("动作") == "合成":
                    _物 = str(步.get("物品") or "")
                    if _物 and (time.monotonic() - float(_补料说过.get("t") or 0)) > 15.0:
                        try:
                            _背 = dict((s or {}).get("items") or {}) if isinstance(s, dict) else {}
                            _求 = _求解器()
                            _常3 = _找生存常识()
                            _表 = None
                            if _常3 is not None and callable(getattr(_常3, "可用方块", None)) \
                                    and isinstance(s, dict):
                                _表 = _常3.可用方块(s)
                            _计 = _求.求解(_物, 1, 背包=_背, 方块在哪=_表) if _求 else None
                            _挖步 = [x for x in ((_计 or {}).get("计划") or [])
                                   if isinstance(x, dict) and x.get("动作") == "挖"]
                            # ★★ 求解器也排不出（石头在洞壁上、雷达没读数 ✓）
                            #   ⇒ **直接往下盲挖** ✓（主人原话：「**先让他直接执行向下挖**，
                            #      因为这是最好的办法做石镐，我平时就是这样干的」✓）
                            if not _挖步 and _常3 is not None \
                                    and callable(getattr(_常3, "安排一趟向下盲挖", None)) \
                                    and isinstance(s, dict):
                                try:
                                    _盲, _盲说 = _常3.安排一趟向下盲挖(s, 背包=_背)
                                except Exception:
                                    _盲, _盲说 = None, "排盲挖时出岔子"
                                if _盲:
                                    _挖步 = [x for x in _盲 if isinstance(x, dict)]
                                    _挖步 = _挖步 or None
                            if _挖步:
                                _补料说过["t"] = time.monotonic()
                                _任3 = 任 if isinstance(任, dict) else getattr(self, "任务", None)
                                _表3 = list((_任3 or {}).get("步骤") or [])
                                try:
                                    _号3 = int((_任3 or {}).get("第几步") or 0)
                                except Exception:
                                    _号3 = 0
                                if 0 <= _号3 < len(_表3):
                                    _新 = list(_挖步)
                                    # 求解器给的是符号步（挖/stone ✓）⇒ 要用落坐标换成坐标 ✓
                                    # 盲挖给的**本来就是坐标步** ✓ ⇒ 直接用 ✓（判据：有没有 p ✓）
                                    if not all(isinstance(x.get("p"), (list, tuple)) for x in _新):
                                        _新 = _常3.落坐标(_挖步, s)[0] if (_常3 is not None
                                                and callable(getattr(_常3, "落坐标", None))
                                                and isinstance(s, dict)) else None
                                    if _新:
                                        _表3[_号3:_号3] = list(_新)
                                        _任3["步骤"] = _表3
                                        _任3["重试"] = 0
                                        _任3["重试到"] = 0.0
                                        _任3["下发过"] = False
                                        _说(f"[记性·补料] 要合成「{_物}」✗ 可料不够"
                                            f"（求解器说还得挖 {len(_挖步)} 下）⇒ "
                                            f"**就地插进 {len(_新)} 步补挖** ✓（主人："
                                            f"「让他直接挖完配方需要的数量」✓）")
                                        return False
                        except Exception as _e4:
                            _说(f"[记性·补料] 核对料够不够时出岔子（{type(_e4).__name__}: {_e4}）"
                                f"⇒ 照旧下发 ✓（不静默 ✗）")
                if isinstance(步, dict) and 步.get("动作") == "挖":
                    # ══════ ★★★ 要挖的正是**我脚下那一格** ⇒ 先挪开一格 ✓ ══════
                    #   2026-10-10 深夜（主人：「你看看他做了没有」那会儿抓到的）：
                    #     手当场拒绝：「**那是我正脚下那块，挖了我自己就掉下去了**」✗
                    #     ⇒ 60 秒超时 ×3 ⇒ 整条活失败 ⇒ 重排 ⇒ 还是挖脚下 ⇒ 死循环 ✓
                    #   规矩（生存常识里**早就写着**这条 ✓「先挪开一格再挖，不猜坐标」✓
                    #     —— 只是别处的计划没走它 ✗ ⇒ 我在这儿**补上同一套** ✓ 不另写算法 ✗）：
                    #     挖脚下 ⇒ **先插一步「走到旁边」** ✓ 人就挪开了 ✓ 再挖 ✓
                    try:
                        _我6 = (s or {}).get("pos") if isinstance(s, dict) else None
                        _p6 = 步.get("p")
                        if isinstance(_我6, (list, tuple)) and len(_我6) >= 3 \
                                and isinstance(_p6, (list, tuple)) and len(_p6) >= 3:
                            _脚6 = [int(float(_我6[0]) // 1), int(float(_我6[1]) - 1),
                                   int(float(_我6[2]) // 1)]
                            _要6 = [int(float(_p6[0]) // 1), int(float(_p6[1]) // 1),
                                   int(float(_p6[2]) // 1)]
                            if _要6 == _脚6:
                                # ★ 2026-10-10 深夜（主人：「你看看他做了没有」时抓到）：
                                #   手侧**本来就有** `允许挖脚下` 这个开关 ✓
                                #     （`proto_body.js`：`if (… !a.允许挖脚下)` ✓）
                                #   玩家自己就是这么干的 ✓ —— 站在坑底往下挖一格、掉下去一格 ✓
                                #     **只有在"下面不安全"时才算冒险** ✗
                                #   ⇒ 判据：目标方块是**普通土石**（不在沙/砾/水/岩浆那一类 ✓）
                                #     ⇒ 直接挖 ✓ 加旗子 ✓；是那种危险的就照旧"先挪开" ✓
                                _危6 = ("sand", "gravel", "water", "lava", "magma_block",
                                       "fire", "soul_fire", "powder_snow", "air",
                                       "cave_air", "void_air")
                                _名下6 = str(步.get("方块") or 步.get("目标方块") or "")
                                if _名下6 and _名下6 not in _危6:
                                    步["允许挖脚下"] = True
                                    _允许脚下[0] = True
                                    if (time.monotonic() - float(_挖账说过.get("t4") or 0)) > 5.0:
                                        _挖账说过["t4"] = time.monotonic()
                                        _说(f"[记性·往下挖] 这一步挖的正是脚下那格 {_要6} ✓"
                                            f"（「{_名下6}」是普通土石 ✓）⇒ **直接挖** ✓"
                                            f"掉下去一格没关系 ✓ —— 玩家就是这么干的 ✓"
                                            f"（手侧那个「允许挖脚下」开关 ✓ 不是新开的口子 ✗）")
                                    # 不 return ✗ —— 让它继续往下走正常的下发流程 ✓
                                # ⚠⚠ 立了旗子就**别再插"挪脚"那一步** ✗
                                #   （2026-10-10 实机：两条规则同一拍都跑 ⇒ 旗子立了 ✓
                                #     可"挪脚"照样把这一步**换掉** ✗ ⇒ 永远挖不到脚下 ⇒ 死循环 ✓）
                                if not 步.get("允许挖脚下"):
                                    _任6 = 任 if isinstance(任, dict) else getattr(self, "任务", None)
                                    _表6 = list((_任6 or {}).get("步骤") or [])
                                    try:
                                        _号6 = int((_任6 or {}).get("第几步") or 0)
                                    except Exception:
                                        _号6 = 0
                                    if 0 <= _号6 < len(_表6):
                                        _旁6 = [int(float(_我6[0]) // 1) + 1, int(float(_我6[1]) // 1),
                                               int(float(_我6[2]) // 1)]
                                        _表6[_号6:_号6] = [{"动作": "走到", "p": _旁6, "到点": 1.0}]
                                        _任6["步骤"] = _表6
                                        _任6["重试"] = 0
                                        _任6["重试到"] = 0.0
                                        _任6["下发过"] = False
                                        if (time.monotonic() - float(_挖账说过.get("t3") or 0)) > 5.0:
                                            _挖账说过["t3"] = time.monotonic()
                                            _说(f"[记性·挪脚] 这一步要挖的正是**我脚下那格**"
                                                f"{_要6} ✗（手会拒绝：挖了自己就掉下去 ✓）"
                                                f"⇒ **先插一步走到旁边 {_旁6}** ✓ 挪开再挖 ✓"
                                                f"（跟生存常识那条「先挪开一格再挖」同一套 ✓）")
                                        return False
                    except Exception as _e6:
                        _说(f"[记性·挪脚] 判脚下那格时出岔子（{type(_e6).__name__}: {_e6}）"
                            f"⇒ 照旧下发 ✓（不静默 ✗）")
                    # ══════ ★ 主人要求①（2026-10-10）：**挖矿前先读账本** ══════
                    #   「询问「记性」："这个坐标被我挖过吗？" 如果挖过，跳过。」✓
                    #   ⚠ 判据：账上有这一格 **而且** 现状读数是空气 ⇒ 跳过 ✓
                    #     （只信账本不够 ✗：世界会变 ✓ 读数说那儿有东西就照挖 ✓）
                    _位挖 = 步.get("p")
                    if isinstance(_位挖, (list, tuple)) and len(_位挖) >= 3 and 挖过吗(_位挖):
                        _现状 = _那格是什么(s, _位挖)
                        if (not _现状) or str(_现状) in ("air", "cave_air", "void_air"):
                            if (time.monotonic() - float(_挖账说过.get("t") or 0)) > 5.0:
                                _挖账说过["t"] = time.monotonic()
                                _说(f"[记性·挖账] 这一步要挖 {[int(float(v)) for v in _位挖[:3]]} ✗ "
                                    f"可**账上记着它挖过** ✓ 而且现状就是空气 ✓ ⇒ **跳过** ✓"
                                    f"（主人要求①：挖过就跳过 ✓ 不挖空气 ✗）")
                            _标记做完(任 if isinstance(任, dict) else getattr(self, "任务", None))
                            return False
                    # ══════ ★ 主人要求②：挖的"挖前数量"要记下来 ══════
                    #   完成判据 = **背包里真多出那个掉落物** ✓（见 `看完成了没` ✓）
                    if 步.get("_挖前") is None:
                        try:
                            _名5 = str(步.get("方块") or 步.get("目标方块") or "")
                            _常5 = _找生存常识()
                            _掉5 = (_常5.挖了掉什么(_名5) if (_常5 is not None and _名5
                                    and callable(getattr(_常5, "挖了掉什么", None))) else None)
                            if _掉5:
                                步["_挖前"] = float(((s or {}).get("items") or {}).get(_掉5) or 0)
                                步["_挖掉啥"] = _掉5
                        except Exception:
                            pass
                    真 = _那格是什么(s, 步.get("p"))
                    要 = str(步.get("方块") or 步.get("目标方块") or "")
                    if 真 and 要 and 真 != 要:
                        常2 = _找生存常识()
                        同族 = getattr(常2, "_同族吗", None) if 常2 is not None else None
                        族名 = getattr(常2, "_族名", None) if 常2 is not None else None
                        if callable(同族) and callable(族名):
                            try:
                                是 = bool(同族(真, 要))
                            except Exception:
                                是 = False
                            if 是 and (time.monotonic() - float(_换树说过.get("t") or 0)) > 5.0:
                                _换树说过["t"] = time.monotonic()
                                _说(f"[记性·换树] 计划要挖「{要}」✗ 可那一格是「{真}」✓ "
                                    f"—— **同族（{族名(真)}）就换成它** ✓"
                                    f"（不换的话后面「拾 {要}」永远是 0 个 ✗ 死循环 ✓）")
                            步["方块"] = 真
                            if 步.get("目标方块") is not None:
                                步["目标方块"] = 真
                            步表 = list((任 or {}).get("步骤") or [])
                            try:
                                号 = int((任 or {}).get("第几步") or 0)
                            except Exception:
                                号 = 0
                            for _后 in 步表[号 + 1:号 + 3]:
                                if isinstance(_后, dict) and _后.get("动作") == "拾" \
                                        and str(_后.get("物品") or "") == 要:
                                    try:
                                        掉 = 常2.挖了掉什么(真)
                                    except Exception:
                                        掉 = 真
                                    _后["物品"] = str(掉 or 真)
                                    _说(f"[记性·换树] 后面那步「拾 {要}」也改成"
                                        f"「拾 {_后['物品']}」✓（配对，不能只改一半 ✗）")
                # ══════ ★ 通用的「调」步骤：**脑点名要某节车厢的本事** ══════
                #   主人 2026-10-09：「没给他调用车厢工具的能力吗」✓ —— 这就是那条能力 ✓
                if isinstance(步, dict) and 步.get("动作") == "调":
                    要 = str(步.get("要") or "")
                    有 = _找生存常识() if 要 == "安排一趟挖到" else None
                    if 有 is None:
                        有 = _册子要(要)
                    if 有 is None:
                        _说(f"[记性·调] ✗ 没有哪节车厢会「{要}」—— **这一步什么都不做** ✓"
                            f"（主人点过：别抄第二遍 ✗）")
                        _标记做完(任)
                        return False
                    参 = list(步.get("p") or [])
                    # ★ 各个本事的**长参不统一** ✗ ⇒ 试几种叫法 ✓ 都不行就出声 ✗
                    层 = int(参[1]) if len(参) >= 3 else None
                    试法 = [
                        lambda f: f((s or {}), list(参), 背包=None, 最远=24),
                        lambda f: f((s or {}), list(参)),
                        lambda f: f((s or {}), None, 目标层=层),
                        lambda f: f((s or {}), None, 层),
                    ]
                    果 = None
                    错们 = []
                    for 第, 招 in enumerate(试法):
                        try:
                            果 = 招(有)
                            break
                        except Exception as e:
                            错们.append(f"第{第 + 1}式 {type(e).__name__}: {e}")
                    if 果 is None:
                        _说(f"[记性·调] ✗「{要}」的参我凑不上（试了 4 种叫法 ✗）⇒ 跳过 ✓"
                            f" ｜ {错们[-1] if 错们 else '没试成'}")
                        _标记做完(任)
                        return False
                    调完了(步, 果, 任, _说)
                    return False
                if isinstance(步, dict) and 步.get("动作") == "降到":
                    import time as _t
                    键 = id(任)
                    上 = _降层上次.get(键)
                    单 = _t.monotonic()
                    if 上 is not None and 单 - 上 < 降层间隔秒:
                        return False
                    新步, 说明 = _降层(步, s)
                    if 新步 is None:
                        return False             # 到层了 ✓
                    _降层上次[键] = 单
                    if 说明:
                        _说(f"[记性·降层] 说明：{说明}")
                    return 原下发(self, 新步, 任, 现在, s)
            except Exception as e:
                _说(f"[记性·降层] 下发闭环出岔子（按原样走 ✓）：{e}")
            # ══════ ★★★ 甲/乙（2026-10-09 主人：「挖了一个怎么就停了」+「到点对不上」）══════
            #   现场：挖下来的原木**掉在地上没人捡** ✗ —— 手侧压根没有"捡"这个命令 ✓
            #   它只有原版的**自动吸附**（得走到 ~1 格内 ✓），
            #   而脑侧挖之前只走到 **3 格之外** ✗ ⇒ 第 2 步「拾 oak_log」干等 60 秒超时 ✓
            #   ⇒ 整条链停住（后面 木板/工作台/木棍/木镐 一步都没机会跑 ✓）
            #   规矩（**红线一个字不碰** ✗ —— 全在这一层包壳里做）：
            #     甲：看到「拾」→ 用状态里**已经报上来的掉落物坐标**（`s["drops"]` ✓ 手侧现成的）
            #         补发一条 `goto … near:1` ✓ 走过去，自动吸附自己就完成了 ✓
            #     乙：看到「走到」而**到点 < 手侧停靠距离**（默认 2 格 ✓）→ 也补一条带 `near` 的
            #         goto ✓（不然脑侧永远判"没到"✗ = 主人截图里那个「慢 31 倍」✓）
            try:
                _步动 = str((步 or {}).get("动作") or "") if isinstance(步, dict) else ""
                # ══════ ★★★ 2026-10-09 主人：「**不能返回 None 摆烂**」══════
                #   实机：计划里的「挖」没坐标 ⇒ **照发空镐** ⇒
                #     手侧回「要给我一个坐标 p:[x,y,z]」×N ⇒ 卡死 ✗（几十次 ✓）
                #   主人给的修法：雷达扫不到目标时，**要么走两步换角度、要么仰视再扫** ✓
                #   所以：没坐标的「挖」**这一拍不发** ✗；改成**朝雷达报回来的那格走** ✓
                #     （哪怕它标着"被埋住/视线被挡"✓ —— 走过去换个角度，它就露出来了 ✓）
                if _步动 == "挖" and isinstance(s, dict) \
                        and not (isinstance(步.get("p"), (list, tuple)) and len(步["p"]) >= 3):
                    _名 = str(步.get("方块") or 步.get("目标方块") or "")
                    _候 = []
                    _扫 = (s.get("scan") or {})
                    for _b in (list(_扫.get("找") or []) + list(_扫.get("可交互") or [])
                               + ([_扫.get("石头")] if isinstance(_扫.get("石头"), dict) else [])):
                        if isinstance(_b, dict) and isinstance(_b.get("p"), (list, tuple)) \
                                and len(_b["p"]) >= 3:
                            if (not _名) or str(_b.get("name")) == _名 \
                                    or str(_b.get("name") or "").endswith(("_log", "_leaves")):
                                _候.append(_b)
                    _候.sort(key=lambda b: float(b.get("距") or 99))
                    if _候:
                        # ★★★ 2026-10-09 主人：「**不能返回 None 摆烂**」——
                        #   雷达报了坐标 ⇒ **就别摆烂** ✓ 直接把坐标补进步里、照常下发 ✓
                        #   （实机：木头就在它**头顶两格** [2688,66,2267] ✓ 而它站着不动 ✗）
                        _中 = _候[0]
                        _位 = [float(v) for v in list(_中["p"])[:3]]
                        步["p"] = _位
                        if not 步.get("方块"):
                            步["方块"] = str(_中.get("name") or "")
                        if (time.monotonic() - float(_拾过.get("补坐标t") or 0)) > 2.0:
                            _拾过["补坐标t"] = time.monotonic()
                            _说(f"[记性·补坐标] 「{步.get('方块') or _名}」这步没坐标 ✗ —— "
                                f"雷达报它在 {[int(v) for v in _位]}（{_中.get('距')} 格）⇒ "
                                f"**补上，照常下发** ✓（不许摆烂 ✗）")
                        # ⚠ 不 return ✗ —— 让它继续往下走正常的下发流程 ✓
                    # ★★★ 2026-10-09 主人：「**要么去周围走两步**（更高的地方/换角度）」
                    #   雷达一个都没报 ⇒ 那就**借常识的探路**走两步 ✓
                    #   （⚠ 不抄第二遍 ✗ —— `探路一步()` 是生存常识那一份 ✓ 借它 ✓）
                    # ★★★ 2026-10-09 主人：**「去雷达没扫过的隔壁看看」或许更好** ✓
                    #   比"随便走两步"强 ✓：有账 ✓ 不会来回打转 ✓（转圈那毛病今天吃过一次 ✗）
                    #   做法：把地图按 16×16 分格 ✓ 记住**去过哪些格** ✓
                    #     目标 = 我所在格的**四邻**里、没去过的那个（挨个来 ✓ 都去过就扩一圈 ✓）
                    #   ⚠ 不猜方块、不猜坐标 ✓ —— 猜的只有"去哪儿看看" ✓ 那是探索 ✓ 不是断言 ✓
                    try:
                        if (time.monotonic() - float(_拾过.get("盲走t") or 0)) > 3.0:
                            _拾过["盲走t"] = time.monotonic()
                            _我 = (s or {}).get("pos") or [0, 0, 0]
                            _格 = (int(_我[0]) // 16, int(_我[2]) // 16)
                            _去过 = _拾过.setdefault("去过格", set())
                            _去过.add(_格)
                            _选 = None
                            for _圈 in (1, 2, 3):
                                _邻 = [(_格[0] + dx, _格[1] + dz)
                                      for dx in range(-_圈, _圈 + 1)
                                      for dz in range(-_圈, _圈 + 1)
                                      if max(abs(dx), abs(dz)) == _圈]
                                _新 = [g for g in _邻 if g not in _去过]
                                if _新:
                                    _新.sort(key=lambda g: abs(g[0] - _格[0]) + abs(g[1] - _格[1]))
                                    _选 = _新[0]
                                    break
                            if _选 is not None:
                                _去 = [float(_选[0] * 16 + 8), float(int(_我[1])), float(_选[1] * 16 + 8)]
                                _栈1 = _活着任务栈()
                                _发1 = getattr(_栈1, "发", None) if _栈1 is not None else None
                                if callable(_发1):
                                    _发1({"act": "goto", "p": _去, "near": 2.5})
                                    _说(f"[记性·去隔壁看看] 「{_名 or '那块'}」没坐标、雷达也没报 ⇒ "
                                        f"**去没扫过的隔壁** {_选}（≈{_去[0]:.0f},{_去[2]:.0f}）看看 ✓"
                                        f"（已走 {len(_去过)} 格 ✓ 不来回打转 ✗）")
                            else:
                                _说(f"[记性·去隔壁看看] 周围 3 圈（约 112 格）都去过了 ✗ —— "
                                    f"这一片大概真没有「{_名}」✓（不是「再走走」能解决的了 ✓）")
                    except Exception as _e4:
                        _说(f"[记性·去隔壁看看] 出岔子（{type(_e4).__name__}: {_e4}）✗ 出声 ✓")
                    return False
                if _步动 in ("拾", "走到") and isinstance(s, dict):
                    import time as _t3
                    _今3 = _t3.monotonic()
                    _要发 = None
                    # ★ 记住**刚挖过的那一格** ✓ —— 拾不到掉落物时它就是兜底坐标 ✓
                    if _步动 == "挖" and isinstance(步.get("p"), (list, tuple)):
                        try:
                            _拾过["挖点"] = [float(v) for v in list(步["p"])[:3]]
                        except Exception:
                            pass
                    if _步动 == "拾":
                        _要 = str(步.get("物品") or "")
                        _候 = [d for d in (s.get("drops") or [])
                              if isinstance(d, dict)
                              and isinstance(d.get("pos"), (list, tuple))
                              and (not _要 or str(d.get("name")) == _要)]
                        _候.sort(key=lambda d: float(d.get("dist") or 99))
                        # ⚠⚠ 2026-10-09 主人：「那为啥在这里发呆？」——
                        #   实机原话：`★ 漏了：动作「拾」需要【掉落物在哪儿】，可这一帧里 drops 全空 ✗`
                        #   ⇒ 掉落物**没报上来**（可能刚被捡走/超了 14 格/名字对不上 ✓）
                        #     ⇒ 我那条"走到掉落物那儿"就没坐标可走 ✓ ⇒ 它干等 60 秒 ✓ 发呆 ✓
                        #   兜底：**回到刚挖过的那一格** ✓（那儿的坐标我们自己有 ✓）——
                        #     挖下来的东西就掉在附近 ✓ 走过去自然就吸附了 ✓
                        if not _候 and _拾过.get("挖点"):
                            _位挖 = list(_拾过["挖点"])
                            if _拾过.get("回挖点") != _位挖 or (_今3 - float(_拾过.get("t") or 0)) > 2.0:
                                _拾过["回挖点"], _拾过["t"] = _位挖, _今3
                                _要发 = _位挖
                                _说(f"[记性·捡] 「{_要 or '掉落物'}」这一帧 **drops 全空** ✗ —— "
                                    f"那就**回到刚挖的 {_位挖} 那儿**找 ✓（东西就掉在附近 ✓）")
                        if _候 and float(_候[0].get("dist") or 99) > 1.2:
                            _位 = [float(v) for v in list(_候[0]["pos"])[:3]]
                            if _拾过.get("p") != _位 or (_今3 - float(_拾过.get("t") or 0)) > 2.0:
                                _拾过["p"], _拾过["t"] = _位, _今3
                                _要发 = _位
                                _说(f"[记性·捡] 「{_要 or '掉落物'}」掉在 {_位}"
                                    f"（{_候[0].get('dist')} 格）—— **走过去捡** ✓"
                                    f"（手侧没有「捡」命令，走近了才自动吸附 ✓）")
                    else:
                        try:
                            _到点 = float(步.get("到点") or 2.5)
                        except Exception:
                            _到点 = 2.5
                        if _到点 < 2.4 and isinstance(步.get("p"), (list, tuple)):
                            _位 = [float(v) for v in list(步["p"])[:3]]
                            if (_今3 - float(_拾过.get("走t") or 0)) > 2.5:
                                _拾过["走t"] = _今3
                                _要发 = _位
                    if _要发:
                        _栈 = _活着任务栈()
                        _发 = getattr(_栈, "发", None) if _栈 is not None else None
                        if callable(_发):
                            # ★★★ 2026-10-10 深夜（主人：「让他直接挖完配方需要的数量然后回工作台」）：
                            #   现场：石块挖下来了 ✓ 圆石就掉在 **1.48 格**外 ✓
                            #     可它**绕着那格转了 5 圈**也捡不到 ✗（日志原话：「绕着掉落物转圈捡（第 5 圈，它在 1.5 格外）」✓）
                            #   缘由：`near: 1` = 停在**离目标 1 格**的地方 ✗ ——
                            #     而原版的吸附范围 ≈ 1 格以内 ✗ ⇒ 差那一口气，永远捡不着 ✓
                            #     （手侧注释里早写着这一条「不然它会停在 2 格外看着掉落物干等」✓
                            #        —— 我传 1 就是**又踩了同一脚** ✗）
                            #   规矩：**捡东西要走到它**那一格 ✓（`near: 0` ✓ 站上去 ✓）
                            _发({"act": "goto", "p": _要发, "near": 0})
            except Exception as _e3:
                _说(f"[记性·捡] 补发 goto 没成（{type(_e3).__name__}: {_e3}）")
            # ★★★ 2026-10-09：这一镐**是任务栈自己派的** ✓ ⇒ 立个标记，
            #   让最后一跳那道闸**放行** ✓（不然它会把它当"光杆目标"再拆一次任务 ✗
            #   = 自己拦自己 ✓ 手侧永远收不到 craft ✓）
            if _步动 == "合成":
                _放行合成[0] = True
            try:
                return 原下发(self, 步, 任, 现在, s)
            finally:
                _放行合成[0] = False

        栈类._看完成了没 = 看完成了没
        栈类._下发 = 下发

        # ══════ ★ 把"允许挖脚下"这面小旗子**送到手上** ══════
        #   2026-10-10 深夜：手侧支持 `msg.允许挖脚下` ✓ 可**命令是主链 bridge.py 拼的** ✗
        #     红线不许动 ✗ ⇒ 那就**在这儿包一层 `发`** ✓ 出去的那条 dig 上把旗子贴上 ✓
        #     （旗子由 `下发` 决定 ✓ 用完就摘 ✓ 只影响**这一步** ✓）
        原发2 = getattr(栈类, "发", None)
        if callable(原发2):
            _原发3[id(栈类)] = 原发2

            def 发(self, 东西, _原=原发2):
                try:
                    if isinstance(东西, dict) and str(东西.get("cmd") or "") == "dig":
                        if _允许脚下[0]:
                            东西 = dict(东西)
                            东西["允许挖脚下"] = True
                        _允许脚下[0] = False
                except Exception:
                    pass
                return _原(self, 东西)

            栈类.发 = 发
        _说("[记性] 降层闭环挂上了 ✓ 骨架：1宽/1高/45° ✓（挖到 Y 层为准 ✓ 一拍一判 ✓ 不是固定步数 ✓）")

    def 接(self, 名字, 步骤, s):
        try:
            # ★★★ 顺序是**先用后记** ✓ —— 我第一版写反了，当场被 C1 抓住 ✗
            #   写反的后果：计划里「放 crafting_table @新的地方」先被记下来 ✓
            #   → 把**要用的那条旧账盖掉了** ✗ → 于是又走回新地方重做 ✗
            #   一句话：**先拿本子查，再把新事记上** ✓（不能拿今天盖掉昨天 ✓）
            新步骤, 说明 = 改计划(步骤, 名字, s)
            for x in 说明:
                _说(f"[记性] {x}")
            记了 = 记计划(新步骤)
            for 名, 位 in 记了:
                _说(f"[记性] 记下了：自己把「{名}」放在 {位} ✓（下次要用就直接过去 ✓）")
            if 说明:
                return 原接(self, 名字, 新步骤, s)
        except Exception as e:
            # ★★★ 2026-10-09：**光打一句 e 不够** ✗ —— 主人截图里那句
            #   「cannot unpack non-iterable NoneType object」根本看不出是哪儿 ✓
            #   （我翻了三个函数才猜到 ✓）⇒ 连**栈**一起打 ✓（这才是"不许静默" ✓）
            import traceback as _tb
            print(f"[记性] 出岔子（不影响主链，按原样接单）：{e}", flush=True)
            print("[记性] 现场：" + " ⏪ ".join(
                f"{x.filename.split('/')[-1]}:{x.lineno} {x.name}"
                for x in _tb.extract_tb(e.__traceback__)[-4:]), flush=True)
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
        for 表, 名 in ((_原下发, "_下发"), (_原看完了, "_看完成了没")):
            try:
                栈类.__dict__  # noqa
                setattr(栈类, 名, 表[id(栈类)])
                表.pop(id(栈类), None)
            except Exception as e:
                _说(f"[记性] 还原 {名} 出岔子：{e}")
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
