#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查 JSON —— 把仓库里所有该合法的 JSON 过一遍，坏掉就**当场红**。

English: Validates every JSON file the project depends on. A broken manifest must fail
loudly here, not blow up four test files later.

★ 为什么要有它（2026-10-09，**同一天栽了两次**）
================================================
  第一次：`外挂/复核/manifest.json` 里混进一个 **ASCII 双引号**（本来该用「」）
          → 车钩读不动 → `发现车厢` 抛异常 → **一次带崩 4 个测试文件**（667 条过 ✗）
  第二次：`node/plugins/能力/collect/manifest.json` 同样的事 ✓
  ⇒ 同一个病，**两小时里来了两次** ✗ 那就是"该有个闸门"的信号 ✓

★ 这正好也是主人问「GitHub 上有什么能用的」时我列的第 ③ 条
  （`ajv` / `zod` 校验 ✓ MIT ✓）—— **但这件事用 Python 标准库 20 行就够** ✓
  所以**不引库** ✓：多一个依赖就多一份许可证账 ✓ 没必要 ✗
  （⚠ 引库要看许可证 ✓ 而"能不引就不引"是更省事的纪律 ✓）

跑法：python3 tools/查JSON.py        （`tools/跑全部.sh` 里已经挂上 ✓）
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 这些目录里的 .json **必须合法**（车厢清单 / 常识库 / 手侧插件 / 配置）
要找 = ("外挂", "常识库", "node/plugins", ".")
跳过目录 = {".git", "node_modules", "__pycache__", ".venv", "logs", "runtime", "历史"}


def 扫():
    出 = []
    for 根, 子目录们, 文件们 in os.walk(ROOT):
        子目录们[:] = [d for d in 子目录们 if d not in 跳过目录]
        for f in 文件们:
            if not f.endswith(".json"):
                continue
            p = os.path.join(根, f)
            相对 = os.path.relpath(p, ROOT)
            # 只查我们自己的那几个目录（别去踩第三方的东西 ✗）
            if not (相对.startswith("外挂/") or 相对.startswith("常识库/")
                    or 相对.startswith("node/plugins/") or "/" not in 相对):
                continue
            出.append(p)
    return sorted(出)


def 主():
    坏 = []
    好 = 0
    for p in 扫():
        try:
            with open(p, encoding="utf-8") as f:
                json.load(f)
            好 += 1
        except Exception as e:
            # 把**位置**说清楚（第几行第几列）+ 把那一行列出来 ✓
            行号 = getattr(e, "lineno", None)
            提示 = ""
            if 行号:
                try:
                    with open(p, encoding="utf-8") as f2:
                        行 = f2.read().splitlines()
                    if 0 < 行号 <= len(行):
                        列 = getattr(e, "colno", 0) or 0
                        提示 = (f"\n        第 {行号} 行：{行[行号 - 1][:150]}"
                              + (f"\n        {' ' * (8 + max(0, 列 - 1))}^ 这里" if 列 else ""))
                except Exception:
                    pass
            坏.append((os.path.relpath(p, ROOT), str(e), 提示))
    print(f"查 JSON：{好} 个好 ｜ {len(坏)} 个坏")
    for 名, 错, 提示 in 坏:
        print(f"  ❌ {名}\n        {错}{提示}")
    if 坏:
        print("\n★ 规矩：**这些文件必须合法** ✗ —— 一个坏的 manifest 会带崩一整列车 ✓"
              "\n  （2026-10-09 同一天因为这个栽了两次 ✓ 所以加了这道闸门 ✓）")
        print("★ 手写 JSON 里**不许出现 ASCII 双引号** ✗ —— 中文里要引东西请用「」✓")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(主())
