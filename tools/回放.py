#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M3·回放：把录下来的状态序列喂给反射层，看它每一步做什么。

为什么需要它：M2 / M2.1 那两轮，改一个参数就得放僵尸、肉眼看日志。
到 M3 彻底撑不住了 —— LLM 的行为没法肉眼比对，反射层也越改越细。
有了回放，改一个参数之后**同一段录像跑两遍，逐帧对比动作序列**。

用法：
    python3 tools/录制.py 30                       # 先录一段
    python3 tools/回放.py logs/录像-xxx.jsonl --存 logs/基准.json
    # 改参数 / 改代码之后：
    python3 tools/回放.py logs/录像-xxx.jsonl --对照 logs/基准.json

退出码：0 = 和基准一致；1 = 有差异（会把差异逐条打出来）。

⚠ 时间处理：反射层用 time.time() 做冷却判断（逃跑冷却、进食冷却、反击冷却…）。
回放时如果按真实时间跑，100 帧会在 1 毫秒内过完，所有冷却都算作"刚触发过"，
结果全错。所以这里**用一个虚拟时钟**，按录像里的 t 字段推进。
"""
import argparse
import json
import os
import sys
import time as _时间

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ── 虚拟时钟必须在 import bridge 之前装好，而且装的是同一个模块对象 ──
_虚拟 = [0.0]
_时间.time = lambda: _虚拟[0]

import bridge  # noqa: E402


class 假温度计:
    cpu = None
    gpu = None
    def 采样(self, 强制=False):
        return None, None


class 假接口:
    def __init__(self, 记录):
        self.记录 = 记录
    def 发(self, 命令):
        self.记录.append(命令)
        return True


def 跑一遍(状态们, cfg):
    """喂一串状态，返回每一步的动作 + 发出去的命令。"""
    m1 = cfg.get("m1") or {}
    m2 = cfg.get("m2") or {}
    m4 = cfg.get("m4") or {}
    日志 = []
    说 = lambda 行, 紧急=False, 不计流=False: None      # 回放时不打叙事，只看动作
    反射 = bridge.反射层({**m1, **m2, **m4}, 说)  # 和主链保持一致，不然测的是另一个东西
    节拍 = bridge.节拍器(m2, 说)
    节拍.外部要快 = 反射.在追猎        # 主链也是这么接的，别漏
    温度 = 假温度计()

    for 帧 in 状态们:
        _虚拟[0] = float(帧.get("t", _虚拟[0])) / 1000.0
        命令 = []
        iface = 假接口(命令)
        try:
            bridge._跑一轮反射(帧, 反射, type("N", (), {"静默移动": False})(),
                              温度, iface, False, 节拍, None)
        except Exception as e:
            日志.append({"t": 帧.get("t"), "错误": f"{type(e).__name__}: {e}", "命令": []})
            continue
        日志.append({
            "t": 帧.get("t"),
            "状态": 反射.状态,
            "命令": 命令,
        })
    return 日志


def 精简(日志):
    """只留下"动作变了"的帧 —— 逐帧比会把噪音算进来。"""
    出 = []
    上次 = None
    for 条 in 日志:
        现在 = (条.get("状态"), json.dumps(条.get("命令", []), ensure_ascii=False, sort_keys=True))
        if 现在 != 上次:
            出.append({"状态": 条.get("状态"), "命令": 条.get("命令")})
            上次 = 现在
    return 出


def 主():
    p = argparse.ArgumentParser(description="把录像喂给反射层，看它每一步做什么")
    p.add_argument("录像")
    p.add_argument("--存", dest="存到", help="把这次的动作序列存成基准")
    p.add_argument("--对照", dest="对照", help="和基准比，有差异就以退出码 1 结束")
    p.add_argument("--详细", action="store_true", help="逐帧打印（默认只打印动作变化）")
    a = p.parse_args()

    if not os.path.exists(a.录像):
        print(f"找不到录像：{a.录像}")
        return 1

    状态们 = []
    with open(a.录像, encoding="utf-8") as f:
        for 行 in f:
            行 = 行.strip()
            if 行:
                try:
                    状态们.append(json.loads(行))
                except Exception:
                    pass
    if not 状态们:
        print("录像里一帧都没有。")
        return 1

    cfg = bridge.读配置()
    日志 = 跑一遍(状态们, cfg)
    动作 = 精简(日志)

    # 统计
    计数 = {}
    for 条 in 日志:
        计数[条.get("状态")] = 计数.get(条.get("状态"), 0) + 1
    错误 = [x for x in 日志 if "错误" in x]

    print(f"回放 {len(状态们)} 帧（{os.path.basename(a.录像)}）")
    print("  各状态帧数：" + "、".join(f"{k}={v}" for k, v in
                                  sorted(计数.items(), key=lambda x: -x[1])))
    print(f"  动作变化 {len(动作)} 次" + (f"，**执行异常 {len(错误)} 次**" if 错误 else "，无异常"))
    for e in 错误[:5]:
        print(f"    ✗ {e['错误']}")

    if a.详细:
        for 条 in 日志[:200]:
            print(f"    {条.get('t')} {条.get('状态')} {条.get('命令')}")

    if a.存到:
        os.makedirs(os.path.dirname(os.path.abspath(a.存到)), exist_ok=True)
        with open(a.存到, "w", encoding="utf-8") as f:
            json.dump(动作, f, ensure_ascii=False, indent=1)
        print(f"  基准已存 → {a.存到}")
        return 0

    if a.对照:
        if not os.path.exists(a.对照):
            print(f"找不到基准：{a.对照}")
            return 1
        with open(a.对照, encoding="utf-8") as f:
            基准 = json.load(f)
        差异 = []
        for i in range(max(len(基准), len(动作))):
            x = 基准[i] if i < len(基准) else None
            y = 动作[i] if i < len(动作) else None
            if json.dumps(x, ensure_ascii=False, sort_keys=True) != \
               json.dumps(y, ensure_ascii=False, sort_keys=True):
                差异.append((i, x, y))
        if not 差异:
            print("  ✅ 和基准完全一致")
            return 0
        print(f"  ⚠ 和基准有 {len(差异)} 处不同（前 8 处）：")
        for i, x, y in 差异[:8]:
            print(f"    #{i}  基准 {x}")
            print(f"    #{i}  现在 {y}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(主())
