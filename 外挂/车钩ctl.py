#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外挂列车·遥控器 —— 脑在跑的时候，从另一个终端给车钩下命令。

┌───────────────────────────────────────────────────────────────┐
│ 这就是「随时连/断」的那只手                                    │
└───────────────────────────────────────────────────────────────┘
脑是以 `车钩.py` 起的，它会在 `外挂/车钩.sock` 上开一个只给本机
这个用户的插座（0600）。本脚本连上去，发一行 JSON，收一行 JSON。

用法：
    python3 外挂/车钩ctl.py                看现在挂了哪几节（同 编组）
    python3 外挂/车钩ctl.py 编组           同上
    python3 外挂/车钩ctl.py 列             列出**磁盘上**发现到的所有车厢
    python3 外挂/车钩ctl.py 挂 受限脚本     热挂一节（不用重启脑）
    python3 外挂/车钩ctl.py 摘 受限脚本     热摘一节
    python3 外挂/车钩ctl.py 摘 受限脚本,动作面   一次摘多节（原子）
    python3 外挂/车钩ctl.py 重排 受限脚本,动作面 重新排序
    python3 外挂/车钩ctl.py 验             重跑宪法体检
    python3 外挂/车钩ctl.py 记事           看换轨历史
    python3 外挂/车钩ctl.py 查 动作面      看某节的铭牌

★ 命令失败（比如「任务正用着这节，不许摘」）会**原样把车钩的理由打出来**，
  不会吞掉。退出码：0 成功 / 1 车钩拒绝 / 2 连不上插座。
"""

import json
import os
import socket
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
插座路径 = os.path.join(ROOT, "外挂", "车钩.sock")

帮助 = __doc__


def 连(路径=插座路径, 超时=8):
    if not os.path.exists(路径):
        print(f"❌ 连不上车钩插座：{os.path.relpath(路径, ROOT)} 不存在。", file=sys.stderr)
        print("   可能是：① 脑没在跑；② 脑不是用 `车钩.py` 起的（而是老的 大脑外挂.py）。",
              file=sys.stderr)
        print("   起车：bash 外挂/启动列车.sh", file=sys.stderr)
        return None
    甲 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    甲.settimeout(超时)
    try:
        甲.connect(路径)
    except OSError as e:
        print(f"❌ 插座连不上：{e}", file=sys.stderr)
        甲.close()
        return None
    return 甲


def 问(请求, 路径=插座路径):
    甲 = 连(路径)
    if 甲 is None:
        return None
    try:
        with 甲:
            甲.sendall((json.dumps(请求, ensure_ascii=False) + "\n").encode("utf-8"))
            缓冲 = b""
            while b"\n" not in 缓冲:
                块 = 甲.recv(65536)
                if not 块:
                    break
                缓冲 += 块
    except OSError as e:
        print(f"❌ 收发失败：{e}", file=sys.stderr)
        return None
    if b"\n" not in 缓冲:
        print("❌ 车钩没回话（它可能在忙，或者刚退出）", file=sys.stderr)
        return None
    try:
        return json.loads(缓冲.split(b"\n", 1)[0].decode("utf-8"))
    except Exception as e:
        print(f"❌ 回话看不懂：{e}", file=sys.stderr)
        return None


# ══════════════════════════ 打印 ══════════════════════════

def 印编组(单):
    编 = 单.get("编组") or []
    if not 编:
        print("🚂 现在是**空车**（一节车厢都没挂）")
    else:
        print(f"🚂 现在挂着 {len(编)} 节：" + " → ".join(编))
    for 节 in (单.get("车厢") or []):
        尾 = []
        if 节.get("提供动作"):
            尾.append("提供 " + "、".join(节["提供动作"]))
        if not 节.get("可热拔"):
            尾.append("**不可热拔**")
        print(f"   · {节['id']}　{节['名字']}　v{节['版本']}"
              + ("　（" + "｜".join(尾) + "）" if 尾 else ""))


def 印结果(单):
    if 单 is None:
        return 2
    if not 单.get("ok"):
        print("❌ 车钩拒绝：" + str(单.get("错")))
        if 单.get("栈"):
            print("  （车钩自己的异常栈，前几行）")
            for 行 in str(单["栈"]).splitlines()[:6]:
                print("     " + 行)
        return 1
    if 单.get("备注"):
        print("✅ " + 单["备注"])
    if "编组" in 单:
        印编组(单)
    if 单.get("体检"):
        体 = 单["体检"]
        print("   宪法体检：" + ("✅ 全过" if 体.get("好") else "❌ 有问题"))
        for x in (体.get("查了") or []):
            print("     ✓ " + x)
        for x in (体.get("问题") or []):
            print("     ✗ " + x)
    return 0


def 看磁盘():
    """`列` 命令：不用连插座，直接扫磁盘 —— 脑没跑的时候也能看家底。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import 车钩
    try:
        表 = 车钩.发现车厢()
    except 车钩.清单错 as e:
        print("❌ 车厢清单有问题：" + str(e))
        return 1
    if not 表:
        print("（一节车厢都没有。一个目录里放 manifest.json 就成了车厢。）")
        return 0
    print(f"磁盘上发现 {len(表)} 节车厢：")
    for 名 in sorted(表, key=lambda n: (表[n].顺序, n)):
        节 = 表[名]
        print(f"  · {节.名:10s} {节.全名}")
        print(f"      入口 {节.入口}｜顺序 {节.顺序}｜"
              f"{'可热拔' if 节.可热拔 else '**不可热拔**'}"
              f"｜{'依赖 ' + '、'.join(节.依赖) if 节.依赖 else '无依赖'}")
        if 节.提供动作:
            print(f"      提供动作 {'、'.join(节.提供动作)}")
        if 节.补丁点:
            print(f"      补丁点 {'、'.join(节.补丁点)}")
    编 = None
    try:
        with open(os.path.join(ROOT, "外挂", "编组.json"), encoding="utf-8") as f:
            编 = json.load(f).get("编组")
    except Exception:
        pass
    if 编 is not None:
        print(f"（上次存的编组：{'、'.join(编) or '空车'}）")
    return 0


# ══════════════════════════ 主入口 ══════════════════════════

def 主(argv):
    if not argv:
        argv = ["编组"]
    头 = argv[0]
    尾 = argv[1:]

    if 头 in ("-h", "--help", "帮助", "help"):
        print(帮助)
        return 0
    if 头 == "列":
        return 看磁盘()

    if 头 == "编组":
        return 印结果(问({"cmd": "编组"}))
    if 头 == "验":
        return 印结果(问({"cmd": "验"}))
    if 头 == "记事":
        单 = 问({"cmd": "记事"})
        if 单 is None:
            return 2
        if not 单.get("ok"):
            print("❌ " + str(单.get("错")))
            return 1
        事 = 单.get("记事") or []
        if not 事:
            print("（还没有换过轨）")
        for x in 事:
            print(f"  {x.get('t')}　{x.get('备注')}")
        return 0
    if 头 in ("挂", "摘", "重排", "查"):
        if not 尾:
            print(f"❌ `{头}` 要跟一个车厢名。先跑 `车钩ctl.py 列` 看有哪些。",
                  file=sys.stderr)
            return 1
        值 = 尾[0]
        if 头 == "挂":
            return 印结果(问({"cmd": "挂", "名": 值}))
        if 头 == "摘":
            return 印结果(问({"cmd": "摘", "名": 值}))
        if 头 == "查":
            单 = 问({"cmd": "查", "名": 值})
            if 单 is None:
                return 2
            if not 单.get("ok"):
                print("❌ " + str(单.get("错")))
                return 1
            print(json.dumps(单.get("车厢"), ensure_ascii=False, indent=1))
            return 0
        # 重排
        顺序 = [x.strip() for x in 值.split(",") if x.strip()]
        return 印结果(问({"cmd": "重排", "顺序": 顺序}))

    print(f"❌ 不认识的命令「{头}」\n", file=sys.stderr)
    print(帮助, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(主(sys.argv[1:]))
