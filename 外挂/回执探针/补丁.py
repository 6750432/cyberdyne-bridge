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
