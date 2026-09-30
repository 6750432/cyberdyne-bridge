#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M3·录制：把大脑收到的那串原始状态**原封不动**录下来，供离线回放。

为什么需要它：M2/M2.1 那两轮，改一个参数就得放僵尸、肉眼看日志。
到 M3 这一步彻底撑不住了 —— 行为越来越复杂，肉眼比对不可靠。

用法：
    python3 tools/录制.py 30            # 连上大脑录 30 秒
    python3 tools/录制.py 60 -o 录的.jsonl
"""
import argparse
import json
import os
import socket
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import bridge  # noqa: E402  只为了复用它的接线口解析


def 主():
    p = argparse.ArgumentParser(description="录一段状态流，供 tools/回放.py 离线重放")
    p.add_argument("秒", type=float, nargs="?", default=30, help="录多久（秒）")
    p.add_argument("-o", "--输出", default=None)
    a = p.parse_args()

    cfg = bridge.读配置()
    方式, 目标 = bridge.解析接线口(cfg)
    s = socket.socket(socket.AF_UNIX if 方式 == "unix" else socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(目标)
    except OSError as e:
        print(f"接不上大脑（{e}）—— 手那边先跑起来再录。")
        return 1
    s.settimeout(1.0)

    路 = a.输出 or os.path.join(ROOT, "logs", f"录像-{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    os.makedirs(os.path.dirname(路), exist_ok=True)

    条 = 0
    开始 = time.time()
    print(f"开始录 {a.秒:.0f} 秒 → {路}")
    with open(路, "w", encoding="utf-8") as f:
        缓冲 = b""
        while time.time() - 开始 < a.秒:
            try:
                块 = s.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not 块:
                break
            缓冲 += 块
            while b"\n" in 缓冲:
                行, 缓冲 = 缓冲.split(b"\n", 1)
                行 = 行.strip()
                if not 行:
                    continue
                try:
                    消息 = json.loads(行)
                except Exception:
                    continue
                if 消息.get("type") != "state":
                    continue
                f.write(json.dumps(消息, ensure_ascii=False) + "\n")
                条 += 1
    s.close()
    print(f"录完了：{条} 帧状态 → {路}")
    return 0


if __name__ == "__main__":
    sys.exit(主())
