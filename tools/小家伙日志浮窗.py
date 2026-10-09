#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小家伙日志浮窗.py —— 把小家伙的日志贴在你游戏窗口的左上角。

主人 2026-10-09 的想法：「我说把小家伙的日志移植到我游戏窗口里面（左上角）」

它做的事
========
1. 找到 Minecraft 窗口（wmctrl 里那个「Minecraft 1.21.1」）
2. 在它的**左上角**贴一层**无边框、置顶、点击穿透**的小窗
3. 每 1 秒读一次小家伙的日志（logs/大脑.log），只挑"有信息量"的行显示
4. 每 2 秒重新对一次位（你拖动/缩放游戏窗口，它跟着走）

三个要紧的细节（都是踩过的坑）
============================
· **点击穿透**：用 XShape 把输入区置空（`玻璃.py` 那套）—— 不然它会挡住游戏点击 ✗
· **不抢焦点**：`overrideredirect(True)` = override-redirect 窗口，窗口管理器不管它 ✓
  否则你一进游戏，浮窗就把焦点抢走 ✗
· **绝对坐标**：游戏窗口的坐标要用 `xwininfo -id` 的 Absolute upper-left ✓
  （不是相对坐标 —— 这条写在我的教训里了 ✓）

用法
====
  python3 tools/小家伙日志浮窗.py            # 起
  python3 tools/小家伙日志浮窗.py --停        # 停
  python3 tools/小家伙日志浮窗.py --宽 560 --高 200 --字号 11
  （主人 2026-10-09：默认改窄了 —— 940 太宽，长句子会自动折行 ✓）
"""

import argparse
import ctypes
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
日志 = os.path.join(ROOT, "logs", "大脑.log")
呼吸 = os.path.join(ROOT, "logs", "浮窗.pid")

# 只显示这些行 —— 其余（【视觉】那种每拍都刷的）滤掉，免得看不出重点
留 = re.compile(r"成了|没做成|干不了|计划明细|工具查表|声呐耳朵|就地取材|我听见|接单|"
                r"挡着|陈的|挖掉=|合成|放/|走到|定位不到|起车|耳|挂上了")


def 找游戏窗口():
    """返回 (窗口id, 左上角x, 左上角y, 宽, 高) 或 None。"""
    try:
        出 = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True,
                            timeout=5).stdout
    except Exception:
        return None
    for 行 in 出.splitlines():
        if "Minecraft" in 行:
            标 = 行.split()[0]
            try:
                信 = subprocess.run(["xwininfo", "-id", 标], capture_output=True,
                                    text=True, timeout=5).stdout
            except Exception:
                continue
            def 取(名, 兜底=0):
                m = re.search(rf"{名}:\s*(-?\d+)", 信)
                return int(m.group(1)) if m else 兜底
            宽 = 取("Width", 854)
            高 = 取("Height", 480)
            return 标, 取("Absolute upper-left X"), 取("Absolute upper-left Y", 40), 宽, 高
    return None


def 穿透(窗口id):
    """把窗口的输入区置空 = 看得见点不到（点了会穿到下面的游戏里）。"""
    # ★ 直接用 tkinter 给的那个窗口 id —— 按标题找太脆了 ✗
    #   （第一次跑就是这么失败的：明明窗口在、却"找不到标题"）
    try:
        # ⚠ XShapeCombineRectangles 在 **libXext** 里，不在 libX11 ✗
        #   （第一次跑报的就是 "undefined symbol" —— 经典坑）
        lib = ctypes.CDLL("libX11.so.6")
        ext = ctypes.CDLL("libXext.so.6")
        lib.XOpenDisplay.restype = ctypes.c_void_p
        dpy = lib.XOpenDisplay(None)
        if not dpy:
            return False
        目标 = int(窗口id)
        if 目标 <= 0:
            return False
        # ShapeInput = 2；传 0 个矩形 = 空输入区 ✓（点了会穿到下面的游戏里）
        ext.XShapeCombineRectangles(ctypes.c_void_p(dpy), ctypes.c_ulong(目标),
                                    2, 0, 0, None, 0, 0, 0)
        lib.XFlush(ctypes.c_void_p(dpy))
        lib.XCloseDisplay(ctypes.c_void_p(dpy))
        return True
    except Exception as e:
        print(f"穿透设置失败（不影响显示）：{e}", flush=True)
        return False


def 读日志(要几条=14):
    try:
        with open(日志, encoding="utf-8", errors="replace") as f:
            行 = f.readlines()[-400:]
    except Exception:
        return []
    出 = []
    for l in reversed(行):
        l = l.rstrip()
        if not l or l.startswith("现在是第") or "【视觉】" in l or l.startswith("看得见"):
            continue
        if 留.search(l):
            出.append(l[:120])
        if len(出) >= 要几条:
            break
    出 = list(reversed(出))
    # ★ 去重：同一个错它一秒能重试十来次，原样列出来满屏都是同一句 ✗
    #   （第一次跑就撞上了：12 行全是「「place」没做成：六面全是空的」）
    #   规矩：**连续的同一句合成一条**，后面标 ×N ✓
    合 = []
    for l in 出:
        去时 = re.sub(r"^\[\d{2}:\d{2}\]\s*", "", l)      # 比内容时先去掉时间戳
        if 合 and 合[-1]["净"] == 去时:
            合[-1]["数"] += 1
        else:
            合.append({"净": 去时, "文": l, "数": 1})
    return [f"{x['文']}" + (f"   ×{x['数']}" if x["数"] > 1 else "") for x in 合]


def 主():
    ap = argparse.ArgumentParser()
    ap.add_argument("--停", action="store_true")
    ap.add_argument("--宽", type=int, default=560)
    ap.add_argument("--高", type=int, default=200)
    ap.add_argument("--字号", type=int, default=11)
    ap.add_argument("--透明", type=float, default=0.78,
                    help="0~1，越小越透（默认 0.78 半透明；这台机器有合成器，能生效 ✓）")
    参 = ap.parse_args()

    if 参.停:
        try:
            pid = int(open(呼吸).read().strip())
            os.kill(pid, 15)
            print(f"停了浮窗（pid {pid}）")
        except Exception as e:
            print(f"没在跑（或停不掉）：{e}")
        return 0

    # 已经在跑就别起第二个
    try:
        pid = int(open(呼吸).read().strip())
        os.kill(pid, 0)
        print(f"浮窗已经在跑（pid {pid}）—— 先 --停 再起")
        return 1
    except Exception:
        pass

    游 = 找游戏窗口()
    if not 游:
        print("找不到 Minecraft 窗口 —— 先把游戏开起来 ✗")
        return 2
    标, x, y, 宽, 高 = 游
    print(f"游戏窗口 {标}：左上角 ({x}, {y})，{宽}x{高}")

    import tkinter as tk
    root = tk.Tk()
    root.title("小家伙日志")
    root.overrideredirect(True)          # 无边框、不抢焦点 ✓
    root.attributes("-topmost", True)    # 置顶 ✓
    宽 = min(参.宽, max(300, 宽))
    root.geometry(f"{宽}x{参.高}+{x}+{y}")
    root.configure(bg="black")
    try:
        root.attributes("-alpha", max(0.15, min(1.0, 参.透明)))   # ★ 半透明
    except Exception as e:
        print(f"半透明设不上（不影响显示）：{e}")
    文 = tk.Label(root, text="（小家伙的日志）", justify="left", anchor="nw",
                  bg="black", fg="#e8e8e8", font=("monospace", 参.字号),
                  wraplength=宽 - 12)
    文.pack(fill="both", expand=True, padx=6, pady=4)
    root.update()
    GLib穿透 = 穿透(root.winfo_id())

    def 刷新():
        # ① 对位（拖动/缩放游戏窗口时跟着走）
        try:
            今 = 找游戏窗口()
            if 今:
                _, x2, y2, 宽2, _ = 今
                root.geometry(f"{min(参.宽, max(300, 宽2))}x{参.高}+{x2}+{y2}")
        except Exception:
            pass
        # ② 刷字
        try:
            行 = 读日志()
            文.config(text="\n".join(行) if 行 else "（还没有可显示的日志）")
        except Exception as e:
            文.config(text=f"读日志失败：{e}")
        root.after(1000, 刷新)

    root.after(300, 刷新)
    with open(呼吸, "w") as f:
        f.write(str(os.getpid()))
    print(f"浮窗起来了 ✓ 点击穿透={'成功' if GLib穿透 else '没成功（先看显示，再修穿透）'}")
    try:
        root.mainloop()
    finally:
        try:
            os.unlink(呼吸)
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(主())
