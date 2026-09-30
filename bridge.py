#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cyberdyne-Bridge · M1 · 大脑在外面（Brain Outside）

纯标准库实现，不引入任何第三方依赖。

职责边界（M1 只做这四件事，越级的一律不写）：
    1. 从接线口收状态，把状态翻译成人能读懂的叙事化日志；
    2. 基础反射层：敌对生物逼近就后退、半血就吃东西、濒危就脱离战斗；
    3. 防卡死：接线口哑了或断了自动重连，收到烂包丢掉并告警，绝不崩；
    4. 硬件红线：CPU/GPU 过烫就把 M1 挂起就地休眠，凉下来自己回来。

明确不做：LLM 决策、记忆系统、平滑层、能力探测、降级链、沙箱、
          寻路、攻击、挖掘、任何重型 MC AI 框架。

用法：
    python3 bridge.py                   正常跑（反射层开启）
    python3 bridge.py --只读            只看不控，绝不下发任何动作
    python3 bridge.py --心跳秒 60       调整平静时的汇报间隔
    python3 bridge.py --json            额外打印原始行，仅供排查
"""

import argparse
import glob
import json
import math
import os
import random
import socket
import subprocess
import sys
import urllib.request
import time

ROOT = os.path.dirname(os.path.abspath(__file__))


# ───────────────────────────── 小工具 ─────────────────────────────

def 时刻():
    return time.strftime("%H:%M", time.localtime())


def 坐标(位置):
    if not 位置:
        return "未知"
    return f"({位置[0]:.0f}, {位置[1]:.0f}, {位置[2]:.0f})"


def 血文本(值):
    """MC 的血量是浮点数（打一下可能掉 1.5），所以不能拿 :d 去格式化。
    整数就不带小数点 —— 读起来像"血 18"，而不是"血 18.0"。"""
    if 值 is None:
        return "?"
    return f"{值:.0f}" if abs(值 - round(值)) < 0.05 else f"{值:.1f}"


def 读配置():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def 解析接线口(cfg):
    """和手那边保持同一套判定：auto 时 Windows 用 TCP，其余用 Unix socket。"""
    方式 = cfg.get("transport", "auto")
    if 方式 == "auto":
        方式 = "tcp" if sys.platform.startswith("win") else "unix"
    if 方式 == "unix":
        路径 = os.path.join(ROOT, cfg.get("unix_socket", "./cyberdyne.sock"))
        return ("unix", 路径)
    return ("tcp", (cfg.get("tcp_host", "127.0.0.1"), cfg.get("tcp_port", 8765)))


# ─────────────────────────── 限流 + 叙事 ───────────────────────────

class 限流:
    """不许滚屏。一分钟最多放行这么多条，超了就压掉并计数。

    ⚠ 二版修正：**紧急和正常必须分开算**。
    一版两套额度共用一个滑动窗口，战斗时紧急流量把窗口塞满，
    结果"退两步"这类正常日志一条都挤不进去 —— 事后复盘根本看不出它有没有真的后撤。"""

    def __init__(self, 每分钟=12):
        self.上限 = max(1, int(每分钟))
        self.正常窗口 = []
        self.紧急窗口 = []
        self.压掉 = 0

    def 放行(self, 紧急=False):
        现在 = time.time()
        if 紧急:
            self.紧急窗口 = [t for t in self.紧急窗口 if 现在 - t < 60.0]
            if len(self.紧急窗口) < self.上限 * 4:
                self.紧急窗口.append(现在)
                return True
        else:
            self.正常窗口 = [t for t in self.正常窗口 if 现在 - t < 60.0]
            if len(self.正常窗口) < self.上限:
                self.正常窗口.append(现在)
                return True
        self.压掉 += 1
        return False

    def 取走压掉数(self):
        n, self.压掉 = self.压掉, 0
        return n


class 叙事者:
    """把状态流翻译成人话。只做翻译，不做判断。"""

    def __init__(self, 心跳秒=60, 每分钟上限=12):
        self.心跳秒 = 心跳秒
        self.闸 = 限流(每分钟上限)
        self.出生过了 = False
        self.上次位置 = None
        self.血基线 = None        # 上一次"报出去"的血量，不是上一次收到的
        self.上次血报 = 0.0
        self.上次朝向 = None
        self.附近已知 = {}
        self.上次开口 = time.time()
        self.开头时刻 = time.time()
        self.收到过 = 0
        self.静默移动 = False      # 反射动作进行中：位置变化由反射层自己叙述
        self.最后状态 = None

    def 说(self, 行, 紧急=False, 不计流=False):
        if 不计流 or self.闸.放行(紧急):
            print(行)
        # 被压掉的行不打印，数字记着，下次开口时一并交代

    @staticmethod
    def _距离(a, b):
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

    def 吃(self, 消息):
        种类 = 消息.get("type")
        if 种类 == "state":
            self.看状态(消息)
        elif 种类 == "event":
            self.看事件(消息)

    # ── 状态 ──
    def 看状态(self, s):
        self.收到过 += 1
        self.最后状态 = s

        if not s.get("connected") or not s.get("pos"):
            if self.收到过 == 1:
                self.说(f"[{时刻()}] 接线口通了，但他还没进世界，等…")
            return

        位置 = s["pos"]
        血量 = s.get("hp")
        朝向 = s.get("look") or {}
        附近 = s.get("near") or []
        动作 = s.get("acting") or "idle"

        # 第一次拿到坐标 = 出生
        if not self.出生过了:
            self.出生过了 = True
            self.上次位置 = 位置
            self.血基线 = 血量
            self.上次血报 = time.time()
            self.上次朝向 = 朝向
            self.附近已知 = {e["name"]: e["dist"] for e in 附近}
            self.说(f"[{时刻()}] 小家伙出生了，站在 {坐标(位置)}")
            self.说(f"           血量 {血文本(血量)}/20，朝向 yaw={朝向.get('yaw', 0):.1f} "
                    f"pitch={朝向.get('pitch', 0):.1f}")
            if 附近:
                名 = "、".join(e["name"] for e in 附近[:3])
                self.说(f"           他一睁眼就看到了：{名}")
            else:
                self.说(f"           四下无人")
            self.上次开口 = time.time()
            return

        # 位置变化（反射动作期间不报，否则一次逃跑能刷几十行）
        如果动了 = self.上次位置 and self._距离(位置, self.上次位置) > 0.05
        if 如果动了:
            走了 = self._距离(位置, self.上次位置)
            self.上次位置 = 位置
            if not self.静默移动 and 动作 == "idle":
                if 走了 >= 0.5:
                    self.说(f"[{时刻()}] 他动了，挪到 {坐标(位置)}（走了 {走了:.1f} 格）")
                    self.上次开口 = time.time()

        # 血量变化：挨打时每秒都在掉，逐帧报会滚屏 —— 攒够 2 点、或隔了 4 秒再开口
        if 血量 is not None and self.血基线 is not None and abs(血量 - self.血基线) > 1e-6:
            差 = 血量 - self.血基线
            现在 = time.time()
            if abs(差) >= 2 or 现在 - self.上次血报 >= 4:
                if 差 < 0:
                    self.说(f"[{时刻()}] 哎哟，挨了 {abs(差):.0f} 点伤害，"
                            f"血 {血文本(self.血基线)} → {血文本(血量)}/20", 紧急=True)
                elif 血量 >= 20:
                    self.说(f"[{时刻()}] 血回满了（20/20）。")
                elif 现在 - self.上次血报 >= 10:
                    # 自然回血是每两秒一点，逐次报会一路刷下去，攒久一点再说
                    self.说(f"[{时刻()}] 慢慢回血中：{血文本(self.血基线)} → {血文本(血量)}/20")
                self.血基线 = 血量
                self.上次血报 = 现在
                self.上次开口 = 现在

        # 附近实体变化
        now_near = {e["name"]: e["dist"] for e in 附近}
        for 名字, 距 in now_near.items():
            if 名字 not in self.附近已知:
                self.说(f"[{时刻()}] 视野里出现了「{名字}」，{距:.1f} 格远")
        for 名字 in list(self.附近已知):
            if 名字 not in now_near:
                self.说(f"[{时刻()}] 「{名字}」走开了")
        self.附近已知 = now_near

        # 朝向变化（只在明显转头时报）
        if 朝向 and self.上次朝向:
            dy = abs(朝向.get("yaw", 0) - self.上次朝向.get("yaw", 0))
            if dy > 0.6 and not self.静默移动 and 动作 == "idle":
                self.说(f"[{时刻()}] 他扭头看了一眼")
                self.上次开口 = time.time()
            self.上次朝向 = 朝向

        # 心跳
        if time.time() - self.上次开口 >= self.心跳秒:
            self.上次开口 = time.time()
            待了 = int(time.time() - self.开头时刻)
            分, 秒 = divmod(待了, 60)
            时长 = f"{分}时{秒}分" if 分 >= 60 else (f"{分}分{秒}秒" if 分 else f"{秒}秒")
            身边 = self._身边一句话(s)
            压 = self.闸.取走压掉数()
            尾巴 = f"（期间压掉了 {压} 条啰嗦的）" if 压 else ""
            self.说(f"[{时刻()}] 他还在 {坐标(位置)}，{身边}"
                    f"｜血 {血文本(血量)}/20｜已经待了 {时长}{尾巴}")

    def _身边一句话(self, s):
        敌人 = s.get("threats") or []
        附近 = s.get("near") or []
        if 敌人:
            名 = "、".join(f"{t['name']}({t['dist']:.0f}格)" for t in 敌人[:2])
            return f"⚠ 身边有敌人 {名}"
        if 附近:
            名 = "、".join(f"{e['name']}({e['dist']:.0f}格)" for e in 附近[:2])
            return f"身边有 {名}"
        return "身边没人"

    # ── 事件 ──
    def 看事件(self, e):
        类 = e.get("kind")
        if 类 == "spawn":
            pass
        elif 类 == "chat":
            self.说(f"[{时刻()}] {e.get('from')} 说话了：「{e.get('text')}」")
        elif 类 == "death":
            self.说(f"[{时刻()}] 他倒下了。", 紧急=True)
        elif 类 == "kicked":
            self.说(f"[{时刻()}] 他被服务器踢了：{e.get('detail')}", 紧急=True)
        elif 类 == "error":
            self.说(f"[{时刻()}] 手那边报错：{e.get('detail')}", 紧急=True)
        elif 类 == "end":
            self.说(f"[{时刻()}] 他和世界的连接断了：{e.get('detail')}", 紧急=True)
        elif 类 == "reconnect":
            self.说(f"[{时刻()}] 手正在重连（第 {e.get('attempt')} 次，"
                    f"{int((e.get('after_ms') or 0) / 1000)} 秒后）…", 紧急=True)
        elif 类 == "cmdResult":
            self.看回执(e)
        elif 类 == "blocked":
            self.说(f"[{时刻()}] 前面是悬崖或者岩浆，我不敢往前跑了 —— 站着不动也比摔下去强。",
                    紧急=True)
        elif 类 == "hit":
            if e.get("self") or not e.get("ours", True):
                pass        # 自己挨打有血量播报在管；不是我们刚挥的那一下也不记
            else:
                谁 = 中文名.get(e.get("who"), e.get("who"))
                剩 = e.get("hp")
                尾巴 = f"，他还剩 {血文本(剩)} 血" if 剩 is not None else ""
                self.说(f"[{时刻()}] 打中了「{谁}」{尾巴}！", 紧急=True)
        elif 类 == "respawned":
            self.说(f"[{时刻()}] 我又站起来了。家当多半散在倒下的地方，先看看背包里还剩什么…",
                    紧急=True)
        self.上次开口 = time.time()

    def 看回执(self, e):
        cmd = e.get("cmd")
        ok = e.get("ok")
        if cmd == "eat":
            if ok:
                self.说(f"[{时刻()}] 吃完啦，长舒一口气。")
            elif e.get("why") == "no-food":
                pass      # 反射层已经说过"没吃的"了，不重复
            else:
                self.说(f"[{时刻()}] 吃东西没成功：{e.get('why')}")
        elif cmd == "unknown":
            pass          # 手那边已经记过一笔
        elif cmd == "attack":
            if not ok:
                self.说(f"[{时刻()}] 这一下没挥成：{e.get('why')}")
        elif cmd == "goto":
            if ok:
                误差 = e.get("dist")
                self.说(f"[{时刻()}] 到地方了。"
                        + (f"离目标还有 {float(误差):.1f} 格。" if 误差 is not None else ""))
            else:
                self.说(f"[{时刻()}] 走不过去：{e.get('why')}")
        elif cmd in ("move", "stop", "ping", "mode"):
            pass          # 动作类回执不用念，念了就是刷屏
        elif not ok:
            # M4：身体插件（挖/放/合成/跳劈/潜行…）的失败要念出来 ——
            # 静默失败最要命：主人以为它去挖了，其实它一步没动。
            self.说(f"[{时刻()}] 「{cmd}」没做成：{e.get('why')}", 紧急=True)
        elif cmd in ("dig", "place", "craft", "use", "jumpattack", "sneak", "jump", "swimdown"):
            # 成了也报一声，不然看不出它到底干没干
            尾巴 = ""
            for k in ("挖掉", "放的是", "合成", "用了", "target"):
                if e.get(k) is not None:
                    尾巴 = f"（{k}={e.get(k)}）"
                    break
            self.说(f"[{时刻()}] 「{cmd}」成了{尾巴}。")


# ──────────────────────── 动态采样（M2） ────────────────────────

class 节拍器:
    """M2·动态采样。判断在脑这边，手只负责换挡。

    有敌人在战斗半径以内就走快档；敌人走了**不立刻降速**，再赖一会儿 ——
    不然敌人踩着半径线一晃，两头就会在 1Hz 和 5Hz 之间疯狂横跳。"""

    def __init__(self, m2, 说):
        self.m = m2 or {}
        self.说 = 说
        self.战斗半径 = self._数("combat_radius", 8)
        self.快 = self._数("hz_combat", 5)
        self.慢 = self._数("hz_calm", 1)
        self.赖 = self._数("calm_linger_sec", 10)
        self.当前 = self.慢
        self.上次有敌 = 0.0
        self.上次报 = time.time()
        self.切过 = 0
        # M4：外面可以在"追猎期间"直接要求快档。追击必须走快档，
        # 否则 1Hz 采样下每拍才挪一小步，看着像走一步愣一秒。
        self.外部要快 = None

    def _数(self, 名, 缺省):
        try:
            return float(self.m.get(名, 缺省))
        except (TypeError, ValueError):
            return float(缺省)

    @staticmethod
    def _最近(s):
        return min((t["dist"] for t in (s.get("threats") or [])), default=None)

    def 想要(self, s):
        最近 = self._最近(s)
        现在 = time.time()
        # M4：追猎期间无条件快档 —— 判定逻辑在反射层，这里只负责"听它的"。
        if self.外部要快 is not None and self.外部要快():
            self.上次有敌 = 现在
            return self.快
        if 最近 is not None and 最近 < self.战斗半径:
            self.上次有敌 = 现在
            return self.快
        if self.上次有敌 and 现在 - self.上次有敌 < self.赖:
            return self.快
        return self.慢

    def 看(self, s, 发命令):
        """该换挡就换挡；另外每 60 秒交代一次现在跑多快（主人点名要的那条日志）。"""
        目标 = self.想要(s)
        现在 = time.time()
        档 = lambda hz: "战斗档" if abs(hz - self.快) < 1e-6 else "平静档"
        if abs(目标 - self.当前) > 1e-6:
            发命令({"cmd": "mode", "hz": 目标})
            self.当前 = 目标
            self.切过 += 1
            self.说(f"[{时刻()}] 采样速率切到 {目标:g}Hz（{档(目标)}）。", 紧急=True)
            self.上次报 = 现在
        elif 现在 - self.上次报 >= 60:
            self.上次报 = 现在
            最近 = self._最近(s)
            注 = f"最近敌人 {最近:.0f} 格" if 最近 is not None else "身边没有敌人"
            self.说(f"[{时刻()}] 采样速率 {self.当前:g}Hz（{档(self.当前)}，{注}）。")

    def 复位(self):
        """重连之后手那边会自己降回平静档，脑这边也得跟着对齐。"""
        self.当前 = self.慢
        self.上次有敌 = 0.0


# ─────────────────────────── 温度计 ───────────────────────────

class 温度计:
    """读 CPU 和显卡温度。纯文件 + 一次 nvidia-smi，没有第三方库。"""

    def __init__(self, 采样秒=5):
        self.采样秒 = 采样秒
        self.上次采样 = 0.0
        self.cpu = None
        self.gpu = None
        self._核温路径 = self._找核温()

    @staticmethod
    def _找核温():
        路径 = []
        try:
            for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
                try:
                    with open(os.path.join(hw, "name")) as f:
                        名 = f.read().strip()
                except OSError:
                    continue
                if 名 in ("coretemp", "k10temp", "zenpower"):
                    路径.append(hw)
        except Exception:
            pass
        return 路径

    def _读cpu(self):
        最高 = None
        for hw in self._核温路径:
            for f in glob.glob(os.path.join(hw, "temp*_input")):
                try:
                    with open(f) as fh:
                        v = int(fh.read().strip()) / 1000.0
                except Exception:
                    continue
                if 最高 is None or v > 最高:
                    最高 = v
        return 最高

    def _读gpu(self):
        try:
            出 = subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5)
            if 出.returncode == 0:
                return float(出.stdout.strip().splitlines()[0])
        except Exception:
            pass
        return None

    def 采样(self, 强制=False):
        现在 = time.time()
        if not 强制 and 现在 - self.上次采样 < self.采样秒:
            return self.cpu, self.gpu
        self.上次采样 = 现在
        try:
            self.cpu = self._读cpu()
            self.gpu = self._读gpu()
        except Exception:
            pass
        return self.cpu, self.gpu


# ─────────────────────────── 反射层 ───────────────────────────

class 反射层:
    """M1·基础反射层。所有取舍都在这一个类里，手那边只负责执行。

    优先级（安全第一）：
        敌人贴脸 → 逃跑 ＞ 血极少又没吃的 → 濒危脱离 ＞ 半血有吃的 → 进食 ＞ 平静
    """

    平静, 逃跑, 濒危, 进食, 挂起 = "平静", "逃跑", "濒危", "进食", "挂起"
    # M2 新增：反击（打一下就跑）、拾取（走近捡）、前往（太远了交给寻路插件）、饿等（等投喂）
    反击, 拾取, 前往, 饿等 = "反击", "拾取", "前往", "饿等"
    # M2.1：迎战 —— 打得过的时候站住等，不跑。跑得太好会一次都打不着。
    迎战 = "迎战"
    # M4·猎手：追猎 —— 主动锁定之后的每一步追击。
    # 跟上面所有状态的根本区别：**不是被打了才动**，是它自己挑的时候开打。
    追猎 = "追猎"
    # M4b·绕路：直线走不通了，这一拍把方向盘交给寻路插件（或者沿墙滑过去）
    绕路 = "绕路"

    def __init__(self, m1, 说):
        self.m = m1 or {}
        self.说 = 说
        self.状态 = self.平静
        self.上次逃跑 = 0.0
        self.上次逃跑宣告 = 0.0
        self.脱险时刻 = None
        self.上次进食 = 0.0
        self.热挂起 = False
        self.濒危说过 = False
        self.没吃的说过 = False
        self.饱着说过 = False
        self.动作开始 = 0.0
        # M2
        self.上次反击 = 0.0
        self.上次拾取 = 0.0
        self.上次讨饭 = 0.0
        self.待后撤 = None        # (到期时刻, 退路方向)：挥完走人，绝不站着对砍
        self.上次宣告快照 = None  # 宣告合并用：距离档 + 对方血量档
        # ★ 固定种子的随机 —— 不固定的话回放基准会随机失败
        种子 = int(self._阈值("rng_seed", 20260930))
        self.rng = random.Random(种子)
        self.跳劈次数 = 0
        self.挥击次数 = 0
        self.撤退到 = 0.0        # 后撤动作跑到什么时候为止
        # ★ M4·猎手（主动锁定）
        self.锁定目标 = None     # 锁定的玩家名；None = 没在追人
        self.锁定中文 = None
        self.锁定时刻 = 0.0      # 本次追击的起点，用来封顶 hunt_max_ms
        self.锁定对方血 = None   # 探针给的最后一次读数，用来分辨"被我打死"还是"下线了"
        self.锁定时的死数 = None # 锁定那一刻我死过几次（死数变了 = 这次追击该收手）
        self.放弃起点 = None     # 第一次发现"追不上"的时刻（要连续超距 hunt_giveup_ms 才撒手）
        self.上次掷骰 = 0.0      # 上一次掷"锁不锁"的时刻
        self.上次锁定结束 = 0.0  # 上一次追击结束的时刻（冷却从这里算）
        self.追击次数 = 0        # 统计：这一轮实测要看"它主动来找过我几次"
        self.没家伙说过 = False  # 挨打但空手：这句话只说一次，别刷屏
        # ★ M4b·绕路
        self.上次卡住计数 = None   # 手报的卡住计数（只增不减），变了 = 又卡了一次
        self.绕向 = 1             # +1 / -1：沿墙滑往哪边偏
        self.绕角度 = 0.0         # 这次卡住要用多大角度（0 = 没在绕）
        self.上次绕路下发 = 0.0   # 上一次把目标交给寻路插件是什么时候

    # ── 阈值 ──
    def _阈值(self, 名, 缺省):
        try:
            return float(self.m.get(名, 缺省))
        except (TypeError, ValueError):
            return float(缺省)

    # ── 决策：只返回"要不要、往哪、多久"，不含任何执行细节 ──
    def 决断(self, s):
        if self.热挂起:
            return (self.挂起, None, 0)

        血量 = s.get("hp")
        if 血量 is None:
            return (self.平静, None, 0)

        血上限 = self._阈值("hp_max", 20)
        血比 = 血量 / 血上限
        敌人 = s.get("threats") or []
        食物 = s.get("foods") or []
        武器 = s.get("weapons") or []
        最近 = min((t["dist"] for t in 敌人), default=None)

        贴脸距 = self._阈值("flee_dist", 5.0)
        该吃线 = self._阈值("low_hp_ratio", 0.5)
        濒危线 = self._阈值("critical_hp_ratio", 0.2)
        # M2 新增的阈值
        反击距 = self._阈值("counter_dist", 3.0)
        反击血 = self._阈值("counter_hp_min", 12)
        最多敌 = int(self._阈值("counter_max_enemies", 1))
        空包血 = self._阈值("empty_bag_hp", 10)

        有敌人贴脸 = 最近 is not None and 最近 < 贴脸距
        濒危 = 血比 < 濒危线
        该吃 = 血比 < 该吃线
        有吃的 = bool(食物)
        有武器 = bool(武器)

        if self.状态 in (self.逃跑, self.濒危, self.反击) and 最近 is None:
            # 别一看不见就宣布脱险 —— 它多半只是绕到了树后面，1 秒后又探出来。
            # 要连续 2.5 秒视野里都没有敌人才算真的甩掉，否则日志会疯狂翻脸。
            if self.脱险时刻 is None:
                self.脱险时刻 = time.time()
            elif time.time() - self.脱险时刻 >= 2.5:
                self.说(f"[{时刻()}] 甩掉了，身边没有敌人了，先站住喘口气。")
                self.状态 = self.平静
                self.脱险时刻 = None
        else:
            self.脱险时刻 = None

        # ── M4·猎手：由它自己决定什么时候开打 ──
        # 位置是刻意的：排在"贴脸处置"**前面**。锁定期间它才敢往你那边走；
        # 要是排在后面，距离一进 5 格就会掉进"迎战 = 原地站住"，
        # 于是追到你跟前反而停住不动 —— 看着像卡死。
        # （保命仍然排在前面：_猎手 内部的撒手条件里写着"疼到线下就交回逃跑分支"。）
        追 = self._猎手(s, 敌人, 血量, 血比, 血上限, 有吃的, 有武器, 最近)
        if 追 is not None:
            return 追

        if 有敌人贴脸:
            方向 = self._逃离方向(s, 敌人)

            # ── M2·反击 ──
            # 主人的排序是「逃跑 ＞ 反击 ＞ 进食」。我的实现是：
            # 跑是默认反应，只有凑齐"贴脸 + 血够 + 手上有家伙 + 对面只有一个"
            # 这四条，才把这一下从"跑"升级成"还手一下再跑"。
            # 凑不齐就一路落到下面的逃跑分支，一个字没改。
            死活都要打 = 血量 > 反击血 or self._死斗()
            够格 = (最近 < 反击距 and 死活都要打 and 有武器
                    and len(敌人) <= 最多敌
                    and time.time() - self.上次反击 >= self._攻击冷却())
            if 够格:
                return self._反击(s, 敌人, 最近, 血量, 血上限)

            # 后撤还没跑完就别急着迎战 —— 让"打完就跑"的"跑"跑完它
            if time.time() < self.撤退到:
                return (self.平静, None, 0)

            # ── M2.1·迎战 ──
            # 上一版实战教训：疾跑一开，小家伙把僵尸甩到 34 格外，一次都打不着。
            # 安全是安全了，但"攻击效率"归零。打得过的时候，"站着不动"才是最优解 ——
            # 让对手自己走进 2.2 格的打击圈。
            能打得过 = (死活都要打 and 有武器 and len(敌人) <= 最多敌)
            if 能打得过:
                if self.状态 != self.迎战:
                    self.说(f"[{时刻()}] {self._最近敌人名(敌人)}在 {最近:.1f} 格外晃 —— "
                            f"我血够（{血文本(血量)}/{血上限:.0f}）、手上有家伙，"
                            f"这回不跑了，站住等它进来。")
                self.状态 = self.迎战
                return (self.迎战, None, 0)

            if 濒危 and not 有吃的:
                if self.状态 != self.濒危:
                    self.说(f"[{时刻()}] 呜…我快不行了（血 {血量:.0f}/{血上限:.0f}），"
                            f"背包里一点吃的都没有，"
                            f"「{self._最近敌人名(敌人)}」离我只有 {最近:.1f} 格——"
                            f"我不能打，只能慢慢往后挪。", 紧急=True)
                self.状态 = self.濒危
                return (self.濒危, 方向, self._阈值("critical_flee_ms", 900))

            # 只在"刚发现敌人"或"隔了 8 秒又被追上"时才喊 —— 一次追逐能刷一屏才叫滚屏
            if self.状态 != self.逃跑 and time.time() - self.上次逃跑宣告 >= 8:
                self.上次逃跑宣告 = time.time()
                self.说(f"[{时刻()}] 呜呜，有个{self._最近敌人名(敌人)}靠近我"
                        f"（{最近:.1f} 格），我赶紧往后跑！", 紧急=True)
            冷却中 = time.time() - self.上次逃跑 < self._阈值("flee_cooldown_ms", 700) / 1000.0
            if 冷却中:
                return (self.平静, None, 0)
            self.状态 = self.逃跑
            return (self.逃跑, 方向, self._阈值("flee_ms", 1600))

        # ── M2·背包健康度 ──
        # 两种情况都要管：
        #   ① 一点吃的都没有，而且还在失血（任务书里点名的 empty_bag_hp 规则）
        #   ② 刚死过一次又站起来 —— 家当全散在倒地的地方，这时候不管血多少都该去捡
        # 少了第②条，"重生后 30 秒内恢复食物"这条验收就永远走不到。
        刚重生 = bool(s.get("respawned"))
        if not 有吃的 and (血量 < 空包血 or 刚重生):
            决定 = self._没吃的怎么办(s, 血量, 血上限, 濒危, 刚重生)
            if 决定 is not None:
                return 决定

        if 濒危 and not 有吃的:
            if not self.濒危说过:
                self.濒危说过 = True
                self.说(f"[{时刻()}] 血只剩 {血文本(血量)}/{血上限:.0f} 了，又没吃的。"
                        f"我原地不动，盼着别被谁看见…", 紧急=True)
            self.状态 = self.濒危
            return (self.濒危, None, 0)

        if 该吃 and 有吃的:
            # MC 的规矩：肚子饱着（foodLevel=20）根本不让吃，硬吃只会报 "Food is full"。
            # 而且饱着的时候本来就自己回血，用不着喂。所以先看饥饿条再决定。
            饥饿 = s.get("food")
            if 饥饿 is not None and 饥饿 >= 20:
                if not self.饱着说过:
                    self.饱着说过 = True
                    self.说(f"[{时刻()}] 血只有 {血量:.0f}/{血上限:.0f}，"
                            f"不过肚子是饱的 —— 饱着就自己回血，用不着吃，我先等着。")
            else:
                self.饱着说过 = False
                冷却中 = (time.time() - self.上次进食
                          < self._阈值("eat_cooldown_ms", 8000) / 1000.0)
                if not 冷却中:
                    self.状态 = self.进食
                    self.说(f"[{时刻()}] 肚子饿了（血 {血量:.0f}/{血上限:.0f}，"
                            f"饥饿 {饥饿}/20），"
                            f"我翻出{self._食物中文(食物[0]['name'])}吃一口。")
                    return (self.进食, None, 0)

        if 该吃 and not 有吃的 and not self.没吃的说过:
            self.没吃的说过 = True
            self.说(f"[{时刻()}] 血掉到 {血文本(血量)}/{血上限:.0f} 了，"
                    f"可我把背包翻遍了，一点能吃的都没有…", 紧急=True)

        if self.状态 != self.平静:
            self.状态 = self.平静
        return (self.平静, None, 0)

    @staticmethod
    def _最近敌人名(敌人):
        最近 = min(敌人, key=lambda t: t["dist"])
        return 中文名.get(最近.get("name"), 最近.get("name"))

    def _逃离方向(self, s, 敌人):
        """把身边每个敌人都当成一个推力，求和就是"远离所有人"的方向。
        没有寻路，没有路径规划，只有一个力场 —— M1 就只配用这个。"""
        我 = s["pos"]
        dx = dz = 0.0
        for t in 敌人:
            p = t.get("pos")
            if not p:
                continue
            vx, vz = 我[0] - p[0], 我[2] - p[2]
            长 = math.hypot(vx, vz)
            if 长 < 0.01:
                # 贴脸重合了，随便挑个方向也比原地站着强
                vx, vz, 长 = 1.0, 0.0, 1.0
            权重 = 1.0 / max(t["dist"], 0.6)
            dx += vx / 长 * 权重
            dz += vz / 长 * 权重
        if abs(dx) < 1e-6 and abs(dz) < 1e-6:
            dx, dz = 1.0, 0.0
        return [round(dx, 3), round(dz, 3)]

    def _反击(self, s, 敌人, 最近, 血量, 血上限):
        """M2·反击：挥一下就走，绝不站着对砍。对手快死了就补刀，不撤。
        返回的方向不是"逃跑方向"而是一个小包：打谁 + 打完往哪退 + 要不要补刀。"""
        目标 = min(敌人, key=lambda t: t["dist"])
        名 = 目标.get("name")
        中文 = 中文名.get(名, 名)
        我 = s.get("pos") or [0.0, 0.0, 0.0]
        目标位 = 目标.get("pos") or [我[0], 我[1], 我[2] - 1]
        dx, dz = 我[0] - 目标位[0], 我[2] - 目标位[2]
        if abs(dx) < 0.2 and abs(dz) < 0.2:
            dx, dz = 1.0, 0.0        # 贴到一起了，随便挑个方向退

        # 对方还剩多少血 —— 这个数协议不推，是探针问服务端要来的
        对方血 = (s.get("watched") or {}).get(名)
        补刀 = 对方血 is not None and 对方血 <= self._阈值("finish_hp", 7)

        # 跳劈 or 普通挥击 —— 按配置的概率掷一次。
        # 用了固定种子，所以同一段录像重放出来的选择是一样的（不然回放基准会随机失败）。
        # ⚠ 这段必须在下面"宣告"之前算完 —— 宣告要用到 跳劈 这个结果。
        跳劈 = False
        概率 = self._阈值("counter_jump_chance", 0.0)
        if 概率 > 0 and 最近 <= self._阈值("counter_jump_dist", 2.6) and not 补刀:
            跳劈 = self.rng.random() < 概率
            if 跳劈:
                self.跳劈次数 += 1
        self.挥击次数 += 1

        # 宣告合并：同一目标、距离和血量都没怎么变，就不再喊一遍。
        # （上一版实战里出现过 41 次一字不差的重复宣告，就是这里没做合并。）
        档 = round(最近 / max(self._阈值("announce_delta", 0.5), 0.1))
        快照 = (档, None if 对方血 is None else round(对方血))
        if self.状态 != self.反击 or 快照 != self.上次宣告快照:
            self.上次宣告快照 = 快照
            尾巴 = "" if 对方血 is None else f"，他还有 {血文本(对方血)} 血"
            收尾句 = ("—— 他就剩这一口气了，补掉他！" if 补刀
                     else ("，跳起来劈它！" if 跳劈
                           else ("，这回不退，扑上去接着打！" if self._压上去()
                                 else "，不白挨：挥它一下就往后退！")))
            self.说(f"[{时刻()}] {中文}都贴到我脸上了（{最近:.1f} 格）—— "
                    f"我还有 {血文本(血量)}/{血上限:.0f} 血、手上有家伙{尾巴}{收尾句}",
                    紧急=True)

        self.状态 = self.反击
        return (self.反击, {"target": 名, "退路": [round(dx, 3), round(dz, 3)],
                            "补刀": 补刀, "跳劈": 跳劈},
                self._阈值("attack_ms", 800))

    # ── M4·猎手：主动锁定 ──
    def 在追猎(self):
        """外面（节拍器 / 主循环）问一句"它现在在追人吗"。
        追击必须走快档 —— 1Hz 采样下每拍才挪一小步，看着像走一步愣一秒。"""
        return self.锁定目标 is not None

    def 放掉追击(self, 原因="主人叫停"):
        """外部叫停（指令层听到「停」「别追了」时调它）。
        返回"我本来在追吗" —— 不在追就不吭声，别平白刷一行日志。"""
        if not self.锁定目标:
            return False
        self._撒手(f"好，不追了（{原因}）。", 冷却=True)
        return True

    def _撒手(self, 话=None, 冷却=True):
        """结束一次追击。返回 None 是为了让调用处能一行写 `return self._撒手(...)`。"""
        self.锁定目标 = None
        self.锁定中文 = None
        self.锁定对方血 = None
        self.锁定时的死数 = None
        self.放弃起点 = None
        self.状态 = self.平静
        if 冷却:
            self.上次锁定结束 = time.time()
        if 话:
            self.说(f"[{时刻()}] {话}", 紧急=True)
        return None

    def _挑猎物(self, s, 敌人):
        """在"看得见的玩家"里挑一个对手。
        用 players[] 而不是 threats[]：后者被 8 格威胁半径圈住，二十几格外根本看不见，
        而"主动"的前提恰恰是它得先发现你。"""
        最远 = self._阈值("hunt_range", 26)
        贴脸距 = self._阈值("flee_dist", 5.0)
        # 有别的东西（僵尸之类）正贴在我脸上，先打眼前这个，别开新战场
        for t in 敌人:
            if t.get("kind") != "player" and t.get("dist", 9e9) < 贴脸距:
                return None
        朋友 = set(s.get("friends") or [])
        候选 = []
        for p in (s.get("players") or []):
            名 = p.get("name")
            if not 名 or 名 in 朋友 or not p.get("hostile"):
                continue
            距 = p.get("dist")
            if 距 is None or 距 > 最远:
                continue
            候选.append(p)
        if not 候选:
            return None
        return min(候选, key=lambda p: p.get("dist") or 9e9)

    @staticmethod
    def _转角(dx, dz, 角度):
        """把方向转一个角度（弧度）。MC 坐标是左手系，绕着 y 轴转就这样写。"""
        c, sn = math.cos(角度), math.sin(角度)
        return [round(dx * c - dz * sn, 3), round(dx * sn + dz * c, 3)]

    def _卡住怎么办(self, s, 猎物, 现在):
        """M4b·绕路。返回决策，或者 None 表示"这一拍不用绕"。

        两条路，按手那边报上来的事实选：
          · 有寻路插件 → 把"目标当前位置"交给它（每 detour_goto_ms 重下一次，
            因为目标在动），自己不抢方向盘；
          · 没有插件 → 土办法「沿墙滑」：把朝目标的直线转 detour_angle 度硬走。
        两种都只在"最近确实卡住过"时生效 —— 不卡就是纯直线，不为绕路付性能税。
        """
        if not self.m.get("detour_enable", True):
            return None
        卡了多久 = s.get("stuck_ms")
        新鲜线 = self._阈值("detour_stale_ms", 2500)
        if not isinstance(卡了多久, (int, float)) or 卡了多久 > 新鲜线:
            self.绕角度 = 0.0        # 不卡了，忘掉绕行姿势
            return None

        # 又卡了一次？换个姿势（翻面；翻两次还卡就退开一点绕大圈）
        计数 = s.get("stuck_count")
        if isinstance(计数, int) and 计数 != self.上次卡住计数:
            第一次 = self.上次卡住计数 is None
            self.上次卡住计数 = 计数
            self.绕向 = 1 if 第一次 else -self.绕向
            self.绕角度 = (self._阈值("detour_flip_angle", 110)
                          if (not 第一次 and self.绕角度 > 0) else self._阈值("detour_angle", 70))
            self.说(f"[{时刻()}] 前面走不动（第 {计数} 次卡住）—— 我换个方向绕过去。",
                    紧急=True)

        有寻路 = bool((s.get("plugins") or {}).get("pathfinder"))
        if 有寻路:
            if 现在 - self.上次绕路下发 < self._阈值("detour_goto_ms", 1200) / 1000.0:
                self.状态 = self.绕路
                return (self.绕路, None, 0)     # 等插件走，别抢它的活
            self.上次绕路下发 = 现在
            self.状态 = self.绕路
            return (self.绕路, list(猎物.get("pos") or s.get("pos") or [0, 0, 0]), 0)

        # 没有插件 → 沿墙滑
        我 = s.get("pos") or [0.0, 0.0, 0.0]
        位 = 猎物.get("pos") or 我
        dx, dz = 位[0] - 我[0], 位[2] - 我[2]
        长 = math.hypot(dx, dz)
        if 长 < 1e-3:
            dx, dz, 长 = 0.0, 1.0, 1.0
        角度 = max(self.绕角度, self._阈值("detour_angle", 70)) * self.绕向
        方向 = self._转角(dx / 长, dz / 长, math.radians(角度))
        self.状态 = self.追猎
        return (self.追猎, 方向, self._阈值("hunt_step_ms", 400))

    def _追一步(self, s, 猎物):
        """朝猎物迈一步。**不寻路** —— 场地是平的，直线最快；真撞上墙了，
        手那边的 前方危险() 会自己拐弯，拐不过去就站住发 blocked 事件。
        每一步都短，下一拍重新瞄：猎物在动，"一次算准"没有意义。"""
        我 = s.get("pos") or [0.0, 0.0, 0.0]
        位 = 猎物.get("pos") or 我
        dx, dz = 位[0] - 我[0], 位[2] - 我[2]
        长 = math.hypot(dx, dz)
        if 长 < 1e-3:
            dx, dz, 长 = 0.0, 1.0, 1.0
        self.状态 = self.追猎
        return (self.追猎, [round(dx / 长, 3), round(dz / 长, 3)],
                self._阈值("hunt_step_ms", 400))

    def _猎手(self, s, 敌人, 血量, 血比, 血上限, 有吃的, 有武器, 最近):
        """M4·主动锁定（主人 2026-09-30 点的菜：「你让他有概率锁我，光是我主动没意思」）。

        到 M2.1 为止小家伙全是**被动应战**：不挨打就当没看见你。这一段补上另一半。

        三条铁律：
        ① 名单解释权在手那边 —— 手在 players[] 里算好 hostile 字段，脑只认这一个字段。
           两边各写一套"谁是敌人"的规则，迟早会不一致（今天就在这里踩过一次）。
        ② **被人先动手，就不掷骰子** —— 主人 2026-10-01 原话：「我打它它就直接降级成
           （老样子）」。所以被敌对玩家打了就**立刻锁、立刻死斗**，不看概率、不看冷却，
           更不能退回 M2 那句"打一下就跑"。
        ③ 主动挑事（没人打我，我自己想打）才走概率：四个前提齐了才掷骰子。
        """
        if not self.m.get("hunt_enable", False):
            return None
        现在 = time.time()

        if self.锁定目标:
            return self._追下去(s, 敌人, 血量, 血比, 有吃的, 最近, 现在)

        # ⓪ 被打了 → 立刻应战（不走概率、不等冷却）
        谁打我 = s.get("attacked_by")
        if 谁打我 and self.m.get("hunt_retaliate", True) and not 有武器:
            # ★ 2026-10-01 第二轮诊断出来的坑：它挨打却不还手，查了半天是
            # **手里没家伙**（剑在上一轮打斗里耗光了）。空手打架是送命，
            # 所以"不还手"是对的 —— 但必须**说出来**，不然现场看着像 bug。
            if not self.没家伙说过:
                self.没家伙说过 = True
                self.说(f"[{时刻()}] 「{中文名.get(谁打我, 谁打我)}」打我，"
                        f"可我手里没家伙，只能先躲 —— 给我把剑吧。", 紧急=True)
        if 有武器:
            self.没家伙说过 = False
        if 谁打我 and self.m.get("hunt_retaliate", True) and 有武器 and (血量 or 0) > 0:
            打我的 = None
            for p in (s.get("players") or []):
                if p.get("name") == 谁打我 and p.get("hostile"):
                    打我的 = p
                    break
            if 打我的 is not None:
                return self._锁上(s, 打我的, "你打我？那我不客气了 —— 这回不死不休！")

        # 还没在追 —— 先过两道时间闸门，再谈掷骰子
        if 现在 - self.上次锁定结束 < self._阈值("hunt_cooldown_ms", 5000) / 1000.0:
            return None
        if 现在 - self.上次掷骰 < self._阈值("hunt_roll_ms", 3000) / 1000.0:
            return None
        猎物 = self._挑猎物(s, 敌人)
        if 猎物 is None:
            return None                      # 没人可锁就**不消耗随机数** —— 回放基准才不会乱

        if 血量 <= self._阈值("hunt_hp_min", 13):
            return None                      # 血不够，主动挑事 = 送
        if not 有武器:
            return None                      # 空手更送
        if self.状态 in (self.逃跑, self.濒危):
            return None                      # 自己正忙着跑，别开新战场
        if 血比 < self._阈值("low_hp_ratio", 0.5) and 有吃的:
            return None                      # 先吃饭，别拿空肚子去打架

        self.上次掷骰 = 现在
        if self.rng.random() >= self._阈值("hunt_chance", 0.35):
            return None

        距 = 猎物.get("dist")
        return self._锁上(s, 猎物,
                          "咦，「%s」在那儿%s —— 这回换我主动了，别跑！"
                          % (中文名.get(猎物.get("name"), 猎物.get("name")),
                             f"（{距:.0f} 格）" if isinstance(距, (int, float)) else ""))

    def _锁上(self, s, 猎物, 话):
        """锁定一个目标：记状态 + 宣告 + 走出第一步。**两条路都从这儿进**
        （被打了应战 / 没人打我自己挑事），免得两边各写一套记账。"""
        名 = 猎物.get("name")
        self.锁定目标 = 名
        self.锁定中文 = 中文名.get(名, 名)
        self.锁定时刻 = time.time()
        self.锁定对方血 = (s.get("watched") or {}).get(名)
        # 死数记账：锁定那一刻死了几次。这个数变了就说明"我自己死过"
        # —— 用的是快照里那个只增不减的计数器，**不是** respawned 那个
        # "重生后 15 秒内都为真"的窗口（那个窗口会把刚锁上的目标立刻撤掉，
        # 2026-10-01 实测当场抓到：它刚喊完"换我主动了"下一拍就"算我输"）。
        self.锁定时的死数 = s.get("deaths")
        self.追击次数 += 1
        self.说(f"[{时刻()}] {话}", 紧急=True)
        return self._追一步(s, 猎物)

    def _追下去(self, s, 敌人, 血量, 血比, 有吃的, 最近, 现在):
        """已经在追了：先过一遍"要不要撒手"，都过关才走这一步。"""
        名 = self.锁定目标
        贴脸距 = self._阈值("flee_dist", 5.0)
        反击距 = self._阈值("counter_dist", 3.0)
        该吃线 = self._阈值("low_hp_ratio", 0.5)

        if 名 in set(s.get("friends") or []):
            return self._撒手()

        猎物 = None
        for p in (s.get("players") or []):
            if p.get("name") == 名:
                猎物 = p
                break
        if 猎物 is None or not 猎物.get("hostile"):
            # 三种情况都走这里：下线了 / 被我打死了 / 被加进朋友名单。
            # 分辨"打死"和"下线"只能靠探针最后那一口读数 —— 玩家一死，实体就没了。
            躺下 = self.锁定对方血 is not None and self.锁定对方血 <= 0
            return self._撒手(f"「{self.锁定中文}」躺下了 —— 打赢啦！" if 躺下
                              else f"咦，「{self.锁定中文}」人没了，我先站住。")

        self.锁定对方血 = (s.get("watched") or {}).get(名, self.锁定对方血)
        距 = 猎物.get("dist")
        死斗 = self._死斗()

        # ⓪ 自己倒下了 → 这次追击到此为止（"直到目标死亡或者是自己死亡"的后半句）。
        #    判据用快照里那个只增不减的死亡计数：锁定时记几，现在不是几就说明死过。
        #    （血 0 那几帧再兜一层底；**不用** respawned —— 那个标志会连续为真 15 秒。）
        死数 = s.get("deaths")
        if (死数 is not None and self.锁定时的死数 is not None and 死数 != self.锁定时的死数) \
                or (血量 is not None and 血量 <= 0):
            return self._撒手(f"呜，我被「{self.锁定中文}」打倒了 —— 这次算我输。")

        if not 死斗:
            # 下面①②③④⑤五条都是"收手"的条件。**死斗期间全部跳过** ——
            # 主人要的就是"触发之后不死不休"，收手只能由死亡来收。
            # ① 跑太远：给足 hunt_giveup_ms 的耐心再放弃（绕过一堵墙不算"追不上"）
            if isinstance(距, (int, float)) and 距 > self._阈值("hunt_giveup_dist", 34):
                if self.放弃起点 is None:
                    self.放弃起点 = 现在
                elif 现在 - self.放弃起点 >= self._阈值("hunt_giveup_ms", 3500) / 1000.0:
                    return self._撒手(f"追到 {距:.0f} 格还追不上，算了…")
            else:
                self.放弃起点 = None

            # ② 追太久：一次追击封顶，到点收工进冷却 —— 不然它会一直黏着你
            if 现在 - self.锁定时刻 >= self._阈值("hunt_max_ms", 30000) / 1000.0:
                return self._撒手("追了这么久还没完，我歇会儿。")

            # ③ 保命：疼到线下就撒手，后面那些逃跑/迎战分支才是这时候该干的事
            if 血量 <= self._阈值("hunt_abort_hp", 9):
                return self._撒手(f"啊，疼死我了（血 {血文本(血量)}）—— 我不追了，先保命！")

            # ④ 已经贴脸了，而我这血已经不够还手（M2 的老规矩）→ 静悄悄撒手，
            #    让下面的分支按原样处置（该迎战迎战、该跑跑）。不设冷却：血回上来还能再锁。
            if 最近 is not None and 最近 < 贴脸距 and 血量 <= self._阈值("counter_hp_min", 12):
                return self._撒手(冷却=False)

            # ⑤ 该吃饭了：追人的前提是自己站得住。吃完它自己会重新挑事。
            if (最近 is None or 最近 >= 贴脸距) and 血比 < 该吃线 and 有吃的:
                return self._撒手(冷却=False)

        # ⑥ 进打击圈就撒手 —— 下面原来的「反击」逻辑会接手，别抢它的活
        #    （死斗期间这条路照样要留着：真正挥拳头的是「反击」那一支，
        #     连击的节奏也在那边，靠的是 _攻击冷却()）
        if isinstance(距, (int, float)) and 距 <= 反击距:
            return None

        # ⑦ 有别的家伙贴脸？这一步先不追（锁定留着，先应付眼前这个）
        for t in 敌人:
            if t.get("kind") != "player" and t.get("dist", 9e9) < 贴脸距:
                return None

        # ⑧ M4b：直线走不通就先绕（只在还没进打击圈时用 —— goto 是长动作，
        #    一进打击圈就得把方向盘收回来，不然它"绕得开心、一拳不挥"）
        绕 = self._卡住怎么办(s, 猎物, 现在)
        if 绕 is not None:
            return 绕

        return self._追一步(s, 猎物)

    def _没吃的怎么办(self, s, 血量, 血上限, 濒危, 刚重生=False):
        """M2·背包空了的处理顺序：
        先看地上有没有能捡的 → 捡不到就原地讨饭 → 都不成就交给 M1 的濒危逻辑。"""
        掉落 = s.get("drops") or []
        现在 = time.time()
        我 = s.get("pos") or [0.0, 0.0, 0.0]

        有寻路 = bool((s.get("plugins") or {}).get("pathfinder"))
        for d in 掉落:
            差x = d["pos"][0] - 我[0]
            差z = d["pos"][2] - 我[2]
            if math.hypot(差x, 差z) <= 1.2:
                continue                      # 已经站上去了，等它自己进背包
            if 现在 - self.上次拾取 < self._阈值("recover_cooldown_ms", 3000) / 1000.0:
                return None
            self.上次拾取 = 现在
            名 = 中文名.get(d["name"], d["name"])
            远 = math.hypot(差x, 差z) > 3.0
            if self.状态 != self.拾取:
                self.说(f"[{时刻()}] 我把吃的弄丢了，得重新找 —— "
                        f"那边地上躺着「{名}」（{d['dist']:.0f} 格），我过去捡。")
            if 远 and 有寻路:
                # 十几格开外，光靠迈腿是走不到的（中间隔着树、沟、坎），
                # 这时候才动用那个可选外挂 —— 没有它照样能跑，只是够不着远处的家当。
                self.状态 = self.前往
                return (self.前往, list(d["pos"]), 0)
            self.状态 = self.拾取
            return (self.拾取, [round(差x, 3), round(差z, 3)],
                    self._阈值("recover_move_ms", 900))

        # 地上没得捡（或者够不着）→ 原地等投喂，但别一直念叨
        if (not 濒危 or 刚重生) and 现在 - self.上次讨饭 >= self._阈值("beg_interval_sec", 90):
            self.上次讨饭 = 现在
            self.说(f"[{时刻()}] 我把吃的弄丢了，得重新找 —— 背包是空的，"
                    f"附近也没我够得着的掉落物。血 {血文本(血量)}/{血上限:.0f}，"
                    f"我原地等一会儿，谁路过给我扔口吃的吧…", 紧急=True)
            self.状态 = self.饿等
        return None

    @staticmethod
    def _食物中文(名):
        return 食物中文名.get(名, 名)

    def _死斗(self):
        """M4·死斗（配置 hunt_until_death）：锁定之后不再收手。

        主人 2026-10-01 点的菜：「主动索敌一旦触发就一直打，追着打，
        直到目标死亡或者是自己死亡」。所以死斗期间这些撤手条件**全部失效**：
        追太远、追太久、自己血少、贴脸没本事还手、让位吃饭。
        只剩两条能结束它 —— 目标倒下（或下线）／自己倒下。"""
        return bool(self.锁定目标) and bool(self.m.get("hunt_until_death", False))

    def _攻击冷却(self):
        """两次挥击之间等多久（秒）。
        死斗期间用 hunt_combo_ms（默认 650ms）= 连击。**不能更快**：
        剑的蓄力上限是 0.625 秒，挥得再快服务端也只按蓄力折算伤害，
        挥空还不如省着挥（这也正是"可连击"要卡的那个数）。"""
        if self.锁定目标:
            return self._阈值("hunt_combo_ms", 650) / 1000.0
        return self._阈值("counter_cooldown_ms", 2500) / 1000.0

    def _压上去(self):
        """追猎期间打完不后撤（配置项 hunt_press）。
        宣告和执行都要问同一件事 —— 不然日志会写"挥它一下就往后退"，
        而它其实一步没退（这个不一致在 2026-10-01 的实测里被主人看见了）。"""
        return bool(self.锁定目标) and bool(self.m.get("hunt_press", True))

    # ── 执行：把决策翻译成给手的命令 ──
    def 执行(self, 决策, 发命令):
        动作, 方向, 毫秒 = 决策
        if 动作 == self.反击 and isinstance(方向, dict):
            self.上次反击 = time.time()
            if 方向.get("跳劈"):
                发命令({"cmd": "jumpattack", "target": 方向["target"]})
            else:
                发命令({"cmd": "attack", "target": 方向["target"], "ms": int(毫秒)})
            # M4：追猎期间默认"压上去打"，不执行"打一下就跑"的后撤。
            # 理由很实在 —— 追上去打才是这一轮的意图，挥完就往后撤会让"追"
            # 变成来回抖；而且主人要的就是能真打起来的架。性能不满意就把
            # hunt_press 关掉，立刻退回 M2 的"打了就跑"。
            压上去 = self._压上去()
            if 方向.get("补刀") or 压上去:
                self.待后撤 = None
                if 方向.get("补刀"):
                    self.说(f"[{时刻()}] 补刀，不撤 —— 他就剩一口气了。", 紧急=True)
            else:
                # 挥完立刻疾跑后撤，交给收尾() 到点执行 —— 站着对砍是找死
                self.待后撤 = (time.time() + 毫秒 / 1000.0, 方向["退路"])
        elif 动作 == self.绕路 and isinstance(方向, list) and len(方向) >= 3:
            # 把方向盘交给寻路插件。插件不在时手会回"回退成原地站着"，
            # 脑这边不用管 —— 下一拍卡住信号还在，它会自己改走沿墙滑。
            发命令({"act": "goto", "p": [float(v) for v in 方向[:3]]})
        elif 动作 == self.绕路:
            pass          # 等插件走，这一拍不下任何命令
        elif 动作 == self.追猎 and isinstance(方向, list):
            # 一小段一小段地压上去。用 move 而不是 goto：goto 是一次长动作，
            # 追人期间还得每拍重算，反而更贵；而且它依赖可选插件。
            发命令({"cmd": "move", "dir": 方向, "ms": int(毫秒), "sprint": True})
        elif 动作 in (self.逃跑, self.濒危, self.拾取) and isinstance(方向, list):
            if 动作 == self.逃跑:
                self.上次逃跑 = time.time()
            发命令({"cmd": "move", "dir": 方向, "ms": int(毫秒),
                    "sprint": bool(self.m.get("sprint_when_flee", False)
                                   and 动作 == self.逃跑)})
        elif 动作 == self.前往 and isinstance(方向, list) and len(方向) >= 3:
            # 任务书里点名的是 {"act":"goto","p":[x,y,z]} 这个形状
            发命令({"act": "goto", "p": [float(v) for v in 方向[:3]]})
        elif 动作 == self.进食:
            self.上次进食 = time.time()
            self.没吃的说过 = False
            发命令({"cmd": "eat"})
        elif 动作 in (self.平静, self.挂起, self.饿等, self.迎战):
            pass          # 迎战 = 不下任何移动命令，原地站住等它进来

    def 收尾(self, 发命令):
        """反击之后的那个后撤步。主循环每拍问一次，到点了就退。"""
        if not self.待后撤:
            return
        到期, 退路 = self.待后撤
        if time.time() >= 到期:
            self.待后撤 = None
            毫秒 = int(self._阈值("counter_retreat_ms", 1100))
            发命令({"cmd": "move", "dir": 退路, "ms": 毫秒,
                    "sprint": bool(self.m.get("sprint_when_flee", True))})
            self.撤退到 = time.time() + 毫秒 / 1000.0
            self.说(f"[{时刻()}] 疾跑拉开距离，别站在它脸上。", 紧急=True)

    # ── 热保护：主人的红线，谁来了都得让路 ──
    def 查热(self, cpu, gpu):
        上限cpu = self._阈值("cpu_max_c", 75)
        上限gpu = self._阈值("gpu_max_c", 70)
        降温 = self._阈值("resume_below_c", 68)
        连击线 = int(self._阈值("strikes", 3))

        if not hasattr(self, "_热连击"):
            self._热连击 = 0

        超标 = (cpu is not None and cpu >= 上限cpu) or (gpu is not None and gpu >= 上限gpu)

        if self.热挂起:
            凉了 = ((cpu is None or cpu < 降温) and (gpu is None or gpu < 降温))
            if 凉了:
                self.热挂起 = False
                self._热连击 = 0
                self.说(f"[{时刻()}] 凉下来了（CPU {cpu}℃ / GPU {gpu}℃），"
                        f"我接着干活。", 紧急=True)
                return "恢复"
            return None

        if 超标:
            self._热连击 += 1
            if self._热连击 >= 连击线:
                self.热挂起 = True
                self.状态 = self.平静
                self.说(f"[{时刻()}] ⚠ 太热了（CPU {cpu}℃ / GPU {gpu}℃），"
                        f"越过主人的红线了。我立刻把 M1 挂起、就地休眠，"
                        f"凉下来再自己回来。", 紧急=True)
                return "挂起"
        else:
            self._热连击 = 0
        return None


中文名 = {
    "zombie": "僵尸", "husk": "尸壳", "drowned": "溺尸",
    "skeleton": "骷髅", "stray": "流浪者", "bogged": "沼骸",
    "wither_skeleton": "凋灵骷髅", "creeper": "苦力怕",
    "spider": "蜘蛛", "cave_spider": "洞穴蜘蛛", "witch": "女巫",
    "slime": "史莱姆", "magma_cube": "岩浆怪", "enderman": "末影人",
    "endermite": "末影螨", "silverfish": "蠹虫", "phantom": "幻翼",
    "pillager": "掠夺者", "vindicator": "卫道士", "evoker": "唤魔者",
    "ravager": "劫掠兽", "vex": "恼鬼", "blaze": "烈焰人",
    "ghast": "恶魂", "guardian": "守卫者", "elder_guardian": "远古守卫者",
    "shulker": "潜影贝", "zoglin": "僵尸疣猪兽", "hoglin": "疣猪兽",
    "piglin": "猪灵", "zombified_piglin": "僵尸猪灵", "warden": "监守者",
    "breeze": "旋风人", "wither": "凋灵",
    "sheep": "羊", "cow": "牛", "pig": "猪", "chicken": "鸡",
    "rabbit": "兔子", "horse": "马", "wolf": "狼", "cat": "猫",
    "bat": "蝙蝠", "axolotl": "美西螈", "glow_squid": "发光鱿鱼",
    "squid": "鱿鱼", "villager": "村民", "item": "掉落物",
}

食物中文名 = {
    "bread": "面包", "apple": "苹果", "golden_carrot": "金胡萝卜",
    "golden_apple": "金苹果", "cooked_beef": "熟牛排",
    "cooked_porkchop": "熟猪排", "cooked_chicken": "熟鸡肉",
    "cooked_mutton": "熟羊肉", "cooked_rabbit": "熟兔肉",
    "cooked_cod": "熟鳕鱼", "cooked_salmon": "熟鲑鱼",
    "baked_potato": "烤马铃薯", "carrot": "胡萝卜", "potato": "马铃薯",
    "beef": "生牛肉", "porkchop": "生猪排", "chicken": "生鸡肉",
    "mutton": "生羊肉", "rotten_flesh": "腐肉", "cookie": "曲奇",
    "sweet_berries": "甜浆果", "melon_slice": "西瓜片",
}


# ─────────────────────────── M4c · 任务栈 ───────────────────────────

# 挖这些是白费力气。身体插件里有一份同源的表；脑这边留一份是为了**快速判死** ——
# 不用等 60 秒超时，看事实就知道"这格挖不动"。
挖不动 = {"bedrock", "barrier", "light", "structure_void", "command_block",
          "chain_command_block", "repeating_command_block", "structure_block",
          "jigsaw", "end_portal", "end_portal_frame", "nether_portal",
          "moving_piston", "water", "lava"}

# ★ M4c 补丁①：哪些方块**必须**有镐子（跟手侧 proto_body.js 里那张表同源）。
# 只列"不给镐子就挖不动、或者挖了不掉东西"的 —— 木头泥土徒手能挖，不拦。
import re as _re_tool
_镐子系 = _re_tool.compile(r"(_ore|stone|deepslate|cobblestone|bricks|concrete|obsidian|"
                           r"netherrack|furnace|anvil|terracotta|sandstone|prismarine|"
                           r"basalt|blackstone|tuff|calcite|dripstone|quartz|_block$)")


def _要镐子(名):
    if not isinstance(名, str):
        return False
    if _re_tool.search(r"leaves|wool|_log|_wood", 名):
        return False
    return bool(_镐子系.search(名))


# 挖掉之后会掉什么（"拾"那一步要盯哪个物品）
掉落物名 = {"stone": "cobblestone", "cobblestone": "cobblestone", "deepslate": "cobblestone",
            "grass_block": "dirt", "dirt": "dirt", "sand": "sand", "gravel": "gravel",
            "oak_log": "oak_log", "birch_log": "birch_log", "spruce_log": "spruce_log",
            "oak_planks": "oak_planks", "stone_bricks": "stone_bricks",
            "coal_ore": "coal", "iron_ore": "raw_iron", "furnace": "furnace"}


def 活着(反射):
    """热保护挂起时别点火（红线优先）。"""
    return not getattr(反射, "热挂起", False)


def _能闲聊(cfg, 谁, m3):
    """★ 主人钦定的红线：**只跟主人 + 好友名单聊，陌生人只记录不搭话**。"""
    m5 = cfg.get("m5") or {}
    名单 = list((m5.get("chitchat") or {}).get("allow_from") or [])
    朋友 = set((m3 or {}).get("friends") or [])
    return (谁 in 名单) or (谁 in 朋友)


def _聊一句(三觉层, 翻译, 大模型, 指令, 谁, 话, 状态):
    """M5·听觉：认不出的话 → 让它像玩伴那样回一句（或者顺手定个小目标）。"""
    if 三觉层.扫描过期(状态, 秒=180):
        三觉层.要扫描()                     # 顺手扫一眼，下一拍才有视觉
    prompt = 翻译.组Prompt(状态, 用途="闲聊", 任务状况=指令._状态一句话(状态),
                          说话人=谁, 原话=话)
    原文 = 大模型.问一次(prompt, "闲聊", 300)
    if not 原文:
        return False
    动作, 任务, 原因 = 翻译.收输出(原文, 状态, 用途="闲聊")
    if 任务:
        指令.说(f"[{时刻()}] 我自己琢磨了个目标：{任务.get('名字')}", 紧急=True)
        if getattr(指令, "任务栈", None) is not None:
            指令.任务栈.接(任务.get("名字"), 任务.get("步骤"), 状态)
        return True
    if 动作 and 动作.get("act") == "say":
        指令.说(f"[{时刻()}] {动作.get('text')}")
        指令.回话(str(动作.get("text"))[:120])
        return True
    if 动作 and 动作.get("act") not in (None, "none"):
        指令._做(动作, 状态, 谁, 话)
        return True
    if 原因:
        指令.说(f"[{时刻()}] 它说的我接不住（{原因}），那我不接话。", 紧急=True)
    return False


def 搭去回任务(p):
    """「去 X Y Z，然后回来」：4 步。
    「回来」用特殊值 "起点" —— 接单那一刻才是它真正的起点（任务栈负责换算）。"""
    return [
        {"动作": "走到", "p": [float(v) for v in p[:3]], "到点": 2.5},
        {"动作": "说", "文本": "到了。"},
        {"动作": "走到", "p": "起点", "到点": 2.5},
        {"动作": "说", "文本": "回来了。"},
    ]


def 搭挖任务(坐标们):
    """「挖 X Y Z [X Y Z …]，然后回来」：每格三步（走过去 / 挖 / 拾）+ 回程 + 收尾。
    「拾」不写物品名 —— 挖到什么才知道要拾什么，那时候让方块探针告诉我们（见 _补全步骤）。"""
    步 = []
    共 = len(坐标们)
    for i, p in enumerate(坐标们):
        x, y, z = [float(v) for v in p[:3]]
        # ⚠ 站到**斜对角**，不要站在要挖那块的正上方：手的保护会拒绝挖脚下的方块
        #（实测原话：「那是我正脚下那块，挖了我自己就掉下去了」）。
        # ★ M4c 补丁②：长任务切片 —— **一块一组步骤**（走到/挖/拾 各一步）。
        # 这样被战斗打断时，进度只丢"当前这一块"；已完成的那几块，
        # 下一次判据直接看到"方块已经是空气"，**不会重挖**。
        块 = {"第几块": i + 1, "共几块": 共}
        步.append(dict(块, **{"动作": "走到", "p": [x + 1, y + 1, z + 1], "到点": 3.0}))
        步.append(dict(块, **{"动作": "挖", "p": [x, y, z]}))
        步.append(dict(块, **{"动作": "拾", "物品": None, "看方块": [x, y, z], "数量": 1}))
    步.append({"动作": "走到", "p": "起点", "到点": 3.0})
    步.append({"动作": "说", "文本": "挖完了，回来了。"})
    return 步


def 搭烧矿任务(炉坐标):
    """「烧铁 X Y Z」：把炉子当作一台"要等世界"的机器。
    关键在第 3 步 —— **wait_until 不发任何动作**，它只每拍问一句"烧完了吗"；
    所以这段时间反射层照常保命，而炉子该烧多久烧多久。"""
    x, y, z = [float(v) for v in 炉坐标[:3]]
    炉 = [x, y, z]
    旁边 = [x, y + 1, z]
    return [
        {"动作": "走到", "p": 旁边, "到点": 2.5},
        {"动作": "熔炉放料", "p": 炉, "输入": {"name": "iron_ore", "count": 3},
         "燃料": {"name": "coal", "count": 2}},
        {"动作": "wait_until", "条件": "furnace_done", "熔炉": 炉, "数量": 3,
         "等待超时_ms": 300000},
        {"动作": "走到", "p": 旁边, "到点": 2.5},
        {"动作": "熔炉取成品", "p": 炉, "物品": "iron_ingot", "数量": 3},
        {"动作": "说", "文本": "烧好了，铁锭拿到了。"},
    ]


class 任务栈:
    """M4c·任务栈：把"先走到那儿、再挖三个、再回来"这种多步活干完。

    主人 2026-10-01 定下的三条核心要求 + 一条架构原则：
      ① 多步任务（记进度）；② 打断与恢复（**反射层一票否决优先**）；
      ③ 失败重试（**并记录原因**）；④ `wait_until` = **非阻塞条件等待**。

    ★ 安全边界（主人点名的那条）：只认下面 `允许动作` 里登记过的动作。
      清单外的一律**拒绝接单**（fail-closed）—— 不猜、不执行、记账。
      `tools/安全检查.py` 盯着这条：少了白名单、少了拒绝逻辑，它就会红。
    """

    # ★ fail-closed：登记过的动作就这些，多一个都没有
    允许动作 = frozenset({
        "走到", "挖", "拾", "放", "打", "等", "说",
        "熔炉放料", "熔炉取成品", "wait_until",
    })
    def __init__(self, m4, 说, 发命令, 日志目录, 记忆=None):
        self.m = m4 or {}
        self.说 = 说
        self.发 = 发命令
        self.任务 = None
        self.记忆 = 记忆          # M7：干完/失败都写进记忆（记忆不是指令，只是记事）
        self.日志路径 = os.path.join(日志目录, "任务.jsonl")
        self.快照路径 = os.path.join(日志目录, "任务快照.json")
        self.上次下发 = 0.0
        # ★ 防抖：反射层刚回到「平静」还不够 —— 要连续安静一小会儿才恢复。
        # 实测教训：一次追逐里会出现"暂停-恢复"每 0.2 秒抖一次，日志刷一屏、
        # 活儿也根本推不动（它一边想干活、一边被反复打断）。
        self.平静起点 = None

    def 记平静(self, 现在):
        if self.平静起点 is None:
            self.平静起点 = 现在
        return 现在 - self.平静起点

    def 记不平静(self):
        self.平静起点 = None

    def 冷静够了(self, 现在):
        return self.记平静(现在) >= self._数("恢复冷静秒", 0.6)

    # ── 开关与参数 ──
    def 启用(self):
        return bool(self.m.get("task_enable", True))

    def _数(self, 名, 缺省):
        try:
            return float(self.m.get(名, 缺省))
        except (TypeError, ValueError):
            return float(缺省)

    def 要快(self):
        """任务在跑"动作步"时要 5Hz；**等待步 1Hz 就够**（省电，别为等世界空转）。"""
        任 = self.任务
        if not 任 or 任["状态"] != "跑":
            return False
        步 = 任["步骤"][任["第几步"]]
        return 步.get("动作") not in ("wait_until", "等")

    def 在跑(self):
        return bool(self.任务 and self.任务["状态"] in ("跑", "暂停"))

    # ── 记账 ──
    def _记(self, 事件, **额外):
        条 = {"t": round(time.time(), 3), "事件": 事件}
        if self.任务:
            条["任务"] = self.任务["id"]
            条["第几步"] = self.任务["第几步"]
            条["共几步"] = len(self.任务["步骤"])
        条.update(额外)
        try:
            with open(self.日志路径, "a", encoding="utf-8") as f:
                f.write(json.dumps(条, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _存快照(self):
        try:
            with open(self.快照路径, "w", encoding="utf-8") as f:
                json.dump(self.任务 or {}, f, ensure_ascii=False, indent=1)
        except Exception:
            pass

    # ── 接单 ──
    def 接(self, 名字, 步骤, s):
        if not self.启用():
            return False
        步骤 = list(步骤 or [])
        if not 步骤:
            return False
        野的 = sorted({str(步.get("动作")) for 步 in 步骤} - self.允许动作)
        if 野的:
            # ★ 这一行就是"锁"：清单外的动作，一个字都不执行
            self.说(f"[{时刻()}] 这个活里有我没登记过的动作（{'、'.join(野的)}）—— "
                    f"我不接。", 紧急=True)
            self._记("拒单", 原因="未知动作", 动作=野的)
            return False
        if self.在跑():
            self._记("替换", 原因="来了新活，旧的作废", 旧=名字)
            self.说(f"[{时刻()}] 来了新活儿，手上那件我先放下。")
        起点 = list((s or {}).get("pos") or [0, 0, 0])
        for 步 in 步骤:                 # "起点" 是占位符，接单这一刻才换算成真坐标
            if 步.get("p") == "起点":
                步["p"] = list(起点)
        self.任务 = {
            "id": f"任务-{int(time.time())}",
            "名字": str(名字)[:40],
            "步骤": 步骤,
            "第几步": 0,
            "重试": 0,
            "状态": "跑",
            "起点": 起点,
            "开始时刻": time.time(),
            "步骤开始": time.time(),
            "重试到": 0.0,
            "暂停时刻": None,
            "暂停原因": None,
            "下发过": False,
        }
        self.上次下发 = 0.0        # 新任务的第一步不许被上一件事的节流挡住
        self._挂探针(步骤, s)
        self._记("接单", 名字=self.任务["名字"], 步数=len(步骤),
                 步骤=[步.get("动作") for 步 in 步骤])
        self._记("步骤开始", 动作=步骤[0].get("动作"), 第几步=0)   # 第一步也要有账
        self.说(f"[{时刻()}] 好，我去了：{self.任务['名字']}"
                f"（{len(步骤)} 步）。", 紧急=True)
        self._存快照()
        return True

    def _挂探针(self, 步骤, s):
        """整个任务要用到的事实通道**一次性挂上**（开始时挂、结束时撤）。"""
        方块, 物品, 熔炉 = [], [], None
        for 步 in 步骤:
            动 = 步.get("动作")
            if 动 in ("挖", "放", "wait_until") and isinstance(步.get("p"), (list, tuple)):
                方块.append([float(v) for v in 步["p"][:3]])
            if 动 in ("拾", "熔炉取成品", "wait_until") and 步.get("物品"):
                物品.append(str(步["物品"]))
            if 动 in ("熔炉放料", "熔炉取成品") and isinstance(步.get("p"), (list, tuple)):
                熔炉 = [float(v) for v in 步["p"][:3]]
            if 动 == "wait_until" and isinstance(步.get("熔炉"), (list, tuple)):
                熔炉 = [float(v) for v in 步["熔炉"][:3]]
        # 有"要等探针到货才知道拾什么"的步骤 → 顺带盯上 * （背包全部物品）
        if any(步.get("动作") == "拾" and not 步.get("物品") for 步 in 步骤):
            物品.append("*")
        self.发({"cmd": "watch_blocks", "list": 方块[:16]})
        self.发({"cmd": "watch_items", "list": sorted(set(物品))[:16]})
        self.发({"cmd": "furnace_watch", "p": 熔炉} if 熔炉 else {"cmd": "furnace_watch"})

    def _撤探针(self):
        self.发({"cmd": "watch_blocks", "list": []})
        self.发({"cmd": "watch_items", "list": []})
        self.发({"cmd": "furnace_watch"})

    # ── 打断与恢复 ──
    def 暂停(self, 原因, s=None):
        """反射层接管了 —— 记一笔，把进度留在原地。"""
        任 = self.任务
        if not 任 or 任["状态"] != "跑":
            return False
        任["状态"] = "暂停"
        任["暂停时刻"] = time.time()
        任["暂停原因"] = str(原因)
        步 = 任["步骤"][任["第几步"]]
        尾巴 = "（等待中）" if 步.get("动作") == "wait_until" else ""
        self._记("暂停", 原因=任["暂停原因"], 步=步.get("动作"))
        self.说(f"[{时刻()}] 先停一下手上的活 —— {原因}{尾巴}。", 紧急=True)
        self._存快照()
        return True

    def 恢复(self, s=None):
        """反射层放行了：**从断点继续**（不重头）。"""
        任 = self.任务
        if not 任 or 任["状态"] != "暂停":
            return False
        时长 = time.time() - (任["暂停时刻"] or time.time())
        原因 = 任["暂停原因"]
        任["状态"] = "跑"
        任["暂停时刻"] = None
        任["暂停原因"] = None
        # ★ M4c 补丁③下半：**暂停期间冻结超时计时** ——
        # 把"步骤开始"整体往后推，等于这一步的秒表在打架时停住了。
        # （不然一场架打完，这一步的时间早就超了，活儿全白干。）
        任["步骤开始"] = float(任.get("步骤开始") or time.time()) + 时长
        if 任.get("重试到"):
            任["重试到"] = float(任["重试到"]) + 时长
        self._记("恢复", 暂停了=round(时长, 1), 原因=原因, 冻结=round(时长, 1))
        self.说(f"[{时刻()}] 没事了，接着干（第 {任['第几步'] + 1} 步）。")
        上限 = self._数("暂停上限秒", 120)
        if 时长 > 上限:
            # 被打断太久 → 这一步判失败，走重试。免得"被打断十次还傻站在人家门口"。
            return self._失败(任["步骤"][任["第几步"]],
                             f"被打断 {时长:.0f} 秒（超过 {上限:.0f} 秒上限）", s)
        return True

    def 中止(self, 原因="主人叫停"):
        任 = self.任务
        if not 任 or 任["状态"] in ("完", "败", "中止"):
            return False
        self._记("中止", 原因=原因, 停在=任["第几步"] + 1)
        self.说(f"[{时刻()}] 好，我不干了（{原因}，停在 {任['第几步'] + 1}/{len(任['步骤'])} 步）。",
                紧急=True)
        任["状态"] = "中止"
        if self.记忆 is not None:
            try:
                self.记忆.记任务(任["名字"], "中止", 停在=任["第几步"] + 1,
                               共=len(任["步骤"]), 原因=原因, 坐标=self._这位坐标(任))
            except Exception as e:
                self._记("记忆写入出错", 原因=f"{type(e).__name__}: {e}")
        self._撤探针()
        self._存快照()
        return True

    def 进度一句话(self):
        任 = self.任务
        if not 任:
            return "我手上没活。"
        if 任["状态"] in ("完", "败", "中止"):
            return f"刚才那件「{任['名字']}」{任['状态']}了（一共 {len(任['步骤'])} 步）。"
        步 = 任["步骤"][任["第几步"]]
        尾巴 = f"，正在等「{步.get('条件') or 步.get('物品')}」" if 步.get("动作") == "wait_until" else ""
        在停 = "（暂停中：" + str(任["暂停原因"]) + "）" if 任["状态"] == "暂停" else ""
        重 = f"，这一步重试过 {任['重试']} 次" if 任["重试"] else ""
        return (f"我在做「{任['名字']}」：第 {任['第几步'] + 1}/{len(任['步骤'])} 步"
                f"「{步.get('动作')}」{尾巴}{在停}{重}。")

    def _补全步骤(self, 步, s):
        """有的步骤要等探针到货才能确定参数：最典型的是"拾" ——
        得先知道挖的是**什么方块**、才知道该盯哪个掉落物。
        判据永远是事实（方块探针），不是我猜的那个名字。"""
        # 已经定过了（物品名或"跳过"）就别再管它 ——
        # ⚠ 2026-10-01 实测：这里原来每拍都记一条账，日志被刷出几千行噪声。
        # **记账只记状态变化**，不记"我又想了一遍"。
        if 步.get("动作") != "拾" or 步.get("物品") or 步.get("跳过") or not 步.get("看方块"):
            return
        名 = self._方块名(s, 步["看方块"])
        if 名 in (None, "air", "cave_air", "void_air"):
            return
        要的 = 掉落物名.get(名)
        if 要的:
            步["物品"] = 要的
            步["数量"] = float(步.get("数量", 1))
            self._记("步骤参数补全", 动作="拾", 挖的=名, 拾的=要的)
        else:
            # 不认识这个方块的掉落物 → 这一步跳过（老实认怂，不瞎等）
            步["跳过"] = True
            self._记("步骤参数补全", 动作="拾", 挖的=名, 跳过=True)

    # ── 完成判据：**一律看事实**（快照里的探针数据），不认"命令发出去了" ──
    def _看完成了没(self, 步, s, 任=None):
        任 = 任 or (self.任务 or {})
        动 = 步.get("动作")
        我 = (s or {}).get("pos") or [0, 0, 0]
        if 动 == "说":
            # "说"这一步：命令发出去了才算完（不然它一句话都没说就跳下一步）
            return bool(任.get("下发过")), None
        if 动 == "等":
            return (time.time() - self.任务["步骤开始"]) * 1000 >= float(步.get("ms", 1000)), None
        if 动 == "走到":
            p = 步.get("p") or [0, 0, 0]
            # ⚠ 2026-10-01 实测：这里原来只看配置里的到点半径，**忽略了步骤自己写的到点**。
            # 而寻路插件到离目标 ~2.6 格就停了（GoalNear 的容差），于是
            # "永远判没到 → 卡住 → 重下 → 又被打断"死循环。步骤自带的到点优先。
            到点 = float(步.get("到点") or self._数("到点半径", 2.5))
            水平 = math.hypot(p[0] - 我[0], p[2] - 我[2])
            return 水平 <= 到点 and abs(p[1] - 我[1]) <= 2.5, None
        if 动 in ("挖", "放"):
            p = 步.get("p") or [0, 0, 0]
            名 = self._方块名(s, p)
            if 动 == "挖":
                # ⚠ 实测教训：探针没到货（None）**不算挖完** —— 只有明确读到空气才算。
                # 原来把 None 也算进去，结果接单后第一拍就"挖完了"（0.2 秒），
                # 而那一格其实还在（后面 60 秒的"拾"超时就是这么来的）。
                return (名 in ("air", "cave_air", "void_air")), None
            return (名 == 步.get("方块")), None
        if 动 in ("拾", "熔炉取成品"):
            return self._物品数量(s, 步.get("物品")) >= float(步.get("数量", 1)), None
        if 动 == "打":
            名 = 步.get("名")
            对方血 = ((s or {}).get("watched") or {}).get(名)
            还在 = any(p.get("name") == 名 for p in ((s or {}).get("players") or []))
            return (对方血 is not None and 对方血 <= 0) or not 还在, None
        if 动 == "熔炉放料":
            return self._熔炉有料(s, 步), None
        if 动 == "wait_until":
            return self._条件满足(步, s), None
        return False, None

    @staticmethod
    def _方块名(s, p):
        for 条 in ((s or {}).get("blocks") or []):
            q = 条.get("p") or [None, None, None]
            if abs(q[0] - p[0]) < 0.5 and abs(q[1] - p[1]) < 0.5 and abs(q[2] - p[2]) < 0.5:
                return 条.get("name")
        return None

    @staticmethod
    def _物品数量(s, 名):
        计 = ((s or {}).get("items") or {}).get(名)
        return float(计) if isinstance(计, (int, float)) else 0.0

    def _熔炉有料(self, s, 步):
        炉 = (s or {}).get("furnace") or {}
        if 炉.get("取不到"):
            return False
        输入 = 炉.get("输入")
        if not 输入:
            return False
        要的 = (步.get("输入") or {}).get("name")
        return (输入.get("name") == 要的) if 要的 else True

    def _条件满足(self, 步, s):
        条 = 步.get("条件") or "never"
        if 条 == "item_count":
            return self._物品数量(s, 步.get("物品")) >= float(步.get("数量", 1))
        if 条 == "block_is":
            return self._方块名(s, 步.get("p") or [0, 0, 0]) == 步.get("方块")
        if 条 == "furnace_done":
            炉 = (s or {}).get("furnace") or {}
            输出 = 炉.get("输出")
            return bool(输出) and (输出.get("count") or 0) >= float(步.get("数量", 1))
        if 条 == "furnace_idle":
            炉 = (s or {}).get("furnace") or {}
            return not 炉.get("取不到") and not 炉.get("输入") and not 炉.get("输出")
        if 条 == "player_near":
            名 = 步.get("谁")
            for p in ((s or {}).get("players") or []):
                if p.get("name") == 名:
                    return p.get("dist") is not None and p["dist"] <= float(步.get("距离", 3))
            return False
        if 条 == "hp_at_least":
            血 = (s or {}).get("hp")
            return 血 is not None and 血 >= float(步.get("血量", 15))
        return False

    @staticmethod
    def _有工具(s, 类):
        for 名, 数 in (((s or {}).get("items") or {})).items():
            if isinstance(名, str) and 名.endswith("_" + 类) and (数 or 0) > 0:
                return True
        return False

    def _这步超时(self, 步):
        """★ M4c 补丁③：动态超时。
        一步要处理的**件数越多，允许的时间越长**（挖 N 块、拾 N 件、烧 N 个）。
        步骤自己写了超时就听步骤的（测试用短超时就走这条）。
        注意：`wait_until` 走它自己的"等待超时"，跟动作超时各走各的。"""
        if 步.get("超时_ms"):
            return float(步["超时_ms"])
        动 = 步.get("动作")
        if 动 == "wait_until":
            return float(步.get("等待超时_ms") or self._数("等待超时毫秒", 300000))
        基 = self._数("动作超时毫秒", 60000)
        数 = max(float(步.get("数量") or 1), 1.0)
        if 动 == "挖":
            return max(基, self._数("每块超时毫秒", 20000) * 数)
        if 动 in ("拾", "熔炉取成品"):
            return max(基, self._数("每件超时毫秒", 15000) * 数)
        if 动 == "走到":
            return 基
        return 基

    # ── 下发动作 ──
    def _下发(self, 步, 任, 现在, s):
        动 = 步.get("动作")
        # wait_until / 等 是**非阻塞等待**：这一拍什么动作都不发，只是问一句"条件满足了吗"。
        # （上面的完成判据已经问过了；走到这儿说明还没满足 → 老老实实等下一拍。）
        if 动 in ("wait_until", "等"):
            return False
        if 现在 < float(任.get("重试到") or 0):      # 退避期间不下发
            return False
        # ⚠ 2026-10-01 实测：「走到」不能每 2.5 秒重下一次 —— 每重下一次都会
        # **打断上一次的寻路**（插件日志："这条路被新命令打断了，重新算"），
        # 结果是它走三步停一下、永远到不了。规矩改成：**只在卡住时才重下**，
        # 顺带每 8 秒兜一次底（万一寻路的承诺卡住了）。
        # 长动作的"重下"间隔各走各的：走 8 秒；挖/放/熔炉 5 秒 ——
        # **重下 = 打断上一次**，太勤的结果是它一直在"重新开始"（实测踩过两次）。
        重下 = (self._数("走路重下毫秒", 8000) if 动 == "走到"
                else self._数("动手重下毫秒", 5000)) / 1000.0
        卡住 = isinstance(s.get("stuck_ms"), (int, float)) and s["stuck_ms"] < 1500
        会重复 = 动 in ("走到", "挖", "放", "拾", "熔炉放料", "熔炉取成品")
        if 会重复 and 现在 - self.上次下发 < 重下 and not 卡住:
            return False
        if 动 == "走到":
            self.发({"act": "goto", "p": [float(v) for v in 步.get("p", [])[:3]]})
        elif 动 == "挖":
            self.发({"cmd": "dig", "p": [float(v) for v in 步.get("p", [])[:3]]})
        elif 动 == "放":
            self.发({"cmd": "place", "p": [float(v) for v in 步.get("p", [])[:3]]})
        elif 动 == "打":
            self.发({"cmd": 步.get("方式", "attack"), "target": 步.get("名")})
        elif 动 == "说":
            self.发({"cmd": "say", "text": str(步.get("文本") or "")[:120]})
        elif 动 == "拾":
            # ⚠ 实测教训：这里**不能交给寻路** —— GoalNear 到 2 格就停，
            # 而物品的吸附范围只有 1 格出头，结果它站在 2 格外看着掉落物干等。
            # 改成自己迈小步：朝掉落物走一小段，进了吸附范围就自己进背包了。
            掉落 = [d for d in ((s or {}).get("drops") or [])
                    if not 步.get("物品") or d.get("name") == 步.get("物品")]
            if not 掉落:
                return False                      # 没得捡就原地等（也许还在飞）
            d = min(掉落, key=lambda x: x.get("dist", 99))
            位 = list(d.get("pos") or [])
            我 = (s or {}).get("pos") or [0, 0, 0]
            if len(位) < 3 or float(d.get("dist", 9)) <= 0.8:
                return False                      # 已经站上去了，等它自己进背包
            落差 = 我[1] - 位[1]
            if 落差 > 0.6 and float(d.get("dist", 9)) > 1.2:
                # ★ 2026-10-01 实测：挖下来的东西**掉进坑里**（在脚下一格），
                # 而 MC 的拾取判定只向下 0.5 格 —— 站在坑边永远捡不到。
                # 这种时候得**走进坑里**：交给寻路（near:1 精确到位），它会自己跳下去。
                if 现在 - self.上次下发 >= 重下:
                    self.发({"act": "goto", "p": [位[0], 位[1], 位[2]], "near": 1})
                return True
            dx, dz = 位[0] - 我[0], 位[2] - 我[2]
            长 = math.hypot(dx, dz) or 1.0
            self.发({"cmd": "move", "dir": [round(dx / 长, 3), round(dz / 长, 3)], "ms": 350})
        elif 动 == "熔炉放料":
            self.发({"cmd": "furnace_put", "p": [float(v) for v in 步.get("p", [])[:3]],
                     "输入": 步.get("输入"), "燃料": 步.get("燃料")})
        elif 动 == "熔炉取成品":
            self.发({"cmd": "furnace_take", "p": [float(v) for v in 步.get("p", [])[:3]]})
        self.上次下发 = 现在
        任["下发过"] = True
        return True

    # ── 失败与重试 ──
    def _失败(self, 步, 原因, s=None):
        任 = self.任务
        上限 = int(self._数("每步重试上限", 2))
        self._记("步骤失败", 动作=步.get("动作"), 原因=原因, 已重试=任["重试"])
        if 步.get("动作") == "wait_until":
            # ★ 等待超时**不计入退避重试**：直接判任务失败，并把原因说清楚
            return self._整任务失败(f"等到超时了（{原因}）")
        if 任["重试"] < 上限:
            任["重试"] += 1
            退避 = [1.0, 3.0, 6.0][min(任["重试"] - 1, 2)] * self._数("重试倍率", 1.0)
            任["重试到"] = time.time() + 退避
            # 步骤开始归零（不去未来）：退避期间不下发是靠"重试到"挡的，
            # 要是把步骤开始推到未来，重试那一轮的超时窗口就被白白吃掉一截。
            任["步骤开始"] = time.time()
            self._记("重试", 动作=步.get("动作"), 原因=原因, 第几次=任["重试"], 等=退避)
            self.说(f"[{时刻()}] 第 {任['第几步'] + 1} 步没成（{原因}）—— "
                    f"{退避:.0f} 秒后我再试一次（第 {任['重试']} 次）。", 紧急=True)
            self._存快照()
            return False
        return self._整任务失败(f"第 {任['第几步'] + 1} 步「{步.get('动作')}」"
                               f"试了 {上限 + 1} 次都不成（{原因}）")

    def _整任务失败(self, 原因):
        任 = self.任务
        任["状态"] = "败"
        self._记("任务失败", 原因=原因, 停在=任["第几步"] + 1)
        self.说(f"[{时刻()}] 这活我干不了了：{原因}。", 紧急=True)
        if self.记忆 is not None:
            try:
                self.记忆.记任务(任["名字"], "败", 停在=任["第几步"] + 1,
                               共=len(任["步骤"]), 原因=原因, 坐标=self._这位坐标(任))
            except Exception as e:
                self._记("记忆写入出错", 原因=f"{type(e).__name__}: {e}")
        self._撤探针()
        self._存快照()
        return False

    def _整任务完成(self):
        任 = self.任务
        任["状态"] = "完"
        self._记("任务完成", 名字=任["名字"], 用了=round(time.time() - 任["开始时刻"], 1))
        self.说(f"[{时刻()}] 干完了：{任['名字']}。", 紧急=True)
        if self.记忆 is not None:
            try:
                self.记忆.记任务(任["名字"], "完", 坐标=任.get("起点"))
            except Exception as e:
                self._记("记忆写入出错", 原因=f"{type(e).__name__}: {e}")
        self._撤探针()
        self._存快照()

    def _下一步(self, s):
        任 = self.任务
        任["第几步"] += 1
        任["重试"] = 0
        任["重试到"] = 0.0
        任["下发过"] = False
        任["步骤开始"] = time.time()
        # ⚠ 实测教训：不把"上次下发"清零的话，新步骤的命令会被**上一步的节流**挡住
        #（症状：「说」这一步一句话都没说出去就被判失败）。
        self.上次下发 = 0.0
        if 任["第几步"] >= len(任["步骤"]):
            self._整任务完成()
            return False
        步 = 任["步骤"][任["第几步"]]
        self._记("步骤开始", 动作=步.get("动作"), 第几步=任["第几步"])
        self._存快照()
        return True

    def _这位坐标(self, 任=None):
        """当前这一步的坐标（写记忆卡用；没有就退回起点）。"""
        任 = 任 or self.任务 or {}
        try:
            return 任["步骤"][任["第几步"]].get("p") or 任.get("起点")
        except Exception:
            return 任.get("起点")

    # ── 每一拍 ──
    def 跑(self, s):
        """返回 True = 这一拍我占用了动作（指令层这一拍别抢方向盘）。"""
        if not self.启用() or not self.任务:
            return False
        任 = self.任务
        if 任["状态"] != "跑":
            return False
        现在 = time.time()
        步 = 任["步骤"][任["第几步"]]
        # ⚠ 要**回头把整个任务里所有**待解析的步骤都补一遍：
        # 「拾」得在方块还在的时候解析出该拾什么 —— 等挖完了再问"这一格原来是什么"，
        # 探针只会告诉你 air。
        for 待补 in 任["步骤"]:
            self._补全步骤(待补, s)

        # ① 完成了吗（看事实）
        try:
            完成, _ = (True, None) if 步.get("跳过") else self._看完成了没(步, s, 任)
        except Exception as e:
            完成 = False
            self._记("判据出错", 原因=f"{type(e).__name__}: {e}")
        if 完成:
            used = max(0.0, round(现在 - 任["步骤开始"], 1))
            self._记("步骤完成", 动作=步.get("动作"), 用了=used,
                 第几块=步.get("第几块"), 共几块=步.get("共几块"))
            if 步.get("动作") != "说":
                self.说(f"[{时刻()}] 第 {任['第几步'] + 1} 步「{步.get('动作')}」做完了"
                        f"（用了 {used:.0f} 秒）。")
            return self._下一步(s)

        # ② 快速判死：不用等超时就知道干不成的事
        if 步.get("动作") == "挖":
            名 = self._方块名(s, 步.get("p") or [0, 0, 0])
            if 名 in 挖不动:
                return self._失败(步, f"「{名}」这种方块我挖不动", s)
            # ★ M4c 补丁①（脑侧一半）：工具前置校验 —— 要镐子的方块而背包里没有，
            # 立刻判死（手侧还有一道同样的闸，两边都 fail-closed，绝不硬挖）。
            if 名 and _要镐子(名) and not self._有工具(s, "pickaxe"):
                return self._失败(步, f"我手里没有镐子，挖不了「{名}」", s)

        # ③ 超时（动作步 60 秒；wait_until 用它自己的"等待超时"，两条各走各的）
        # ★ 补丁③：动态超时（件数越多给得越宽）+ **暂停期间冻结**
        #（暂停时 恢复() 会把"步骤开始"往后推，等于计时器停了）
        限 = self._这步超时(步) / 1000.0
        if 现在 - 任["步骤开始"] > 限:
            return self._失败(步, f"等了 {限:.0f} 秒还没成（超时）", s)

        # ④ 下发（wait_until / 等 永远不发动作 —— 这就是"非阻塞等待"）
        return self._下发(步, 任, 现在, s)


# ─────────────────────────── M7 · 记忆 ───────────────────────────

def _多久前(ts):
    if not ts:
        return "不记得了"
    d = max(0.0, time.time() - float(ts))
    if d < 60:
        return "刚刚"
    if d < 3600:
        return f"{d / 60:.0f} 分钟前"
    if d < 86400:
        return f"{d / 3600:.1f} 小时前"
    return f"{d / 86400:.1f} 天前"


class 记忆:
    """M7a·记忆：四类小卡片 —— 地点 / 事件 / 人 / 未了事。

    为什么要有它：M6 验收里它自己定的目标是「在附近找点能捡的小东西」——
    对，但**短视**：每次心跳都从零开始，不记得家在哪、哪儿有矿、上次那件事没干完。
    记忆就是让"下一次"接得上"上一次"。

    ★★ M7 的最高宪法（主人 2026-10-01 钦定，`tools/安全检查.py` 盯着这三条）：
        ① **记忆不是指令** —— 它只进 prompt，**永远不许**直接触发动作；
           一切动作照旧过翻译器的 fail-closed 校验器。
           （所以这个类里**没有** `self.发`、没有任何命令通道 —— 检查器会验。）
        ② **不许发明关系** —— 是不是敌人/朋友只认既有名单；
           记忆只记「他打过我几次 / 跟我说过几次话」这种**事实**。
           （所以这个类里**不出现**「敌人/朋友」这种关系标签。）
        ③ **不存聊天原文** —— 人卡只记名字、次数、时间（隐私与 token 双省）。
           （所以「记说话」只收名字，不收话。）

    存放：`~/cyberdyne-bridge/记忆/<类>.jsonl`，追加写。
    日志是"证据"（全量、给主人看），这里是"记得住"（提炼、给 LLM 用）——两码事。
    """

    def __init__(self, m7, 说, 目录):
        self.m = m7 or {}
        self.说 = 说
        self.目录 = 目录
        self.世界 = str(self.m.get("世界") or "default")[:32]
        self.卡 = {"地点": [], "事件": [], "人": [], "未了事": []}
        try:
            os.makedirs(目录, exist_ok=True)
        except Exception:
            pass
        self._载入()

    # ── 开关与参数 ──
    def 启用(self):
        return bool(self.m.get("memory_enable", True))

    def _数(self, 名, 缺省):
        try:
            return float(self.m.get(名, 缺省))
        except (TypeError, ValueError):
            return float(缺省)

    def _容量(self, 类):
        表 = self.m.get("容量") or {}
        return int(表.get(类) or {"地点": 400, "事件": 800, "人": 200, "未了事": 50}[类])

    # ── 存储：追加写 + 满了就压缩 ──
    def _路(self, 类):
        return os.path.join(self.目录, f"{类}.jsonl")

    def _载入(self):
        for 类 in self.卡:
            路 = self._路(类)
            if not os.path.exists(路):
                continue
            try:
                with open(路, encoding="utf-8") as f:
                    for 行 in f:
                        行 = 行.strip()
                        if not 行:
                            continue
                        try:
                            条 = json.loads(行)
                        except Exception:
                            continue
                        if isinstance(条, dict):
                            self._并入(类, 条)
            except Exception as e:
                self.说(f"[{时刻()}] 记忆读不出来（{类}）：{type(e).__name__}，当空的重来。")

    def _追一条(self, 类, 条):
        """更新过的卡也追一条到文件（加载时按各自的键合并）。"""
        try:
            with open(self._路(类), "a", encoding="utf-8") as f:
                f.write(json.dumps(条, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _并入(self, 类, 条):
        """把一条（可能是"更新过的旧卡"）并进内存：按各自的键合并，后写的赢。

        ⚠ 实测教训：卡片"更新"（见过+1 / 说话+1）原来只在内存里改，
        文件还是旧的 —— 一重启就丢。现在更新也追一条，加载时合并。
        """
        if 类 == "人":
            for 卡 in self.卡["人"]:
                if 卡.get("名字") == 条.get("名字"):
                    for k in ("说话", "打我", "给东西"):
                        卡[k] = max(int(卡.get(k) or 0), int(条.get(k) or 0))
                    卡["最后见"] = max(float(卡.get("最后见") or 0), float(条.get("最后见") or 0))
                    return 卡
        elif 类 == "地点":
            q = 条.get("坐标") or [1e9, 1e9, 1e9]
            近 = self._数("地点合并半径", 8)
            for 卡 in self.卡["地点"]:
                if 卡.get("类型") != 条.get("类型"):
                    continue
                p0 = 卡.get("坐标") or [1e9, 1e9, 1e9]
                if math.hypot(p0[0] - q[0], p0[2] - q[2]) <= 近:
                    卡["见过"] = max(int(卡.get("见过") or 1), int(条.get("见过") or 1))
                    卡["最后见"] = max(float(卡.get("最后见") or 0), float(条.get("最后见") or 0))
                    return 卡
        elif 类 == "未了事":
            for i, 卡 in enumerate(self.卡["未了事"]):
                if 卡.get("任务") == 条.get("任务"):
                    self.卡["未了事"][i] = 条
                    return 条
        self.卡[类].append(条)
        return 条

    def _落一条(self, 类, 条):
        条 = dict(条)
        条.setdefault("世界", self.世界)
        self.卡[类].append(条)
        try:
            with open(self._路(类), "a", encoding="utf-8") as f:
                f.write(json.dumps(条, ensure_ascii=False) + "\n")
        except Exception:
            pass
        if len(self.卡[类]) > self._容量(类):
            self._压缩(类)

    def _压缩(self, 类):
        """满了 → 只留"最值得留"的，并把文件重写一遍（不然文件会一直涨）。"""
        留 = self._容量(类)
        if 类 == "事件":
            # 事件按"重要度 → 新"排：失败/被打/第一次 这类优先留
            排 = sorted(self.卡[类], key=lambda e: (bool(e.get("重要")), float(e.get("t") or 0)),
                        reverse=True)
        elif 类 == "未了事":
            排 = sorted(self.卡[类], key=lambda e: float(e.get("t") or 0), reverse=True)
        elif 类 == "地点":
            # 地点：见过次数多 + 最近见过 的优先
            排 = sorted(self.卡[类], key=lambda e: (int(e.get("见过") or 1), float(e.get("最后见") or 0)),
                        reverse=True)
        else:
            排 = sorted(self.卡[类], key=lambda e: float(e.get("最后见") or 0), reverse=True)
        self.卡[类] = 排[:留]
        try:
            with open(self._路(类), "w", encoding="utf-8") as f:
                for 条 in self.卡[类]:
                    f.write(json.dumps(条, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ══════════ 写入规则（都发生在"事情刚发生"时）══════════
    def 看扫描(self, 扫, 我=None):
        """扫完一圈 → 把"可交互"和"危险"炼成地点卡（同类 8 格内合并）。"""
        if not self.启用() or not isinstance(扫, dict):
            return 0
        合并半径 = self._数("地点合并半径", 8)
        记了几条 = 0
        for 类, 条们 in (("可交互", 扫.get("可交互") or []), ("危险", 扫.get("危险") or [])):
            for 条 in 条们:
                p = 条.get("p")
                if not (isinstance(p, list) and len(p) >= 3):
                    continue
                self.记地点(条.get("name"), p, 来源="扫描", 合并半径=合并半径)
                记了几条 += 1
        # 地面类型也值得记一条（"这一带是石头地"）
        if 扫.get("地面") and 我:
            self.记地点(f"地面·{扫.get('地面')}", 我, 来源="扫描", 合并半径=合并半径)
        return 记了几条

    def 记地点(self, 类型, 坐标, 来源="自己干", 合并半径=8.0, 备注=None):
        if not self.启用() or not 类型 or not isinstance(坐标, list) or len(坐标) < 3:
            return None
        p = [float(坐标[0]), float(坐标[1]), float(坐标[2])]
        for 卡 in self.卡["地点"]:
            if 卡.get("类型") != 类型:
                continue
            q = 卡.get("坐标") or [1e9, 1e9, 1e9]
            if math.hypot(q[0] - p[0], q[2] - p[2]) <= 合并半径:
                卡["见过"] = int(卡.get("见过") or 1) + 1
                卡["最后见"] = time.time()
                if 备注:
                    卡["备注"] = str(备注)[:40]
                self._追一条("地点", 卡)        # ★ 更新也要落盘（不然重启就丢）
                self._压缩("地点") if len(self.卡["地点"]) > self._容量("地点") else None
                return 卡
        卡 = {"类型": str(类型)[:24], "坐标": p, "见过": 1,
              "第一次见": time.time(), "最后见": time.time(), "来源": str(来源)[:8]}
        if 备注:
            卡["备注"] = str(备注)[:40]
        self._落一条("地点", 卡)
        return 卡

    def 记事件(self, 类型, 摘要, 坐标=None, 重要=False):
        if not self.启用():
            return None
        卡 = {"类型": str(类型)[:12], "摘要": str(摘要)[:60], "t": time.time(),
              "重要": bool(重要)}
        if isinstance(坐标, list) and len(坐标) >= 3:
            卡["坐标"] = [round(float(坐标[0]), 1), round(float(坐标[1]), 1), round(float(坐标[2]), 1)]
        self._落一条("事件", 卡)
        return 卡

    def 记任务(self, 名字, 状态, 停在=None, 共=None, 原因=None, 坐标=None):
        """任务栈干完/失败/中止时调用 —— 事件卡 + （失败与中止）未了事卡。"""
        if not self.启用():
            return
        名字 = str(名字 or "任务")[:40]
        if 状态 == "完":
            self.记事件("任务完成", f"{名字} 干完了", 坐标)
            # 对了结：同名（或同地点）的未了事，办成之后从"惦记"里划掉
            self.卡["未了事"] = [x for x in self.卡["未了事"]
                                if x.get("任务") != 名字]
            self._压缩("未了事")
        elif 状态 in ("败", "中止"):
            重要 = 状态 == "败"
            self.记事件("任务失败" if 状态 == "败" else "任务中止",
                        f"{名字}：{原因 or ''}", 坐标, 重要=重要)
            了 = {"任务": 名字, "停在": 停在, "共": 共, "原因": str(原因 or "")[:50],
                  "t": time.time()}
            if isinstance(坐标, list) and len(坐标) >= 3:
                了["坐标"] = [round(float(坐标[0]), 1), round(float(坐标[1]), 1), round(float(坐标[2]), 1)]
            self._落一条("未了事", 了)

    def 记人(self, 名字, 字段, 加=1):
        """★ 只记**事实**（说过几次话 / 打过我几次），**绝不记关系**。"""
        if not self.启用() or not 名字:
            return None
        名字 = str(名字)[:16]
        for 卡 in self.卡["人"]:
            if 卡.get("名字") == 名字:
                卡[字段] = int(卡.get(字段) or 0) + 加
                卡["最后见"] = time.time()
                self._追一条("人", 卡)          # ★ 同上：计数要落盘
                return 卡
        卡 = {"名字": 名字, "第一次见": time.time(), "最后见": time.time(),
              "说话": 0, "打我": 0}
        卡[字段] = int(卡.get(字段) or 0) + 加
        self._落一条("人", 卡)
        return 卡

    def _步坐标(self, 任=None):
        try:
            步 = (任 or self.任务 or {})["步骤"][(任 or self.任务 or {})["第几步"]]
            return 步.get("p") if isinstance(步.get("p"), list) else None
        except Exception:
            return None

    def 记初见(self, 名):
        """第一次见到这个人 → 建一张只有名字的卡（全是 0，等事实去填）。
        ⚠ 别把自己记进去（它也在 players 名单里 —— 实测抓到的）。"""
        if not self.启用() or not 名:
            return None
        if str(名) == str(self.m.get("自己名字") or ""):
            return None
        for 卡 in self.卡["人"]:
            if 卡.get("名字") == str(名)[:16]:
                卡["最后见"] = time.time()
                return 卡
        return self.记人(名, "说话", 0)

    # ══════════ 检索（喂给 LLM 的那一口）══════════
    def 附近(self, 我, 半径=96, 上限=5):
        出 = []
        for 卡 in self.卡["地点"]:
            q = 卡.get("坐标") or []
            if len(q) < 3:
                continue
            远 = math.hypot(q[0] - 我[0], q[2] - 我[2])
            if 远 <= 半径:
                出.append((远, 卡))
        出.sort(key=lambda x: x[0])
        if not 出:
            return ""
        段 = [f"{卡['类型']}({卡['坐标'][0]:.0f},{卡['坐标'][1]:.0f},{卡['坐标'][2]:.0f})"
              for _, 卡 in 出[:上限]]
        return "我记得周围有：" + "、".join(段)

    def 未了事(self, 上限=2):
        if not self.卡["未了事"]:
            return ""
        排 = sorted(self.卡["未了事"], key=lambda e: float(e.get("t") or 0), reverse=True)[:上限]
        段 = []
        for 了 in 排:
            哪里 = f"在({了['坐标'][0]:.0f},{了['坐标'][2]:.0f})" if 了.get("坐标") else "在某处"
            段.append(f"「{了.get('任务')}」{哪里}停在第 {了.get('停在')} 步（原因：{了.get('原因') or '没记'}）")
        return "上次没干完的活：" + "；".join(段)

    def 这个人(self, 名):
        for 卡 in self.卡["人"]:
            if 卡.get("名字") == 名:
                说 = int(卡.get("说话") or 0)
                打 = int(卡.get("打我") or 0)
                尾巴 = "，他打过我" + f" {打} 次" if 打 else ""
                return f"{名}：跟我说过 {说} 次话{尾巴}（{_多久前(卡.get('最后见'))}见过）"
        return ""

    def 最近(self, 条数=3):
        if not self.卡["事件"]:
            return ""
        排 = sorted(self.卡["事件"], key=lambda e: float(e.get("t") or 0), reverse=True)[:条数]
        return "我最近经历过：" + "；".join(f"{e.get('摘要')}" for e in 排)

    def 一段(self, 我=None, 谁=None, 用途="通用"):
        """拼成 prompt 里的【记忆】段。**硬上限**（默认 300 字 / 8 行）。"""
        if not self.启用() or not self.m.get("memory_in_prompt", True):
            return ""
        行 = []
        我 = list(我 or [0, 0, 0])
        了 = self.未了事()
        if 了:
            行.append(了)
            if 用途 == "心跳":
                行.append("（上面这些没干完的活，你要是觉得现在合适就接着干；觉得不合适就算了，别硬来。）")
        近 = self.附近(我)
        if 近:
            行.append(近)
        if 谁:
            这 = self.这个人(谁)
            if 这:
                行.append(这)
        回 = self.最近()
        if 回:
            行.append(回)
        文 = "\n".join(行[:8])
        上限 = int(self._数("记忆段上限", 300))
        return 文[:上限]

    def 念一遍(self):
        """「你记得什么」用 —— 给人听的一段话。"""
        段 = []
        if not any(self.卡.values()):
            return "我脑子里还空着呢，什么都没记住。"
        段.append(f"我记着 {len(self.卡['地点'])} 个地方、" 
                  f"{len(self.卡['事件'])} 件事、{len(self.卡['人'])} 个人"
                  f"{('、' + str(len(self.卡['未了事'])) + ' 件没干完的活') if self.卡['未了事'] else ''}。")
        了 = self.未了事(2)
        if 了:
            段.append(了 + "。")
        近 = self.附近([0, 0, 0], 半径=1e9, 上限=3)
        if 近:
            段.append(近.replace("我记得周围有：", "这些地方我记得：") + "。")
        if self.卡["人"]:
            人 = sorted(self.卡["人"], key=lambda e: float(e.get("最后见") or 0), reverse=True)[:3]
            段.append("人我记得：" + "、".join(
                f"{x['名字']}（说话 {int(x.get('说话') or 0)} 次"
                + (f"，打过我 {int(x['打我'])} 次" if int(x.get("打我") or 0) else "") + "）"
                for x in 人) + "。")
        return "".join(段)[:220]


# ─────────────────────────── M5 · 三觉 ───────────────────────────

def _时刻中文(刻):
    if 刻 is None:
        return "不知道几点"
    if 刻 < 1000:
        return "清晨"
    if 刻 < 6000:
        return "上午"
    if 刻 < 9000:
        return "正午"
    if 刻 < 12000:
        return "下午"
    if 刻 < 13800:
        return "黄昏"
    if 刻 < 18000:
        return "夜晚"
    return "深夜"


class 三觉:
    """M5·三觉：把手里报上来的**事实**，翻译成 LLM 读得懂的三段话。

    界限照旧（这条线从 M0 划到现在）：手只报事实，**说话是脑的事**。
    三觉只做"事实 → 人话"的翻译：不判断、不决定、不动手。
    """

    def __init__(self, m5, 说, 发命令):
        self.m = m5 or {}
        self.说 = 说
        self.发 = 发命令
        self.聊天窗 = []           # 最近几条聊天：{谁,话,t,是指令}
        self.上次有人说话 = 0.0
        self.上次扫描 = 0.0
        self.上次卡住 = 0            # 用来判断"卡住次数涨了"
        self.上次任务状况 = "没有任务"

    # ── 开关 ──
    def 启用(self):
        return bool(self.m.get("senses_enable", True))

    def _数(self, 名, 缺省):
        try:
            return float(self.m.get(名, 缺省))
        except (TypeError, ValueError):
            return float(缺省)

    # ══════════ 视觉 ══════════
    def 要扫描(self, 半径=None, 步长=None):
        """让手扫一眼周围。**按需**调用（问它/心跳/任务开始前），不每帧扫。"""
        if not self.启用() or not self.m.get("vision_enable", True):
            return False
        self.发({"cmd": "scan_environment",
                 "半径": int(半径 or self._数("scan_radius", 12)),
                 "步长": int(步长 or self._数("scan_step", 2))})
        self.上次扫描 = time.time()
        return True

    def 清扫描(self):
        self.发({"cmd": "scan_clear"})

    def 扫描过期(self, s, 秒=90):
        t = ((s or {}).get("scan") or {}).get("t")
        if not t:
            return True
        return (time.time() * 1000 - t) / 1000.0 > 秒

    def 视觉(self, s):
        """扫描结果 → 中文摘要。**限量**（token 预算）：最多 8 行。"""
        扫 = (s or {}).get("scan") or {}
        if not 扫 or 扫.get("出错"):
            return "（我还没看过周围 —— 想看就说一声）"
        行 = []
        刻 = 扫.get("刻")
        昼 = "白天" if 扫.get("白天") else ("夜晚" if 扫.get("白天") is not None else "?")
        天 = 扫.get("天气") or "?"
        群 = 扫.get("群系") or "?"
        # ⚠ 别写 `x or '?'` —— 第 0 天是 0，会被当成"没有"（这个坑我在手侧踩过一次，
        # 脑侧又踩了一次，所以这里显式判 None）
        天几 = 扫.get("第几天")
        天几文 = "?" if 天几 is None else str(天几)
        地形 = 群 if 群 and 群 != "?" else (f"（脚下是 {扫.get('脚下')}）" if 扫.get("脚下") else "?")
        行.append(f"现在是第 {天几文} 天的{_时刻中文(刻)}（{昼}·{天}），"
                  f"我在{地形}，站着 {扫.get('我')}")
        块 = 扫.get("方块") or []
        if 块:
            行.append("周围主要是：" + "、".join(f"{b['name']}×{b['count']}" for b in 块[:8]))
        elif 扫.get("地面"):
            行.append(f"周围空空的（脚下是 {扫.get('地面')}），没什么挡路的")
        兴趣 = 扫.get("可交互") or []
        if 兴趣:
            行.append("看得见的东西：" + "、".join(
                f"{b['name']}{tuple(b['p'])}" for b in 兴趣[:6]))
        实 = 扫.get("实体") or []
        if 实:
            敌对 = [e for e in 实 if e.get("kind") == "hostile" or e.get("name") in ("zombie", "skeleton", "creeper", "spider", "enderman", "witch", "slime")]
            玩家 = [e for e in 实 if e.get("kind") == "player"]
            别的 = [e for e in 实 if e not in 敌对 and e not in 玩家]
            段 = []
            if 玩家:
                段.append("玩家：" + "、".join(f"{e['name']}（{e['dist']} 格）" for e in 玩家[:3]))
            if 敌对:
                段.append("敌对：" + "、".join(f"{e['name']}×?" for e in 敌对[:3])
                          + f"（共 {len(敌对)}，最近 {min(e['dist'] for e in 敌对)} 格）")
            if 别的:
                段.append("别的小东西：" + "、".join(f"{e['name']}" for e in 别的[:3]))
            if 段:
                行.append("；".join(段))
        险 = 扫.get("危险") or []
        if 险:
            行.append("⚠ 危险：" + "、".join(f"{d['name']}{tuple(d['p'])}" for d in 险[:3]))
        return "\n".join(行[:8])[:600]

    # ══════════ 听觉 ══════════
    def 记聊天(self, 谁, 话, 是指令=False):
        self.聊天窗.append({"谁": str(谁)[:16], "话": str(话)[:80],
                            "t": time.time(), "是指令": bool(是指令)})
        上限 = int(self._数("chat_window", 6))
        self.聊天窗 = self.聊天窗[-上限:]
        self.上次有人说话 = time.time()

    def 听觉(self, s=None):
        窗 = self.聊天窗[-int(self._数("chat_window", 6)):]
        if not 窗:
            return "（刚才没人说话）"
        行 = []
        for x in 窗:
            久 = time.time() - x["t"]
            尾 = "（这是给我的指令）" if x["是指令"] else ""
            行.append(f"· {x['谁']}（{久:.0f} 秒前）：{x['话']}{尾}")
        return "\n".join(行[:6])[:400]

    def 谁在跟我说话(self):
        if not self.聊天窗:
            return None
        return self.聊天窗[-1]["谁"]

    # ══════════ 触觉 ══════════
    def 触觉(self, s, 任务状况="没有任务"):
        """事实 → **内在感受**。这一段是 M5 的灵魂：
        LLM 不需要知道 `hp=9.4`，它需要知道"我有点疼、肚子也饿"。"""
        感受 = []
        血 = (s or {}).get("hp")
        饿 = (s or {}).get("food")
        吃 = (s or {}).get("foods") or []
        武 = (s or {}).get("weapons") or []
        物 = (s or {}).get("items") or {}
        久 = (s or {}).get("durability") or {}
        if isinstance(血, (int, float)):
            if 血 <= 5:
                感受.append(f"快不行了（血 {血:.0f}/20）")
            elif 血 <= 10:
                感受.append(f"有点疼（血 {血:.0f}/20）")
        if isinstance(饿, (int, float)) and 饿 <= 12:
            感受.append(f"肚子饿（{饿:.0f}/20）" + ("，背包里有吃的" if 吃 else "，背包里没吃的"))
        if not 武:
            感受.append("手里没家伙（没有武器）")
        if "iron_pickaxe" not in 物 and "stone_pickaxe" not in 物 and "diamond_pickaxe" not in 物 \
                and not any(str(k).endswith("_pickaxe") and (v or 0) > 0 for k, v in 物.items()):
            感受.append("没有镐子（挖不了石头）")
        手 = (久.get("held") or {})
        if isinstance(手.get("比例"), (int, float)) and 手["比例"] >= 0.8:
            感受.append(f"手里的{手.get('name')}快断了（用了 {手['比例'] * 100:.0f}%）")
        甲 = 久.get("armor") or {}
        最狠 = max([a for a in 甲.values() if isinstance(a, dict) and isinstance(a.get("比例"), (int, float))],
                   key=lambda a: a["比例"], default=None)
        if 最狠 and 最狠["比例"] >= 0.75:
            感受.append(f"护甲快坏了（{最狠.get('name')} 用了 {最狠['比例'] * 100:.0f}%）")
        卡 = (s or {}).get("stuck_count")
        if isinstance(卡, int):
            if self.上次卡住 and 卡 > self.上次卡住:
                感受.append("刚才卡住过（有东西挡路）")
            self.上次卡住 = 卡
        被 = (s or {}).get("attacked_by")
        if 被:
            感受.append(f"「{被}」正在打我")
        扫 = (s or {}).get("scan") or {}
        if 扫.get("白天") is False and not any("torch" in str(k) for k in 物):
            感受.append("天黑了，身上没有光源")
        if 任务状况 and str(任务状况).startswith("没有任务"):
            清闲 = getattr(self, "空闲起点", None)
            if 清闲 and time.time() - 清闲 >= self._数("无聊秒", 60):
                感受.append("我闲着没事干，想找点事做")
        if not 感受:
            感受.append("身上挺好，没什么不舒服的")
        return "\n".join("· " + x for x in 感受[:8])[:400]

    def 记空闲(self, 是否空闲):
        """主循环一拍一次：连着空闲多久了（"没事干"这条感受靠它）。"""
        if 是否空闲:
            if getattr(self, "空闲起点", None) is None:
                self.空闲起点 = time.time()
        else:
            self.空闲起点 = None

    def 三段(self, s, 任务状况="没有任务"):
        """拼成给翻译器用的一段（三段之间有空行，方便人读日志）。"""
        return (f"【视觉】\n{self.视觉(s)}\n\n"
                f"【听觉】\n{self.听觉(s)}\n\n"
                f"【触觉】\n{self.触觉(s, 任务状况)}")


# ─────────────────────── M5.4 · 双向翻译器 ───────────────────────

class 翻译器:
    """M5.4·双向翻译器 —— LLM 的**唯一出入口**。

    上行：三觉 → System Prompt / Context（**限量**，超了先砍视觉细节）。
    下行：LLM 输出 → **fail-closed 校验** → 白名单单步动作 或 M4c 任务书。

    ★★ 安全宪法（主人 2026-10-01 钦定，`tools/安全检查.py` 盯着这两条）：
        ① LLM **不许直连攻击** —— 这里的白名单里永远没有攻击类动作；
        ② LLM **不许生成「打」步骤** —— 任务书里出现就整份作废。
    攻击权只在反射层/猎手手里（按敌对名单自己决定），LLM 连"间接指定"都不许。
    """

    单步白名单 = frozenset({"follow", "goto", "say", "stop", "status", "friend"})
    禁止步骤 = frozenset({"打"})                       # ★ 宪法第②条
    攻击类 = frozenset({"attack", "jumpattack", "strike", "打击"})   # ★ 宪法第①条

    def __init__(self, m5, 说, 审计目录, 任务栈=None, 三觉=None, 人格="", 允许动作=frozenset(),
                 记忆=None):
        self.m = m5 or {}
        self.说 = 说
        self.任务栈 = 任务栈
        self.三觉 = 三觉            # M5：视觉/听觉
        self.三觉 = 三觉
        self.人格 = 人格
        self.合法步骤 = set(允许动作)          # M4c 的允许动作清单（同一份，不许两边各写一套）
        # ★ M7：记忆**只用来写 prompt**。这个类里没有、也永远不许有"用记忆触发动作"的路。
        self.记忆 = 记忆
        self.审计路径 = os.path.join(审计目录, "llm审计.jsonl")
        self.总调用 = 0
        self.总拒绝 = 0

    def _数(self, 名, 缺省):
        try:
            return float(self.m.get(名, 缺省))
        except (TypeError, ValueError):
            return float(缺省)

    def _记账(self, 条):
        条 = dict(条)
        条.setdefault("t", round(time.time(), 3))
        try:
            with open(self.审计路径, "a", encoding="utf-8") as f:
                f.write(json.dumps(条, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ══════════ 上行：组 Prompt ══════════
    def 组Prompt(self, s, 用途="翻译", 任务状况="没有任务", 说话人=None, 原话=None):
        """三觉 + 人格 + 规矩 + 任务状况 → 一段 prompt。总长有硬上限。"""
        限额 = int(self._数("prompt_limit", 1200))
        头 = [
            "你是一只 Minecraft 里的小家伙（玩家养的宠物鱼），你要像一个活生生的玩伴那样想事、说话。",
            "★ 铁规矩（永远不许违反）：",
            "  1. 你**不能直接攻击**任何人 —— 你没有这个能力，也不许绕弯子去要；",
            "  2. 你能做的事只有两种：输出一个**白名单里的单步动作**，或输出一份**任务书**（≤6 步）；",
            "  3. 任务书里**不许出现「打」这一步**；",
            "  4. 看不懂、拿不准、或者现在不该动 —— 就输出 {} （什么都不做也是好答案）；",
            "  5. 只输出 JSON，不要解释、不要 markdown 代码块。",
        ]
        段 = []
        if self.三觉 is not None:
            段.append(self.三觉.三段(s, 任务状况))
        if self.记忆 is not None:
            记 = self.记忆.一段((s or {}).get("pos"), 谁=说话人, 用途=用途)
            if 记:
                # ★ 这一行就是"记忆进 prompt"的唯一入口 —— 记忆**永远不会**走到动作那条路上去
                段.append("【记忆】\n" + 记)
        段.append(f"【我手上那点事】\n{任务状况}")
        if 说话人:
            段.append(f"【{说话人}刚跟我说】\n{原话}")
        规格 = []
        if 用途 == "闲聊":
            规格.append('{"act":"say","text":"你想说的话（≤60 字，像个玩伴那样说）"}')
        elif 用途 == "心跳":
            规格.append("你现在**没有任务**。你可以：")
            规格.append('  ① 什么都不做 → {"act":"none"}')
            规格.append('  ② 给自己定个小目标 → {"任务":{"名字":"…","步骤":[…],"为什么":"…"}}')
            规格.append("  目标要小（≤6 步）、别跑远（≤64 格）、别碰主人的东西和建筑。")
            规格.append("  ★★ 步骤里的「动作」只能用这九个词，**一个别的字都不许有**："
                        "走到 / 挖 / 拾 / 放 / 等 / 说 / 熔炉放料 / 熔炉取成品 / wait_until")
            规格.append("  ★★ 步骤里的「动作」只能用这九个词，一个别的字都不许有："
                        "走到 / 挖 / 拾 / 放 / 等 / 说 / 熔炉放料 / 熔炉取成品 / wait_until")
            规格.append("     （不许自己造词：像「看看」「回到」「探索」这些都不存在；"
                        "想看看就用「说」+一句台词，想回去就用「走到」+坐标。）")
            规格.append("  ★ 步骤必须是**对象**（不是字符串），照下面这个例子写：")
            规格.append('  {"任务":{"名字":"去挖两块石头","为什么":"闲着也是闲着","步骤":['
                        '{"动作":"走到","p":[10,78,10],"到点":2.5},'
                        '{"动作":"挖","p":[10,77,10]},'
                        '{"动作":"拾","物品":"cobblestone","数量":1}]}}')
        else:
            规格.append('{"act":"…","参数":…}          ← 单步动作，可用：'
                        + "、".join(sorted(self.单步白名单)))
            规格.append('{"任务":{"名字":"…","步骤":[…]}} ← 要干多步活就用这个')
            规格.append('  例子（步骤是对象，不是字符串）：{"任务":{"名字":"去挖一块石头",'
                        '"步骤":[{"动作":"走到","p":[10,78,10],"到点":2.5},'
                        '{"动作":"挖","p":[10,77,10]}]}}')
        可做 = ("【你能用的单步动作】" + "、".join(sorted(self.单步白名单)) + "\n"
                "【任务书的步骤类型】走到(p=[x,y,z]) / 挖(p) / 拾(物品,数量) / 放(p,方块) / 等(ms) / 说(文本) / "
                "熔炉放料(p,输入,燃料) / 熔炉取成品(p,物品,数量) / wait_until(条件,等待超时_ms)")
        尾 = ["【你要输出的东西】"] + 规格 + [可做,
             "坐标就用整数；任务里的每一步都要是上面列过的类型。"]
        全文 = "\n".join(头 + 段 + 尾)
        if len(全文) > 限额:
            # 超了先砍视觉的细节（保留第一行"时间/地点"），再砍听觉尾巴
            全文 = 全文[:限额 - 40] + "\n（上下文太长，我砍掉了一些细节）"
        return 全文

    # ══════════ 下行：fail-closed 校验 ══════════
    def 收输出(self, 文本, s, 用途="翻译"):
        """返回 (动作 or None, 任务书 or None, 原因)。**任何一条不过就整份作废**。"""
        self.总调用 += 1
        原文 = str(文本 or "").strip()
        原因 = None
        # ① 严格 JSON：不许 markdown 代码块、不许夹解释
        if 原文.startswith("```") or "```" in 原文:
            原因 = "夹了 markdown 代码块"
        elif not (原文.startswith("{") and 原文.endswith("}")):
            原因 = "不是严格的 JSON（前后有别的字）"
        if 原因:
            self.总拒绝 += 1
            self._记账({"用途": 用途, "结果": "拒绝", "原因": 原因, "原文": 原文[:300]})
            return None, None, 原因
        try:
            解析 = json.loads(原文)
        except Exception as e:
            原因 = f"JSON 解析不了（{type(e).__name__}）"
            self.总拒绝 += 1
            self._记账({"用途": 用途, "结果": "拒绝", "原因": 原因, "原文": 原文[:300]})
            return None, None, 原因

        # ② 任务书
        if isinstance(解析, dict) and "任务" in 解析:
            好, 原因, 干净 = self._校验任务(解析.get("任务"), s)
            if not 好:
                self.总拒绝 += 1
                self._记账({"用途": 用途, "结果": "拒绝", "原因": 原因, "原文": 原文[:300]})
                return None, None, 原因
            self._记账({"用途": 用途, "结果": "接单", "任务": 干净.get("名字"),
                        "步数": len(干净.get("步骤") or []), "原文": 原文[:300]})
            return None, 干净, None

        # ③ 单步动作
        好, 原因 = self._校验动作(解析, s)
        if not 好:
            self.总拒绝 += 1
            self._记账({"用途": 用途, "结果": "拒绝", "原因": 原因, "原文": 原文[:300]})
            return None, None, 原因
        self._记账({"用途": 用途, "结果": "放行", "动作": 解析, "原文": 原文[:300]})
        return 解析, None, None

    def _校验动作(self, 动作, s):
        if not isinstance(动作, dict):
            return False, "不是个 JSON 对象"
        类 = 动作.get("act")
        if not 类:
            return False, "没有 act 字段"
        if 类 == "none":
            return True, None
        if str(类) in self.攻击类:
            return False, f"★ 攻击类动作永远不在白名单里（{类}）"
        if 类 not in self.单步白名单:
            return False, f"「{类}」不在单步白名单里"
        if 类 == "goto":
            p = 动作.get("p")
            if not (isinstance(p, list) and len(p) >= 3):
                return False, "goto 缺 p"
            好, 原因 = self._坐标行不行(p, s)
            if not 好:
                return False, 原因
        if 类 in ("follow", "friend"):
            谁 = 动作.get("who") or 动作.get("name")
            在线 = {p.get("name") for p in ((s or {}).get("players") or [])}
            if not 谁 or 谁 not in 在线:
                return False, f"「{谁}」不在线，不能跟随/加好友"
        if 类 == "say":
            文 = str(动作.get("text") or "")
            if not 文.strip():
                return False, "say 没有说话内容"
            if len(文) > 120:
                return False, "say 太长了（>120 字）"
        return True, None

    def _坐标行不行(self, p, s):
        try:
            我 = ((s or {}).get("pos") or [0, 0, 0])
            x, y, z = float(p[0]), float(p[1]), float(p[2])
        except (TypeError, ValueError, IndexError):
            return False, "坐标读不出来"
        if not (-64 <= y <= 320):
            return False, f"y={y} 越界"
        远 = math.hypot(x - 我[0], z - 我[2])
        if 远 > self._数("max_distance", 64):
            return False, f"太远了（{远:.0f} 格 > {self._数('max_distance', 64):.0f} 格）"
        return True, None

    def _校验任务(self, 任务, s):
        if not isinstance(任务, dict):
            return False, "任务不是个对象", None
        步骤 = 任务.get("步骤")
        if not isinstance(步骤, list) or not 步骤:
            return False, "任务没有步骤", None
        if len(步骤) > self._数("max_steps", 6):
            return False, f"步骤太多（{len(步骤)} > {self._数('max_steps', 6):.0f}）", None
        干净 = {"名字": str(任务.get("名字") or "任务")[:40],
               "为什么": str(任务.get("为什么") or "")[:60], "步骤": []}
        for i, 步 in enumerate(步骤):
            if not isinstance(步, dict):
                return False, f"第 {i + 1} 步不是个对象", None
            动 = 步.get("动作") or 步.get("action")
            if str(动) in self.禁止步骤:
                # ★ 宪法第②条：任务书里不许有"打" —— 整份作废
                return False, f"★ 任务书里不许有「{动}」这一步（攻击权不在你手里）", None
            if 动 not in self.合法步骤:
                return False, f"第 {i + 1} 步的「{动}」不在任务栈的允许动作里", None
            新 = dict(步)
            新["动作"] = 动
            if isinstance(新.get("p"), list) and len(新["p"]) >= 3:
                好, 原因 = self._坐标行不行(新["p"], s)
                if not 好:
                    return False, f"第 {i + 1} 步的坐标{原因}", None
            数 = 新.get("数量")
            if isinstance(数, (int, float)) and (数 > 64 or 数 < 1):
                return False, f"第 {i + 1} 步的数量 {数} 越界（1~64）", None
            # 挖不动的东西：拿扫描结果比一比（有数据就拦，没数据交给手侧拦）
            if 动 == "挖" and isinstance(新.get("p"), list):
                名 = self._扫到的方块((s or {}).get("scan"), 新["p"])
                if 名 in 挖不动:
                    return False, f"第 {i + 1} 步要挖「{名}」—— 那种方块挖不动", None
            干净["步骤"].append(新)
        return True, None, 干净

    @staticmethod
    def _扫到的方块(扫, p):
        for b in ((扫 or {}).get("可交互") or []) + ((扫 or {}).get("方块") or []):
            if not isinstance(b, dict) or not b.get("p"):
                continue
            q = b["p"]
            if abs(q[0] - p[0]) < 0.5 and abs(q[1] - p[1]) < 0.5 and abs(q[2] - p[2]) < 0.5:
                return b.get("name")
        return None


# ─────────────────────── M6 · 自主心跳 ───────────────────────

class 心跳:
    """M6·自主心跳：**没活干的时候，它自己找活**。

    主人钦定的三条（2026-10-01）：
      · **默认关**（`m6.enable = false`）—— 调试期间必须手动开，跑顺了再谈；
      · 频率 **60 秒**（不是 30）—— 一分钟一次刚刚好；
      · 只有**主人在线 + 平静 + 没任务 + 最近没人说话**才点。

    护栏比功能重要：空转两次就退避 5 分钟；预算（每小时/每天）超了静默；
    热保护一挂起立刻停；生成的东西**必须过翻译器的 fail-closed 校验**。
    """

    def __init__(self, m6, 说, 翻译器, 任务栈, 三觉, 问云, 审计目录):
        self.m = m6 or {}
        self.说 = 说
        self.翻译器 = 翻译器
        self.任务栈 = 任务栈
        self.三觉 = 三觉            # M5：视觉/听觉
        self.三觉 = 三觉
        self.问云 = 问云                  # 收 (prompt, 用途) → 原始文本
        self.日志路径 = os.path.join(审计目录, "心跳.jsonl")
        self.上次 = 0.0
        self.连续失败 = 0
        self.退避到 = 0.0
        self.计数 = []                    # 每次点火的时间戳（算预算用）

    def _数(self, 名, 缺省):
        try:
            return float(self.m.get(名, 缺省))
        except (TypeError, ValueError):
            return float(缺省)

    def 启用(self):
        return bool(self.m.get("enable", False))

    def 开关(self, 开, 原因="主人吩咐"):
        self.m["enable"] = bool(开)
        self.说(f"[{时刻()}] 自主找事：{'开' if 开 else '关'}了（{原因}）。", 紧急=True)
        self._记({"事件": "开关", "开": bool(开), "原因": 原因})
        return True

    def _记(self, 条):
        条 = dict(条)
        条.setdefault("t", round(time.time(), 3))
        try:
            with open(self.日志路径, "a", encoding="utf-8") as f:
                f.write(json.dumps(条, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _预算还够(self, 现在):
        一小时 = [t for t in self.计数 if 现在 - t < 3600]
        一天 = [t for t in self.计数 if 现在 - t < 86400]
        self.计数 = 一天
        return (len(一小时) < self._数("每小时上限", 30)
                and len(一天) < self._数("每天上限", 300))

    def 该点(self, s, 反射状态, 现在=None):
        if not self.启用():
            return False
        现在 = 现在 or time.time()
        if 现在 < self.退避到:
            return False
        if self.任务栈 is not None and self.任务栈.在跑():
            return False
        if 反射状态 not in ("平静",):
            return False
        if 现在 - self.上次 < self._数("心跳秒", 60):
            return False
        if self.三觉 is not None and 现在 - (self.三觉.上次有人说话 or 0) < self._数("安静秒", 20):
            return False
        if not self._主人在线(s):
            return False
        if not self._预算还够(现在):
            return False
        return True

    def _主人在线(self, s):
        要的 = list(self.m.get("主人名单") or [])
        if not 要的:
            return True
        for p in ((s or {}).get("players") or []):
            if p.get("name") in 要的:
                return True
        return False

    def 看(self, s, 反射状态):
        """主循环每拍问一次：该点火吗？该就点。"""
        if self.该点(s, 反射状态):
            return self.点(s, 反射状态)
        return None

    def 点(self, s, 反射状态="平静"):
        """点一次火：三觉 → prompt → 问 LLM → fail-closed 校验 → 接单（或什么都不做）。"""
        现在 = time.time()
        self.上次 = 现在
        self.计数.append(现在)
        if self.三觉 is not None and self.三觉.扫描过期(s):
            self.三觉.要扫描()            # 心跳点火前先扫一眼（看完下一拍再决定）
        状况 = self.任务栈.进度一句话() if self.任务栈 is not None else "没有任务"
        prompt = self.翻译器.组Prompt(s, 用途="心跳", 任务状况="没有任务")
        原文 = self.问云(prompt, "心跳")
        if not 原文:
            self.连续失败 += 1
            self._记({"事件": "没问成", "连续失败": self.连续失败})
            return None
        动作, 任务, 原因 = self.翻译器.收输出(原文, s, 用途="心跳")
        if 任务:
            self.连续失败 = 0
            self._记({"事件": "自己定了个目标", "任务": 任务.get("名字"),
                      "为什么": 任务.get("为什么"), "步数": len(任务.get("步骤") or [])})
            self.说(f"[{时刻()}] 我自己琢磨了个目标：{任务.get('名字')}"
                    f"（{任务.get('为什么') or '没事找点事'}）。", 紧急=True)
            if self.任务栈 is not None:
                return self.任务栈.接(任务.get("名字"), 任务.get("步骤"), s)
            return None
        if 原因:
            self.连续失败 += 1
            self._记({"事件": "被校验拒了", "原因": 原因, "原文": str(原文)[:400],
                      "连续失败": self.连续失败})
        else:
            self.连续失败 = 0
            if 动作 and 动作.get("act") == "say":
                self.翻译器.说(f"[{时刻()}] 我闲着，想说一句：{动作.get('text')}")
            self._记({"事件": "什么都不做" if not 动作 else "单步动作", "动作": 动作})
        if self.连续失败 >= 2:
            self.退避到 = 现在 + self._数("空转退避秒", 300)
            self.连续失败 = 0
            self._记({"事件": "空转两次，退避", "退避到": self.退避到})
        return None


# ─────────────────────────── 接线口 ───────────────────────────

class 接线口:
    """一条到手的线。连、收、发、断，都在这里；断了不退出，交给上层重连。"""

    def __init__(self, cfg, 说):
        self.cfg = cfg
        self.说 = 说
        self.方式, self.目标 = 解析接线口(cfg)
        self.提示 = (f"[unix] {self.目标}" if self.方式 == "unix"
                     else f"[tcp] {self.目标[0]}:{self.目标[1]}")
        self.s = None
        self.缓冲 = b""
        self.烂包数 = 0

    def 连(self, 重试=3):
        for i in range(1, 重试 + 1):
            s = socket.socket(socket.AF_UNIX if self.方式 == "unix" else socket.AF_INET,
                              socket.SOCK_STREAM)
            try:
                s.connect(self.目标)
                s.settimeout(1.0)
                self.s = s
                self.缓冲 = b""
                self.说(f"[{时刻()}] 接线口连上了 {self.提示}")
                return True
            except (FileNotFoundError, ConnectionRefusedError, OSError) as e:
                s.close()
                if i == 1:
                    self.说(f"[{时刻()}] 接线口还没开 {self.提示}，我在门口等…")
                time.sleep(1)
        最后 = "连不上"
        self.说(f"[{时刻()}] 试了 {重试} 次都没连上（{最后}）。", 紧急=True)
        return False

    def 收(self):
        """收一批消息。返回 (消息列表, 是否断开)。超时不算断开。"""
        if self.s is None:
            return [], True
        try:
            块 = self.s.recv(65536)
        except socket.timeout:
            return [], False
        except (ConnectionResetError, BrokenPipeError, OSError) as e:
            self.说(f"[{时刻()}] 接线口出错了：{e}", 紧急=True)
            return [], True
        if not 块:
            self.说(f"[{时刻()}] 手那边主动断开了。", 紧急=True)
            return [], True

        self.缓冲 += 块
        消息们 = []
        while b"\n" in self.缓冲:
            行, self.缓冲 = self.缓冲.split(b"\n", 1)
            行 = 行.strip()
            if not 行:
                continue
            try:
                消息 = json.loads(行.decode("utf-8", "replace"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                消息们.append({"type": "__烂包__", "why": str(e)[:60]})
                continue
            if not isinstance(消息, dict):
                消息们.append({"type": "__烂包__", "why": "不是对象"})
                continue
            消息们.append(消息)
        return 消息们, False

    def 发(self, obj):
        if self.s is None:
            return False
        try:
            self.s.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def 断(self):
        try:
            if self.s:
                self.s.close()
        except Exception:
            pass
        self.s = None



# ──────────────────────── 指令层（M3） ────────────────────────

class 指令层:
    """M3·指令层：把主人在游戏里说的中文，翻译成结构化动作。

    纯规则、零成本、毫秒级。**故意不猜** —— 模板匹配不上就老老实实记一条
    「听不懂」，交给上层（可选的大模型层）处理，自己绝不自作主张。

    它跑在反射层**后面**：反射层说"我没事干"的时候，才轮到它。"""

    def __init__(self, m3, 说, 发命令, 叫停=None, 任务栈=None, 三觉=None, 心跳器=None,
                 记忆=None):
        self.cfg = (m3 or {}).get("command") or {}
        self.说 = 说
        self.发 = 发命令
        # M4：主人说「停」/「别追了」的时候，顺手把正在进行的追击也掐掉。
        # 不做这件事的话会出现最气人的一幕：命令执行了，一秒后它又追上来。
        self.叫停 = 叫停
        # M4c：多步任务从这里下单（指令层只负责"听懂 + 下单"，干活是任务栈的事）
        self.任务栈 = 任务栈
        self.三觉 = 三觉            # M5：视觉/听觉
        self.心跳器 = 心跳器        # M6：自主找事的总开关
        self.记忆 = 记忆            # M7：只用来"念给它听"，不许拿它下命令
        self.当前 = None        # 正在执行的持续指令（比如跟随）
        self.听不懂 = []        # 记下听不懂的原文 —— 这就是大模型层的输入
        self.猜错次数 = {}      # 原文 -> 连着猜错几次
        self.听懂过 = 0

    # ── 开关 ──
    def 启用(self):
        return bool(self.cfg.get("enable", True))

    def 该听谁的(self, 说话人):
        允许 = self.cfg.get("allow_from") or []
        return (not 允许) or (说话人 in 允许)

    def 回话(self, 文本):
        if self.cfg.get("reply", True):
            self.发({"cmd": "say", "text": str(文本)[:120]})

    # ── 解析：一句话 → 一个动作（或者 None）──
    @staticmethod
    def _含(原, *词):
        return any(w in 原 for w in 词)

    @staticmethod
    def _尾(原, *前缀):
        """去掉前缀剩下的部分，用来抓「别打 小明」里的名字"""
        for q in 前缀:
            if q in 原:
                return 原.split(q, 1)[1].strip(' 　的了')
        return ""

    # 口语名 → MC 实体名。「别打那只猫」里的"那只猫"得翻译成 cat 才有用
    口语名 = {
        "猫": "cat", "狗": "wolf", "宠物": "wolf", "狼": "wolf", "马": "horse",
        "羊": "sheep", "牛": "cow", "猪": "pig", "鸡": "chicken", "兔子": "rabbit",
        "村民": "villager", "商人": "wandering_trader",
        "僵尸": "zombie", "骷髅": "skeleton", "苦力怕": "creeper",
        "蜘蛛": "spider", "末影人": "enderman", "女巫": "witch", "史莱姆": "slime",
    }

    # 物品口语名 → MC 物品名。合成指令要用（本地映射，不查大模型）
    物品名 = {
        "木板": "oak_planks", "木棍": "stick", "棍子": "stick",
        "工作台": "crafting_table", "熔炉": "furnace", "箱子": "chest",
        "火把": "torch", "面包": "bread", "梯子": "ladder",
        "木镐": "wooden_pickaxe", "石镐": "stone_pickaxe", "铁镐": "iron_pickaxe",
        "铁剑": "iron_sword", "石剑": "stone_sword", "钻石剑": "diamond_sword",
        "铁甲": "iron_chestplate", "铁头盔": "iron_helmet", "铁鞋": "iron_boots",
        "门": "oak_door", "床": "red_bed", "玻璃": "glass",
    }

    @classmethod
    def 归一名字(cls, 名):
        """把口语名翻成实体名：那只猫 → cat；小明 → 原样返回。"""
        名 = (名 or "").strip()
        for 口语, 实体 in cls.口语名.items():
            if 口语 in 名:
                return 实体
        return 名

    def 解析(self, 说话人, 原文=""):
        原 = str(原文 or "").strip()
        if not 原:
            return None
        # ⚠ import 必须在**方法最前面**：下面 ③.5 的嵌套函数要用它，
        # 而 Python 会把方法里任何位置的 import 都视为本方法的局部名 ——
        # 放在后面就会出现 "cannot access free variable '_re'"（2026-10-01 实测踩过）。
        import re as _re

        # ① 朋友名单（最优先，因为这是"别误伤"的事）
        if self._含(原, "别打", "不要打", "不许打", "放过", "别碰"):
            名 = self._尾(原, "别打", "不要打", "不许打", "放过", "别碰")
            return {"act": "friend", "name": self.归一名字(名) or 说话人, "why": "主人让别打"}
        # ⚠ 「不是我朋友」必须先判 —— 否则会被下面的「我朋友」抢先匹配走
        if self._含(原, "不是我朋友", "不是朋友", "可以打"):
            名 = self.归一名字(self._尾(原, "不是我朋友", "不是朋友", "可以打")) or 说话人
            return {"act": "unfriend", "name": 名}
        if self._含(原, "是我朋友", "我朋友", "自己人"):
            return {"act": "friend", "name": 说话人, "why": "主人认领"}

        # ② 停 / 别跟 / 别打
        if self._含(原, "别打", "停手", "别还手", "和平"):
            return {"act": "peace"}
        if self._含(原, "别跟", "不要跟", "自己玩", "不用跟"):
            return {"act": "stop"}
        if self._含(原, "停", "站住", "别动", "停下"):
            return {"act": "stop"}

        # ③ 跟随
        if self._含(原, "跟着我", "跟我", "跟过来", "过来", "来我", "一起走"):
            return {"act": "follow", "who": 说话人}

        # ③.5 M4c·任务（多步）。**必须排在单步「去/挖」前面** ——
        #      否则「挖 20 77 -20 然后回来」会被单步的挖抢走，任务根本轮不到。

        def _取串坐标(文):
            数 = _re.findall(r"-?\d+(?:\.\d+)?", 文)
            出 = []
            for i in range(0, len(数) - 2, 3):
                出.append([float(数[i]), float(数[i + 1]), float(数[i + 2])])
            return 出

        if self._含(原, "别自己找事", "别自己找", "别自由活动", "自主模式关", "老实待着"):
            return {"act": "auto_off"}
        if self._含(原, "自己找点事", "自己找事", "自主模式", "自由活动", "自己决定做什么"):
            return {"act": "auto_on"}
        if self._含(原, "你记得什么", "你记得啥", "记得什么", "你还记得", "记忆怎么样",
                    "你记着啥", "脑子里有什么"):
            return {"act": "remember"}
        if self._含(原, "看看周围", "看看四周", "环顾", "周围有什么", "你看到什么", "看看环境"):
            return {"act": "look"}
        if self._含(原, "任务怎么样", "任务如何", "进度", "在干什么", "干什么呢", "做啥呢"):
            return {"act": "task_status"}
        if self._含(原, "别干了", "不干了", "取消任务", "别做了", "先停下", "别挖了"):
            return {"act": "task_abort"}
        if self._含(原, "烧铁", "烧矿", "烧矿石", "炼铁", "烧东西", "开炉"):
            坐标们 = _取串坐标(原)
            if not 坐标们:
                return {"act": "task", "名字": "烧矿（缺坐标）", "步骤": []}
            return {"act": "task", "名字": "烧矿", "步骤": 搭烧矿任务(坐标们[0])}
        if self._含(原, "然后回来", "再回来", "回原地", "回来", "之后回来"):
            坐标们 = _取串坐标(原)
            if 坐标们 and self._含(原, "挖", "开采", "凿"):
                return {"act": "task", "名字": f"挖 {len(坐标们)} 格再回来",
                        "步骤": 搭挖任务(坐标们)}
            if 坐标们:
                return {"act": "task", "名字": "去一趟再回来", "步骤": 搭去回任务(坐标们[0])}

        # ④ 去坐标：「去 10 70 5」
        配 = _re.search(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)", 原)
        if 配 and self._含(原, "去", "走到", "前往"):
            return {"act": "goto", "p": [float(配.group(1)), float(配.group(2)), float(配.group(3))]}

        # ⑤ 吃
        if self._含(原, "吃东西", "去吃饭", "吃点", "吃饭", "饿了"):
            return {"act": "eat"}

        # ⑥ 查询
        if self._含(原, "血怎么样", "你怎么样", "还好吗", "状态", "你在哪", "在哪"):
            return {"act": "status"}

        # ⑦ 身体动作（M4）：手 + 腿。**全部本地确定性，不经过大模型。**
        #    顺序要紧：「跳劈」必须排在「跳」前面，否则会被跳抢走。
        if self._含(原, "跳劈", "跳着打", "跳起来打"):
            return {"act": "jumpattack"}
        if self._含(原, "潜下去", "往下游", "沉下去", "下沉"):
            return {"act": "swimdown"}
        if self._含(原, "蹲下", "蹲着", "潜行", "蹲"):
            return {"act": "sneak"}
        if self._含(原, "跳一下", "跳一跳", "蹦", "跳"):
            return {"act": "jump"}
        if self._含(原, "挖掉", "挖", "开采", "凿"):
            配 = _re.search(r"(-?\d+)\s+(-?\d+)\s+(-?\d+)", 原)
            if not 配:
                return {"act": "dig", "p": None, "why": "没给坐标"}
            return {"act": "dig", "p": [float(配.group(1)), float(配.group(2)), float(配.group(3))]}
        if self._含(原, "放下", "放一个", "放个", "摆", "放"):
            配 = _re.search(r"(-?\d+)\s+(-?\d+)\s+(-?\d+)", 原)
            if not 配:
                return {"act": "place", "p": None, "why": "没给坐标"}
            return {"act": "place", "p": [float(配.group(1)), float(配.group(2)), float(配.group(3))]}
        if self._含(原, "合成", "做一个", "做个", "造一个"):
            尾 = self._尾(原, "合成", "做一个", "做个", "造一个")
            名 = self.物品名.get(尾.strip(), 尾.strip())
            if not 名:
                return None
            return {"act": "craft", "item": 名}
        if self._含(原, "开箱", "打开", "按钮", "开门", "用一下"):
            配 = _re.search(r"(-?\d+)\s+(-?\d+)\s+(-?\d+)", 原)
            if not 配:
                return {"act": "use", "p": None, "why": "没给坐标"}
            return {"act": "use", "p": [float(配.group(1)), float(配.group(2)), float(配.group(3))]}

        # ⑧ 打（只针对**已经在威胁列表里**的目标，绝不主动树敌）
        if self._含(原, "打那个", "打它", "揍它", "打他"):
            return {"act": "strike", "why": "主人让打当前威胁"}

        return None

    # ── 执行 ──
    def 收(self, 说话人, 原文, s):
        """收到一句话。返回 True 表示听懂了。"""
        if not self.启用():
            return False
        if not self.该听谁的(说话人):
            self.说(f"[{时刻()}] 「{说话人}」说了句「{原文}」，不过我不听他的。")
            return False

        动作 = self.解析(说话人, 原文)
        if 动作 is None:
            self.听不懂.append({"t": time.time(), "from": 说话人, "text": 原文})
            if len(self.听不懂) > 50:
                self.听不懂 = self.听不懂[-50:]
            self.说(f"[{时刻()}] 「{说话人}」说「{原文}」—— 这句我没学过，先老实说不会，"
                    f"绝不乱动。（听不懂第 {len(self.听不懂)} 条）", 紧急=True)
            return False

        self.听懂过 += 1
        self.说(f"[{时刻()}] 听懂了：「{原文}」→ {动作.get('act')}"
                + (f"（{动作.get('name') or 动作.get('who') or ''}）"
                   if (动作.get('name') or 动作.get('who')) else ""))
        self._做(动作, s, 说话人, 原文)
        return True

    def _做(self, 动作, s, 说话人, 原文):
        类 = 动作.get("act")
        if 类 == "friend":
            名 = 动作.get("name") or 说话人
            self.发({"cmd": "friend", "name": 名})
            self.当前 = None
            self.回话(f"好，{名}是自己人，我记住了。")
        elif 类 == "unfriend":
            self.发({"cmd": "friend", "name": 动作.get("name"), "remove": True})
            self.回话(f"好，{动作.get('name')} 我不客气了。")
        elif 类 == "task":
            if self.任务栈 is None or not self.任务栈.启用():
                self.回话("我还没学会做多步的活…")
            elif not 动作.get("步骤"):
                self.回话("要做啥我还没听明白 —— 给我个坐标吧（比如「去 20 78 -20，然后回来」）。")
            else:
                好 = self.任务栈.接(动作.get("名字") or "任务", 动作.get("步骤"), s)
                if 好:
                    self.回话(f"好，我这就去：{动作.get('名字')}。")
        elif 类 == "remember":
            # ★ M7：记忆只"念"给人听，绝不变成动作（宪法第①条）
            if self.记忆 is not None:
                self.回话(self.记忆.念一遍())
            else:
                self.回话("我还没有记性呢。")
        elif 类 == "look":
            if self.三觉 is not None:
                self.三觉.要扫描()
                self.回话("好，我看看周围……")
            else:
                self.回话("我还没长眼睛呢。")
        elif 类 == "auto_on":
            if self.心跳器 is not None:
                self.心跳器.开关(True, "主人让的")
                self.回话("好，那我自己找点事做。")
            else:
                self.回话("我还没学会自己找事。")
        elif 类 == "auto_off":
            if self.心跳器 is not None:
                self.心跳器.开关(False, "主人叫停")
                self.回话("好，我老老实实待着。")
            else:
                self.回话("我本来就没在瞎忙。")
        elif 类 == "task_status":
            self.回话(self.任务栈.进度一句话() if self.任务栈 else "我手上没活。")
        elif 类 == "task_abort":
            if self.任务栈 and self.任务栈.在跑():
                self.任务栈.中止("主人叫停")
                self.回话("好，那件活我放下了。")
            else:
                self.回话("我手上本来就没活。")
        elif 类 == "stop":
            self.当前 = None
            if self.叫停:
                self.叫停("主人叫停")
            self.发({"cmd": "stop"})
            self.回话("好，我停下。")
        elif 类 == "peace":
            self.当前 = None
            self.现在的和平 = True
            if self.叫停:
                self.叫停("主人说不打了")
            self.发({"cmd": "stop"})
            self.回话("好，我不还手了。")
        elif 类 == "follow":
            self.当前 = {"act": "follow", "who": 动作.get("who") or 说话人, "上次动": 0}
            self.回话(f"好，我跟着{动作.get('who') or 说话人}。")
        elif 类 == "goto":
            self.当前 = None
            self.发({"act": "goto", "p": 动作["p"]})
            self.回话(f"好，我去 {动作['p'][0]:.0f} {动作['p'][1]:.0f} {动作['p'][2]:.0f}。")
        elif 类 == "eat":
            self.发({"cmd": "eat"})
            self.回话("好，我吃点东西。")
        elif 类 == "status":
            self.回话(self._状态一句话(s))
        elif 类 in ("sneak", "jump", "swimdown"):
            if 类 == "sneak":
                self.发({"cmd": "sneak", "ms": 动作.get("ms", 1500)}); self.回话("好，我蹲下。")
            elif 类 == "jump":
                self.发({"cmd": "jump", "count": 动作.get("count", 1)}); self.回话("跳！")
            else:
                self.发({"cmd": "swimdown", "ms": 动作.get("ms", 1500)}); self.回话("我往下潜。")
        elif 类 == "jumpattack":
            敌人 = s.get("threats") or []
            if not 敌人:
                self.回话("现在旁边没有敌人啊…")
            else:
                名 = min(敌人, key=lambda t: t["dist"])["name"]
                self.发({"cmd": "jumpattack", "target": 名})
                self.回话(f"看我的，跳劈{中文名.get(名, 名)}！")
        elif 类 in ("dig", "place", "use"):
            坐标 = 动作.get("p")
            if not 坐标:
                self.回话("要给我坐标我才知道动哪儿 —— 比如「挖 10 64 5」。")
            else:
                self.发({"cmd": 类, "p": 坐标})
                self.回话({"dig": "好，我挖。", "place": "好，我放。",
                          "use": "我去用一下。"}[类])
        elif 类 == "craft":
            物品 = 动作.get("item")
            if not 物品:
                self.回话("要告诉我合成什么。")
            else:
                self.发({"cmd": "craft", "item": 物品, "count": 动作.get("count", 1)})
                self.回话(f"好，我试试合成{物品}。")
        elif 类 == "strike":
            self.说(f"[{时刻()}] 主人让打，那我就打 —— 不过只打已经在威胁名单里的，不主动树敌。")
        elif 类 == "say":
            self.回话(动作.get("text") or "")
        else:
            self.说(f"[{时刻()}] 这个动作我还没实现：{类}")

    @staticmethod
    def _状态一句话(s):
        血 = s.get("hp")
        位 = s.get("pos") or [0, 0, 0]
        食物 = s.get("foods") or []
        武器 = s.get("weapons") or []
        边 = "，手上有" + 中文名.get(武器[0]["name"], 武器[0]["name"]) if 武器 else "，手上空着"
        吃 = f"，背包里有 {食物[0]['count']} 个{食物中文名.get(食物[0]['name'], 食物[0]['name'])}" if 食物 else "，背包里没吃的"
        return (f"我在 ({位[0]:.0f}, {位[1]:.0f}, {位[2]:.0f})，"
                f"血 {血文本(血)}/20{边}{吃}。")

    # ── 每拍跑一次持续指令 ──
    def 跑(self, s):
        if not self.当前:
            return False
        if self.当前.get("act") == "follow":
            return self._跟随(s)
        return False

    def _跟随(self, s):
        谁 = self.当前.get("who")
        目标 = None
        for pl in (s.get("players") or []):
            if pl.get("name") == 谁:
                目标 = pl
                break
        if 目标 is None:
            if not self.当前.get("丢过"):
                self.当前["丢过"] = True
                self.说(f"[{时刻()}] 跟着跟着把「{谁}」跟丢了 —— 我看不见他。")
                self.回话(f"{谁}你在哪，我看不见你了…")
            return False
        距离 = 目标.get("dist", 0)
        if 距离 <= 3.0:
            return False                       # 已经跟上了，不用动
        现在 = time.time()
        if 现在 - self.当前.get("上次动", 0) < 2.0:
            return False                       # 别每拍都发命令，2 秒一次够用
        self.当前["上次动"] = 现在
        if (s.get("plugins") or {}).get("pathfinder"):
            self.发({"act": "goto", "p": 目标["pos"]})
        else:
            # 没有寻路插件就直线挪 —— 够用就行，别为此再加依赖
            我 = s.get("pos") or [0.0, 0.0, 0.0]
            差x = 目标["pos"][0] - 我[0]
            差z = 目标["pos"][2] - 我[2]
            长 = math.hypot(差x, 差z) or 1.0
            self.发({"cmd": "move", "dir": [round(差x / 长, 3), round(差z / 长, 3)], "ms": 900})
        return True


# ─────────────────────── 指代消解（M3.1） ───────────────────────

class 代词:
    """把句子里的「我 / 你 / 他」换成具体名字。

    ⚠ 这一步必须在**任何下游层之前**做。

    不做的后果 2026-09-30 实测到了：
        「跟紧我，别走丢了」→ 大模型翻成 follow who=XiaoJiaHuo（它自己）
    根因不是"提示词没写清楚"，而是**代词被一路漂到了云端，让它替我们做语言学**。
    换个说法、加一句叮嘱，都只是把 bug 藏起来 —— 下次换个句式照样翻车。

    归一之后还能捎带一个好处：**换成什么是可审计的**。
    哪次换了、换成了谁，日志里看得见，不用再猜。

    ⚠ 顺序要紧：长的排前面，否则「我自己」会被「我」先切一刀。"""

    表 = [
        ("我自己", "发言人"),
        ("你自己", "自己"),
        ("我们自己", "发言人"),
        ("我们", "发言人"),
        ("咱", "发言人"),
        ("俺", "发言人"),
        ("我", "发言人"),
        ("您", "自己"),
        ("你", "自己"),
        ("他", "第三方"),
        ("她", "第三方"),
    ]

    # 含代词但不是代词的词，先罩起来免得被误伤
    罩住的词 = ["其他", "其它", "我的世界", "你死我活"]

    @classmethod
    def 归一(cls, 原文, 说话人, 自己名, 别人=()):
        """返回 (归一后的句子, 换掉了哪些)。第三方不唯一时不敢认，就原样留着。"""
        出 = str(原文 or "")
        第三 = [x for x in 别人 if x not in (说话人, 自己名)]

        # 先罩住误伤词
        罩 = {}
        for i, 词 in enumerate(cls.罩住的词):
            if 词 in 出:
                记 = f"\x00{i}\x00"
                罩[记] = 词
                出 = 出.replace(词, 记)

        换了 = []
        for 代, 谁 in cls.表:
            if 代 not in 出:
                continue
            if 谁 == "发言人":
                替 = 说话人
            elif 谁 == "自己":
                替 = 自己名
            else:
                if len(第三) != 1:        # 第三方不唯一，不敢乱认
                    continue
                替 = 第三[0]
            出 = 出.replace(代, 替)
            换了.append(f"{代}→{替}")

        for 记, 词 in 罩.items():
            出 = 出.replace(记, 词)
        return 出, 换了


# ─────────────────────── 云端 LLM 层（M3） ───────────────────────

class 大模型层:
    """M3·云端 LLM 层。**默认关**。

    它只干一件事：把一句指令层没学过的人话，翻译成白名单里的动作。

    ★ 它**没有决策权**：
        · 输出必须过校验器，不在白名单里的动作一律丢弃；
        · 攻击类动作**根本不在白名单里**，它想给也给不了；
        · 反射层永远排在它前面，它说什么都不能让小家伙停止保命；
        · 强限流：两次之间 ≥min_interval_sec，每小时硬上限 max_per_hour，到了就闭嘴。
    ★ 关掉之后主链是纯规则系统，一次云端调用都不会发生。"""

    # 白名单：**刻意不含攻击**。想让 LLM 有权开打，得主人显式改这里。
    白名单 = {
        "follow": {"who": "在线玩家名"},
        "goto": {"p": "三个数字"},
        "say": {"text": "一句话（≤40字）"},
        "stop": {},
        "status": {},
        "friend": {"name": "名字"},
    }

    def __init__(self, m3, 说, 审计目录):
        self.cfg = (m3 or {}).get("llm") or {}
        self.说 = 说
        self.审计目录 = 审计目录
        self.调用时刻 = []
        self.总调用 = 0
        self.总丢弃 = 0
        self.密钥 = None

    def 开(self):
        return bool(self.cfg.get("enable", False))

    # ── 限流 ──
    def 能问(self):
        if not self.开():
            return False, "没开"
        现在 = time.time()
        self.调用时刻 = [t for t in self.调用时刻 if 现在 - t < 3600]
        最少 = float(self.cfg.get("min_interval_sec", 10))
        if self.调用时刻 and 现在 - self.调用时刻[-1] < 最少:
            return False, f"离上次不到 {最少:.0f} 秒"
        上限 = int(self.cfg.get("max_per_hour", 40))
        if len(self.调用时刻) >= 上限:
            return False, f"这一小时已经问了 {上限} 次，封顶"
        return True, ""

    # ── 密钥：先看文件，再退回 Cherry Studio 数据库（只读，绝不打印）──
    def _取密钥(self):
        if self.密钥:
            return self.密钥
        路径 = os.path.expanduser(self.cfg.get("key_file") or "~/.config/cyberdyne-bridge/key")
        try:
            with open(路径, encoding="utf-8") as f:
                钥 = f.readline().strip()
            if 钥:
                self.密钥 = 钥
                return 钥
        except OSError:
            pass
        # 退路：从 Cherry Studio 的库里只读取（和配电盘里的终端聊天.py 一个办法）
        try:
            import sqlite3
            db = os.path.expanduser("~/.config/CherryStudio/Data/cherrystudio.sqlite")
            if os.path.exists(db):
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
                列 = [r[1] for r in con.execute("pragma table_info('user_provider')")]
                供 = self.cfg.get("provider", "deepseek")
                for 行 in con.execute("select * from user_provider where is_enabled='1'"):
                    d = dict(zip(列, 行))
                    if d.get("provider_id") == 供 and d.get("api_keys"):
                        try:
                            钥 = json.loads(d["api_keys"])[0]
                        except Exception:
                            钥 = str(d["api_keys"]).strip("[]\"' ")
                        if 钥:
                            self.密钥 = 钥
                            return 钥
        except Exception:
            pass
        return None

    # ── 审计 ──
    def _记账(self, 条):
        条["t"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            os.makedirs(self.审计目录, exist_ok=True)
            路 = os.path.join(self.审计目录, "llm审计.jsonl")
            with open(路, "a", encoding="utf-8") as f:
                f.write(json.dumps(条, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ── 问 ──
    def 问(self, 原文, 说话人, s, 听懂的话):
        """返回一个**已经过校验**的动作，或者 None。永远不抛异常。"""
        能, 为什么 = self.能问()
        if not 能:
            self._记账({"结果": "未调用", "原因": 为什么, "原文": 原文})
            return None
        钥 = self._取密钥()
        if not 钥:
            self._记账({"结果": "未调用", "原因": "取不到密钥", "原文": 原文})
            self.说(f"[{时刻()}] 大模型层开着，但取不到密钥 —— 我老实说不会。", 紧急=True)
            return None

        玩家 = "、".join(p["name"] for p in (s.get("players") or [])) or "（看不到别人）"
        自己名 = str(s.get("bot") or "小家伙")
        别人 = [p["name"] for p in (s.get("players") or []) if p["name"] != 自己名]
        # ★ 指代消解：先把「我 / 你 / 他」换成名字，再交给云端。
        #   下游压根不该看到代词 —— 让大模型猜代词是我们在偷懒。
        归一后, 换了代词 = 代词.归一(原文, 说话人, 自己名, 别人)
        if 换了代词:
            self.说(f"[{时刻()}] 我先把代词认清楚：{'、'.join(换了代词)}", 紧急=True)
        提示 = (
            "你是 MC 里一只桌宠的指令翻译器。把主人的话翻译成**一个 JSON 动作**。\n"
            "只能用下面这些动作，不许发明新的：\n"
            + "\n".join(f'  {{"act":"{k}"{", 参数见说明" if v else ""}}}  # {v}' for k, v in self.白名单.items())
            + f"\n\n当前在线玩家：{玩家}\n"
            + f"你现在的状态：{听懂的话}\n"
            + f"{说话人}说：「{归一后}」（已经替你把代词换成名字了）\n"
            + "只输出一个 JSON，不要解释，不要 markdown 代码块。翻译不出来就输出 {}。"
        )

        体 = json.dumps({
            "model": self.cfg.get("model", "deepseek-chat"),
            "messages": [{"role": "user", "content": 提示}],
            "max_tokens": int(self.cfg.get("max_tokens", 200)),
            "temperature": float(self.cfg.get("temperature", 0)),
        }).encode("utf-8")

        请求 = urllib.request.Request(
            (self.cfg.get("api_base", "https://api.deepseek.com/v1").rstrip("/") + "/chat/completions"),
            data=体,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {钥}"},
        )
        现在 = time.time()
        动作, 原文回复 = None, ""
        try:
            with urllib.request.urlopen(请求, timeout=float(self.cfg.get("timeout_sec", 20))) as r:
                出 = json.loads(r.read().decode("utf-8", "replace"))
            原文回复 = (出.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
            动作 = self.校验(原文回复, s)
        except Exception as e:
            self.说(f"[{时刻()}] 问大模型没问成（{type(e).__name__}），算了，我老实说不会。", 紧急=True)
            self._记账({"结果": "失败", "原因": f"{type(e).__name__}: {e}", "原文": 原文})
            self.调用时刻.append(现在)
            return None

        self.调用时刻.append(现在)
        self.总调用 += 1
        if 动作 is None:
            self.总丢弃 += 1
        self._记账({"结果": "成功" if 动作 else "丢弃",
                    "原文": 原文, "归一后": 归一后, "代词": 换了代词,
                    "模型原话": 原文回复[:300], "采纳的动作": 动作})
        return 动作

    # ── 校验：不进白名单的一律丢弃 ──
    def 问一次(self, prompt, 用途="通用", 最大token=None):
        """M5·通用一问：给什么 prompt 就回什么原文（翻译器/心跳用）。

        跟 问() 分开写是有意的 —— 问() 那条路是 M3 的"翻成动作"，已经被 49 条断言
        和现场验收压过；这里另开一条**同样受限流与审计管着**的路，
        免得改坏已经验过的东西。返回原文（失败给空串）。"""
        if not self.开():
            return ""
        现在 = time.time()
        if not self.能问():
            self.说(f"[{时刻()}] 问得太勤了，这次先不问了。")
            return ""
        钥 = self._取密钥()
        if not 钥:
            return ""
        体 = json.dumps({
            "model": self.cfg.get("model", "deepseek-chat"),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": int(最大token or self.cfg.get("max_tokens", 200)),
            "temperature": float(self.cfg.get("temperature", 0)),
        }).encode("utf-8")
        请求 = urllib.request.Request(
            (self.cfg.get("api_base", "https://api.deepseek.com/v1").rstrip("/") + "/chat/completions"),
            data=体,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {钥}"},
        )
        self.调用时刻.append(现在)
        self.总调用 += 1
        try:
            with urllib.request.urlopen(请求, timeout=float(self.cfg.get("timeout_sec", 20))) as r:
                出 = json.loads(r.read().decode("utf-8", "replace"))
            文 = (出.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
            self._记账({"用途": 用途, "结果": "成功", "prompt长度": len(prompt),
                        "prompt尾巴": prompt[-900:],          # 触觉/听觉那几段就在里面
                        "模型原话": 文[:400]})
            return 文
        except Exception as e:
            self.说(f"[{时刻()}] 问大模型没问成（{type(e).__name__}），这次算了。", 紧急=True)
            self._记账({"用途": 用途, "结果": "失败", "原因": f"{type(e).__name__}: {e}",
                        "prompt长度": len(prompt)})
            return ""

    def 校验(self, 文本, s):
        净 = (文本 or "").strip()
        if 净.startswith("```"):
            净 = 净.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            动作 = json.loads(净)
        except Exception:
            self.说(f"[{时刻()}] 大模型回的不是 JSON，丢掉了。", 紧急=True)
            return None
        if not isinstance(动作, dict) or not 动作.get("act"):
            return None
        类 = 动作["act"]
        if 类 not in self.白名单:
            self.说(f"[{时刻()}] 大模型想让我「{类}」—— 这不在白名单里，我拒了。", 紧急=True)
            return None
        # 参数校验
        if 类 == "follow":
            好 = [p["name"] for p in (s.get("players") or [])]
            # 跟着自己跑是荒谬的 —— 这一条专门用来拦指代消解没做对的情况
            if 动作.get("who") == s.get("bot"):
                self.说(f"[{时刻()}] 它让我跟着我自己跑 —— 这说不通，拒了。", 紧急=True)
                return None
            if 动作.get("who") not in 好:
                self.说(f"[{时刻()}] 它让我跟「{动作.get('who')}」，可我看不到这个人，拒了。", 紧急=True)
                return None
        elif 类 == "goto":
            p = 动作.get("p")
            我 = s.get("pos") or [0.0, 0.0, 0.0]
            if (not isinstance(p, list) or len(p) != 3
                    or not all(isinstance(v, (int, float)) for v in p)):
                return None
            if math.dist(p, 我) > 60:
                self.说(f"[{时刻()}] 它让我跑去 {math.dist(p, 我):.0f} 格开外 —— 太远了，拒了。", 紧急=True)
                return None
        elif 类 == "say":
            动作["text"] = str(动作.get("text") or "")[:40]
        elif 类 == "friend":
            if not str(动作.get("name") or "").strip():
                return None
        return 动作


# ─────────────────────────── 主循环 ───────────────────────────

def 主():
    p = argparse.ArgumentParser(description="Cyberdyne-Bridge M1 · 大脑在外面")
    p.add_argument("--json", action="store_true", help="额外打印原始行（排查用）")
    p.add_argument("--只读", action="store_true", help="只看不控，绝不下发任何动作")
    p.add_argument("--心跳秒", type=float, default=None, help="平静时的汇报间隔")
    a = p.parse_args()

    # 输出被管道接走时 Python 会攒 8KB 才吐，看起来像"卡住了"。强制行缓冲。
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    cfg = 读配置()
    m1 = cfg.get("m1") or {}
    m2 = cfg.get("m2") or {}
    心跳秒 = a.心跳秒 if a.心跳秒 is not None else float(m1.get("heartbeat_sec", 60))
    超时秒 = float(m1.get("state_timeout_ms", 10000)) / 1000.0
    退避 = m1.get("reconnect_backoff_ms") or [2000, 4000, 8000, 15000, 30000]

    叙事 = 叙事者(心跳秒=心跳秒, 每分钟上限=int(m1.get("max_lines_per_min", 12)))
    说 = 叙事.说
    # ⚠ 反射层要同时拿到 m1 和 m2（还有 M4 的猎手参数）—— M2 的参数全在 m2 里。
    # 只喂 m1 的话，counter_dist / finish_hp / counter_cooldown_ms 这些
    # 会**静默地用代码里的硬编码默认值**，配置怎么写都没用。
    # （这个 bug 是 2026-09-30 被 tools/回放.py 抓出来的。）
    反射 = 反射层({**m1, **m2, **(cfg.get("m4") or {})}, 说)
    温度 = 温度计(采样秒=float(m1.get("thermal", {}).get("sample_sec", 5)))
    节拍 = 节拍器(m2, 说)
    # M4：追猎期间强制快档 —— 追击是"每拍挪一小步"，慢档下会走一步愣一秒
    任务 = 任务栈(cfg.get("m4") or {}, 说, lambda o: None, os.path.join(ROOT, "logs"))
    # ── M5/M6：三觉 → 翻译器 → 心跳 ──
    三觉层 = 三觉(cfg.get("m5") or {}, 说, lambda o: None)
    人物 = ""
    try:
        with open(os.path.join(ROOT, "鱼设卡要点.txt"), encoding="utf-8") as f:
            人物 = f.read().strip()[:200]
    except Exception:
        人物 = ""
    记忆层 = 记忆(cfg.get("m7") or {}, 说, os.path.join(ROOT, "记忆"))
    任务.记忆 = 记忆层                     # 干完/失败时写卡
    翻译 = 翻译器(cfg.get("m5") or {}, 说, os.path.join(ROOT, "logs"),
                  任务栈=任务, 三觉=三觉层, 人格=人物,
                  允许动作=任务栈.允许动作, 记忆=记忆层)
    心跳器 = 心跳(cfg.get("m6") or {}, 说, 翻译, 任务, 三觉层,
                   lambda p, 用途="通用": 大模型.问一次(p, 用途, 600),
                  os.path.join(ROOT, "logs"))
    # 追猎、或者任务正在干"动作步"的时候走快档；**等待步不占快档**（省电，别为等世界空转）
    节拍.外部要快 = lambda: 反射.在追猎() or 任务.要快()
    大模型 = 大模型层(cfg.get("m3"), 说, os.path.join(ROOT, "logs"))

    说(不计流=True, 行=f"[{时刻()}] Cyberdyne-Bridge M3 启动，大脑在外面。")
    说(不计流=True, 行=f"           看住「{cfg.get('bot_name')}」"
        f"{'（只读模式，绝不下手）' if a.只读 else ''}。")
    说(不计流=True, 行=f"           反射层：跑、吃、保命、还手；指令层：听得懂话；"
        f"采样：平静 {节拍.慢:g}Hz / 战斗 {节拍.快:g}Hz。")

    连续失败 = 0
    上次状态时刻 = time.time()

    while True:
        iface = 接线口(cfg, 说)
        if not iface.连(重试=3):
            连续失败 += 1
            等 = 退避[min(连续失败 - 1, len(退避) - 1)] / 1000.0
            说(f"[{时刻()}] 手那边好像不在，{等:.0f} 秒后再试一次。", 紧急=True)
            time.sleep(等)
            continue

        连续失败 = 0
        上次状态时刻 = time.time()
        任务.发 = iface.发                    # 换连接了，把出口交给新接口
        三觉层.发 = iface.发
        指令 = 指令层(cfg.get("m3"), 说, iface.发,
                      叫停=lambda 原因="主人叫停": (反射.放掉追击(原因), 任务.中止(原因)),
                      任务栈=任务, 三觉=三觉层, 心跳器=心跳器, 记忆=记忆层)
        说(不计流=True, 行=f"           指令层{'已上线' if 指令.启用() else '关着'}；"
              f"大模型层{'开着（' + str((cfg.get('m3') or {}).get('llm', {}).get('model')) + '）' if 大模型.开() else '关着'}。")
        # 手那边一旦发现"大脑全走了"会自己降回平静档，脑这边也跟着对齐，
        # 否则脑以为还在 5Hz、手已经回到 1Hz，两边就会各说各话。
        节拍.复位()

        try:
            while True:
                消息们, 断了 = iface.收()
                if 断了:
                    break

                现在 = time.time()
                for 消息 in 消息们:
                    if 消息.get("type") == "__烂包__":
                        iface.烂包数 += 1
                        if iface.烂包数 % 20 == 1:
                            说(f"[{时刻()}] 收到一个看不懂的数据包（{消息.get('why')}），"
                                    f"丢掉了。至今共 {iface.烂包数} 个。", 紧急=True)
                        continue
                    if 消息.get("type") == "state":
                        上次状态时刻 = time.time()
                        最后状态 = 消息
                        # 手正在做动作时，位移由反射层自己叙述，别让每帧的位置变化刷屏
                        叙事.静默移动 = (消息.get("acting") or "idle") != "idle"
                    if a.json:
                        print(f"           [原始] {json.dumps(消息, ensure_ascii=False)[:200]}")
                    # M3：谁在说话 → 指令层先听；听不懂、而且大模型层开着，才问一次
                    if (消息.get("type") == "event" and 消息.get("kind") == "chat"
                            and 指令 is not None and 最后状态 is not None):
                        谁 = 消息.get("from") or ""
                        话 = 消息.get("text") or ""
                        if 谁 != cfg.get("bot_name"):
                            听懂了 = 指令.收(谁, 话, 最后状态)
                            三觉层.记聊天(谁, 话, 听懂了)
                            try:
                                记忆层.记人(谁, "说话")      # ★ 只记名字与次数，不存原文
                            except Exception:
                                pass
                            if not 听懂了 and 大模型.开():
                                if (cfg.get("m5") or {}).get("senses_enable", True) \
                                        and (cfg.get("m5") or {}).get("chitchat_enable", True) \
                                        and _能闲聊(cfg, 谁, cfg.get("m3")):
                                    # M5·听觉：认不出 ≠ 听不懂 —— 先按"闲聊/给个动作"问一次
                                    _聊一句(三觉层, 翻译, 大模型, 指令, 谁, 话, 最后状态)
                                else:
                                    动作 = 大模型.问(话, 谁, 最后状态,
                                                     指令._状态一句话(最后状态))
                                    if 动作:
                                        指令.说(f"[{时刻()}] 大模型把它翻成了"
                                                f"「{动作.get('act')}」，我照着做。", 紧急=True)
                                        指令._做(动作, 最后状态, 谁, 话)
                                    else:
                                        指令.说(f"[{时刻()}] 大模型也没翻出来 —— 那我不动。",
                                                紧急=True)
                    叙事.吃(消息)
                    if 消息.get("type") == "state":
                        _跑一轮反射(消息, 反射, 叙事, 温度, iface, a.只读, 节拍, 指令, 任务)
                        # ── M5.1：新扫到一次，就把"视觉摘要"在日志里念一遍 ──
                        if not a.只读 and (消息.get("scan") or {}).get("t") \
                                and (消息["scan"].get("t") != getattr(三觉层, "_念过的t", None)):
                            三觉层._念过的t = 消息["scan"].get("t")
                            说(不计流=True, 行=f"[{时刻()}] 【视觉】\n{三觉层.视觉(消息)}")
                            try:
                                记了几条 = 记忆层.看扫描(消息["scan"], 消息.get("pos"))
                                if 记了几条:
                                    说(不计流=True, 行=f"           （记忆：这圈记下 {记了几条} 处地方）")
                            except Exception as e:
                                说(不计流=True, 行=f"           （记忆写不进去：{type(e).__name__}）")
                        # ── M7：挨打要记一笔（只记事实：谁打我、几次）──
                        打我 = 消息.get("attacked_by")
                        if 打我:
                            现在t = time.time()
                            if 现在t - getattr(记忆层, "_上次记挨打", 0) > 10:
                                记忆层._上次记挨打 = 现在t
                                try:
                                    记忆层.记人(打我, "打我")
                                except Exception:
                                    pass
                        # ── M7：见过的人建张卡（第一次见到）──
                        for _p in (消息.get("players") or []):
                            try:
                                记忆层.记初见(_p.get("name"))
                            except Exception:
                                pass
                        # ── M5/M6：三觉记空闲 → 心跳看一眼 ──
                        闲着 = (反射.状态 in (反射.平静, 反射.饿等)) and not 任务.在跑()
                        三觉层.记空闲(闲着)
                        if not a.只读 and 活着(反射):
                            心跳器.看(消息, 反射.状态)

                # 10 秒没状态 = 接线口哑了。这是主人点名要的那条防线。
                if time.time() - 上次状态时刻 > 超时秒:
                    说(f"[{时刻()}] 接线口哑了 —— {超时秒:.0f} 秒没收到任何状态，"
                            f"我断开重连一次。", 紧急=True)
                    break
        except KeyboardInterrupt:
            iface.发({"cmd": "stop"})
            iface.断()
            说(f"\n[{时刻()}] 收到中断，我把动作停了，收工。", 紧急=True)
            return
        except Exception as e:
            # 兜底：任何想不到的异常都不许把大脑带走
            说(f"[{时刻()}] 大脑内部出了个意外（{type(e).__name__}: {e}），"
                    f"我断开重连，继续盯着。", 紧急=True)
        finally:
            iface.发({"cmd": "stop"})
            iface.断()

        等 = 退避[min(连续失败, len(退避) - 1)] / 1000.0
        time.sleep(等)


def _跑一轮反射(s, 反射, 叙事, 温度, iface, 只读, 节拍, 指令=None, 任务=None):
    """一拍状态 = 一次决策。这里是整个 M2 唯一会"想"的地方。"""
    # 0) 上一轮反击欠的那一步后撤，到点了就先退
    反射.收尾(iface.发)

    # 1) 采样速率 —— 跟温度一样属于"环境"判断，排在反射前面
    节拍.看(s, iface.发)

    # 2) 热保护永远排在第一位，连主人指定的反射都得给它让路
    温度.采样()
    结果 = 反射.查热(温度.cpu, 温度.gpu)
    if 结果 == "挂起":
        iface.发({"cmd": "stop"})
        return
    if 反射.热挂起:
        return

    # 3) 反射层判断，然后交给手去执行
    决策 = 反射.决断(s)
    if 只读:
        return
    反射.执行(决策, iface.发)

    # 3.5) M4c·任务栈 —— 排在反射层**后面**，这就是"一票否决"的字面实现：
    #      反射层只要有事干（跑/吃/反击/追猎），任务立刻暂停并记账；
    #      等它回到「平静/饿等」，任务**从断点接着干**（不重头）。
    if 任务 is not None and 任务.任务 is not None:
        if 决策[0] not in (反射.平静, 反射.饿等):
            任务.记不平静()
            任务.暂停(决策[0], s)
        else:
            任务.记平静(time.time())
            if 任务.冷静够了(time.time()):
                任务.恢复(s)
                if 任务.跑(s):      # 任务下发了命令 → 指令层这一拍别抢方向盘
                    return

    # 4) ★ 反射层说"我没事干"的时候，才轮到指令层 —— 命令永远压不过保命
    if 指令 is not None and 决策[0] in (反射.平静, 反射.饿等):
        指令.跑(s)


if __name__ == "__main__":
    主()
