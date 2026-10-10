#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回执探针车厢 —— 把 T2「静默失败」抓出来。

实机证据（2026-10-08）：
  · 手侧日志有 `[探针-挖] 目标=stone ｜ 背包共…｜ 我手里没有镐子，挖不了 stone`
    → 说明命令**到了手**，手也**看清了、也拒了**；
  · 大脑日志里**一条「没做成」都没有**，只有 15 条「等了 60 秒还没成（超时）」
    → 说明手的回执**在路上丢了**，大脑只能干等到超时。

主链 bridge.py 的 `叙事者.看回执()`（第 282 行起）本来就写得好好的：
成功念「「dig」成了（挖掉=…）」、失败念「「dig」没做成：{why}」。
走到走不到，全看回执有没有回来 —— 所以这里就盯这一件事。

做两件事（**只记录，不改行为**）：
  ① 每一次「任务栈._下发」和每一次「叙事者.看回执」都落一条 jsonl
     （`logs/回执.jsonl`），事后能对帳：发了多少、回了多少、丢了多少；
  ② 下发之后 `回执超时秒`（默认 8 秒）还没回音 → **点名报警**：
     哪一步、什么命令、等了多久。「静默」从此是一条看得见的日志。

⚠ 只盯「本来就该有回执」的命令（走到/挖/放/合成/打/熔炉/箱子/递）。
  「说」「等」「拾」不走 socket，**不计入** —— 免得自己造出一堆误报。
⚠ 探针不许影响功能：包起来的函数原样返回、异常一律吞在自己肚子里。

★★★ 2026-10-09 加的一处**例外**（如实写在最显眼的地方 ✓ 不许偷偷改行为 ✗）：
  「大模型层.问」哑了（返回 None/空串/抛异常）→ **出声 + 重试一次** ✓
  为什么归它：受限脚本 那节起车时会早退（车钩先挂空车再换轨 ✓）⇒ 兜底写那儿**跑不到** ✗；
    这节证明挂得上 ✓ 而且本来就包着 `大模型层.问` ✓ 是天然位置 ✓
  为什么非要有它：主人原话「**我说了怎么连日志都没有？**」——
    实机就是 大模型层.问 抛异常/返回 None，异常一路被吞 ⇒ 看上去"没反应也没日志" ✗
"""

import json
import os
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_日志 = None
_原件 = {}          # id(类) -> {"看回执": 原函数, "下发": 原函数}
_状态 = {"下发": 0, "回执": 0, "丢": 0, "在飞": {}}
_停 = threading.Event()
_线程 = None
_锁 = threading.Lock()
_落路径 = None      # 测试可以指到临时文件去，免得污染真日志
_代 = {"n": 0}      # 看门狗的"代"号，见 装上() 里的说明

# 计划里的动作 → socket 命令（**只有这些才该有回执**）
动作到命令 = {
    "走到": "goto", "挖": "dig", "放": "place", "合成": "craft",
    "打": "attack", "熔炉放料": "furnace_put", "熔炉取成品": "furnace_take",
    "箱子里取": "chest_take", "往箱子里放": "chest_put", "给": "递",
}
回执超时秒 = 8.0


def _描一眼(们):
    """把参数描成**一行短话** ✓（绝不 dump 一大坨 ✗ —— 日志是给人看的 ✓）"""
    出 = []
    for x in 们:
        if isinstance(x, str):
            出.append(x[:70].replace("\n", " "))
        elif x is None or isinstance(x, (int, float, bool)):
            出.append(repr(x))
        elif isinstance(x, dict):
            出.append("{" + "、".join(f"{k}={str(v)[:20]}" for k, v in list(x.items())[:4]) + "}")
        else:
            出.append(type(x).__name__)
    return " ｜ ".join(出)[:240]


def _说(文):
    if _日志:
        try:
            _日志(文)
            return
        except Exception:
            pass
    print(文, flush=True)


def _落(条):
    """落一条 jsonl —— 落不下也不许影响主流程。"""
    try:
        路 = _落路径 or os.path.join(ROOT, "logs", "回执.jsonl")
        os.makedirs(os.path.dirname(路), exist_ok=True)
        with open(路, "a", encoding="utf-8") as f:
            f.write(json.dumps(条, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _摘要(步):
    try:
        动 = 步.get("动作")
        p = 步.get("p")
        return f"{动}@{list(p)}" if p else str(动)
    except Exception:
        return "?"


def 装上(bridge, 日志=None, 回执超时=8.0, 落哪里=None, **kw):
    """挂上探针。**幂等**：挂第二次什么都不做。

    ★ 铁律：**验齐了才动全局状态**。
      第一版把 `_日志/_落路径/回执超时秒` 的赋值放在最前面，结果
      「故意让它失败」的那次调用（缺 叙事者）虽然返回了「好=False」，
      **却已经把超时线偷偷改成默认的 8 秒** ✗ —— 后来测试里那条
      「下发 0.4 秒没回音就该报警」于是怎么也不响，查了好久。
      这就是「半个装上」：说没装上，实际动了手脚。装上要么全做，要么什么都不做。
    """
    global _日志, _线程, 回执超时秒, _落路径

    栈类 = getattr(bridge, "任务栈", None)
    叙类 = getattr(bridge, "叙事者", None)
    if 栈类 is None or 叙类 is None:
        return {"好": False, "为什么": "找不到 任务栈 或 叙事者 类", "打了": []}
    if getattr(栈类, "_回执探针装了", False):
        return {"好": True, "为什么": "已经装过了（幂等）", "打了": []}

    原下发 = getattr(栈类, "_下发", None)
    原回执 = getattr(叙类, "看回执", None)
    if not callable(原下发) or not callable(原回执):
        return {"好": False, "为什么": "_下发 / 看回执 不是函数", "打了": []}

    # ── ★ 到这里才算验齐了，从这一行往下才允许动全局状态 ──
    _日志 = 日志
    if 落哪里:
        _落路径 = 落哪里
    try:
        回执超时秒 = float(回执超时)
    except Exception:
        pass

    _原件[id(栈类)] = {"下发": 原下发, "回执": 原回执}

    def 下发(self, *a, **k):
        """记一笔"我发了"—— **先记后发**，免得发出去才炸就没有记录。"""
        try:
            步 = a[0] if a else k.get("步") or {}
            动 = 步.get("动作") if isinstance(步, dict) else None
            命 = 动作到命令.get(动)
            if 命:
                with _锁:
                    _状态["下发"] += 1
                    _状态["在飞"][id(步) if isinstance(步, dict) else 命] = {
                        "t": time.time(), "cmd": 命, "步": _摘要(步)}
                _落({"事件": "下发", "时刻": round(time.time(), 3),
                     "命令": 命, "步": _摘要(步)})
        except Exception:
            pass
        return 原下发(self, *a, **k)

    def 看回执(self, e):
        """记一笔"回来了"—— 然后**原样交回主链**去处理（绝不改行为）。"""
        try:
            if isinstance(e, dict):
                命 = e.get("cmd")
                with _锁:
                    _状态["回执"] += 1
                    # 认领掉一个同名的"在飞"（同名多个就认最早那个）
                    候选 = [k for k, v in _状态["在飞"].items() if v["cmd"] == 命]
                    if 候选:
                        k0 = min(候选, key=lambda k: _状态["在飞"][k]["t"])
                        飞 = _状态["在飞"].pop(k0)
                        迟 = time.time() - 飞["t"]
                        _落({"事件": "回执", "时刻": round(time.time(), 3),
                             "命令": 命, "成不成": e.get("ok"),
                             "为什么": e.get("why"), "步": 飞["步"],
                             "等了秒": round(迟, 2)})
                        if 迟 >= 回执超时秒:
                            _说(f"[回执探针] ⚠ 回执晚了 {迟:.1f} 秒（步={飞['步']}）"
                                f"—— 超时线是 {回执超时秒:.0f} 秒，说明它卡过")
                    else:
                        _落({"事件": "回执", "时刻": round(time.time(), 3),
                             "命令": 命, "成不成": e.get("ok"),
                             "为什么": e.get("why"), "步": None, "等了秒": None})
        except Exception:
            pass
        return 原回执(self, e)

    栈类._下发 = 下发
    叙类.看回执 = 看回执
    栈类._回执探针装了 = True                  # ★ 幂等标记

    # ── 看门狗：下发之后 N 秒没回音 → 点名 ──
    #   ⚠ 用「代」号：拆了再装有可能会留下上一代的线程 —— 每一代只认自己，
    #     旧线程醒了发现代号变了就自己退，**绝不出现两个看门狗一起叫**。
    _代["n"] += 1
    我这代 = _代["n"]
    _停.clear()

    def 看门():
        while not _停.wait(0.5):
            if _代["n"] != 我这代:
                return
            try:
                现在 = time.time()
                丢 = []
                with _锁:
                    for k, v in list(_状态["在飞"].items()):
                        if 现在 - v["t"] >= 回执超时秒:
                            丢.append(v)
                            _状态["在飞"].pop(k, None)
                for v in 丢:
                    _状态["丢"] += 1
                    _说(f"[回执探针] ★★ **回执丢了**：命令「{v['cmd']}」"
                        f"（步={v['步']}）发出去 {回执超时秒:.0f} 秒了，一点回音都没有"
                        f" —— 大脑只会干等到超时 ✗（这就是 T2「静默失败」）")
                    _落({"事件": "回执丢了", "时刻": round(现在, 3),
                         "命令": v["cmd"], "步": v["步"],
                         "等了秒": round(现在 - v["t"], 2)})
            except Exception:
                pass

    _线程 = threading.Thread(target=看门, name="回执探针-看门", daemon=True)
    _线程.start()

    # ══════ ★★★ 听力探针（2026-10-09 主人：「我说了怎么连日志都没有？」）══════
    #   实机铁证：主人 21:56:51 说了「我要一把石镐」✓（**服务端日志里有** ✓）
    #   可脑那边**没回复、没任务、一行日志都没有** ✗ = **静默失败** ✗
    #   （项目铁律：不许静默 ✗ —— 一个功能可以不成，但不许让人猜它到底走到哪一步了 ✓）
    #   规矩（跟这节车厢一致）：**只记不改** ✓ 原样返回 ✓ 自己的异常自己吞 ✓
    听力打过 = []
    # ⚠ 2026-10-09 实机：`三觉层`/`大模型`/`指令` 是主链里的**局部变量** ✗
    #   （`getattr(bridge, …)` 摸不到 ✓ 我第一版就报了三条"摸不到" ✓）
    #   ⇒ 改成**包类方法** ✓ —— 类是模块级的 ✓ 摸得到 ✓（跟其他车厢一个路子 ✓）
    for 类名, 方法 in (("三觉", "记聊天"), ("指令层", "收"),
                     ("大模型层", "问"), ("大模型层", "_取"),
                     ("翻译器", "收输出")):
        类 = getattr(bridge, 类名, None)
        if not isinstance(类, type) or not callable(getattr(类, 方法, None)):
            _说(f"[听力探针] ⚠ 摸不到 {类名}.{方法} —— 这一跳记不了（出声 ✗ 不装看不见 ✓）")
            continue
        if getattr(类, "_听力探针_" + 方法, False):
            continue
        原 = getattr(类, 方法)

        def _包(self, *a, _原=原, _类名=类名, _方=方法, **k):
            try:
                _说(f"[听力探针] {_类名}.{_方} ← {_描一眼(a)}")
            except Exception:
                pass
            try:
                果 = _原(self, *a, **k)
            except Exception as _e:
                # ★★★ 2026-10-09 实机：`大模型层.问` **是抛异常**的 ✗ ——
                #   我第一版没接异常 ⇒ 日志**断在半路** ✓（主人看到的"什么都没有" ✓）
                #   规矩：**记下来，再原样抛** ✓（探针不许改行为 ✗）
                _说(f"[听力探针] {_类名}.{_方} ✗✗ 抛了 {type(_e).__name__}: {_e}")
                raise
            try:
                _说(f"[听力探针] {_类名}.{_方} → {_描一眼((果,))}")
            except Exception:
                pass
            return 果

        setattr(类, 方法, _包)
        setattr(类, "_听力探针_" + 方法, True)
        听力打过.append(f"{类名}.{方法}()")
    # ★ 再包一层**实例**方法 ✓：生存常识 那节是包实例的 ✓（它先装 ✓ 我们再包外面 ✓）
    #   ⇒ 这一跳**整跳**收到什么、返回什么，才算真正看得见 ✓
    try:
        翻 = getattr(bridge, "翻译器", None)
        if 翻 is not None and callable(getattr(翻, "收输出", None)) \
                and not getattr(翻, "_听力探针实例", False):
            原实例 = 翻.收输出

            def _实例包(文本=None, 状态=None, *a, **k):
                _说(f"[听力探针] 翻译器.收输出（整跳）← {_描一眼((文本,))}")
                果 = 原实例(文本, 状态, *a, **k)
                _说(f"[听力探针] 翻译器.收输出（整跳）→ {_描一眼((果,))}")
                return 果

            翻.收输出 = _实例包
            翻._听力探针实例 = True
            听力打过.append("翻译器.收输出（整跳）")
    except Exception as _e:
        _说(f"[听力探针] ⚠ 整跳那一层包不上（{type(_e).__name__}: {_e}）✓ 出声 ✗")

    if 听力打过:
        _说("[回执探针] **听力探针**装上了 ✓（听见谁说话→听没听懂→问没问大模型→"
            "答了什么→有没有变成任务 ✓ 每跳一行 ✓）：" + "、".join(听力打过))

    # ══════ ★★★ 大模型兜底（2026-10-09 主人「挪」）══════
    类问 = getattr(bridge, "大模型层", None)
    if isinstance(类问, type) and callable(getattr(类问, "问", None)) \
            and not getattr(类问, "_回执兜底哑跳", False):
        _原问 = 类问.问

        def _跑一次(self, *a, **k):
            try:
                return _原问(self, *a, **k), None
            except Exception as e:
                return None, e

        def _问兜(self, *a, **k):
            # ★★★ 2026-10-09 主人第二条：**"答不上来"要重试 2 次、再不行就熔断** ✓
            #   ⚠ 主循环是**单线程** ✗ ⇒ 重试**不能 sleep**（一 sleep 整个脑停住 ✓）
            #     ⇒ 计数**跨拍**算 ✓（脑本来每 ~20 秒问一次 ✓ 正好当重试 ✓）
            import time as _t
            _到 = float(_状态.get("问熔断到") or 0)
            if _t.time() < _到:
                _说(f"[回执探针·兜底] **熔断中** ✗ 不再问（还剩 {_到 - _t.time():.0f} 秒 ✓ "
                    f"主人定的：重试 2 次还不行就停一会儿 ✓）")
                return None
            果, 错 = _跑一次(self, *a, **k)
            哑 = (错 is not None) or (果 is None) or (isinstance(果, str) and not 果.strip())
            if not 哑:
                return 果
            _状态["大模型空跳"] = _状态.get("大模型空跳", 0) + 1
            # ★★★ 2026-10-09：**先问"能不能问"** ✗ ——
            #   类里 `能问()` 有三道闸：没开 / `离上次不到 min_interval_sec 秒` /
            #   `这一小时已经问了 max_per_hour 次，封顶` ✓
            #   而**理由是被丢掉的** ✗ ⇒ 上一版我"立刻重试一次"注定撞第二道闸 ✓
            #   （同一秒里再问 = 必被拒 ✓）⇒ 先把理由喊出来 ✓ 再决定要不要重试 ✓
            能, 为啥 = True, ""
            try:
                _能问 = getattr(类问, "能问", None)
                if callable(_能问):
                    能, 为啥 = _能问(self)
            except Exception as _e2:
                能, 为啥 = True, f"（能问() 自己出岔子：{type(_e2).__name__}）"
            _说("[回执探针·兜底] ✗ 大模型这一跳**哑了**（"
               + (f"抛了 {type(错).__name__}：{str(错)[:70]}" if 错 else f"返回 {type(果).__name__}")
               + f"）｜ 能问() 说：{能} {为啥}"
               + (f"（今天第 {_状态['大模型空跳']} 次）" if True else ""))
            if not 能:
                _说("[回执探针·兜底] ⇒ **不重试** ✗ —— 闸门说了现在不能问 ✓"
                    "（重试也是白撞 ✓ 这就是「明明有理由却看不见」的那类坑 ✗）")
                return 果
            果, 错 = _跑一次(self, *a, **k)
            if 错 is not None or 果 is None or (isinstance(果, str) and not 果.strip()):
                _状态["问连错"] = _状态.get("问连错", 0) + 1
                if _状态["问连错"] >= 3:          # 原试 + 每拍一拍 = 重试 2 次 ✓
                    _状态["问熔断到"] = _t.time() + 60
                    _状态["问连错"] = 0
                    _说(f"[回执探针·兜底] ✗✗ **熔断**：连着 3 次都没答上来 —— "
                        f"**停 60 秒再试** ✓（不再每拍空转 ✗）")
                else:
                    _说(f"[回执探针·兜底] ✗✗ 重试还是哑的 —— **如实说**：这一跳没答上来 ✗"
                        f"（第 {_状态['问连错']} 次 ✓ 到 3 次就熔断 ✓ 不许让你猜 ✓）")
            else:
                _状态["问连错"] = 0
                _说("[回执探针·兜底] ✓ 重试成了 ✓")
            return 果

        _原件["问"] = _原问
        类问.问 = _问兜
        类问._回执兜底哑跳 = True
        _说("[回执探针] **大模型兜底**装上了 ✓（哑了出声 + 重试一次 ✓ —— "
            "这节唯一一处真改行为 ✗ 已写进头注释 ✓）")


    # ⚠⚠ 2026-10-09 我自己踩的：本来想在这儿包 `bridge._聊一句`（闲聊/翻译那条路）✗
    #   结果**宪法①当场拦下**：「顶层对象『_聊一句』被换掉了」⇒ **起车失败、退回** ✓
    #   主人定这条宪法的理由，我今天亲手验证了一次 ✓：
    #     车厢只能给**类**打钩子 ✓ 绝不能换主链顶层对象 ✗（不然主链本体就不是它自己了 ✓）
    #   ⇒ 「一句话听不懂就把脑带崩」那条（红线里的 UnboundLocalError ✗）我**不自己动** ✗
    #     要改得主人点头 ✓（或者在宪法允许的范围内另想办法 ✓）

    # ══════ ★★★ 接单链**逐层点名**（2026-10-09 主人：「逐层点名」）══════
    #   缘由：真机 `栈.接 返回 False` ✗ 而账本里**一条拒单都没有** ✗
    #     ⇒ 有一层在**悄悄拒** ✓ 那就把整条链子**印出来** ✓（起车那一刻是最好的时机 ✓
    #       因为车厢是一个一个挂上去的 ✓ 挂完就定型了 ✓）
    try:
        import inspect as _ins
        f = getattr(类栈, "接", None) if False else getattr(getattr(bridge, "任务栈", None), "接", None)
        链, _seen = [], set()
        for _ in range(30):
            if f is None or id(f) in _seen:
                break
            _seen.add(id(f))
            链.append(f)
            下 = None
            for c in (getattr(f, "__closure__", None) or ()):
                try:
                    v = c.cell_contents
                except Exception:
                    continue
                if callable(v):
                    try:
                        if _ins.getsource(v).lstrip().startswith(("def 接", "def 新接")):
                            下 = v
                            break
                    except Exception:
                        if str(getattr(v, "__name__", "")).startswith(("接", "新接")):
                            下 = v
                            break
            f = 下
        if 链:
            _说(f"[逐层点名] 任务栈.接 一共 {len(链)} 层（外 → 内）：")
            for _i, _x in enumerate(链):
                try:
                    _源 = _ins.getsource(_x)
                except Exception:
                    _源 = ""
                _拒 = [l.strip()[:60] for l in _源.split("\n") if "return False" in l]
                _模 = str(getattr(_x, "__module__", "?")).split(".")[-1]
                _说(f"    {_i}. [{_模}] {getattr(_x, '__qualname__', _x)} ｜ return False × {len(_拒)}"
                   + (f" ｜ {_拒[0]}" if _拒 else ""))
        else:
            _说("[逐层点名] ⚠ 接 上摸不到链子（出声 ✗）")
    except Exception as _e:
        _说(f"[逐层点名] ⚠ 扒链子出岔子（{type(_e).__name__}: {_e}）✓ 出声 ✗")

    return {"好": True, "为什么": "", "打了": [
        "任务栈._下发()  ← 记「我发了」（只记录，不改行为）",
        "叙事者.看回执() ← 记「回来了」（只记录，不改行为）",
        "看门狗线程     ← 下发 N 秒没回音就点名（T2 探测器）",
    ]}


def 卸下(bridge):
    栈类 = getattr(bridge, "任务栈", None)
    叙类 = getattr(bridge, "叙事者", None)
    原 = _原件.pop(id(栈类), None) if 栈类 is not None else None
    _停.set()
    if not 原:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    try:
        栈类._下发 = 原["下发"]
        叙类.看回执 = 原["回执"]
        类问2 = getattr(bridge, "大模型层", None)
        if isinstance(类问2, type) and callable(_原件.get("问")):
            类问2.问 = _原件["问"]
            try:
                delattr(类问2, "_回执兜底哑跳")
            except Exception:
                pass
        try:
            del 栈类._回执探针装了
        except AttributeError:
            pass
    except Exception as e:
        return {"好": False, "为什么": f"还原时出错：{e}", "打了": []}
    报 = (f"下发 {_状态['下发']} ｜ 回执 {_状态['回执']} ｜ "
          f"丢 {_状态['丢']} ｜ 还在飞 {len(_状态['在飞'])}")
    _说(f"[回执探针] 卸了。这一程：{报}")
    return {"好": True, "为什么": "", "打了": ["还原 任务栈._下发()", "还原 叙事者.看回执()"]}


def 报个话(bridge=None):
    with _锁:
        return {"下发": _状态["下发"], "回执": _状态["回执"],
                "丢": _状态["丢"], "在飞": len(_状态["在飞"])}
