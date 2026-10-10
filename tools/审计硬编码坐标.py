#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""硬编码坐标审计 —— 把「坐标写死在代码里」的地方**全找出来、分好类**。

English: Audits hard-coded coordinate literals across the brain. It classifies every
hit (comment / prompt example / test fixture / dangerous fallback / safe sentinel) and
prints a report, so "we bake coordinates into plans" is a visible number rather than a
feeling.

主人 2026-10-09 点名（【五】排队第 4 条）：**硬编码坐标审计**

为什么要审
==========
坐标**只有一处**合法来源：**当帧状态帧**（`s.pos` / `s.scan`）✓
写死在代码里的坐标，最坏情况是「它照着一条陈坐标跑过去」✗ ——
这正是 2026-10-08 那串怪事的同一个总根（陈坐标）✓

⚠ 但**不能一刀切** ✗ —— 有三类写了坐标却完全没问题：
  · **注释里**：那是历史证据（"实机铁证：计划挖 [-164,77,158]"）✓ 删了才是坏事
  · **提示词里的例子**：教模型"步骤长什么样"，**必须**有具体数字 ✓
  · **测试夹具**：假坐标是测试的本体 ✓
  真正要盯的是第四类：**执行路径上的兜底值** ✓
  （比如 `p or [0,0,0]` —— 没有坐标时默认去世界原点 ✗ 那是个真陷阱）

跑法：python3 tools/审计硬编码坐标.py            # 出报告
      python3 tools/审计硬编码坐标.py --只看危险   # 只列"执行路径上的"
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 只看这几处（主链 + 车厢 + 手侧）—— 工具/文档/日志不在审计范围
要看 = ["bridge.py"]
for 名 in sorted(os.listdir(os.path.join(ROOT, "外挂"))):
    甲 = os.path.join(ROOT, "外挂", 名, "补丁.py")
    if os.path.isfile(甲):
        要看.append(os.path.join("外挂", 名, "补丁.py"))
for 名 in ("node/server.js", "node/plugins/body/proto_body.js"):
    甲 = os.path.join(ROOT, 名)
    if os.path.isfile(甲):
        要看.append(名)

# 三个数字的列表 = 一个坐标（允许 1~4 位、允许负号）
坐标 = re.compile(r"\[\s*(-?\d{1,4})\s*,\s*(-?\d{1,4})\s*,\s*(-?\d{1,4})\s*\]")
# 明显是"占位/哨兵"而不是真坐标的
哨兵 = {(0, 0, 0), (1, 2, 3), (10, 60, 10), (10, 70, 10), (10, 77, 10), (10, 78, 10),
        (50, 60, 10), (60, 60, 10), (70, 60, 10), (80, 60, 10), (90, 60, 10),
        (100, 60, 10), (10, 20, 30), (1, 1, 1), (0, 1, 0), (0, -1, 0)}

分类名 = {
    "方向": "方向向量/偏移量（不是坐标 ✗ 本来就该写死）",
    "注释": "注释里（历史证据 ✓ 留着）",
    "提示词": "提示词/文案里的例子（教模型格式 ✓ 留着）",
    "测试": "测试夹具（假坐标是测试本体 ✓ 留着）",
    "兜底": "★ 执行路径上的兜底值（要盯着 ✗）",
    "正文": "★ 执行路径上的写死坐标（要盯着 ✗）",
}


def 是不是注释(行):
    一 = 行.strip()
    return 一.startswith("#") or 一.startswith("//") or 一.startswith("*") or 一.startswith("/*")


def 是不是文案(行):
    """提示词 / 报错文案 / 说明字符串 —— 特征：整行大部分是中文，或者带 '规格.append'"""
    if "规格.append" in 行 or "组Prompt" in 行:
        return True
    if re.search(r"console\.log|log\(|print\(|_说\(|self\.说\(", 行) and '"' in 行:
        # 有中文的日志/话术行
        if re.search(r"[\u4e00-\u9fff]", 行):
            return True
    return False


def 是不是兜底(行):
    return (" or " in 行 or "??" in 行 or "get(" in 行 or "||" in 行) and 坐标.search(行)


def 主():
    只看危险 = "--只看危险" in sys.argv
    账 = {}
    明细 = []
    for 相对 in 要看:
        路 = os.path.join(ROOT, 相对)
        try:
            with open(路, encoding="utf-8") as f:
                行们 = f.readlines()
        except Exception:
            continue
        for 行号, 行 in enumerate(行们, 1):
            for m in 坐标.finditer(行):
                三 = tuple(int(x) for x in m.groups())
                # ★ 先把「方向向量」摘出去 ✗ ——
                #   `[[0,-1,0],[1,0,0],…]` 是**六个面**的偏移量 ✓ 本来就该写死 ✓
                #   我第一版把它当坐标报出来，13 条"危险"里 12 条是它 ✗
                #   **误报比漏报更危险**：报一堆假的，真的那条就没人看了 ✓
                # ⚠ `[0,0,0]` 不在这一条里 ✗ —— 它是我**故意写死的兜底值** ✓
                #   把兜底当"方向向量"跳过，正是"误报改完变漏报"的经典坑 ✓
                if all(abs(x) <= 1 for x in 三) and 三 != (0, 0, 0):
                    类 = "方向"
                elif 是不是注释(行):
                    类 = "注释"
                elif 是不是文案(行):
                    类 = "提示词"
                elif "测" in 相对 or "test" in 相对:
                    类 = "测试"
                elif 是不是兜底(行):
                    类 = "兜底"
                elif 三 in 哨兵:
                    类 = "测试"
                else:
                    类 = "正文"
                账[类] = 账.get(类, 0) + 1
                明细.append((类, 相对, 行号, 三, 行.rstrip()[:120]))

    print("═" * 70)
    print("硬编码坐标审计 —— 坐标只有一处合法来源：**当帧状态帧** ✓")
    print("═" * 70)
    print(f"扫描范围：{len(要看)} 个文件（主链 + 车厢 + 手侧两处）")
    print()
    要盯 = []
    for 类 in ("方向", "注释", "提示词", "测试", "兜底", "正文"):
        n = 账.get(类, 0)
        print(f"  {n:4d} 处　{分类名[类]}")
        if 类 in ("兜底", "正文"):
            要盯.append(类)
    print()
    print("─" * 70)
    if 只看危险:
        print("★ 要盯的那两类，逐条列出来：")
    else:
        print("★ 要盯的那两类，逐条列出来（其余三类只报数）：")
    print()
    有 = 0
    for 类, 相对, 行号, 三, 原文 in 明细:
        if 类 not in ("兜底", "正文"):
            continue
        有 += 1
        print(f"  [{类}] {相对}:{行号}")
        print(f"        坐标 {list(三)}")
        print(f"        {原文}")
    if not 有:
        print("  （一处都没有 ✓）")
    print()
    print("─" * 70)
    print("※ 怎么判「危险」✗：**执行路径上的兜底值**")
    print("  例：`p = 步.get('p') or [0, 0, 0]` —— 没坐标时默认去**世界原点** ✗")
    print("  这类要在实机日志里核对：它真的拿到过那个兜底值吗？")
    print("═" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(主())
