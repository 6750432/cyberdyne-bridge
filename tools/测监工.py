#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测监工.py —— 监督树那几件事的断言（2026-10-09）

为什么要有它（当天两次事故换的）
================================
  ① 主人原话：「**监工别自动拉起手啊，小家伙在服务器日志刷屏了都**」
     当时真因**不是**监工"拉手"本身 ✗ —— 是它探到「进程在、`cyberdyne.sock` 不在」
     就**又起了一个手** ✗ ⇒ **两个手同时在线** ⇒ 服务端日志被 login fight 刷屏：
     `lost connection: You logged in from another location` → left → joined … 每 2 秒一轮 ✗✗
     ⇒ 规矩：**起之前先清场**（先杀后起 ✓）。这条在这里固化成断言 ✓
  ② 另一条：`config.json` 的 `监工.托管` 里点名 `false` 的组件，监工**碰都不碰** ✓
     （不拉、不尸检、不刷日志 ✓；`_说明` 这类注记键**不许**被当成组件名字 ✗）

⚠ 测试只碰**自己造的**进程（`sleep 937` / `sleep 938` 这种独有命令行 ✓）——
   绝不拿 `sleep` 去匹配（那会误杀主人自己的东西 ✗ 这条比测试本身重要 ✓）
"""

import importlib.util
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "监工", os.path.join(ROOT, "tools", "监工.py"))
监工 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(监工)

过, 失败 = 0, 0


def 试(名, 条件, 证据=""):
    global 过, 失败
    if 条件:
        过 += 1
        print("  ✅ %s" % 名)
    else:
        失败 += 1
        print("  ❌ %s —— %s" % (名, 证据))


def 主():
    print("── A 组：托管表（主人点名不托管的，碰都不碰）──")
    表 = 监工.托管表()
    试("A1 托管表读得出来（是个字典 ✓）", isinstance(表, dict), repr(表)[:80])
    试("A2 ⚠ `_说明` 这类注记键**不许**被当成组件名 ✗",
      all(not str(k).startswith("_") for k in 表), repr(list(表)[:6]))

    print("── B 组：清干净（先杀后起 —— 绝不许两份并存）──")
    # ⚠ 今天现学的一条：`/proc/<pid>/cmdline` 里**参数之间是 NUL 字节** ✗
    #   所以 `b"sleep 937"` 这种"带空格的整条命令行"**永远匹配不上** ✓
    #   （实测 B1 红了才看出来 ✓）⇒ 特征只能填**单个词**（`server.js` / `车钩.py` 都是单 token ✓）
    独有 = b"937"
    组 = {"名": "假组件", "进程名": "sleep", "特征": 独有}
    # ★ 测试自己也得干净 ✗：上一轮被 timeout 杀掉的测试**漏下过 4 个 sleep 937** ✓
    #   所以先按「先杀后起」清一次场 ✓（那条规矩对测试同样成立 ✓）
    监工.清干净(组)
    p = subprocess.Popen(["sleep", "937"], start_new_session=True)
    time.sleep(0.6)
    找 = 监工.找进程(组["进程名"], 组["特征"])
    试("B1 找进程认得出自家那一个 ✓（别的 sleep 一个都不碰 ✓）",
     找 == [p.pid], "找到 %r，期望 [%d]" % (找, p.pid))
    杀过 = 监工.清干净(组)
    time.sleep(0.4)
    还活 = 监工.找进程(组["进程名"], 组["特征"])
    试("B2 ★★★ 清干净真把它清掉了 ✓（「先杀后起」的前提 ✓）", 还活 == [], "还剩 %r" % 还活)
    试("B3 ★★★ 而且**出声记账**：返回杀了谁 ✓", p.pid in 杀过, "杀过=%r" % 杀过)
    试("B4 ★★ 清不着的组件 → 返回空表、不炸 ✓",
      监工.清干净({"名": "没有的", "进程名": "绝无此进程", "特征": b"xxx"}) == [])

    print("── C 组：在不在（光有进程不算数）──")
    ok0, 说0 = 监工.在不在({"名": "没有的", "进程名": "绝无此进程", "特征": b"xxx"})
    试("C1 不存在的进程 → 不在 ✓", ok0 is False, str(说0))
    p2 = subprocess.Popen(["sleep", "938"], start_new_session=True)
    time.sleep(0.6)
    ok1, 说1 = 监工.在不在({"名": "假服务端", "进程名": "sleep",
                        "特征": b"938", "端口": 59999})
    试("C2 ★★★ 进程在、端口不通 → **不算在** ✓（不然就是「看着在忙、其实没通」✓）",
      ok1 is False and "不通" in str(说1), str(说1))
    p2.kill()
    try:
        p2.wait(timeout=3)
    except Exception:
        pass

    # ⚠ 汇总行**必须以「N 失败」结尾** ✓ —— 跑全部.sh 就是按这个抓的 ✗
    #   （我第一版尾巴多印了 `═══` → 被闸门判成「一条断言都没解析到」✗ 实测 ✓）
    print("\n监工：%d 过 / %d 失败" % (过, 失败))
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(主())
