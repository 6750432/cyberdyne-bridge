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
import signal
import socket
import subprocess
import sys
import time

根 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
日志 = os.path.join(根, "logs", "监工.log")
放弃牌 = os.path.join(根, "logs", "监工-放弃.txt")


def 托管表():
    """哪些组件**归监工托管** ✓

    ★★★ 2026-10-09 主人点名：「**监工别自动拉起手啊，小家伙在服务器日志刷屏了都**」
      现场：监工起了**两个手**（137620 + 141572 ✗，探测到「进程在但 socket 不在」
      就又起了一个 ✗），加上我手动起的一个 = **三个手抢同一个账号** ✗ ⇒ 服务器日志
      被 login fight 刷屏：`lost connection: You logged in from another location`
      → `left the game` → 立刻又 `joined the game` … 每 2 秒一轮 ✗✗

    规矩：`config.json` 的 `监工.托管` 里点名 `false` 的，**一律不碰** ✓
          没写 = 照旧托管 ✓（缺省行为不变 ✓ 不许悄悄改行为 ✗）
    用法：`"监工": {"托管": {"手": false}}` ✓ —— 想恢复就把它删掉或改 true ✓
    """
    try:
        with open(os.path.join(根, "config.json"), encoding="utf-8") as f:
            配 = json.load(f) or {}
        托 = (配.get("监工") or {}).get("托管") or {}
        # ⚠ `_说明` 这类注记键要**滤掉** ✗（不然它会被当成一个叫「_说明」的组件 ✓ 无害但脏 ✓）
        return {str(k): bool(v) for k, v in 托.items() if not str(k).startswith("_")}
    except Exception:
        return {}                     # 读不了 = 谁都没点名 → 照旧全托管 ✓
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
# ★★ Erlang 那一课的另一半：**崩溃要留「为什么」** ✗
#   监工记着自己起过的进程 ⇒ 它死的时候**拿得到退出码/信号** ✓
#   （不是监工起的就拿不到 ✗ —— 那就老老实实说"拿不到" ✗ 不许编一个原因 ✗）
句柄 = {}                       # 名 → Popen ✓
上次死的因 = {}                 # 名 → 一句话 ✓（写进心跳，也写进日志 ✓）
尸检本 = os.path.join(根, "logs")
上次心跳 = {}
# ★ 监工**自己重启过**的时候，上一批进程的句柄就丢了 ✗
#   ⇒ 从心跳文件里把"上一轮记的 pid"读回来 ✓ 至少知道"它上一轮还在不在"✓
try:
    with open(心跳, "r", encoding="utf-8") as _f:
        _旧 = json.load(_f)
    上次心跳 = _旧.get("各组件") or {}
except (OSError, ValueError):
    pass
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


def 清干净(组):
    """起它之前：把**同一个组件还活着的副本全清掉** ✓（先杀后起 ✓ 绝不许两个同时在线 ✗）

    ★★★ 2026-10-09 主人：「监工别自动拉起手啊，小家伙在服务器日志刷屏了都」
      真因：`在不在` 那句「进程在、但 cyberdyne.sock 不在」⇒ 监工**又起一个** ✗
      ⇒ **两个手同时在线** ⇒ 服务端日志被 login fight 刷屏
        （`lost connection: You logged in from another location` → left → joined … ✗）
      现在：起之前先清场 ✓ —— 而且**只清这个组件的** ✓（别人的进程一根汗毛都不碰 ✗）
      出声记账 ✓：杀了谁、几个 ✓（这条项目铁律）
    """
    try:
        们 = list(找进程(组["进程名"], 组["特征"]) or [])
    except Exception:
        return []
    杀过 = []
    for pid in 们:
        try:
            os.kill(int(pid), signal.SIGTERM)
            杀过.append(int(pid))
        except (OSError, ValueError):
            pass
    if not 杀过:
        return []
    time.sleep(1.5)                      # 给它一点时间体面地走 ✓
    for pid in 杀过:
        try:
            os.kill(pid, signal.SIGKILL)  # 还不走就**必须**请走 ✓（否则就是两份并存 ✗）
        except OSError:
            pass
    return 杀过


def 尾巴(路径, 行数=25):
    """文件最后几行 ✓ 读不到就明说 ✗ 不许装看不见 ✓"""
    try:
        with open(路径, "r", encoding="utf-8", errors="replace") as f:
            所有 = f.readlines()
        return "".join(所有[-行数:]) or "（空的 ✓）"
    except OSError as e:
        return "（读不到：%s）" % e


def 尸检(组, 说明):
    """★★★ 进程死了 ⇒ **留一份现场** ✗ 不许只留一句「进程不在」✓

    为什么这条非得有：今天整机 OOM 那一下，
    我们**只知道"瘫了"，不知道"谁先死的、为什么"** ✗（journald 都没来得及落盘 ✓）
    这就是 Erlang 那套里的 crash dump ✓ —— 跟求解器的**追因链**是同一个思想：
    一个管"活着的失败" ✓ 一个管"死了的失败" ✓
    """
    时刻 = time.strftime("%Y%m%d-%H%M%S")
    路径 = os.path.join(尸检本, "尸检-%s-%s.txt" % (组["名"], 时刻))
    句 = 句柄.get(组["名"])
    上次记的 = (上次心跳.get(组["名"]) or {}).get("pid")
    码 = None
    try:
        if 句 is not None:
            码 = 句.poll()
    except Exception:
        pass
    if 码 is None:
        if 上次记的:
            因 = ("上一条命是监工起的（pid %s）✓ 但监工**自己重启过** ✗"
                 " ⇒ 这段**空窗期**里的退出码/信号**拿不到** ✗（只能靠下面这些线索 ✓）"
                 " —— 不许猜、也不许不认账 ✗" % 上次记的)
        else:
            因 = ("不是监工起的（或还在退出中）⇒ **拿不到退出码** ✗ 只能靠下面这些线索 ✓")
    elif 码 < 0:
        因 = "被信号 %d 杀了（%s）%s" % (-码, {9: "SIGKILL —— OOM 或被 kill -9 ✓",
                                            15: "SIGTERM —— 被叫停 ✓",
                                            6: "SIGABRT —— 自己崩的 ✓"}.get(-码, "查 man 7 signal ✓"),
                                        " ✓")
    else:
        因 = "正常退出码 %d ✓（自己走掉的 ✓ 不是被杀的 ✓）" % 码
    内存 = ""
    try:
        with open("/proc/meminfo") as f:
            for 行 in f:
                if 行.startswith("MemAvailable"):
                    内存 = 行.strip()
                    break
    except OSError:
        pass
    行 = []
    行.append("═══ 尸检 · %s ═══" % 组["名"])
    行.append("时刻：%s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    行.append("发现方式：%s" % 说明)
    行.append("退出/信号：%s" % 因)
    行.append("当时内存：%s" % (内存 or "（读不到 ✗）"))
    if 上次记的:
        行.append("上一轮记的 pid：%s（现在这个位置的进程不在 ⇒ pid 变了或真没了 ✓）" % 上次记的)
    行.append("")
    行.append("── 内核有没有 OOM 记录（试三个地方 ✓ 哪个读得到用哪个 ✓）──")
    找到 = False
    for 源 in ("/var/log/kern.log", "/var/log/syslog"):
        try:
            with open(源, "r", encoding="utf-8", errors="replace") as f:
                尾 = f.readlines()[-400:]
            命 = [x for x in 尾 if "Out of memory" in x or "oom-kill" in x or "Killed process" in x]
            if 命:
                行.append("  %s：找到 %d 行 ✓" % (源, len(命)))
                行 += ["    " + x.rstrip()[:180] for x in 命[-6:]]
                找到 = True
            else:
                行.append("  %s：读得到 ✓ 但**最近没有 OOM 记录** ✓" % 源)
        except OSError as e:
            行.append("  %s：读不到（%s）✗" % (源, e))
    if not 找到:
        行.append("  （都读不到 ⇒ **这次说不清是不是 OOM** ✗ —— 别猜 ✓）")
    行.append("")
    行.append("── 看护的账（温度/内存/两个 RSS ✓ 每 30 秒一条）──")
    行.append(尾巴(os.path.join(根, "logs", "看护.csv"), 6))
    行.append("── ★ 最像死因的行（从日志里挑 ✓ 光看尾巴全是栈帧、找不着病根 ✗）──")
    关键词 = ("Error", "error", "Exception", "exception", "panic", "Cannot", "cannot",
            "undefined", "TypeError", "RangeError", "Killed", "Segmentation")
    try:
        with open(组["日志"], "r", encoding="utf-8", errors="replace") as f:
            所有 = f.readlines()[-1500:]
        命 = [x.rstrip()[:200] for x in 所有 if any(k in x for k in 关键词)]
        if 命:
            行.append("  （最近 %d 行里挑出 %d 条 ✓）" % (len(所有), len(命)))
            行 += ["    " + x for x in 命[-8:]]
        else:
            行.append("  （最近 %d 行里**一条都不像** ✗ —— 那它多半是被外面杀的 ✓ 别栽赃给它 ✓）"
                      % len(所有))
    except OSError as e:
        行.append("  （读不到：%s）✗" % e)
    行.append("")
    行.append("── 这个组件自己的日志尾巴 ──")
    行.append(尾巴(组["日志"], 25))
    行.append("── 监工自己的日志尾巴 ──")
    行.append(尾巴(日志, 12))
    文 = "\n".join(行) + "\n"
    try:
        with open(路径, "w", encoding="utf-8") as f:
            f.write(文)
        print("  ↳ 现场留在 %s ✓" % os.path.basename(路径), flush=True)
    except OSError as e:
        print("  ↳ ✗ 现场写不下去：%s" % e, flush=True)
    return 因, 路径


def 拉起(组):
    """★ 隔离：start_new_session ⇒ 连监工自己死了都带不走它 ✓"""
    os.makedirs(os.path.dirname(组["日志"]), exist_ok=True)
    f = open(组["日志"], "ab")
    p = subprocess.Popen(组["起法"], cwd=根, stdout=f, stderr=f,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    句柄[组["名"]] = p        # ★ 记着它 ✓ 死的时候才拿得到退出码/信号 ✓
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
    托管 = 托管表()
    for 组 in 组件:
        ok, 说明 = 在不在(组)
        if ok:
            好没有.append("%s(%s)" % (组["名"], 说明))
            if 托管.get(组["名"]) is False:
                报("· 「%s」在跑，但它**不归我托管** ✓（config.json 监工.托管）" % 组["名"])
            continue
        # ★ 主人点名不托管的：**碰都不碰** ✓（不拉、不尸检、也不刷日志 ✗）
        if 托管.get(组["名"]) is False:
            好没有.append("%s ✗ %s（**不托管** ✓ 我不管 ✓）" % (组["名"], 说明))
            continue
        if not 干不干:
            好没有.append("%s ✗ %s" % (组["名"], 说明))
            continue
        # ★★★ 先**留现场**，再动手拉 ✗（顺序反了就什么都留不下了 ✓）
        因, _ = 尸检(组, 说明)
        上次死的因[组["名"]] = 因
        报("⚠ 「%s」倒下 ⇒ %s" % (组["名"], 因), 急=True)
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
        # ★★★ 起之前**先清场** ✓（主人 2026-10-09 那次刷屏的总根：两个手同时在线 ✗）
        杀过 = 清干净(组)
        if 杀过:
            报("⚠ 起「%s」之前先清场：还有活着的副本 %s —— **先杀后起** ✓"
               "（绝不许两个同时在线 ✗ 主人那次就是被 login fight 刷屏的 ✓）"
               % (组["名"], "、".join(str(x) for x in 杀过)), 急=True)
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
        global 上次心跳
        新心跳 = {}
        for 组 in 组件:
            ok, 说明 = 在不在(组)
            m = __import__("re").search(r"pid (\d+)", 说明)
            新心跳[组["名"]] = {"在": ok, "说明": 说明, "pid": (m.group(1) if m else None)}
        上次心跳 = 新心跳
        with open(心跳, "w", encoding="utf-8") as f:
            json.dump({"时刻": time.strftime("%Y-%m-%d %H:%M:%S"), "检查次数": 检查次数,
                       "重启次数": dict(重启次数), "现状": 好没有,
                       "上次为什么死": dict(上次死的因), "各组件": 新心跳},
                      f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return 好没有


def 自检():
    """★ 只看不控 ✓ 探到的东西必须**跟真的一样** ✓"""
    过, 不过 = [], []
    托管 = 托管表()
    for 组 in 组件:
        ok, 说明 = 在不在(组)
        不托管 = 托管.get(组["名"]) is False
        # ★ 主人点名不托管的（2026-10-09：监工别自动拉起手 ✗）：
        #   **不在**不算缺点 ✓ —— 不然自检每次都报「2 失败」，看着像坏了 ✗（主人最恨误报 ✓）
        if 不托管:
            print("  · %-4s → %s（**不托管** ✓ 我不管 ✓）" % (组["名"], 说明))
        else:
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
