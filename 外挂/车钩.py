#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外挂列车·车钩 —— 让副链外挂像火车车厢一样随时挂、随时摘、随便重排。

┌───────────────────────────────────────────────────────────────────┐
│ 一句话：车钩把「一个外挂写死在一个入口脚本里」改成「一节一节的车厢」  │
└───────────────────────────────────────────────────────────────────┘
以前只有 `大脑外挂.py` 一个入口，动作面焊死在里面。想要第二种本事，
只能再写一个入口脚本，两个还不能同时跑（抢 socket）。主人 2026-10-07
提的要求是「像开火车那种，随时都可以连/断，自由组合也行」。

本文件就是那根车钩。它自己**不是**外挂，它只是**挂外挂的东西**。

┌───────────────────────────────────────────────────────────────────┐
│ 车厢是什么                                                         │
└───────────────────────────────────────────────────────────────────┘
一个目录，里面有两样东西就能当车厢：
    manifest.json    车厢的**铭牌**：叫什么、入口哪个文件、依赖谁、动哪几处
    补丁.py          车厢**本体**：必须有 `装上(bridge, ...)` 和 `卸下(bridge)`

★ 车厢的接口标准就两条，别的随便：
    def 装上(bridge, **要的)  -> {"好": bool, "为什么": str, "打了": [str]}
    def 卸下(bridge)          -> bool
  车钩会**先看函数签名**，只传它认识的参数（数 / 开关 / 车钩 / 日志）。
  所以老的动作面（它的 `装上(bridge, 数=, 开关=)`）不用改一行就能当车厢。

┌───────────────────────────────────────────────────────────────────┐
│ 三个设计决定，和为什么                                           │
└───────────────────────────────────────────────────────────────────┘
① **换轨 = 全列重排，不做「车上拆钩」**
   补丁是 setattr 覆盖类属性。两节车厢如果动了同一处，精准逆向摘一节
   极易留下半截状态。所以摘一节的动作是：**全部按逆序卸干净 → 从名单里
   划掉它 → 再按正序全挂回去**。代价是毫秒级，换来的是「当前状态永远
   可以从编组名单推导出来」——不会出现摘不干净的幽灵补丁。

② **换轨必须先过闸，违宪就自己退回原位（fail-closed）**
   车厢机制本质上给了「随便改内存」的能力，所以必须配一道闸。
   每次换轨后跑一遍 `宪法体检()`，四条不变量任何一条不过 →
   **把旧编组原样挂回去**，然后报告失败。绝不留在一个「不知道什么状态」
   的中间态上。宁可这次没挂上，也不留隐患。

③ **主链的顶层对象不许被换掉**
   改类的属性 = 外挂；换掉 `bridge.主` 本身 = 改主链。
   车钩在挂载前后各拍一张 `vars(bridge)` 的快照，**任何顶层对象的身份
   （id）发生变化就判违宪**。这样「主链零改动」不再只是一句自觉。

┌───────────────────────────────────────────────────────────────────┐
│ 用法                                                               │
└───────────────────────────────────────────────────────────────────┘
    python3 外挂/车钩.py                     按 编组.json 起车
    python3 外挂/车钩.py --空车              一节都不挂，裸脑起车
    python3 外挂/车钩.py --编组 动作面        指定编组起车
    python3 外挂/车钩.py --列                只列出发现到的车厢，不起车
    python3 外挂/车钩.py --验                只跑宪法体检，不起车
    python3 外挂/车钩.py --演练              走完全流程但不连 socket（验收用）

命令行遥控（脑在跑的时候用，这就是「随时连/断」）：
    python3 外挂/车钩ctl.py 编组              看现在挂了哪几节
    python3 外挂/车钩ctl.py 挂 受限脚本        热挂一节
    python3 外挂/车钩ctl.py 摘 受限脚本        热摘一节
    python3 外挂/车钩ctl.py 重排 受限脚本,动作面  重新排序
    python3 外挂/车钩ctl.py 验                重跑宪法体检
退出码：0 正常 / 2 自检或清单有问题 / 3 换轨失败 / 4 找不到主链
"""

import argparse
import importlib.util
import inspect
import json
import os
import socket
import sys
import threading
import time
import traceback
import weakref

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
外挂根 = os.path.dirname(os.path.abspath(__file__))
主链路 = os.path.join(ROOT, "bridge.py")
日志目录 = os.path.join(ROOT, "logs")
日志文件 = os.path.join(日志目录, "外挂-车钩.log")
插座路径 = os.path.join(外挂根, "车钩.sock")
编组文件 = os.path.join(外挂根, "编组.json")

# ── 车钩自己认的命令行开关，传主链之前必须摘掉 ──
自己的开关 = ("--空车", "--编组", "--列", "--验", "--演练", "--安静", "--json")

# ══════════════════════════════════════════════════════════════════
# 宪法基线 —— **这几个数从 bridge.py 抄来，抄错了这里就会红**
# ══════════════════════════════════════════════════════════════════
# 出处：bridge.py:1371（任务栈.允许动作）/ bridge.py:2491-2493（翻译器三件套）
# ★ 改主链 = 必须同步改这里，而且**会红给你看**。这就是它存在的意义。
基线_任务栈允许动作 = frozenset({
    "走到", "挖", "拾", "放", "打", "等", "说",
    "熔炉放料", "熔炉取成品", "wait_until",
})
基线_单步白名单 = frozenset({"follow", "goto", "say", "stop", "status", "friend"})
基线_禁止步骤_必须有 = frozenset({"打"})
基线_攻击类 = frozenset({"attack", "jumpattack", "strike", "打击"})


# ══════════════════════════ 记账 ══════════════════════════

_日志锁 = threading.Lock()


def 记(文本, 屏幕=True):
    """车钩自己的账本。**不写进主链的日志**，两本账分开。"""
    行 = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {文本}"
    with _日志锁:
        try:
            os.makedirs(日志目录, exist_ok=True)
            with open(日志文件, "a", encoding="utf-8") as f:
                f.write(行 + "\n")
        except Exception:
            pass
    if 屏幕:
        print(行, flush=True)


# ══════════════════════════ 车厢铭牌 ══════════════════════════

class 车厢:
    """一节车厢的**说明书**（不含代码本身）。"""

    def __init__(self, 目录, 清单):
        self.目录 = 目录
        self.清单 = 清单
        self.名 = str(清单.get("id") or os.path.basename(目录))
        self.全名 = str(清单.get("名字") or self.名)
        self.版本 = str(清单.get("版本") or "0")
        self.入口 = str(清单.get("入口") or "补丁.py")
        self.自检 = 清单.get("自检")
        self.依赖 = list(清单.get("依赖") or [])
        self.冲突 = list(清单.get("冲突") or [])
        self.补丁点 = list(清单.get("补丁点") or [])
        self.提供动作 = list(清单.get("提供动作") or [])
        self.顺序 = int(清单.get("顺序") or 50)
        self.开关键 = 清单.get("开关")          # 形如 "m7.expand_actions"
        # ★ 这节车厢在哪些类的**活实例**上留了缓存。车钩会盯住这些类的实例，
        #   换轨之后调它的 同步实例() 去刷新 —— 否则热挂就成了
        #   「你以为开了，其实活着的那个实例还拿着旧状态」（动作面声明的是 翻译器）。
        self.实例缓存 = list(清单.get("实例缓存") or [])
        # ★ 没有 卸下() 的车厢**不许热拔** —— 摘不干净的东西不能上车。
        self.可热拔 = bool(清单.get("可热拔", True))
        self.模块 = None                        # 载入后的入口模块
        self.自检模块 = None
        self.装载情况 = None                    # 上次 装上() 的返回

    def 入口路径(self):
        return os.path.join(self.目录, self.入口)

    def 说(self):
        return (f"{self.名}（{self.全名}）v{self.版本}"
                f"{' 可热拔' if self.可热拔 else ' 不可热拔'}"
                f"{' 提供动作：' + '、'.join(self.提供动作) if self.提供动作 else ''}")

    def 报文(self):
        return {
            "id": self.名, "名字": self.全名, "版本": self.版本,
            "依赖": self.依赖, "冲突": self.冲突,
            "提供动作": self.提供动作, "补丁点": self.补丁点,
            "可热拔": self.可热拔, "顺序": self.顺序,
            # ⚠ 「已挂」要认**开关** ✗ —— 光看"模块载进来了"会把"本趟不上车"报成已挂 ✓
            "已挂": self.模块 is not None and not getattr(self, "开关关着", False),
        }


def 发现车厢(根=None):
    """扫 `外挂/` 下面两层，谁有 manifest.json 谁就是车厢。

    返回 {名: 车厢}；同名或铭牌写坏 → 抛 清单错（fail-closed，不猜）。
    """
    根 = 根 or 外挂根
    找到 = {}
    坏 = []
    for 深度一 in sorted(os.listdir(根)):
        甲 = os.path.join(根, 深度一)
        if not os.path.isdir(甲) or 深度一.startswith((".", "__")):
            continue
        候选 = [(深度一, 甲)]
        for 深度二 in sorted(os.listdir(甲)):
            乙 = os.path.join(甲, 深度二)
            if os.path.isdir(乙) and not 深度二.startswith((".", "__")):
                候选.append((os.path.join(深度一, 深度二), 乙))
        for 标签, 目录 in 候选:
            牌 = os.path.join(目录, "manifest.json")
            if not os.path.isfile(牌):
                continue
            try:
                with open(牌, encoding="utf-8") as f:
                    清单 = json.load(f)
            except Exception as e:
                坏.append(f"{标签}/manifest.json 读不动：{e}")
                continue
            try:
                节 = 车厢(目录, 清单)
            except Exception as e:
                坏.append(f"{标签}/manifest.json 内容不对：{e}")
                continue
            if not os.path.isfile(节.入口路径()):
                坏.append(f"{节.名} 的入口 {节.入口} 不存在")
                continue
            if 节.名 in 找到:
                坏.append(f"车厢名重复：{节.名}（{找到[节.名].目录} 和 {目录}）")
                continue
            找到[节.名] = 节
    if 坏:
        raise 清单错("；".join(坏))
    return 找到


class 清单错(Exception):
    """铭牌有问题 —— 一律拒绝启动，不猜。"""


# ══════════════════════════ 载入车厢 ══════════════════════════

def _载模块(路径, 模块名):
    """**按文件路径**载模块，用独一无二的名字。

    ★ 为什么不能直接 `import 补丁`：两节车厢各有一个 `补丁.py`，
      在 sys.modules 里会撞名，后载的把先载的顶掉 —— 摘的时候就会
      摘到一个"其实不是它"的对象。所以名字必须带车厢 id。
    """
    spec = importlib.util.spec_from_file_location(模块名, 路径)
    if spec is None or spec.loader is None:
        raise 清单错(f"载不动 {路径}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[模块名] = mod
    spec.loader.exec_module(mod)
    return mod


def 载入车厢(节, 重载=True):
    """把车厢的入口模块和自检模块拉进内存（还没有打任何补丁）。"""
    if 节.目录 not in sys.path:
        # 车厢内部会 `import 数据` 这类同目录模块，得让它找得到
        sys.path.insert(0, 节.目录)
    键 = 节.名.replace("/", "_")
    if 节.模块 is None or 重载:
        节.模块 = _载模块(节.入口路径(), f"车厢_{键}_入口")
    if 节.自检:
        牌 = os.path.join(节.目录, 节.自检)
        if os.path.isfile(牌):
            节.自检模块 = _载模块(牌, f"车厢_{键}_自检")
    if not callable(getattr(节.模块, "装上", None)):
        raise 清单错(f"车厢「{节.名}」的 {节.入口} 里没有 装上() —— 拒绝上车")
    if not callable(getattr(节.模块, "卸下", None)):
        # 没有卸下 = 摘不干净 = 不许热拔（但还是能挂，只是得整列重启）
        节.可热拔 = False
    return 节


def _挑参数(函数, 候选):
    """按函数签名挑它认识的参数 —— 这就是车钩的接口标准。

    ★ 好处：老车厢 `装上(bridge, 数=, 开关=)` 和新车厢
      `装上(bridge, 车钩=, 开关=)` 都能直接上车，谁都不用改。
    """
    try:
        签名 = inspect.signature(函数)
    except (TypeError, ValueError):
        return {}
    认的 = set(签名.parameters)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in 签名.parameters.values()):
        return dict(候选)            # 声明了 **kw，全给它
    return {k: v for k, v in 候选.items() if k in 认的}


# ══════════════════════════ 列车 ══════════════════════════

class 换轨失败(Exception):
    """换轨没过闸 —— 已经退回原编组了。"""


class 列车:
    """车钩本体。**主链对象的身份在这里被看住。**"""

    def __init__(self, bridge, 安静=False):
        self.bridge = bridge
        self.安静 = 安静
        self.车厢表 = {}                 # 名 -> 车厢（发现到的全部）
        self.编组 = []                   # 名 -> 当前挂着的顺序
        self.锁 = threading.RLock()      # 换轨是独占操作
        self.顶层快照 = self._拍顶层()
        self.记事 = []                   # 换轨历史，给 ctl 看
        self.__数 = None                 # 懒加载的外置数据（车厢要了才读）
        self.__临时目录 = None

    # ── 实例探针 ──
    def _盯住(self, 类名):
        """盯住某个类**活着的实例**（WeakSet）。

        ★ 为什么非要有这东西：主链是在 `主()` **里面** new 出 任务栈 / 翻译器
          这些实例的，车钩拿不到那些局部变量。可热插拔偏偏要解决两类问题：

          ① 「这节车厢是不是正被一个在跑的任务用着」——
             要看**实例**上的 `任务`（类上根本没有）。
          ② ★ **热挂之后，活着的实例还拿着旧缓存**。
             最典型的就是 `翻译器.合法步骤`：它在 `__init__` 里存成**实例属性**
             （bridge.py:2503 `self.合法步骤 = set(允许动作)`）。
             也就是说，往一个**正在跑的**脑上热挂「动作面」，类属性
             `任务栈.允许动作` 是扩了，可**已经建好的翻译器**还拿着旧的 10 个
             动作 —— 模型写「合成」会被**静默拒掉**。
             这正是本项目最恨的失败方式：你以为开了，其实什么都没发生。
             所以必须能摸到活实例，才能把它们同步过来（见 `同步实例()`）。

        ⚠ 这不算改主链：被改的是 `bridge.任务栈` 这个**类**的属性，而宪法①
          看的是 `vars(bridge)` 里每个顶层对象的**身份** —— 类还是同一个类对象。
        """
        类 = getattr(self.bridge, 类名, None)
        if 类 is None:
            return False
        if hasattr(类, "_车钩原init"):
            return True                      # 已经盯过了
        原 = 类.__init__
        活 = weakref.WeakSet()

        def 新init(自己, *a, **k):
            原(自己, *a, **k)
            活.add(自己)

        类._车钩原init = 原
        类.车钩活着的实例 = 活
        类.__init__ = 新init
        return True

    def _装探针(self):
        """给「任务栈」和所有车厢声明的「实例缓存」类装上探针。

        ★ 必须赶在**任何实例被造出来之前**装好 —— 车钩是在 `bridge.主()`
          之前跑的，所以正好来得及。
        """
        self._盯住("任务栈")
        for 名 in sorted(self.车厢表):
            for 类名 in self.车厢表[名].实例缓存:
                self._盯住(类名)

    def 活实例(self, 类名):
        """这个类现在活着的实例（可能一个都没有，也可能好几个）。"""
        类 = getattr(self.bridge, 类名, None)
        活 = getattr(类, "车钩活着的实例", None) if 类 is not None else None
        return list(活) if 活 else []

    def _同步实例(self):
        """换轨之后调一遍：让每节车厢把自己关心的活实例同步到当前状态。

        ★ 车厢**可选**实现这个钩子（`同步实例(bridge, 日志=, 车钩=)`）。
          没实现 = 不关心实例缓存，不是错误。
        """
        for 名 in sorted(self.车厢表):
            节 = self.车厢表[名]
            if 节.模块 is None:
                continue
            钩 = getattr(节.模块, "同步实例", None)
            if not callable(钩):
                continue
            try:
                钩(self.bridge, **_挑参数(钩, {"日志": 记, "车钩": self}))
            except Exception as e:
                记(f"  ★「{节.名}」的 同步实例() 抛异常：{type(e).__name__}: {e}",
                   屏幕=not self.安静)

    # ── 懒加载的两样公共资源 ──
    @property
    def _数(self):
        """外置数据。★ 必须懒加载：起车时还没有车厢，读它纯属浪费。"""
        if self.__数 is None:
            self.__数 = _读数()
        return self.__数

    @property
    def _临时目录(self):
        if self.__临时目录 is None:
            import tempfile
            self.__临时目录 = tempfile.mkdtemp(prefix="车厢-")
        return self.__临时目录

    # ── 主链顶层对象守卫 ──
    def _拍顶层(self):
        """拍一张 `vars(bridge)` 的身份快照。

        ★ 改类的属性 = 外挂；换掉 `bridge.主` 本身 = 改主链。
          有了这张快照，「主链零改动」就不再只是自觉。
        """
        return {名: id(值) for 名, 值 in vars(self.bridge).items()
                if not 名.startswith("__")}

    def _顶层被动过(self):
        现 = self._拍顶层()
        坏 = []
        for 名, 号 in self.顶层快照.items():
            if 名 not in 现:
                坏.append(f"顶层对象「{名}」被删了")
            elif 现[名] != 号:
                坏.append(f"顶层对象「{名}」被**换掉了**（不是改属性，是换本体）")
        return 坏

    # ── 宪法体检 ──
    def 宪法体检(self, 名单=None):
        """四条不变量。任何一条不过 = 车厢在偷偷扩权，立刻退回。

        `名单` 参数：换轨途中要用**正在挂的那份名单**来算「上限」，
        因为这时 `self.编组` 还是旧的。
        （2026-10-07 第一版就栽在这儿：挂动作面时被误判成偷偷扩权。）
        """
        名单 = list(self.编组 if 名单 is None else 名单)
        问题 = []
        查了 = []
        br = self.bridge

        # ① 主链顶层对象一个都不许被换
        坏 = self._顶层被动过()
        查了.append(f"主链顶层对象 {len(self.顶层快照)} 个身份未变")
        if 坏:
            问题 += ["宪法①（不许换主链本体）：" + x for x in 坏]

        # ② 任务栈允许动作不许凭空变大
        栈 = getattr(br, "任务栈", None)
        允 = frozenset(getattr(栈, "允许动作", ()) or ())
        车厢给的 = frozenset()
        for 名 in 名单:
            if 名 in self.车厢表:
                车厢给的 |= frozenset(self.车厢表[名].提供动作)
        允许上限 = 基线_任务栈允许动作 | 车厢给的
        查了.append(f"任务栈.允许动作 {len(允)} 个 ≤ 上限 {len(允许上限)} 个")
        if not 基线_任务栈允许动作 <= 允:
            问题.append(f"宪法②（不许砍安全白名单）：允许动作丢了 "
                      f"{sorted(基线_任务栈允许动作 - 允)}")
        if not 允 <= 允许上限:
            问题.append(f"宪法②（不许偷偷扩权）：允许动作多出 "
                      f"{sorted(允 - 允许上限)}，但没有车厢声明「提供动作」里包含它")

        # ③ 攻击类动作永远不在单步白名单里（宪法第①条）
        译 = getattr(br, "翻译器", None)
        白 = frozenset(getattr(译, "单步白名单", ()) or ())
        攻 = frozenset(getattr(译, "攻击类", ()) or ())
        坏 = sorted(白 & 攻)
        查了.append(f"单步白名单 {len(白)} 个 ∩ 攻击类 {len(攻)} 个 = {len(坏)} 个")
        if 坏:
            问题.append(f"宪法③（攻击类永不在白名单）：{坏} 混进来了")
        if not 攻 >= 基线_攻击类:
            问题.append(f"宪法③（不许缩小攻击类）：少了 "
                      f"{sorted(基线_攻击类 - 攻)}")
        if not 白 <= 基线_单步白名单:
            问题.append(f"宪法③（不许扩单步白名单）：多出 {sorted(白 - 基线_单步白名单)}")

        # ④ 禁止步骤必须有「打」（宪法第②条）
        禁 = frozenset(getattr(译, "禁止步骤", ()) or ())
        查了.append(f"翻译器.禁止步骤 {len(禁)} 个，含「打」= {'打' in 禁}")
        if not 基线_禁止步骤_必须有 <= 禁:
            问题.append("宪法④（不许把「打」从禁止步骤里摘掉）")

        return {"好": not 问题, "问题": 问题, "查了": 查了}

    # ── 装配 ──
    def _开关值(self, 节):
        """车厢自己的开关，从 config.json 读。没声明开关 = 默认开。"""
        if not 节.开关键:
            return True, "车厢没声明开关（默认开）"
        路 = os.path.join(ROOT, "config.json")
        try:
            with open(路, encoding="utf-8") as f:
                配置 = json.load(f)
        except Exception as e:
            return False, f"读不到 config.json（{e}）—— 按「关」处理（fail-closed）"
        节段, _, 键 = 节.开关键.partition(".")
        有键 = (键 in (配置.get(节段) or {})) if 键 else (节段 in 配置)
        值 = (配置.get(节段) or {}).get(键, False) if 键 else 配置.get(节段, False)
        if not 有键:
            # ★★★ 2026-10-09：**申报了开关、可 config 里压根没有那一段** ✗
            #   原来这儿是**静默**的（按 fail-closed 判「关」，日志只印「开关=关」）✓
            #   实机后果（我栽的，而且判反了两次）：
            #     · 四节车厢（工具查表 / 回执探针 / 就地取材 / 声呐耳朵）
            #       从上线那天起**开关键一直没写** ✓ 日志里印着「开关=关」✓
            #     · 我照着那半个字读成「这节没在跑」✗ 可实际上它们**一直装着在干活** ✓
            #     · 换了个版本的车钩之后，「关」真变成"不挂"了 ✓
            #       要是还静默着，它们就会**不声不响地集体下线** ✗
            #   规矩：**配置缺了要说出来** ✗ —— 别只在日志里印半个字让人猜 ✓
            记(f"  ⚠⚠「{节.名}」声明了开关 `{节.开关键}`，可 **config.json 里没有这个键** ——"
              f" 按「关」处理（fail-closed）✓ 这一节**不会上车** ✓")
            记(f"     （要开就把它写进 config.json 的 `{节段}` 段 ✓ —— "
              f"2026-10-09 就是因为没写，四节车厢一直没上车 ✓）")
            return False, f"config.json **没有** `{节.开关键}`（按关处理）"
        return bool(值), f"config.json 的 {节.开关键}"

    def _挂一节(self, 名):
        节 = self.车厢表[名]
        if 节.模块 is None:
            载入车厢(节)
        开, 出处 = self._开关值(节)
        if not 开:
            # ★★★ 2026-10-09：「关」原来**只是告诉车厢一声** ✗
            #   而 `_挑参数` 对声明了 `**kw` 的 `装上()` 会把 `开关=False` **一起传过去** ✓
            #   → 车厢压根不看这个参数、照样装上、照样打补丁 ✗
            #   而日志里却印着「开关=关」→ **我照着日志把它读成了"这节没在跑"** ✗
            #   （2026-10-09 我因此把因果**判反了两次** ✓
            #     真相：那四节车厢**一直装着、一直在干活** ✓
            #     证据：`logs/回执.jsonl` 一直在写（回执探针的账本），
            #           而且那条卡住的任务**正是**「工具查表」在生效的铁证 ✓）
            #   规矩：**「关」= 这一节不上车** ✓
            #     不打一个补丁 ✓ 不占一个钩子 ✓ 装载情况如实记账 ✓
            #     （"关着"和"装了但不干活"是两回事 —— 别让日志里那半个字骗人 ✗）
            节.开关关着 = True
            节.装载情况 = {"好": True,
                          "为什么": f"开关关着（{出处}）—— 本趟不挂这一节", "打了": []}
            记(f"  挂「{节.名}」… 开关=关（{出处}）→ **这一节不挂**（一个补丁都不打）",
              屏幕=False)
            return 节.装载情况
        节.开关关着 = False
        if not self.安静:
            记(f"  挂「{节.名}」… 开关=开（{出处}）", 屏幕=False)
        try:
            r = 节.模块.装上(self.bridge, **_挑参数(
                节.模块.装上,
                {"数": self._数, "开关": 开, "车钩": self, "日志": 记,
                 "临时目录": self._临时目录}))
        except Exception as e:
            节.装载情况 = None
            raise 换轨失败(f"「{节.名}」装上() 抛异常：{type(e).__name__}: {e}"
                         f"\n{traceback.format_exc(limit=3)}")
        节.装载情况 = r
        if not isinstance(r, dict) or not r.get("好"):
            为啥 = (r or {}).get("为什么") if isinstance(r, dict) else "返回的不是字典"
            raise 换轨失败(f"「{节.名}」拒绝上车：{为啥}")
        return r

    def _卸一节(self, 名):
        节 = self.车厢表.get(名)
        if not 节 or 节.模块 is None:
            return
        卸 = getattr(节.模块, "卸下", None)
        if not callable(卸):
            记(f"  ★「{节.名}」没有 卸下() —— 摘不干净（这节不该被热拔）")
            return
        try:
            卸(self.bridge)
        except Exception as e:
            记(f"  ★「{节.名}」卸下() 抛异常：{type(e).__name__}: {e}")
        # ⚠ 模块**故意留着**（下次重挂不用重新载入）。但车厢自己的模块级
        #   `_已装` 必须由它自己的 `卸下()` 清掉 —— 没清掉的话，重挂时它会
        #   回一句「已经打过了」，换轨就会失败。那是车厢的 bug，会当场暴露。
        节.装载情况 = None

    def _全卸(self):
        """逆序卸干净 —— 后挂的先摘（栈的规矩）。"""
        for 名 in reversed(self.编组):
            self._卸一节(名)

    def _卸这些(self, 名单):
        """逆序卸**指定名单**（不是 `self.编组`）。

        ★ 换轨失败时用它。用 `_全卸()` 会去读 `self.编组`，而那还是旧名单 ——
          刚打上去的补丁一个都不会被摘下来。这个坑 2026-10-07 踩过。
        """
        for 名 in reversed(list(名单)):
            self._卸一节(名)

    def _退回去(self, 旧名单):
        """把车恢复到换轨之前的编组。退不回去就**大声喊人**。"""
        坏 = []
        for 名 in 旧名单:
            try:
                self._挂一节(名)
            except Exception as e2:
                坏.append(f"{名}（{e2}）")
        self.编组 = list(旧名单)
        if 坏:
            # 连退都退不回去 = 最坏情况。绝不假装没事。
            记(f"★★ 退回时这些车厢挂不上：{'、'.join(坏)}")
            记("★★ 现在车上是不确定状态 —— **请重启脑**（bash 外挂/启动列车.sh）")

    def _检查名单(self, 名单):
        """依赖、冲突、存在性 —— 上车前先查户口。"""
        名集 = set(名单)
        if len(名集) != len(名单):
            raise 换轨失败("编组名单里有重复：" + "、".join(名单))
        for 名 in 名单:
            if 名 not in self.车厢表:
                 raise 换轨失败(f"没有叫「{名}」的车厢。现有："
                             f"{'、'.join(sorted(self.车厢表)) or '（一节都没有）'}")
        for 名 in 名单:
            节 = self.车厢表[名]
            缺 = [d for d in 节.依赖 if d not in 名集]
            if 缺:
                raise 换轨失败(f"「{名}」依赖 {'、'.join(缺)} —— 但它们不在编组里")
            撞 = [c for c in 节.冲突 if c in 名集]
            if 撞:
                raise 换轨失败(f"「{名}」声明与 {'、'.join(撞)} 冲突，不能同挂")
            for d in 节.依赖:
                if 名单.index(d) > 名单.index(名):
                    raise 换轨失败(f"「{名}」必须排在它依赖的「{d}」后面")
            # 补丁点撞车：两节动同一处 → 警告（不拦，但要留痕）
        for i, 甲 in enumerate(名单):
            for 乙 in 名单[i + 1:]:
                撞 = set(self.车厢表[甲].补丁点) & set(self.车厢表[乙].补丁点)
                if 撞:
                    记(f"  ⚠ 「{甲}」和「{乙}」都声称动 {sorted(撞)} —— "
                        f"顺序会影响结果，请确认这是你要的", 屏幕=not self.安静)
        return True

    def 换轨(self, 新名单, 理由="手动"):
        """**这是整个车钩的核心动作**：全列重排 + 过闸 + 失败自动退回。

        步骤固定四拍：卸干净 → 按新名单挂 → 宪法体检 → 不过就退回原编组。
        """
        with self.锁:
            新名单 = list(新名单)
            self._检查名单(新名单)
            # ★ 探针要装在**最前面**，不能放在"编组没变就早退"后面 ——
            #   否则「空车起车」这条路上探针永远不会被装上，
            #   热挂的时候就摸不到活实例，同步就是空的。（2026-10-07 踩过）
            self._装探针()
            旧名单 = list(self.编组)
            if 新名单 == 旧名单:
                return {"好": True, "编组": 旧名单, "备注": "编组没变，什么都没做"}

            t0 = time.time()
            self._全卸()
            # ★ **已挂** 和 **编组** 必须分开记。
            #   （2026-10-07 第一版栽过：挂到一半失败时，我在退回里调 `_全卸()`，
            #     而它读的是 `self.编组` —— 那还是**旧名单**，于是刚打上去的
            #     越权补丁**一个都没被卸下来**，就那么留在内存里了。
            #     越权车厢的补丁留在内存 = 闸门形同虚设。这就是那次的教训。）
            已挂 = []
            try:
                for 名 in 新名单:
                    # ★ 先记账再挂：`装上()` 有可能是"打了三个补丁才抛异常"的，
                    #   那一节也必须进 `已挂`，否则它的半截补丁没人卸。
                    已挂.append(名)
                    self._挂一节(名)
            except 换轨失败 as e:
                # ★ 挂不上就**退回原样**，绝不留半挂状态
                记(f"★ 换轨失败（{e}）—— 退回原编组：{旧名单 or '空车'}")
                self._卸这些(已挂)
                self._退回去(旧名单)
                self._同步实例()            # ★ 同上：退回去了就同步活实例
                raise

            # ★ 挂完了，但**活着的实例**可能还拿着旧缓存
            #   （翻译器.合法步骤 就是实例属性 —— bridge.py:2503）。
            #   先同步活实例，再体检。
            self._同步实例()

            体检 = self.宪法体检(新名单)   # ★ 用**新名单**算上限，不是旧的
            if not 体检["好"]:
                # ★ 违宪 → 退回原编组。宁可这次没挂上，也不留隐患。
                记("★ 宪法体检没过 —— 先把刚挂上的**全卸干净**，再退回原编组：")
                for x in 体检["问题"]:
                    记(f"    {x}")
                self._卸这些(已挂)          # ★ 卸的是「刚挂上的」，不是「旧编组」
                self._退回去(旧名单)
                self._同步实例()            # ★ 退回去了，活实例也得跟着收回来
                raise 换轨失败("宪法体检没过（已退回）：" + "；".join(体检["问题"]))

            self.编组 = 新名单
            备注 = (f"{理由}：{旧名单 or '空车'} → {新名单 or '空车'}"
                  f"（{round((time.time() - t0) * 1000)} ms）")
            self.记事.append({"t": round(time.time(), 3), "备注": 备注})
            self._存编组()
            记("换轨完成 — " + 备注)
            for 条 in 体检["查了"]:
                记("  ✓ " + 条, 屏幕=False)
            for 名 in 新名单:
                节 = self.车厢表[名]
                for x in (节.装载情况 or {}).get("打了", []):
                    记("  + " + x, 屏幕=False)
            return {"好": True, "编组": list(self.编组), "备注": 备注,
                    "体检": 体检}

    # ── 热拔安全门 ──
    def 忙不忙(self, 名):
        """这节车厢正被一个在跑的任务用着吗？用着就**不许摘**。

        ★ 为什么需要：任务是异步推进的。把「合成」车厢摘掉的那一刻，
          如果正好有个合成任务跑到第 3 步，它下一拍就会去调一个
          已经不存在的动作 —— 卡死或者静默失败。
        """
        栈 = getattr(self.bridge, "任务栈", None)
        用着的 = frozenset(self.车厢表[名].提供动作)
        if not 用着的:
            return False, ""
        # ★ 扫**所有**活着的 任务栈 实例，任何一个在忙就算忙（保守优先）。
        坏的 = []
        for 实例 in self.活实例("任务栈"):
            任 = getattr(实例, "任务", None)
            if not 任 or 任.get("状态") not in ("跑", "暂停"):
                continue
            for 步 in (任.get("步骤") or []):
                if isinstance(步, dict) and 步.get("动作") in 用着的:
                    坏的.append(f"任务 {任.get('id')} 第 {任.get('第几步')} 步"
                              f"正在用「{步.get('动作')}」（{名} 提供）")
        return (True, 坏的[0]) if 坏的 else (False, "")

    def 挂(self, 名):
        with self.锁:
            # ★ 认不出来就**重新扫一遍磁盘** —— 车厢可能是刚写好的。
            #   原来车厢表只在起车时发现一次，于是「新车厢热挂」永远失败，
            #   只能重启脑。（2026-10-07 实机撞到：挂了半天说「没有叫生存常识的车厢」。）
            if 名 not in self.车厢表:
                try:
                    for 新名, 节 in 发现车厢().items():
                        self.车厢表.setdefault(新名, 节)
                    if 名 in self.车厢表:
                        记(f"重新扫盘发现新车厢：{名}")
                except 清单错 as e:
                    记(f"重新扫盘时清单有问题：{e}")
            if 名 in self.编组:
                return {"好": True, "编组": list(self.编组), "备注": f"{名} 已经在车上了"}
            if 名 not in self.车厢表:
                raise 换轨失败(f"没有叫「{名}」的车厢")
            # 插进名单：按 顺序 字段排，同序就排在最后
            新 = list(self.编组) + [名]
            return self.换轨(self._排序(新), 理由=f"挂上 {名}")

    def 摘(self, 名):
        with self.锁:
            if 名 not in self.编组:
                return {"好": True, "编组": list(self.编组), "备注": f"{名} 本来就不在车上"}
            节 = self.车厢表[名]
            if not 节.可热拔:
                raise 换轨失败(f"「{名}」没有 卸下() —— 摘了会留半截补丁，"
                             f"只能整列重启（不是我不让摘，是摘不干净）")
            # 依赖它的车厢也不许留在车上
            还依赖 = [x for x in self.编组
                     if x != 名 and 名 in self.车厢表[x].依赖]
            if 还依赖:
                raise 换轨失败(f"「{'、'.join(还依赖)}」还依赖着 {名}，"
                             f"先把它们摘了（或在同一批里一起摘）")
            忙, 为啥 = self.忙不忙(名)
            if 忙:
                raise 换轨失败(f"先停任务再摘：{为啥}")
            return self.换轨([x for x in self.编组 if x != 名], 理由=f"摘下 {名}")

    def 重排(self, 名单):
        with self.锁:
            return self.换轨(list(名单), 理由="重排")

    def _排序(self, 名单):
        return sorted(名单, key=lambda n: (self.车厢表[n].顺序, 名单.index(n)))

    def 试试热摘(self, 名单):
        """一次摘多节（原子操作）—— 供 ctl 的 `摘 a,b` 用。"""
        with self.锁:
            for 名 in 名单:
                if 名 not in self.编组:
                    continue
                节 = self.车厢表[名]
                if not 节.可热拔:
                    raise 换轨失败(f"「{名}」不可热拔（没有 卸下()）")
                忙, 为啥 = self.忙不忙(名)
                if 忙:
                    raise 换轨失败(f"先停任务再摘「{名}」：{为啥}")
            剩 = [x for x in self.编组 if x not in 名单]
            for x in 剩:
                缺 = [d for d in self.车厢表[x].依赖 if d in 名单]
                if 缺:
                    raise 换轨失败(f"「{x}」还依赖着 {'、'.join(缺)}")
            return self.换轨(剩, 理由=f"摘下 {'、'.join(名单)}")

    # ── 持久化 ──
    def _存编组(self):
        try:
            with open(编组文件, "w", encoding="utf-8") as f:
                json.dump({"编组": self.编组,
                           "更新时间": time.strftime("%Y-%m-%d %H:%M:%S")},
                          f, ensure_ascii=False, indent=1)
        except Exception as e:
            记(f"编组存不下（{e}）—— 不影响运行")

    def 读编组(self):
        try:
            with open(编组文件, encoding="utf-8") as f:
                单 = json.load(f).get("编组")
            if isinstance(单, list) and all(isinstance(x, str) for x in 单):
                return 单
        except Exception:
            pass
        return None

    def 报单(self):
        return {
            "编组": list(self.编组),
            "车厢": [self.车厢表[n].报文() for n in self.编组],
            "全部车厢": [self.车厢表[n].报文() for n in sorted(self.车厢表)],
            "体检": self.宪法体检(),
        }


# ══════════════════════════ 控制插座 ══════════════════════════
# 「随时连/断」靠的就是这个：脑在跑的时候，另开一个终端发命令。

class 插座:
    """Unix socket + NDJSON 一问一答。权限 0600，只给本机这个用户。"""

    def __init__(self, 列车, 路径=插座路径):
        self.列车 = 列车
        self.路径 = 路径
        self.线程 = None
        self.停 = threading.Event()
        self.srv = None

    def _处理(self, 请求):
        cmd = str(请求.get("cmd") or "")
        try:
            if cmd == "编组":
                return {"ok": True, **self.列车.报单()}
            if cmd == "挂":
                名 = str(请求.get("名") or "")
                if not 名:
                    return {"ok": False, "错": "要摘/挂哪一节？给个名"}
                return {"ok": True, **self.列车.挂(名)}
            if cmd == "摘":
                名 = str(请求.get("名") or "")
                多个 = [x.strip() for x in 名.split(",") if x.strip()]
                if not 多个:
                    return {"ok": False, "错": "要摘哪一节？给个名"}
                return {"ok": True, **self.列车.试试热摘(多个)}
            if cmd == "重排":
                单 = 请求.get("顺序") or []
                if not isinstance(单, list):
                    return {"ok": False, "错": "顺序要是个列表"}
                return {"ok": True, **self.列车.重排([str(x) for x in 单])}
            if cmd == "验":
                体检 = self.列车.宪法体检()
                return {"ok": 体检["好"], "体检": 体检,
                        "编组": list(self.列车.编组),
                        "车厢": [self.列车.车厢表[n].报文() for n in self.列车.编组]}
            if cmd == "记事":
                return {"ok": True, "记事": self.列车.记事[-20:]}
            if cmd == "查":
                名 = str(请求.get("名") or "")
                if 名 not in self.列车.车厢表:
                    return {"ok": False, "错": f"没有叫「{名}」的车厢"}
                return {"ok": True, "车厢": self.列车.车厢表[名].报文()}
            return {"ok": False, "错": f"不认识的命令「{cmd}」"}
        except 换轨失败 as e:
            return {"ok": False, "错": str(e)}
        except Exception as e:
            return {"ok": False, "错": f"{type(e).__name__}: {e}",
                    "栈": traceback.format_exc(limit=4)}

    def 起(self):
        if os.path.exists(self.路径):
            os.unlink(self.路径)
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(self.路径)
        os.chmod(self.路径, 0o600)
        self.srv.listen(8)
        self.srv.settimeout(0.5)
        self.线程 = threading.Thread(target=self._转, daemon=True,
                                     name="车钩插座")
        self.线程.start()
        记(f"控制插座已就位：{os.path.relpath(self.路径, ROOT)}（0600）")
        return self

    def _转(self):
        while not self.停.is_set():
            try:
                连接, _ = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                with 连接:
                    连接.settimeout(10)
                    缓冲 = b""
                    while b"\n" not in 缓冲:
                        块 = 连接.recv(4096)
                        if not 块:
                            break
                        缓冲 += 块
                    if b"\n" not in 缓冲:
                        continue
                    行 = 缓冲.split(b"\n", 1)[0].decode("utf-8", "replace")
                    请求 = json.loads(行)
                    应答 = self._处理(请求)
                    连接.sendall((json.dumps(应答, ensure_ascii=False) + "\n")
                                 .encode("utf-8"))
            except Exception as e:
                记(f"插座出错（不影响脑）：{type(e).__name__}: {e}", 屏幕=False)

    def 收(self):
        self.停.set()
        try:
            if self.srv:
                self.srv.close()
        except Exception:
            pass
        try:
            if os.path.exists(self.路径):
                os.unlink(self.路径)
        except Exception:
            pass


# ══════════════════════════ 主入口 ══════════════════════════

def _读数():
    """外置数据（数据.py）—— 只有声明要它的车厢才拿得到。"""
    try:
        import importlib
        数据模块 = importlib.import_module("数据")
        importlib.reload(数据模块)
        return 数据模块.载入()
    except Exception as e:
        记(f"外置数据读不了（{type(e).__name__}: {e}）", 屏幕=False)
        return None


def 主():
    ap = argparse.ArgumentParser(description="外挂列车·车钩", add_help=True)
    ap.add_argument("--空车", action="store_true", help="一节都不挂，裸脑起车")
    ap.add_argument("--编组", default=None, help="逗号分隔的车厢名，按此顺序挂")
    ap.add_argument("--列", action="store_true", help="只列出发现到的车厢")
    ap.add_argument("--验", action="store_true", help="只跑宪法体检，不起车")
    ap.add_argument("--演练", action="store_true",
                    help="走完全流程但不连 socket、不起主循环（验收用）")
    ap.add_argument("--安静", action="store_true")
    ap.add_argument("--json", action="store_true")
    # ★ 用 parse_known_args：**车钩自己不认识的参数原样留给主链**。
    #   （第一版这里我忘了调用它，`参` 还是个 ArgumentParser，当场 AttributeError。）
    参, 剩下 = ap.parse_known_args()

    # ── ① 主链在不在（fail-closed 第一道）──
    if not os.path.isfile(主链路):
        记(f"★ 找不到主链：{主链路}")
        print(f"\n❌ 找不到主链 {主链路}", file=sys.stderr)
        return 4

    # ── ② 发现车厢 ──
    try:
        表 = 发现车厢()
    except 清单错 as e:
        记(f"★ 车厢清单有问题，拒绝启动：{e}")
        print(f"\n❌ 车厢清单有问题：{e}", file=sys.stderr)
        return 2

    if 参.列:
        print(f"发现 {len(表)} 节车厢：")
        for 名 in sorted(表, key=lambda n: (表[n].顺序, n)):
            节 = 表[名]
            print(f"  {节.名:12s} {节.全名}")
            print(f"   　入口 {节.入口}｜顺序 {节.顺序}｜"
                  f"{'可热拔' if 节.可热拔 else '**不可热拔**'}"
                  f"｜{'依赖 ' + '、'.join(节.依赖) if 节.依赖 else '无依赖'}"
                  f"｜{'提供 ' + '、'.join(节.提供动作) if 节.提供动作 else '不提供动作'}")
            if 节.补丁点:
                print(f"   　补丁点 {'、'.join(节.补丁点)}")
        return 0

    # ── ③ 进主链 ──
    sys.path.insert(0, os.path.dirname(外挂根))
    import bridge

    列 = 列车(bridge, 安静=参.安静)
    列.车厢表 = 表

    if 参.验:
        体检 = 列.宪法体检()
        if 参.json:
            print(json.dumps(体检, ensure_ascii=False, indent=1))
        else:
            print("宪法体检：" + ("✅ 全过" if 体检["好"] else "❌ 有问题"))
            for x in 体检["查了"]:
                print("  ✓ " + x)
            for x in 体检["问题"]:
                print("  ✗ " + x)
        return 0 if 体检["好"] else 2

    # ── ④ 定编组 ──
    if 参.空车:
        名单 = []
    elif 参.编组:
        名单 = [x.strip() for x in 参.编组.split(",") if x.strip()]
    else:
        名单 = 列.读编组()
        if 名单 is None:
            # 第一次：默认把发现到的车厢全挂上（按顺序）
            名单 = 列._排序(list(表))

    记(f"车钩启动：发现 {len(表)} 节车厢，本趟编组 {'、'.join(名单) or '（空车）'}")

    try:
        结果 = 列.换轨(名单, 理由="起车")
    except 换轨失败 as e:
        记(f"★ 起车失败：{e}")
        print(f"\n❌ 起车失败：{e}", file=sys.stderr)
        return 3

    if not 参.安静:
        print(f"🚂 编组：{' + '.join(列.编组) or '（空车）'}")

    if 参.演练:
        体检 = 列.宪法体检()
        穿 = 插座(列, 路径=os.path.join(外挂根, "车钩.演练.sock")).起()
        try:
            print(json.dumps({
                "编组": list(列.编组),
                "体检": 体检["好"],
                "体检详": 体检,
                "报单": 列.报单()["车厢"],
            }, ensure_ascii=False, indent=1))
        finally:
            穿.收()
        记(f"【演练】到此为止：编组 {列.编组}、宪法体检 {'过' if 体检['好'] else '不过'}。"
            f"**没有起主循环。**")
        return 0

    # ── ⑤ 起控制插座，然后交棒 ──
    穿 = 插座(列).起()
    try:
        记("交棒给主链 bridge.主()")
        bak = sys.argv
        try:
            sys.argv = [主链路] + 剩下
            return bridge.主() or 0
        finally:
            sys.argv = bak
    finally:
        穿.收()


# ★ 这里**不要**写 `列车 = None` —— 会和上面的同名类撞车，把类遮住。
#   （2026-10-07 踩过：`TypeError: 'NoneType' object is not callable`。）
#   插座线程自己持着列车对象的引用，不需要模块级全局。

if __name__ == "__main__":
    sys.exit(主())
