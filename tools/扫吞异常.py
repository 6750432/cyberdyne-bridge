#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扫「吞异常」—— 找出所有把异常咽下去、然后装作没事继续跑的地方。

为什么要有这个工具
==================
2026-10-08 主人点名：**T2「静默失败」**。

当天的实机铁证：
    车厢的 `_记账` 是 `except Exception: pass`；
    我把调用它的那一行弄丢之后，**「定位失败」的原因一整个下午不落日志** ——
    我全靠猜，猜了四五轮，浪费的比修的多。

「出错」不可怕，可怕的是**出错了没人知道**。这个扫描器就是拿来把它们揪出来的。

判据（只算「吞」）
------------------
一个 `except` 块，如果它做的事**全都在"咽下去"**，就算吞：
    · pass
    · continue / break
    · return None / return（无值）
    · 只有注释
只要块里**有任何"出声"的动作**（log/print/raise/记账/置标志位/赋值给 self.*），就不算吞。

分级
----
    🔴 严重   `except:` 或者 `except Exception:` —— 什么都吞
    🟡 一般   `except 具体类型:` —— 至少知道可能出什么，但也没出声
    ⚪ 主链   bridge.py 里的（**红线：我不能改**，只列出来给主人看）

跑法： python3 tools/扫吞异常.py [根目录...]
"""

import ast
import io
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 「出声」的动作：只要 except 块里有这些，就不算吞
出声的名字 = {
    "print", "log", "_log", "记", "_记", "_报", "_说", "说", "log_error",
    "raise", "assert", "warn", "warning", "logger", "traceback",
}


def 是出声节点(节):
    """这个 AST 节点算不算"出声了"？"""
    if isinstance(节, ast.Raise | ast.Assert):
        return True
    if isinstance(节, ast.Expr) and isinstance(节.value, ast.Call):
        函 = 节.value.func
        if isinstance(函, ast.Name) and 函.id in 出声的名字:
            return True
        if isinstance(函, ast.Attribute):
            # self._报(...) / logger.warning(...) / print(...) 之类
            if 函.attr in 出声的名字 or 函.attr.startswith(("log", "warn", "error")):
                return True
        # 形如 f"..." 的裸表达式不发声，忽略
    if isinstance(节, ast.Assign | ast.AugAssign | ast.AnnAssign):
        # 赋值给 self.xxx（比如 self.上次失败 = ...）算"记下来了"，但不算"出声"
        # → 这里故意**不算**出声，免得把"悄悄记一笔就继续"当成有交代
        return False
    return False


def 是咽下去(块):
    """except 的 body 是不是"全在咽"？返回 (是不是, 做了啥)。"""
    if not 块:
        return True, ["（空块）"]
    做了 = []
    出声 = False
    for 节 in 块:
        if isinstance(节, ast.Pass):
            做了.append("pass")
        elif isinstance(节, ast.Continue):
            做了.append("continue")
        elif isinstance(节, ast.Break):
            做了.append("break")
        elif isinstance(节, ast.Return):
            做了.append("return" + ("" if 节.value is None else " <值>"))
            if 节.value is not None:
                出声 = True          # 返回一个值当结果，算有交代
        elif isinstance(节, ast.Expr) and isinstance(节.value, ast.Constant):
            做了.append("（注释/空语句）")
        else:
            if 是出声节点(节):
                出声 = True
            做了.append(type(节).__name__)
    return (not 出声), 做了


def 异常名(节):
    t = 节.type
    if t is None:
        return "裸 except（什么都不写）"
    try:
        return ast.unparse(t)
    except Exception:
        return "?"


def 扫一个文件(路):
    出 = []
    try:
        源码 = io.open(路, encoding="utf-8").read()
        树 = ast.parse(源码)
    except Exception as e:
        出.append((0, "解析失败", f"{type(e).__name__}: {e}", ["—"], 0))
        return 出
    for 节 in ast.walk(树):
        if not isinstance(节, ast.ExceptHandler):
            continue
        吞了, 做了 = 是咽下去(节.body)
        if not 吞了:
            continue
        # ★ 再分一层：**纯静默**（pass/continue/什么都不做）比
        #   「记了个标志位就继续」更危险 —— 前者事后连查都没得查。
        纯 = all(x in ("pass", "continue", "break", "（空块）", "（注释/空语句）")
                for x in 做了)
        名 = 异常名(节)
        级 = 0
        if 节.type is None:
            级 = 3
        elif isinstance(节.type, ast.Name) and 节.type.id in ("Exception", "BaseException"):
            级 = 2
        else:
            级 = 1
        # 块里有 print 之外的东西？再松松手：有 print 就算出声（上面已经判过）
        出.append((节.lineno, 名, "、".join(做了), 1 if 纯 else 0, 级))
    return 出


def 主():
    根 = sys.argv[1:] or [ROOT]
    文件们 = []
    for r in 根:
        if os.path.isfile(r):
            文件们.append(r)
            continue
        for 目录, _, 名们 in os.walk(r):
            if any(x in 目录 for x in (".git", "__pycache__", "node_modules", "runtime")):
                continue
            for n in 名们:
                if n.endswith(".py"):
                    文件们.append(os.path.join(目录, n))
    文件们.sort()

    主链 = [f for f in 文件们 if os.path.basename(f) == "bridge.py"]
    车厢 = [f for f in 文件们 if os.path.basename(f) != "bridge.py"]
    总 = []
    for f in 文件们:
        for 行, 名, 做, 纯, 级 in 扫一个文件(f):
            总.append({"级": 级, "文": f, "行": 行, "名": 名, "做": 做, "纯": 纯})

    print("=" * 78)
    print("  扫「吞异常」—— 出错了没人知道的地方")
    print("=" * 78)
    print(f"  扫了 {len(文件们)} 个 .py（主链 {len(主链)}，其它 {len(车厢)}）")
    print()

    各组 = [
        (3, "🔴🔴 **纯静默** —— 块里只有 pass/continue，出事了事后连查都没得查"),
        (2, "🔴 有动作但**不出声** —— 记了个标志位就继续，天知地知它不知"),
    ]
    for 级, 标题 in 各组:
        组 = [x for x in 总 if (x["纯"] == 1) == (级 == 3)]
        组.sort(key=lambda x: (x["级"], x["文"], x["行"]))
        print(f"── {标题} —— {len(组)} 处 ──")
        if not 组:
            print("   （无）")
        for x in 组:
            短 = os.path.relpath(x["文"], ROOT)
            标 = "⚪主链" if os.path.basename(x["文"]) == "bridge.py" else "🔧车厢"
            print(f"   {标} {短}:{x['行']}  except {x['名']}  → {x['做']}")
        print()

    print("─" * 78)
    print(f"  合计 **{len(总)}** 处吞异常："
          f"**纯静默 {sum(1 for x in 总 if x['纯'] == 1)}** 处、"
          f"有动作不出声 {sum(1 for x in 总 if x['纯'] == 0)} 处")
    print(f"  按异常类型：裸 {sum(1 for x in 总 if x['级'] == 3)}、"
          f"Exception {sum(1 for x in 总 if x['级'] == 2)}、"
          f"具体类型 {sum(1 for x in 总 if x['级'] == 1)}")
    print("  其中主链 %d 处（**红线：不许改**，列给主人看）"
          % sum(1 for x in 总 if os.path.basename(x["文"]) == "bridge.py"))
    print("─" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(主())
