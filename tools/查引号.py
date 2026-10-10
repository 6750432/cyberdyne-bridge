#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""查引号.py —— 一次性找出「双引号字符串里又套了 ASCII 双引号」的行。

为什么要有它：大肥鱼 2026-10-08~09 一天里**栽了 8 次** ✗
  `试("D2 交回原方法了（所以抛了那个"原方法"的异常 ✓）"` ← 就是这样
  每次都表现为 SyntaxError: invalid syntax. Perhaps you forgot a comma?
  而每次我都要等跑测试才发现 ✗
规矩：中文文案里的引号一律用「」，不许用 ASCII 的 " ✗
这个脚本不用等跑测试 —— 写完当场扫一遍 ✓
"""
import ast, os, sys

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
坏 = []
for 底, _, 文件们 in os.walk(根):
    if '__pycache__' in 底 or '/.git' in 底:
        continue
    for 名 in 文件们:
        if not 名.endswith('.py'):
            continue
        路 = os.path.join(底, 名)
        try:
            ast.parse(open(路, encoding='utf-8').read())
        except SyntaxError as e:
            if 'invalid syntax' in str(e):
                坏.append((os.path.relpath(路, 根), e.lineno, (e.text or '').strip()[:90]))
if 坏:
    print(f"✗ {len(坏)} 个文件有落单的引号（大概又是双引号套双引号）：")
    for 路, 行, 文 in 坏:
        print(f"  {路}:{行}  {文}")
    sys.exit(1)
print("✓ 所有 .py 都能解析（没有落单的引号）")
