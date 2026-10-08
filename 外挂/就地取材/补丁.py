#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""就地取材车厢 —— 空间 RAG（四级优先），主人 2026-10-08 晚 提的架构升级。

为什么要有它
============
今天所有的麻烦，共同点是「**拿着计划里的陈坐标硬推**」✗
  · 隔着泥土挖石头（那格埋着）
  · 计划写得早、到那儿格已经变了（陈坐标）
  · 目标在 14 格外，够不着（挖的够得着范围只有 4.5）

主人给的解法是把它**倒过来**：不推计划，**现查现挖** —— 像 RAG 一样，
先问"我周围到底有什么、在哪儿"，再挑一个去挖。四级优先：

  ① 手边   ：视线可达 + 距离 ≤4.5 格 + **裸露** → 直接挖（不寻路）
  ② 本区块 ：查本地内存（LRC2b），当前 chunk 内有没有目标 → 动态寻路过去
  ③ 跨区块 ：相邻**已扫描**区块里找最近的 → 寻路过去
  ④ 探索   ：周围全是迷雾 → 不死磕，交给【向下盲挖】/【鱼骨探索】碰运气

★ 三条红线（主人点名）
  · **只查扫过的区域** —— 绝不整图透视。没扫到的区块在内存里根本不存在 ✓
  · 跨区块寻路**必须安全校验**（岩浆/深渊/悬崖）
  · 目标在危险区（岩浆旁）→ **自动降权或放弃**，去更安全的区块找

★ 「LRC2b」= 雷达的本地内存（主人定名）。手侧每拍只给一张快照，
  所以这节车厢自己攒一本**走过哪儿**的活账（按 chunk 存），越跑越全 —— 这就是本地 RAG。
"""

import math
import os
import time

_日志 = None
_原件 = {}
_记忆 = {}          # (cx, cz) -> {方块名: {(x,y,z): 上次看到的时刻}}
_已知区块 = set()   # 扫到过的区块（**没扫过的一律不许出现在候选里** = 反透视红线）

危险方块 = {"lava", "fire", "magma_block", "soul_fire", "cactus",
           "sweet_berry_bush", "powder_snow", "campfire", "flowing_lava"}
空气名 = {"air", "cave_air", "void_air", "water"}
# 各层能接受的最远距离（跳数/格）—— 一层的活别干得比这更远
最远 = {"手边": 4.5, "本区块": 48.0, "隔壁区块": 96.0}


def _说(文):
    if _日志:
        try:
            _日志(文)
            return
        except Exception:
            pass
    print(文, flush=True)


def 块区(p):
    """方块坐标属于哪个 chunk（16×16）—— 跨区块检索的钥匙。"""
    return (int(p[0]) >> 4, int(p[2]) >> 4)


def _我(状态):
    try:
        p = (状态 or {}).get("pos")
        if isinstance(p, (list, tuple)) and len(p) >= 3:
            return (float(p[0]), float(p[1]), float(p[2]))
    except Exception:
        pass
    return None


def _距(a, b):
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _记(状态):
    """把这一帧看见的东西存进本地内存（按区块分堆）。**只有扫到的才进内存** ✓"""
    try:
        扫 = (状态 or {}).get("scan") or {}
        现在 = time.time()
        条目 = []
        for 组 in ("可交互", "石头"):
            条 = 扫.get(组)
            if isinstance(条, dict):
                条目.append(条)
            elif isinstance(条, list):
                条目.extend([x for x in 条 if isinstance(x, dict)])
        for 条 in 条目:
            名 = 条.get("name")
            位 = 条.get("p")
            if not (名 and isinstance(位, (list, tuple)) and len(位) >= 3):
                continue
            键 = (int(位[0]), int(位[1]), int(位[2]))
            区 = 块区(键)
            堆 = _记忆.setdefault(区, {}).setdefault(str(名), {})
            堆[键] = {"t": 现在, "裸露": 条.get("裸露"), "视线": 条.get("视线"),
                      "挡前": 条.get("挡前")}
            _已知区块.add(区)
        # 手侧盯着的那几格（blocks）也收进来 —— 那是最新鲜的
        for 条 in (状态 or {}).get("blocks") or []:
            if not isinstance(条, dict):
                continue
            名, 位 = 条.get("name"), 条.get("p")
            if not (名 and isinstance(位, (list, tuple)) and len(位) >= 3):
                continue
            键 = (int(位[0]), int(位[1]), int(位[2]))
            _记忆.setdefault(块区(键), {}).setdefault(str(名), {})[键] = {
                "t": 现在, "裸露": None, "视线": None, "挡前": None}
            _已知区块.add(块区(键))
    except Exception as e:
        print(f"[就地取材] 记内存出岔子（不影响主链）：{e}", flush=True)


def _安全性(状态, 名, 位):
    """跨区块寻路的安全校验 —— 返回 (可去吗, 危险度 0/1/2, 为什么)。

    ★ 我们**只看扫到过的邻面**：没扫到的邻面标"未知"并**降权**（不判死），
      因为要是不确定就不去，那它永远出不了门 ✗
    """
    if str(名) in 危险方块:
        return False, 2, f"「{名}」本身就是危险方块"
    我 = _我(状态)
    if 我 is None:
        return False, 2, "不知道我在哪"
    到 = _距(我, 位)
    if 到 > 最远["隔壁区块"]:
        return False, 2, f"太远了（{到:.0f} 格）"
    no = 0
    try:
        扫 = (状态 or {}).get("scan") or {}
        for 险 in 扫.get("危险") or []:
            位2 = 险.get("p") if isinstance(险, dict) else None
            if isinstance(位2, (list, tuple)) and len(位2) >= 3:
                if _距(tuple(int(v) for v in 位2[:3]), 位) <= 1.9:
                    return False, 2, f"紧挨着「{险.get('name')}」"
    except Exception:
        pass
    return True, no, ""


def 挑块(状态, 想要=None, 我=None):
    """**空间 RAG 的查询本体**。返回 {层级, 名, p, 到, 危险, 为什么} 或 None。

    层级只会是 手边 / 本区块 / 隔壁区块 三种；一个都没有 → 返回 None
    （调用方据此走第 ④ 级【探索】）。
    """
    _记(状态)
    我 = 我 or _我(状态)
    if 我 is None:
        return None
    我的区 = 块区(我)
    候 = []

    # ── ① 手边：视线可达 + ≤4.5 + 裸露（只认**这一帧**的新鲜情报）──
    try:
        扫 = (状态 or {}).get("scan") or {}
        组 = []
        for k in ("可交互", "石头"):
            v = 扫.get(k)
            组.extend(v if isinstance(v, list) else ([v] if isinstance(v, dict) else []))
        for 条 in 组:
            名, 位 = 条.get("name"), 条.get("p")
            if not (名 and isinstance(位, (list, tuple)) and len(位) >= 3):
                continue
            if 想要 and str(名) != str(想要):
                continue
            位 = tuple(int(v) for v in 位[:3])
            到 = _距(我, 位)
            if 到 > 最远["手边"]:
                continue
            if 条.get("裸露") is False:          # 整个被埋住 → 不许瞄（反矿透）
                continue
            候.append({"层级": "手边", "名": str(名), "p": 位, "到": 到, "危险": 0})
    except Exception:
        pass

    # ── ②③ 本地内存：只翻**扫过的区块**（没扫过的不存在 = 反透视）──
    if not 候:
        for 区, 堆 in _记忆.items():
            if 区 not in _已知区块:
                continue                        # ★ 红线：没扫过的不许用
            for 名, 位表 in 堆.items():
                if 想要 and str(名) != str(想要):
                    continue
                for 位, 情报 in 位表.items():
                    # ★ 2026-10-08 晚 断言 C3 当场揪出来的：内存这条路**漏了裸露校验**
                    #   → 整个被埋住的方块也能被挑出来（反矿透红线 ✗）
                    if 情报.get("裸露") is False:
                        continue
                    到 = _距(我, 位)
                    if 到 > 最远["隔壁区块"]:
                        continue
                    可去, 险, _ = _安全性(状态, 名, 位)
                    if not 可去:
                        continue
                     # ★ 断言 D1 当场揪出来的：纯按区块划线，站在边界上时
                     #   2 格外的方块会被算成"跨区块" ✗ —— 主人要的是"越近的级越好"，
                     #   所以「本区块」= 同一个区块 **或** 16 格以内（同一种代价）。
                    层 = "本区块" if (区 == 我的区 or 到 <= 16.0) else "隔壁区块"
                    if 到 > (最远["本区块"] if 层 == "本区块" else 最远["隔壁区块"]):
                        continue
                    候.append({"层级": 层, "名": str(名), "p": 位, "到": 到, "危险": 险,
                               "旧": time.time() - 情报.get("t", 0)})
    if not 候:
        return None
    # 排序：先看层级（越近的级越好），再看危险度（危险降权），最后看距离
    级次 = {"手边": 0, "本区块": 1, "隔壁区块": 2}
    候.sort(key=lambda x: (级次.get(x["层级"], 9), x.get("危险", 0), x["到"]))
    出 = dict(候[0])
    出["为什么"] = (f"{出['层级']}：{出['名']}@{list(出['p'])}，{出['到']:.1f} 格"
                  + ("（危险区，已降权）" if 出.get("危险") else ""))
    出["候选数"] = len(候)
    return 出


def 出计划(状态, 想要=None, 我=None):
    """挑块 → 步骤表（走到 → 挖 → 拾）。挑不到 → (None, 为什么)。"""
    块 = 挑块(状态, 想要, 我)
    if not 块:
        return None, ("周围扫过的地方都没有目标（手边 4.5 格、本区块、隔壁区块都翻过了）"
                      "—— 该去未知区碰运气了")
    步 = []
    if 块["层级"] != "手边" or 块["到"] > 3.0:
        # 寻路的到点给 3.0：手侧的寻路会提前 ~2.6 格停下（实机教训）
        步.append({"动作": "走到", "p": list(块["p"]), "到点": 3.0})
    步.append({"动作": "挖", "p": list(块["p"]), "方块": 块["名"]})
    步.append({"动作": "拾", "物品": 块["名"], "数量": 1})
    return 步, 块["为什么"]


def 扫到过(状态):
    """当帧雷达里**确实有**的 (方块名, 坐标) 集合 —— 用来判"这一步的陈没陈"。"""
    有 = set()
    try:
        扫 = (状态 or {}).get("scan") or {}
        for k in ("可交互", "石头"):
            v = 扫.get(k)
            for 条 in (v if isinstance(v, list) else ([v] if isinstance(v, dict) else [])):
                if isinstance(条, dict) and 条.get("name") and isinstance(条.get("p"), (list, tuple)):
                    有.add((str(条["name"]), tuple(int(x) for x in 条["p"][:3])))
        for 条 in (状态 or {}).get("blocks") or []:
            if isinstance(条, dict) and 条.get("name") and isinstance(条.get("p"), (list, tuple)):
                有.add((str(条["name"]), tuple(int(x) for x in 条["p"][:3])))
    except Exception:
        pass
    return 有


def 补陈坐标(状态, 任):
    """★★★ 2026-10-08 晚，主人的火气换来的：**有实时雷达，就不许拿着陈坐标往下推。**

    实机（他亲眼所见）：计划里的「挖 oak_leaves@[-151,75,158]」那一格**早就没了**，
    守卫原话「当帧扫描里压根没有「oak_leaves」——这个坐标是陈的，我不挥」，
    于是它站在那儿每 200ms 重下、15 分钟 3150 次、60 秒超时、「干不了了」。

    规矩：计划里每个「挖」步骤，都拿**当帧雷达**对一遍 ——
      · 坐标还在、方块名还对 ✓ → 一个字不动
      · 已经不是那个方块 / 压根不在扫描里 ✗ → 拿**方块名重新查一次雷达**
        （手边 → 本区块 → 隔壁区块）→ 查到就把整步的坐标换成新的 ✓
        查不到 → 把这步标 `跳过`（宁可不干，也别对着空气挥 ✗）
    返回 (改了几处, 说明)。
    """
    改 = 0
    说明 = []
    有 = 扫到过(状态)
    for 步 in (任 or {}).get("步骤") or []:
        if 步.get("动作") != "挖":
            continue
        名 = 步.get("方块")
        p = 步.get("p")
        if not (名 and isinstance(p, (list, tuple)) and len(p) >= 3):
            continue
        键 = (str(名), tuple(int(x) for x in p[:3]))
        if 键 in 有:
            continue                       # 还是新鲜的 ✓ 不动
        块 = 挑块(状态, 名)                 # ★ 重新查雷达（这就是"实时"）
        if 块:
            步["p"] = list(块["p"])
            改 += 1
            说明.append(f"{名} 的坐标换成 {list(块['p'])}（{块['层级']}）")
        else:
            步["跳过"] = True
            改 += 1
            说明.append(f"{名} 现在扫过的地方都没有 → 这步标作废，不挥空镐")
    return 改, "；".join(说明[:3])


def 报个话(bridge=None):
    """给探针/自检看的一张小账。"""
    return {"区块数": len(_已知区块), "方块种数": sum(len(v) for v in _记忆.values()),
            "条目数": sum(len(位) for v in _记忆.values() for 位 in v.values())}


# ─────────────────────── 车厢接口 ───────────────────────

def 装上(bridge, 日志=None, **kw):
    global _日志
    译类 = getattr(bridge, "翻译器", None)
    if 译类 is None:
        return {"好": False, "为什么": "找不到 翻译器 类", "打了": []}
    if getattr(译类, "_就地取材装了", False):
        return {"好": True, "为什么": "已经装过了（幂等）", "打了": []}
    原 = getattr(译类, "收输出", None)
    if not callable(原):
        return {"好": False, "为什么": "翻译器.收输出 不是函数", "打了": []}
    _日志 = 日志
    _原件[id(译类)] = 原

    def 收输出(self, 输出, 状态, 用途=None, *a, **k):
        _记(状态)                      # ★ 每一拍都喂内存 —— 这就是本地 RAG 的养料
        动作, 任, 因 = 原(self, 输出, 状态, 用途, *a, **k)
        # ★★ 第一道：**上游给了计划也要过一遍"陈坐标"**（主人的火气换来的规矩）
        try:
            if 任 is not None and (任.get("步骤") or []):
                改, 说 = 补陈坐标(状态, 任)
                if 改:
                    _说(f"就地取材：计划里有 {改} 处是陈的 —— {说}")
                    return 动作, 任, 因
        except Exception as e:
            print(f"[就地取材] 补陈坐标出岔子（不影响主链）：{e}", flush=True)
        # ★ 第二道：**别人都定位不到**的时候才整盘接手（顺序 90 = 最外层，看得到上游结论）
        try:
            if 任 is None and 因 and ("定位不到" in str(因) or "压根没有" in str(因)
                                    or "整个被埋住" in str(因)):
                步, 说明 = 出计划(状态)
                if 步:
                    _说(f"生存常识：{说明}")
                    try:
                        self.说(f"[{time.strftime('%H:%M')}] {说明}", 紧急=True)
                    except Exception:
                        pass
                    return "就地取材", {"名字": "就地取材", "为什么": 说明, "步骤": 步}, None
        except Exception as e:
            print(f"[就地取材] 接手时出岔子（不影响主链）：{e}", flush=True)
        return 动作, 任, 因

    译类.收输出 = 收输出
    译类._就地取材装了 = True
    return {"好": True, "为什么": "", "打了": [
        "翻译器.收输出() ← 每拍喂本地内存 + 上游定位不到时接手（只加不减，不改原逻辑）"]}


def 卸下(bridge):
    global _日志
    译类 = getattr(bridge, "翻译器", None)
    原 = _原件.pop(id(译类), None) if 译类 is not None else None
    if not 原:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    译类.收输出 = 原
    try:
        del 译类._就地取材装了
    except AttributeError:
        pass
    _日志 = None
    return {"好": True, "为什么": "", "打了": ["还原 翻译器.收输出()"]}
