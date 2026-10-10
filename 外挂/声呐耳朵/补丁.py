#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""声呐耳朵车厢 —— 听见主人说话，当场认口令、当场接单，不等心跳。

主人 2026-10-08 晚 的原话
======================
「反应过来就应该立刻动身啊，那怎么我找他帮忙还以为他在思考呢？」

他说得对。手侧其实很及时 —— 日志里 `[21:59] 听见 mintstar 说：…` 一收到就报过来 ✓
慢的是**脑**：它要等下一次**心跳**才轮到这个活 ✗
中间那几秒它就站着，看上去像在发呆（主人：「他明明是站在我对面没怎么动的」）。

这节车厢照 **声呐外挂** 那套结构（手侧探针 + 核心 + 连耦）做一只「耳朵」，
只不过它挂在**脑侧**的事件口上：

    叙事者.看事件(e)   ← 聊天从这儿进来
        ↓  kind == "chat"
    ① 把这句原话记进「上次原话」（生存常识的 认口令 靠它，拼音也认 ✓）
    ② 拿 self.最后状态（叙事者每拍都存着当前扫描帧 ✓）
    ③ 立刻走一遍翻译器的 收输出()（= 立刻做计划，**不等心跳**）
    ④ 当场 任务栈.接(名字, 步骤, s)（接单入口自带"没登记的动作就拒单"的锁 ✓）

从「听见」到「迈腿」就是同一秒 ✓

规矩
====
· **原来那条路一个字不改** —— 包装函数先把原件跑完，再走耳朵 ✓
· **耳朵听不清不许把脑弄哑** —— 任何异常都吞在耳朵里（但会报出来 ✓ 不静默 ✗）
· 找不到元件（翻译器/任务栈/认口令）就**什么都不做**，并说清为什么 ✓
"""

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_日志 = None
_原件 = {}

# ── 「叮」那一路（2026-10-09 主人点名：盲挖中听见「叮」→ 立刻插队去挖）──
#   岩浆音：冒泡那声「叮」是 `block.lava.pop` ✓ 另外两条一起认着（同源信号 ✓）
岩浆音 = ("block.lava.pop", "block.lava.ambient", "block.lava.extinguish")
#   1.21 的钻石层：y=-64 ~ 16，最密在 y=-59 ~ -53 ✓（wiki + 官方改动日志）
#   岩浆湖一律生成在 y≤10 ✓ → y 比 16 高就没必要为一个提示往下钻 ✓
钻石层 = (-64, 16)
_追叮上次 = {}          # 声源坐标 -> 上次追的时刻（去重用）
_追叮几次 = 0
_桥 = None              # 装上的时候存一份（追「叮」要它去摸任务栈 ✓）


def _说(文):
    if _日志:
        try:
            _日志(文)
            return
        except Exception:
            pass
    print(文, flush=True)


def _找认口令模块():
    """鸭子类型地找「生存常识」那节车厢（它提供 认口令 / _上次原话）。

    ⚠ 不按模块名找 —— 车厢是被 importlib 用别的名字载进来的 ✗
      按**有没有那个函数**找，谁有就用谁（找不到就返回 None，什么都不做）✓
    """
    for m in list(sys.modules.values()):
        try:
            if callable(getattr(m, "认口令", None)) and hasattr(m, "_上次原话"):
                return m
        except Exception:
            continue
    return None


def 听动静(叙事者, e, 桥=None):
    """手侧声呐报上来的"动静"（音效）—— 落在 logs/声呐.jsonl，要命的当场喊出来。

    ★ 跟"耳朵"是两件事：耳朵听**字**（聊天口令），这里听**动静**（音效事件）✓
      主人 2026-10-08 晚：「他现在在自己没事的时候能听见附近的动静了？」
      —— 手侧声呐（outbox 里那份 K0-K3 验收过的）接上之后，这就成立了 ✓
    """
    try:
        级 = str((e or {}).get("级别") or "")
        名 = str((e or {}).get("名") or (e or {}).get("名字") or "动静")
        # ⚠ 键名认多一点：手侧那份声呐用的是它自己的字段名，
        #   我这边别再"猜一个键" ✗（E2 就是这么挂的：我用「距」，它读「距离/环」）
        方 = ""
        for k in ("方位", "方向", "方", "dir", "bearing"):
            方 = str((e or {}).get(k) or "")
            if 方:
                break
        距 = ""
        for k in ("距离", "距", "环", "ring", "dist"):
            距 = (e or {}).get(k) or ""
            if 距:
                break
        位 = (e or {}).get("位置") or (e or {}).get("坐标") or (e or {}).get("p")
        try:
            路 = os.path.join(ROOT, "logs", "声呐.jsonl")
            os.makedirs(os.path.dirname(路), exist_ok=True)
            with open(路, "a", encoding="utf-8") as f:
                f.write(json.dumps({"级别": 级, "名": 名, "方位": 方, "距": 距,
                                    "位": 位, "t": round(time.time(), 3)},
                                   ensure_ascii=False) + "\n")
        except Exception:
            pass
        if 级 == "urgent":          # 要命的即刻喊；frame 只落账，不刷屏 ✓
            尾巴 = f"（{方} {距}）".strip("（）") if (方 or 距) else ""
            叙事者.说(f"[{time.strftime('%H:%M')}] 我听见「{名}」"
                     + (f" —— {尾巴}" if 尾巴 else "") + "！", 紧急=True)
            return f"听见动静：{名} {尾巴}"
        # ★★★ 2026-10-09 主人点名：盲挖中听见「叮」→ **立刻插队去挖** ✓
        #   ⚠ 位置在这儿是**故意的**：主链原来那条路（上面那一整段）**一个字不改** ✓
        #     追「叮」是**加在它后面**的下一步 ✓（原件先把该喊的喊了、该记的记了 ✓）
        try:
            追 = 追叮(_桥, 叙事者, e)
        except Exception as ex2:
            print(f"[声呐耳朵] 追「叮」那一句出岔子：{ex2}", flush=True)
            追 = None
        if 追:
            try:
                叙事者.说(f"[{time.strftime('%H:%M')}] {追}", 紧急=True)
            except Exception:
                pass
            return 追
    except Exception as ex:
        print(f"[声呐耳朵] 听动静出岔子（不影响主链）：{ex}", flush=True)
    return None


def 追叮(bridge, 叙事者, e):
    """听见「叮」（`block.lava.pop`）→ **当场插队去挖**。返回一句说明或 None。

    主人 2026-10-09 点名
    ==================
    「盲挖中听见『叮』→ 立刻插队去挖」

    为什么「叮」值钱（老玩家的常识）
    ==============================
    `block.lava.pop` 是岩浆湖冒泡那一声「叮」✓ —— **附近有岩浆湖**的强信号 ✓
    而钻石就长在深层岩浆湖旁边 ✓（1.21 的钻石层：y=-64 ~ 16，
    最密在 **y=-59 ~ -53**；岩浆湖一律生成在 y≤10 ✓）
    所以听见「叮」= 很可能挖到宝了 ✓ **这条线索比一路盲挖值钱得多** ✓

    ⚠ 但只有一半管用，另一半得**自己判** ✗
    ==============================
    手侧的声呐表（`声音速查_1.21.1.json`）把岩浆那几条标成「警惕 / 威胁 2」✓
    而**只有标「反射」档的才会走 urgent 即刻上报** ✗
    → 光靠手侧，这一声只会随状态帧慢慢过来 ✓
    所以本车厢**在脑侧自己认**：不管它走的是 urgent 还是 frame，
    只要音名是岩浆那几条，就当场判、当场插队 ✓

    ⚠ 什么时候**不**去挖（都是拿血换的）
    ==================================
    1. **不在钻石层就不挖** ✗ —— y>16 的地表岩浆湖旁边没有钻石 ✓
       这一条是"别为了一个提示白挖半天" ✓ 只喊一声、记一笔 ✓
    2. **没有活的任务栈 / 没有扫描帧** → 不接单，照实说 ✓
    3. **排不出路**（太远/太陡）→ 不接单，把理由说出来 ✓
    4. **同一个位置 30 秒内只追一次** ✓（岩浆泡一直在响 ✗ 不去重会疯 ✗）
    """
    global _追叮上次, _追叮几次
    try:
        e = e or {}
        # ★ 认名字要**多认几个键** ✓ —— 手侧那种 payload 用的是 `音名` ✓
        #   可走状态帧窗口那一路的条目，`名` 里放的是**人话**（「附近有危险源」）✗
        #   别把"人话"当音名去对（对不上就会**静默漏掉** ✓ 这正是"链子看着通、其实没通"）
        #   规矩：**每个候选值都要含 `领域.名字` 那个点** ✓ 人话里没有点 ✓
        名 = ""
        for _k in ("音名", "sound", "soundName", "名", "名字"):
            _v = str((e or {}).get(_k) or "")
            if "." in _v:
                名 = _v
                break
        if 名 not in 岩浆音:
            return None                      # 不是岩浆那几条 → 不碰 ✓
        位 = e.get("坐标") or e.get("位置") or e.get("p")
        if not (isinstance(位, (list, tuple)) and len(位) >= 3):
            return None                      # 没有声源坐标 → 没法追 ✓
        状态 = getattr(叙事者, "最后状态", None)
        if not 状态:
            return "听见「叮」了，可这一拍没拿到扫描帧 —— 等下一拍"
        我 = (状态 or {}).get("pos")
        if not (isinstance(我, (list, tuple)) and len(我) >= 3):
            return "听见「叮」了，可不知道我自己在哪 —— 先不动"
        脚下 = int(float(我[1]) // 1)
        # ── 规矩 1：不在钻石层就不挖 ✓（只喊一声、记一笔）──
        if not (钻石层[0] <= 脚下 <= 钻石层[1]):
            return (f"听见「叮」（岩浆泡）@{[int(位[0]), int(位[1]), int(位[2])]} —— "
                    f"可我在 y={脚下}（钻石层是 y={钻石层[0]}~{钻石层[1]}），"
                    f"这儿的岩浆旁边没有钻石 ✗ 记一笔，不下去追")
        # ── 规矩 4：同一个位置 30 秒内只追一次 ✓ ──
        键 = (int(float(位[0])), int(float(位[1])), int(float(位[2])))
        现在 = time.time()
        if 现在 - _追叮上次.get(键, -9999.0) < 30.0:
            return None
        栈 = _活实例(bridge, "任务栈")
        if 栈 is None:
            return f"听见「叮」@{list(键)}，可找不到活着的任务栈 —— 追不了 ✗"
        # ── 规矩 3：排路（挖过去就复用生存常识那一份实现 ✓ 不抄第二遍 ✓）──
        生 = _找挖路模块()
        if 生 is None:
            return f"听见「叮」@{list(键)}，可找不到「安排一趟挖到」—— 排不出路 ✗"
        步, 因 = 生.安排一趟挖到(状态, list(键), 背包=None, 最远=16)
        if not 步:
            _追叮上次[键] = 现在
            return f"听见「叮」@{list(键)}，可排不出路：{因}"
        好 = 栈.接(f"追「叮」：挖到岩浆泡那儿（{list(键)}）", 步, 状态)
        if not 好:
            return f"听见「叮」@{list(键)}，路排好了（{len(步)} 步），可任务栈不接 ✗"
        _追叮上次[键] = 现在
        _追叮几次 += 1
        return (f"★ 听见「叮」（岩浆泡）@{list(键)} —— 钻石就在这种地方！"
                f"我当场插队去挖（{len(步)} 步，第 {_追叮几次} 次）")
    except Exception as ex:
        print(f"[声呐耳朵] 追「叮」出岔子（不影响主链）：{ex}", flush=True)
        return None


def _找挖路模块():
    """鸭子类型地找「生存常识」那节车厢里的 `安排一趟挖到` ✓（不抄第二遍 ✓）"""
    for m in list(sys.modules.values()):
        try:
            if callable(getattr(m, "安排一趟挖到", None)):
                return m
        except Exception:
            continue
    return None





def _活实例(bridge, 类名):
    """车钩的探针登记过的活实例（取最后一个）。"""
    try:
        类 = getattr(bridge, 类名, None)
        活 = list(getattr(类, "车钩活着的实例", []) or [])
        return 活[-1] if 活 else None
    except Exception:
        return None


def 接单(bridge, 叙事者, e):
    """听见一句话 → 立刻认口令、立刻做计划、立刻接单。返回一句说明或 None。"""
    原话 = str((e or {}).get("text") or "").strip()
    谁 = str((e or {}).get("from") or "?")
    if not 原话:
        return None
    常 = _找认口令模块()
    if 常 is None:
        return "耳朵没找到「认口令」（生存常识车厢不在？）"
    # ① 记进「上次原话」—— 认口令 就是靠它 + 90 秒时效判断的
    try:
        常._上次原话.update({"原话": 原话, "时刻": time.time(), "说话人": 谁})
    except Exception as ex:
        return f"耳朵记原话失败：{ex}"
    目标 = None
    try:
        目标 = 常.认口令()
    except Exception as ex:
        return f"耳朵认口令炸了：{ex}"
    if not 目标:
        return None                      # 不是口令，正常聊天，不管 ✓
    # ② 当前扫描帧（叙事者每拍都存着）
    状态 = getattr(叙事者, "最后状态", None)
    if not 状态:
        return f"认出口令「{目标}」，可叙事者还没有扫描帧 —— 等下一拍"
    # ③ 立刻做计划（不等心跳）
    译 = _活实例(bridge, "翻译器")
    if 译 is None:
        return f"认出口令「{目标}」，可是找不到活着的翻译器"
    # ══════ ★★★ 主人 2026-10-09：「LLM 的翻译太不可控了，做本地确定性翻译！」══════
    #   顺序（主人定的）：① 本地精确句式 ✓ ② 本地正则（带数量 ✓）
    #     两层都 Miss ⇒ 才用老路（空串 ⇒ 交给生存常识的意图兜底 / LLM 那条慢路 ✓）
    _文本 = ""
    _本地话 = ""
    try:
        import 本地翻译器 as _本译
        _映射 = None
        try:
            _映射 = 常._名字表()
        except Exception:
            _映射 = None
        _本地 = _本译.译一句(原话, 物品映射=_映射)
        if _本地 and _本地.get("目标"):
            import json as _json
            _文本 = _json.dumps({"意图": "要", "目标": _本地["目标"],
                                "数量": int(_本地.get("数量") or 1)},
                               ensure_ascii=False)
            # ⚠ 这里**只记文本** ✓ 不 return 别的东西 ✗ ——
            #   `接单` 的契约是「返回一句说明 或 None」✓
            #   （我第一版顺手塞了个四元组 ✗ 自己回头看出来的 ✓）
            _本地话 = (f"（本地翻译器·{_本地.get('层')}：要 {_本地['目标']}"
                      f" × {_本地.get('数量') or 1} ✓ 不花大模型 ✓）")
    except Exception:
        pass
    try:
        动作, 任, 因 = 译.收输出(_文本, 状态, 用途="聊天·耳朵")
    except Exception as ex:
        return f"耳朵做计划炸了：{ex}"
    if not (isinstance(任, dict) and 任.get("步骤")):
        return f"认出口令「{目标}」，可这一拍推不出步骤（{str(因)[:60]}）"
    # ④ 当场接单
    栈 = _活实例(bridge, "任务栈")
    if 栈 is None:
        return f"排出 {len(任['步骤'])} 步，可是找不到活着的任务栈"
    try:
        import tempfile
        好 = 栈.接(任.get("名字") or 目标, 任.get("步骤"), 状态)
    except Exception as ex:
        return f"耳朵接单炸了：{ex}"
    if 好:
        return (f"耳朵接单 ✓：「{目标}」{len(任['步骤'])} 步 —— "
                f"{动作 or ''}（听见就动身，没等心跳）")
    # ★★★ 2026-10-09 主人：「把"拒单点名"补上」✓
    #   从前这里是一句**自己编的笼统话** ✗（「任务栈说这个活里有没登记的动作」✓）
    #   结果：主人和我都只能猜到底是哪个动作 ✗ —— 而且**猜错过一次** ✓
    #   规矩（今晚第 N 次）：**拒单必须点到具体名字** ✗
    #     栈返回什么 ✓ 计划里都有哪些动作 ✓ 白名单现在长什么样 ✓ —— 三样一起打 ✓
    _动作们 = sorted({str((x or {}).get("动作")) for x in (任.get("步骤") or [])})
    _白 = sorted(getattr(栈, "允许动作", []) or [])
    return (f"耳朵接单被拒：「{目标}」{len(任['步骤'])} 步 —— "
            f"**栈.接 返回 {好!r}** ｜ 计划里的动作 {_动作们} ｜ 白名单 {_白} ｜ "
            f"不在白名单的 {sorted(set(_动作们) - set(_白))}")


# ─────────────────────── 车厢接口 ───────────────────────

def 装上(bridge, 日志=None, **kw):
    global _日志, _桥
    _日志 = 日志
    _桥 = bridge
    叙类 = getattr(bridge, "叙事者", None)
    if 叙类 is None:
        return {"好": False, "为什么": "找不到 叙事者 类", "打了": []}
    if getattr(叙类, "_声呐耳朵装了", False):
        return {"好": True, "为什么": "已经装过了（幂等）", "打了": []}
    原看事件 = getattr(叙类, "看事件", None)
    if not callable(原看事件):
        return {"好": False, "为什么": "叙事者.看事件 不是函数", "打了": []}
    _原件[id(叙类)] = 原看事件

    def 看事件(self, e):
        r = 原看事件(self, e)              # ★ 原件先跑完，行为一个字不改
        try:
            if isinstance(e, dict) and e.get("kind") == "声呐":
                听动静(self, e, bridge)
            if isinstance(e, dict) and e.get("kind") == "chat":
                说明 = 接单(bridge, self, e)
                if 说明:
                    _说(f"[声呐耳朵] {说明}")
                    try:
                        self.说(f"[{time.strftime('%H:%M')}] {说明}", 紧急=True)
                    except Exception:
                        pass
        except Exception as ex:
            print(f"[声呐耳朵] 耳朵出岔子（不影响主链）：{ex}", flush=True)
        return r

    叙类.看事件 = 看事件
    叙类._声呐耳朵装了 = True
    return {"好": True, "为什么": "", "打了": [
        "叙事者.看事件()  ← 听见 chat 就当场认口令 + 做计划 + 接单（原来那条路一个字不改）"]}


def 卸下(bridge):
    global _日志
    叙类 = getattr(bridge, "叙事者", None)
    原 = _原件.pop(id(叙类), None) if 叙类 is not None else None
    if not 原:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    叙类.看事件 = 原
    try:
        del 叙类._声呐耳朵装了
    except AttributeError:
        pass
    _日志 = None
    return {"好": True, "为什么": "", "打了": ["还原 叙事者.看事件()"]}
