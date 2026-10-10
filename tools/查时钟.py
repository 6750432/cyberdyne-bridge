#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查时钟 —— 老祖课第五课（Lamport：分布式时序）：**墙钟只当时间戳，判据要用单调钟** ✓

为什么要有它
============
`time.time()` 读的是**墙上时钟** ✗ —— 它可以被 NTP 往前/往后拽 ✓ 也可能手工调 ✓
拿它判「过了多久」「超时没超时」，就会出现这些事：

    · 钟被往回拽 ⇒ **过了 = 负数** ⇒ 超时判据永远不成立 ⇒ 卡住也不报 ✗
    · 钟被往前拽 ⇒ **一瞬间全超时** ⇒ 满屏假警报 ✗（误报比漏报更危险 ✓）

单调钟（`time.monotonic()`）**只会往前走** ✓ 是唯一能拿来做判据的钟 ✓
—— 这条是 Lamport 那套（分布式时序）的入门功 ✓

判法（不许猜 ✗）
================
  · 「**盖时间戳**」用墙钟 ✓ 完全正当（给人看的时间、写进日志的 t ✓ 跨天也能读 ✓）
  · 「**判间隔/超时**」用墙钟 ✗ —— 本工具就是抓这个 ✓
  · 真有一处非用不可 ⇒ 在那行加注释 `查时钟:允许` ✓（并写清为什么 ✓）

三个桶
======
  · 主链 `bridge.py` ⇒ **红线 ✗ 只报不改**（改它要走主人的同意 ✓）
  · `外挂/` 和 `tools/` ⇒ **该改 ✗** ⇒ 退出码 1（闸门会拦 ✓）
  · 只是盖戳 ⇒ 列个数字，不算问题 ✓

跑法：python3 tools/查时钟.py        （退出码 0 = 没有该改的 ✓）
"""

import os
import re
import sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

判据味 = ("超时", "间隔", "过期", "多久", "秒后", "deadline", "等到", "过了",
        "已等", "耗时", "逾期", "stuck")
戳味 = ("\"t\"", "'t'", "时刻", "记一笔", "落账", "日志", "stamp", "print", "assert")


def 收文件():
    出 = []
    主链 = os.path.join(根, "bridge.py")
    if os.path.isfile(主链):
        出.append(("主链", 主链))
    for 夹 in ("外挂", "tools"):
        基 = os.path.join(根, 夹)
        for 路 in sorted(os.listdir(基)) if os.path.isdir(基) else []:
            全 = os.path.join(基, 路)
            if os.path.isfile(全) and 路.endswith(".py"):
                出.append((夹, 全))
            elif os.path.isdir(全):
                for 里 in sorted(os.listdir(全)):
                    if 里.endswith(".py"):
                        出.append((夹, os.path.join(全, 里)))
    return 出


def 主():
    该改, 只报, 盖戳, 只列测试 = [], [], 0, []
    单调处 = 0
    for 桶, 路 in 收文件():
        try:
            with open(路, encoding="utf-8") as f:
                行们 = f.readlines()
        except OSError:
            continue
        短名 = os.path.relpath(路, 根)
        内文档 = False
        for i, 行 in enumerate(行们, 1):
            if 行.count(chr(34) * 3) % 2 == 1:      # 三引号开/合那一行
                内文档 = not 内文档
                continue
            if "monotonic()" in 行 or "perf_counter()" in 行:
                单调处 += 1
            if 内文档 or "time.time()" not in 行:
                continue
            if "查时钟:允许" in "".join(行们[max(0, i - 4):i + 1]):
                continue    # 豁免标记写在上一行也算 ✓（注释写在上面最自然 ✓）
            # 误报比漏报更危险 —— 三种不算（都是今天实测撞出来的）：
            #   1. 我自己这个文件：正文里到处在讲 time.time() ✓ 那是文档 ✓
            #   2. 测试文件（测*.py）：它们**故意造假时间戳**来造状态 ✓ 那是正事 ✓
            #   3. 注释行 / 三引号文档块里的举例 ✓
            去空白 = 行.strip()
            if os.path.basename(路) == "查时钟.py" or 去空白.startswith("#"):
                continue
            if os.path.basename(路).startswith("测"):
                只列测试.append("%s:%d  %s" % (短名, i, 去空白[:88]))
                continue
            上下 = "".join(行们[max(0, i - 4):i + 3])
            像判据 = (any(w in 行 for w in 判据味)
                    or any(w in 上下 for w in ("超时", "间隔", "deadline", "过期", "已等"))
                    or re.search(r"time\.time\(\)\s*-\s*\w", 行)
                    or re.search(r"\w\s*-\s*time\.time\(\)", 行))
            if 像判据 and not any(w in 行 for w in 戳味):
                (只报 if 桶 == "主链" else 该改).append("%s:%d  %s" % (短名, i, 行.strip()[:96]))
            else:
                盖戳 += 1

    print("═══ 查时钟（老祖课第五课：Lamport）═══")
    print("单调钟用量：%d 处 ✓ ｜ 墙钟当时间戳：%d 处 ✓（正当 ✓）" % (单调处, 盖戳))
    if 只报:
        print("\n【主链 bridge.py —— 红线 ✗ 只报不改，要动得主人点头】")
        for x in 只报:
            print("  · " + x)
    if 只列测试:
        print("")
        print("【测试 / 工装（测*.py）—— 只列不拦（要故意造假时间戳来造状态）】")
        for x in 只列测试[:8]:
            print("  · " + x)
    if 该改:
        print("\n【外挂 / tools —— 该改 ✗（判据必须走单调钟 ✓）】")
        for x in 该改:
            print("  · " + x)
        print("\n  改法：把那行判据换成 `time.monotonic()` ✓，")
        print("        但**戳和判据要成对** ✗ —— 只改一半比原来更糟（今天亲眼见过 ✓）")
        print("        真有一处非用不可 ⇒ 那行加注释 `查时钟:允许` 并写清为什么 ✓")
        return 1
    print("\n✔ 没有「该改」的 ✓（主链那几处见上，红线只报 ✓）")
    return 0


if __name__ == "__main__":
    sys.exit(主())
