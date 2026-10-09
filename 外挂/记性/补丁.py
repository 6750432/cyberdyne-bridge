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
_原下发 = {}
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
    常 = _找生存常识()
    if 常 is None:
        return None, ("✗ 摸不到「生存常识」车厢 ⇒ 这趟路我**不敢自己乱挖** ✓"
                      "（主人点过我：别抄第二遍 ✗）—— 交给物理体检拦 ✓")
    目 = list(目标)[:3]
    try:
        步, 因 = 常.安排一趟挖到(状态 or {}, 目, 背包=None, 最远=24)
    except Exception as e:
        return None, f"✗ 安排一趟挖到 出岔子（{type(e).__name__}: {e}）⇒ 不动计划 ✓"
    if not 步:
        return None, f"下不去 {目}，而「生存常识」也排不出路（{因 or '没说来由'}）⇒ 不动计划 ✓"
    挖了 = sum(1 for x in 步 if isinstance(x, dict) and x.get("动作") == "挖")
    return list(步), (f"下不去 {目}（落差 {int(我y) - int(目[1])} 格 ✗ 会摔伤 ✓）"
                    f"⇒ **照主人那套黄金模型（1宽/2高/45° ✓）交回 `安排一趟挖到`**："
                    f"{len(步)} 步（挖 {挖了} 格 ✓）（**没有自己另写一套** ✗）")


# ══════════════ 降层闭环（挂在下发与完成判据上，一拍一判 ✓）══════════════
#   规矩：**目标点导向**（挖到 Y 层 ✓）不是固定动作序列 ✓
#   每一拍看一次状态：
#     ① 已经在 Y 层 ⇒ 这一步完 ✓（完成判据收 ✓ 不发任何命令）
#     ② 掉偏了（横向离那一列 > 1 格）⇒ 补一条「走到」校正坐标 ✓
#     ③ 否则 ⇒ 挖**脚下那一格** ✓（掉不掉由它自己决定 ✓ 下一拍再看 ✓）
_降层上次 = {}          # id(任务字典) → 上次下发时刻（单调钟 ✓）

# ★★★ 主人的黄金模型（**数字一律从骨架文件读 ✓ 一个都不新发明** ✗）
#   `常识库/通道骨架.json` 原话：「这几处**不许各自写一套数字** ✗ ——
#     通道骨架**只有这一份** ✓ 改骨架就改这个文件 ✓ 用例 M 组拿它当金标准 ✓」
#   骨架自己写着怎么读：「落脚点从 (y=78,z=180) 到 (y=77,z=179)
#                        —— **y 减 1、z 减 1**」
#   ⇒ 所以降层不是"竖井挖脚下" ✗ 而是**45° 斜巷**：每下一层，**往前一格、往下 1 格** ✓
_骨架 = {"宽": 1, "高": 2, "坡度": "45°"}      # 兜底（读不到时用，并**出声** ✗）
def _读骨架():
    global _骨架
    try:
        import json as _j, os as _o
        路 = _o.path.join(_o.path.dirname(_o.path.dirname(_o.path.dirname(
            _o.path.abspath(__file__)))), "常识库", "通道骨架.json")
        with open(路, encoding="utf-8") as f:
            原 = _j.load(f)
        骨 = 原.get("骨架") or {}
        if "宽" in 骨: _骨架["宽"] = int(骨["宽"])
        if "高" in 骨: _骨架["高"] = int(骨["高"])
        if "坡度" in 骨: _骨架["坡度"] = str(骨["坡度"])
        return True
    except Exception as e:
        _说(f"[记性·降层] ✗ 读不到主人建的通道骨架（{e}）⇒ 用兜底 1宽/2高/45° ✓ **必须出声** ✗")
        return False

降层间隔秒 = 1.5
_方向表 = [(0, 1), (0, -1), (1, 0), (-1, 0)]     # 斜巷往哪边拐（动态挑 ✓）


def _降层(步, s):
    """★ 45° 斜巷降层（照主人的黄金模型 ✓）—— **一拍一判的闭环** ✓

    每一拍看状态，决定**一个**微动作 ✓：
      ① 已经在 Y 层（或更低）      ⇒ None = **完成** ✓（目标点导向 ✓ 不数步数 ✓）
      ② 横向掉偏了（离那一列 > 2）  ⇒ 补「走到」**校正坐标** ✓
      ③ 前方那格**脚下方**没挖开    ⇒ 挖 (前下方) ✓
      ④ 前方那格**头那一格**没挖开  ⇒ 挖 (前方) ✓
      ⑤ 前方两层都空               ⇒ **走到 (前下方)** ✓（一格一格下 ✓ 摔不着 ✓）
    —— 「宽 1」：只往前一格 ✓ 左右不多挖 ✓（外壳就是没挖掉的原地岩石 ✓）
    —— 「高 2」：脚一格 + 头一格 ✓（MC 里人高 1.8 格 ✓ 两格正够站正够跳 ✓）
    """
    p = 步.get("p") or []
    if len(p) < 3:
        return None, "降到 这一步没写全坐标 ✗"
    x, Y, z = int(p[0]), int(p[1]), int(p[2])
    我 = (s or {}).get("pos")
    if not 我 or len(我) < 3:
        return {"动作": "走到", "p": [x, Y, z], "到点": 3.0}, \
            "看不到我的坐标 ⇒ 退回普通走到（可能会摔 ✗ 但比闷着强 ✓）"
    mx, my, mz = int(我[0]), int(我[1]), int(我[2])
    if my <= Y:
        return None, ""                                       # ★ 到层了 ✓ 完成 ✓
    if abs(mx - x) > 2 or abs(mz - z) > 2:
        return {"动作": "走到", "p": [x, my, z], "到点": 1.5}, "掉偏了 ⇒ 走回那一列（校正坐标 ✓）"
    # 斜巷方向：**优先朝目标列那边拐** ✓ 否则按方向表挑一个（下一拍看结果再定 ✓）
    dx = (1 if x > mx else (-1 if x < mx else 0))
    dz = (1 if z > mz else (-1 if z < mz else 0))
    候选 = [(dx, dz)] if (dx or dz) else []
    候选 += [d for d in _方向表 if d not in 候选]
    # 看世界（状态帧里的扫描 ✓）：前下方 / 前方 这两格是什么
    看到 = {}
    for 名 in ("扫描", "方块", "blocks"):
        对 = (s or {}).get(名)
        if isinstance(对, dict):
            看到 = 对
            break
    def 是空气(坐标):
        对 = 看到.get("%d,%d,%d" % tuple(坐标)) or 看到.get("%d %d %d" % tuple(坐标))
        if isinstance(对, dict):
            对 = 对.get("名") or 对.get("name")
        return (str(对) in ("air", "cave_air", "void_air")) if 对 else None
    for ddx, ddz in 候选:
        nx, nz = mx + ddx, mz + ddz
        脚 = [nx, my - 1, nz]        # ★ 下一个落脚点（前下方 ✓ y 减 1 ✓）
        头 = [nx, my, nz]            # ★ 头那一格（前方 ✓ 高 2 的另一格 ✓）
        脚空, 头空 = 是空气(脚), 是空气(头)
        if 脚空 is False:            # 已知不是空气 ⇒ 挖开它 ✓
            return {"动作": "挖", "p": 脚}, "斜巷：先挖开前下方 ✓（45° 下一层落脚点 ✓）"
        if 头空 is False:
            return {"动作": "挖", "p": 头}, "斜巷：挖开前方那一格 ✓（高 2 ⇒ 头得过得去 ✓）"
        if 脚空 is True and 头空 is True:
            return {"动作": "走到", "p": 脚, "到点": 1.5}, \
                "斜巷：前下方两层都空 ⇒ 走进去 ✓（一格一格下 ✓ 摔不着 ✓）"
    # 看不出前面是什么（扫描里没有那几格）⇒ 老老实实挖脚下那一格 ✓ 并出声 ✓
    return {"动作": "挖", "p": [mx, my - 1, mz]}, \
        "前面那几格不在扫描里 ⇒ 退一步挖脚下 ✓（下一拍再看 ✓）"


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
            if 位 is not None and 太深:
                说明.append(f"账上那个工作台在 {位}，比我现在低 {落差:.0f} 格 ✗"
                            f"（落差 > 3 会摔伤 ✓ 物理体检拦得对 ✓）"
                            f"⇒ **就地重做一个** ✓（4 块木板的事 ✓）")
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
                路, 为啥 = 铺路向下(我[1], 步["p"], 状态)
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
    _原[id(栈类)] = 原接

    # ══════ 降层闭环（主人 2026-10-09 亲自定的形状 ✓）══════
    #   挂在**下发**和**完成判据**上 ⇒ 一拍一判 ✓ 不是固定序列 ✓
    #     ① 已经在 Y 层 ⇒ 完成 ✓（不发任何命令）
    #     ② 掉偏了 ⇒ 补一条「走到」校正坐标 ✓
    #     ③ 否则 ⇒ 挖脚下那一格 ✓（掉不掉由它自己决定 ✓ 下一拍再看 ✓）
    #   ⚠ 间隔 1.5 秒：**别每拍重发** ✗ —— 重发会把正在跑的那条路掐断 ✓（老坑 ✓）
    #   ⚠ 判据走**单调钟** ✓（老祖课第五课：墙钟会被拽 ✓）
    原下发 = getattr(栈类, "_下发", None)
    原看完了 = getattr(栈类, "_看完成了没", None)
    if callable(原下发) and callable(原看完了):
        _原下发[id(栈类)] = 原下发
        _原看完了[id(栈类)] = 原看完了

        def 看完成了没(self, 步, s, 任=None):
            try:
                if isinstance(步, dict) and 步.get("动作") == "降到":
                    我 = (s or {}).get("pos") or [0, 0, 0]
                    if int(我[1]) <= int((步.get("p") or [0, 0, 0])[1]):
                        return True, None        # ★ **到层了** = 这一步完 ✓（目标点导向 ✓）
                    return False, None
            except Exception as e:
                _说(f"[记性·降层] 完成判据出岔子（按原样走 ✓）：{e}")
            return 原看完了(self, 步, s, 任)

        def 下发(self, 步, 任, 现在, s):
            try:
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
            return 原下发(self, 步, 任, 现在, s)

        栈类._看完成了没 = 看完成了没
        栈类._下发 = 下发
        _读骨架()
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
            print(f"[记性] 出岔子（不影响主链，按原样接单）：{e}", flush=True)
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
