#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1 看护 —— 保护机器，不是保护小家伙。

主人不在的时候，两层防线：
    第一层在 bridge.py 里：CPU ≥75℃ / GPU ≥70℃ 就把反射层挂起，凉了自动回来。
    第二层就是本脚本：万一大脑自己出事挂了，由它来兜底把机器保住。

它做的事：
    · 每 30 秒采一次样，追加写 logs/看护.csv（给报告用）
    · 连续 3 次超"软红线" → 记一条大字警告
    · 连续 3 次超"硬红线" → 直接停掉手和脑，并写 logs/紧急停机.txt

硬红线（比主人给的高一点，留出反应余量）：
    CPU > 82℃  或  GPU > 76℃  或  可用内存 < 800MB

用法：  python3 tools/看护.py            （后台跑）
        python3 tools/看护.py --前台       （自己看着它刷）
"""
import argparse
import glob
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "logs")

软_CPU, 软_GPU = 75.0, 70.0
硬_CPU, 硬_GPU, 硬_内存MB = 82.0, 76.0, 800


def 核温():
    最高 = None
    for hw in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            with open(os.path.join(hw, "name")) as f:
                if f.read().strip() not in ("coretemp", "k10temp", "zenpower"):
                    continue
        except OSError:
            continue
        for f in glob.glob(os.path.join(hw, "temp*_input")):
            try:
                with open(f) as fh:
                    v = int(fh.read().strip()) / 1000.0
            except Exception:
                continue
            最高 = v if 最高 is None else max(最高, v)
    return 最高


def 显卡温():
    try:
        o = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
        return float(o.stdout.strip().splitlines()[0]) if o.returncode == 0 else None
    except Exception:
        return None


def 可用内存MB():
    try:
        with open("/proc/meminfo") as f:
            for 行 in f:
                if 行.startswith("MemAvailable:"):
                    return int(行.split()[1]) / 1024.0
    except Exception:
        pass
    return None


_上次cpu = None


def 总CPU百分比():
    """用 /proc/stat 两次采样的差值算，不依赖任何第三方库。"""
    global _上次cpu
    try:
        with open("/proc/stat") as f:
            段 = f.readline().split()[1:]
        值 = [int(x) for x in 段]
        闲 = 值[3] + (值[4] if len(值) > 4 else 0)
        总 = sum(值)
    except Exception:
        return None
    if _上次cpu is None:
        _上次cpu = (总, 闲)
        return None
    总差 = 总 - _上次cpu[0]
    闲差 = 闲 - _上次cpu[1]
    _上次cpu = (总, 闲)
    if 总差 <= 0:
        return None
    return 100.0 * (1.0 - 闲差 / 总差)


def 找进程(名字, 模式):
    出 = []
    try:
        o = subprocess.run(["ps", "-eo", "pid,comm,args", "--no-headers"],
                           capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return 出
    for 行 in o.splitlines():
        段 = 行.split(None, 2)
        if len(段) < 3:
            continue
        if 段[1] == 名字 and 模式 in 段[2]:
            出.append(int(段[0]))
    return 出


def 占用RSSMB(pid):
    try:
        with open(f"/proc/{pid}/status") as f:
            for 行 in f:
                if 行.startswith("VmRSS:"):
                    return int(行.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def 全部停掉():
    """紧急情况：手和脑一起停。用 comm + 模式精确匹配，不用 pkill -f（那会杀掉自己）。"""
    停了 = []
    for 名, 模式 in (("node", "server.js"), ("python3", "bridge.py")):
        for pid in 找进程(名, 模式):
            try:
                os.kill(pid, 15)
                停了.append(f"{名}({模式}) pid={pid}")
            except Exception:
                pass
    return 停了


def 主():
    p = argparse.ArgumentParser()
    p.add_argument("--前台", action="store_true", help="输出到终端，方便盯")
    p.add_argument("--间隔", type=float, default=30.0)
    a = p.parse_args()

    os.makedirs(LOG, exist_ok=True)
    csv = os.path.join(LOG, "看护.csv")
    新建 = not os.path.exists(csv)
    f = open(csv, "a", encoding="utf-8")
    if 新建:
        f.write("时刻,cpu温度,cpu占用%,显卡温度,可用内存MB,手RSS_MB,脑RSS_MB\n")
    f.flush()

    连击软 = 连击硬 = 0

    def 报(行, 紧急=False):
        if a.前台 or 紧急:
            print(行, flush=True)

    报(f"[看护] 开工。软线 CPU>{软_CPU:.0f}/GPU>{软_GPU:.0f}，"
       f"硬线 CPU>{硬_CPU:.0f}/GPU>{硬_GPU:.0f}/内存<{硬_内存MB}MB")
    报(f"[看护] 采样写进 {csv}（每 {a.间隔:.0f} 秒一行）")

    while True:
        ct = 核温()
        gt = 显卡温()
        cp = 总CPU百分比()
        mem = 可用内存MB()
        手 = 找进程("node", "server.js")
        脑 = 找进程("python3", "bridge.py")
        手rss = sum(占用RSSMB(p) for p in 手)
        脑rss = sum(占用RSSMB(p) for p in 脑)

        时刻 = time.strftime("%Y-%m-%d %H:%M:%S")
        行 = [时刻,
              f"{ct:.0f}" if ct is not None else "",
              f"{cp:.1f}" if cp is not None else "",
              f"{gt:.0f}" if gt is not None else "",
              f"{mem:.0f}" if mem is not None else "",
              f"{手rss:.0f}", f"{脑rss:.0f}"]
        f.write(",".join(行) + "\n")
        f.flush()

        超软 = (ct is not None and ct >= 软_CPU) or (gt is not None and gt >= 软_GPU)
        超硬 = ((ct is not None and ct >= 硬_CPU) or (gt is not None and gt >= 硬_GPU)
                or (mem is not None and mem < 硬_内存MB))

        连击软 = 连击软 + 1 if 超软 else 0
        连击硬 = 连击硬 + 1 if 超硬 else 0

        if 超硬 and 连击硬 >= 3:
            停了 = 全部停掉()
            说明 = (f"{时刻} 连续 {连击硬} 次越过硬红线"
                    f"（CPU {ct}℃ / GPU {gt}℃ / 可用内存 {mem:.0f}MB），"
                    f"已紧急停掉：{停了}")
            报("[看护] ⚠⚠ " + 说明, 紧急=True)
            with open(os.path.join(LOG, "紧急停机.txt"), "a", encoding="utf-8") as g:
                g.write(说明 + "\n")
            连击硬 = 0
            time.sleep(120)
            continue

        if 超软 and 连击软 >= 3:
            报(f"[看护] ⚠ {时刻} 连续 {连击软} 次越过软红线"
               f"（CPU {ct}℃ / GPU {gt}℃）—— 第一层防线应该已经让大脑挂起了。",
               紧急=True)
            连击软 = 0

        time.sleep(a.间隔)


if __name__ == "__main__":
    try:
        主()
    except KeyboardInterrupt:
        sys.exit(0)
