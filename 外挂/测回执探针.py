#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回执探针车厢 —— 离线测试（不连服务器、不起大脑）。

它要证明的四件事：
  A 装上/卸下/幂等 —— 挂两次不会包两层，卸了能一字不差还原；
  B 「我发了」和「回来了」都记下来了（jsonl 里对得上）；
  C **下发 N 秒没回音 → 点名报出「回执丢了」**（这就是 T2 的探测器本身）；
  D 不该管的不瞎管 —— 「说」「等」「拾」本来就不走 socket，**不许误报**。

跑法：python3 外挂/测回执探针.py
"""

import importlib.util
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
外挂根 = os.path.join(ROOT, "外挂")
通过, 失败 = [], []


def 试(名, 条件, 为啥="条件不成立"):
    (通过 if 条件 else 失败).append(名 if 条件 else {"名": 名, "为啥": 为啥})
    return bool(条件)


class 假任务栈:
    def _下发(self, 步, 状态=None, **k):
        return ("下发了", (步 or {}).get("动作"))


class 假叙事者:
    def 看回执(self, e):
        return ("原回执处理了", (e or {}).get("cmd"))


class 假bridge:
    pass


def 载(名):
    p = os.path.join(外挂根, 名, "补丁.py")
    spec = importlib.util.spec_from_file_location(f"测_{名}", p)
    m = importlib.util.module_from_spec(spec)
    sys.modules[f"测_{名}"] = m
    sys.path.insert(0, os.path.join(外挂根, 名))
    spec.loader.exec_module(m)
    return m


def 清账(探针):
    探针._状态.update({"下发": 0, "回执": 0, "丢": 0, "在飞": {}})


def 读账(路):
    条 = []
    if os.path.exists(路):
        with open(路, encoding="utf-8") as f:
            for 行 in f:
                try:
                    条.append(json.loads(行))
                except Exception:
                    pass
    return 条


def 主():
    sys.path.insert(0, 外挂根)
    探针 = 载("回执探针")
    路 = os.path.join(tempfile.gettempdir(), "测回执探针.jsonl")
    if os.path.exists(路):
        os.unlink(路)

    bridge = 假bridge()
    bridge.任务栈 = 假任务栈
    bridge.叙事者 = 假叙事者
    话 = []

    # ══════════ A 组：装上 / 幂等 ══════════
    print("── A 组：装上 / 幂等 ──")
    # ★ 原函数必须**装上之前**抓 —— 抓晚了抓到的是包过的那个
    #   （E2 第一版就是栽在这儿：断言写成"卸下后 is 我第一次抓的那个"，
    #     可那个本身就是包过的壳 ✗）
    原下发 = 假任务栈._下发
    r = 探针.装上(bridge, 日志=话.append, 回执超时=0.4, 落哪里=路)
    试("A1 装上了", r.get("好") is True, str(r))
    试("A2 打了 3 处补丁（_下发 / 看回执 / 看门狗）", len(r.get("打了", [])) == 3, str(r.get("打了")))
    第一次下发 = 假任务栈._下发
    r2 = 探针.装上(bridge, 日志=话.append, 回执超时=0.4, 落哪里=路)
    试("A3 ★★ **幂等**：挂第二次什么都不做（不然就包两层了）",
       r2.get("好") is True and "已经装过" in str(r2.get("为什么")), str(r2))
    试("A4 ★★ 而且类上的函数**还是同一个对象** —— 没被包第二层",
       假任务栈._下发 is 第一次下发)
    超时前 = 探针.回执超时秒

    def 故意失败():
        b2 = 假bridge()
        b2.任务栈 = 假任务栈          # 故意不给 叙事者
        return 探针.装上(b2, 日志=话.append, 回执超时=99, 落哪里=路)

    好5 = 故意失败().get("好")
    试("A5 缺 叙事者 时**拒绝装**（fail-closed，不装作装上了）", 好5 is False, str(好5))
    试("A6 ★★★ **装上失败时不许动全局设置**（「半个装上」：说没装上、却把超时线改了）",
       探针.回执超时秒 == 超时前, f"{超时前} → {探针.回执超时秒}")

    # ══════════ B 组：发了 / 回了 都记下来 ══════════
    print("── B 组：发了/回了 都记下来 ──")
    清账(探针)
    探针._状态.update({"下发": 0, "回执": 0, "丢": 0, "在飞": {}})
    步 = {"动作": "挖", "p": [1, 2, 3]}
    栈 = 假任务栈()
    出 = 栈._下发(步)                      # 走包过的那一层
    试("B1 ★★ 包起来之后**原样返回**（探针不许改行为）", 出 == ("下发了", "挖"), str(出))
    试("B2 记下了「我发了」", 探针.报个话().get("下发") == 1, str(探针.报个话()))
    叙 = 假叙事者()
    原出 = 叙.看回执({"cmd": "dig", "ok": False, "why": "我手里没有镐子"})
    试("B3 ★★ 回执也**原样交回主链**（返回值不变）",
       原出 == ("原回执处理了", "dig"), str(原出))
    试("B4 ★★ 回执记上了，而且不再「在飞」了（发了 1 回了 1）",
       探针.报个话().get("回执") == 1 and 探针.报个话().get("在飞") == 0,
       str(探针.报个话()))
    试("B5 ★★ **拒绝的理由**被记进了 jsonl —— 这正是实机丢掉的那条信息",
       any(x.get("为什么") == "我手里没有镐子" for x in 读账(路)),
       json.dumps(读账(路)[-2:], ensure_ascii=False)[:200])

    # ══════════ C 组：回执丢了 → 点名（T2 探测器本体）══════════
    print("── C 组：回执丢了要点名 ──")
    清账(探针)
    话.clear()
    栈2 = 假任务栈()
    栈2._下发({"动作": "挖", "p": [9, 9, 9]})        # 发了，**故意不回**
    试("C0 发出去之后「在飞」里确实挂着一条（不然下面失败就说不清是谁的错）",
       探针.报个话().get("在飞") == 1, str(探针.报个话()))
    time.sleep(1.2)                                  # 超时线是 0.4 秒
    有丢 = any("回执丢了" in s for s in 话)
    试("C1 ★★★ **回执丢了会点名报警**（这就是把「静默」变成看得见的日志）",
       有丢, "话=" + str(话)[-200:] + " ｜ 账=" + str(探针.报个话())
       + " ｜ 线程=" + str([t.name for t in __import__("threading").enumerate()]))
    试("C2 报的话里点得出是哪一步、什么命令",
       有丢 and any("挖@[9, 9, 9]" in s for s in 话), str(话)[-200:])
    试("C3 jsonl 里也留了一条「回执丢了」",
       any(x.get("事件") == "回执丢了" for x in 读账(路)),
       json.dumps(读账(路)[-3:], ensure_ascii=False)[:220])
    试("C4 丢的只算一次，不刷屏",
       sum(1 for s in 话 if "回执丢了" in s) == 1, str(话))

    # ══════════ D 组：不该管的别瞎管 ══════════
    print("── D 组：不许误报 ──")
    清账(探针)
    话.clear()
    栈3 = 假任务栈()
    for 动 in ("说", "等", "拾"):
        栈3._下发({"动作": 动})
    time.sleep(1.0)
    试("D1 ★★ 「说」「等」「拾」**本来就不走 socket，不许报警**（免得自己造误报）",
       not any("回执丢了" in s for s in 话), str(话))
    试("D2 它们也不算进「下发」计数里", 探针.报个话().get("下发") == 0,
       str(探针.报个话()))

    # ══════════ E 组：卸下还原 ══════════
    print("── E 组：卸下还原 ──")
    r3 = 探针.卸下(bridge)
    试("E1 卸下了", r3.get("好") is True, str(r3))
    试("E2 ★★ 类上的函数**一字不差还原**（不是「差不多」）",
       假任务栈._下发 is 原下发)
    试("E3 幂等标记也清掉了（下次能再装上）",
       not getattr(假任务栈, "_回执探针装了", False))
    试("E4 卸干净之后再卸一次也不炸", 探针.卸下(bridge).get("好") is True)

    print("\n" + "═" * 62)
    print(f"回执探针车厢：{len(通过)} 过 / {len(失败)} 失败")
    for f in 失败:
        print(f"  ❌ {f['名']} —— {f['为啥']}")
    print("═" * 62)
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
