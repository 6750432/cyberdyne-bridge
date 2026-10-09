#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""监工 —— **Erlang 那一课：监督树** ✓  2026-10-09

═══ 为什么要有它（今天用血换的）═══
  · 手和脑**都带重连** ✓（手 `bot.on('end')` ✓ 脑「断了不退出，交给上层重连」✓）
    可那只管 **连接断** ✗ —— **进程死了没人拉** ✗
  · 今天 OOM 就是这么瘫的 ✓ 三个一起死，谁也没管谁 ✗
  · `tools/看护.py` 只管**温度/内存** ✗ 不管"谁还在不在" ✗
  ⇒ 缺的那块就是 **监督树** ✓

═══ Erlang 的四条课（照抄 ✓ 不加戏）═══
  ① **隔离**：三个各自是独立进程 ✓ 一个死了不带走别人 ✓
     （起子进程用 start_new_session ⇒ 连**监工自己**死了都带不走它们 ✓）
  ② **监督 + 顺序**：谁不在就拉起来 ✓ 但**服务端 → 手 → 脑**这个先后**不能乱** ✗
     （服务端没起来，起了手也连不上 ⇒ 白起 ✓ 还会把它自己刷成一堆失败日志 ✗）
  ③ **let it crash**：不去"修"它 ✓ 直接拉一个干净的 ✓
  ④ **重启强度（max_restarts / max_seconds）**：Erlang 的 supervisor 有这个上限 ✓
     短时间反复死 ⇒ **停手、大喊** ✗ 不许闷头重试 ✗
     （闷头重试 = "看起来在忙" = 这个项目最恨的那种假活 ✓）

═══ 两条铁律（都是这个项目反复吃过的亏）═══
  · **不许用 `ps` 判进程** ✗ —— locale=C 时它把中文 cmdline 糊成 `??????` ✗
    今天一小时内咬我两次（看护找不到脑 + 我以为看护没起来）✓ ⇒ 一律读 `/proc` ✓
  · **每次动手都要出声** ✓ —— 重启了谁、为什么、第几次，全写 logs/监工.log ✓

用法：
    python3 tools/监工.py            # 跑起来（一般交给 systemd 管）
    python3 tools/监工.py --自检     # 只看不控：验证探测器和正门都在 ✓
    python3 tools/监工.py --间隔 10  # 检查间隔秒数（默认 15）
"""

import argparse
import collections
import json
import os
import socket
import subprocess
import sys
import time

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
日志 = os.path.join(根, "logs", "监工.log")
放弃牌 = os.path.join(根, "logs", "监工-放弃.txt")
心跳 = os.path.join(根, "logs", "监工-心跳.json")

# ★ 重启强度：Erlang 的 supervisor 就是这套参数 ✓
滑动窗秒 = 300
窗口内最多 = 5

组件 = [
    {
        "名": "服务端",
        "进程名": "java",
        "特征": b"server.jar",              # 拿**字节**比 ✓ 不经过 ps ✗
        "起法": ["bash", "tools/启动服务端.sh"],
        "日志": os.path.join(根, "logs", "服务端.log"),
        "端口": 25565,
        "等秒": 45,
        "为什么": "它是地 ✓ 没它手和脑连上去也没用 ✗",
    },
    {
        "名": "手",
        "进程名": "node",
        "特征": b"server.js",
        "起法": ["bash", "tools/启动手.sh"],
        "日志": os.path.join(根, "logs", "手.log"),
        "套接文件": os.path.join(根, "cyberdyne.sock"),
        "等秒": 8,
        "为什么": "它握着到 Minecraft 的连接 ✓ 换脑它没感觉 ✓ 但它没了脑就瞎了 ✓",
    },
    {
        "名": "脑",
        "进程名": "python3",
        "特征": "车钩.py".encode("utf-8"),   # ★ 脑**不是** bridge.py ✗ 它跑在车钩里 ✓
        "起法": ["bash", "外挂/启动列车.sh"],
        # ★ 脑自己的 stdout 本来就通向 logs/大脑.log ✓（查 /proc/27062/fd/1 得到的 ✓）
        #   我原先写成 logs/脑.log ✗ ⇒ 两处对不上 ✓ 对齐它 ✓
        "日志": os.path.join(根, "logs", "大脑.log"),
        "等秒": 10,
        "为什么": "它是「想事」的那个 ✓ 换它不影响手 ✓",
    },
]

计数 = collections.defaultdict(lambda: collections.deque())   # 名 → 重启时刻
检查次数 = 0
重启次数 = collections.defaultdict(int)


def 报(文, 急=False):
    行 = "[%s]%s %s" % (time.strftime("%m-%d %H:%M:%S"), " ⚠" if 急 else "", 文)
    print(行, flush=True)
    try:
        with open(日志, "a", encoding="utf-8") as f:
            f.write(行 + "\n")
    except OSError:
        pass


# ── 判进程：**读 /proc** ✓（不碰 ps ✗）──
def 找进程(进程名, 特征):
    出 = []
    try:
        号们 = [d for d in os.listdir("/proc") if d.isdigit()]
    except OSError:
        return 出
    for 号 in 号们:
        try:
            with open("/proc/%s/comm" % 号, "rb") as f:
                if f.read().strip().decode("utf-8", "replace") != 进程名:
                    continue
            with open("/proc/%s/cmdline" % 号, "rb") as f:
                if 特征 in f.read():
                    出.append(int(号))
        except OSError:
            continue
    return 出


def 端口通(端口):
    s = socket.socket()
    s.settimeout(1.0)
    try:
        s.connect(("127.0.0.1", 端口))
        return True
    except OSError:
        return False
    finally:
        s.close()


def 在不在(组):
    """→ (在不在, 说明) ✓ 光有进程不算数：服务端还得**端口通** ✓ 手还得**套接文件在** ✓"""
    pid = 找进程(组["进程名"], 组["特征"])
    if not pid:
        return False, "进程不在"
    if "端口" in 组 and not 端口通(组["端口"]):
        return False, "进程在(pid %s) 但端口 %d 不通" % (pid[0], 组["端口"])
    if "套接文件" in 组 and not os.path.exists(组["套接文件"]):
        return False, "进程在(pid %s) 但 %s 不在" % (pid[0], os.path.basename(组["套接文件"]))
    return True, "pid %s" % pid[0]


def 拉起(组):
    """★ 隔离：start_new_session ⇒ 连监工自己死了都带不走它 ✓"""
    os.makedirs(os.path.dirname(组["日志"]), exist_ok=True)
    f = open(组["日志"], "ab")
    p = subprocess.Popen(组["起法"], cwd=根, stdout=f, stderr=f,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    窗口 = 计数[组["名"]]
    现在 = time.time()
    窗口.append(现在)
    while 窗口 and 现在 - 窗口[0] > 滑动窗秒:
        窗口.popleft()
    重启次数[组["名"]] += 1
    return p.pid, len(窗口)


def 超强度(组):
    窗口 = 计数[组["名"]]
    现在 = time.time()
    while 窗口 and 现在 - 窗口[0] > 滑动窗秒:
        窗口.popleft()
    return len(窗口) >= 窗口内最多


def 服务端健康():
    return 在不在(组件[0])[0]


def 一轮(干不干=True):
    """★ 顺序不能乱 ✗：服务端 → 手 → 脑 ✓
    服务端不在 ⇒ **先把地弄好，别人一个都别动** ✓（动了也是白起 ✗）"""
    global 检查次数
    检查次数 += 1
    好没有 = []
    for 组 in 组件:
        ok, 说明 = 在不在(组)
        if ok:
            好没有.append("%s(%s)" % (组["名"], 说明))
            continue
        if not 干不干:
            好没有.append("%s ✗ %s" % (组["名"], 说明))
            continue
        # 依赖没满足就**先别动它** ✗
        if 组["名"] != "服务端" and not 服务端健康():
            好没有.append("%s（不动：服务端没好 ✓ 起了也白起）" % 组["名"])
            break
        if 超强度(组):
            报("✗✗ %s 在 %d 秒里已经重启 %d 次了 —— **停手** ✓ 不闷头重试 ✗"
               % (组["名"], 滑动窗秒, 窗口内最多), 急=True)
            try:
                with open(放弃牌, "a", encoding="utf-8") as f:
                    f.write("%s %s 超过重启强度，停手\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), 组["名"]))
            except OSError:
                pass
            time.sleep(60)
            计数[组["名"]].clear()
            好没有.append("%s（冷却中）" % 组["名"])
            continue
        pid, 次 = 拉起(组)
        报("★ 拉起了「%s」✓ pid %s ｜ 为什么：%s ｜ 近 %d 秒第 %d 次"
           % (组["名"], pid, 说明, 滑动窗秒, 次), 急=True)
        # 等了再往下走 ✓（服务端要等端口真通 ✓ 手/脑等它自己起完 ✓）
        到 = time.time() + 组["等秒"]
        while time.time() < 到:
            time.sleep(2)
            if 在不在(组)[0]:
                break
        ok, 说明2 = 在不在(组)
        报("   「%s」%s（%s）" % (组["名"], "起来了 ✓" if ok else "还没好 ✗ 下一轮再看 ✓", 说明2),
           急=not ok)
        if 组["名"] == "服务端" and not ok:
            break        # ★ 地没弄好 ⇒ 手和脑一个都别动 ✓
    try:
        with open(心跳, "w", encoding="utf-8") as f:
            json.dump({"时刻": time.strftime("%Y-%m-%d %H:%M:%S"), "检查次数": 检查次数,
                       "重启次数": dict(重启次数), "现状": 好没有},
                      f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return 好没有


def 自检():
    """★ 只看不控 ✓ 探到的东西必须**跟真的一样** ✓"""
    过, 不过 = [], []
    for 组 in 组件:
        ok, 说明 = 在不在(组)
        (过 if ok else 不过).append("%s 探到了" % 组["名"])
        print("  %s %-4s → %s" % ("✓" if ok else "✗", 组["名"], 说明))
        脚本 = os.path.join(根, 组["起法"][-1])
        在 = os.path.exists(脚本)
        (过 if 在 else 不过).append("%s 的正门在" % 组["名"])
        print("     正门：%s %s" % (组["起法"][-1], "✓" if 在 else "✗ 找不到"))
    print("  现状：%s" % " ｜ ".join(一轮(干不干=False)))
    print("\n═══ 自检：%d 过 / %d 失败 ═══" % (len(过), len(不过)))
    return 0 if not 不过 else 1


def 主():
    p = argparse.ArgumentParser()
    p.add_argument("--间隔", type=float, default=15.0)
    p.add_argument("--自检", action="store_true")
    a = p.parse_args()
    if a.自检:
        return 自检()
    报("═══ 监工上班 ✓ 看着：%s ⇒ 谁是「忙」的、谁是「装忙」，它说了算 ✓" %
       " → ".join(g["名"] for g in 组件))
    for 组 in 组件:
        报("   %s：%s" % (组["名"], 组["为什么"]))
    while True:
        现状 = 一轮()
        if 检查次数 % 20 == 0:
            报("例行：%s" % " ｜ ".join(现状))
        time.sleep(a.间隔)


if __name__ == "__main__":
    sys.exit(主())
