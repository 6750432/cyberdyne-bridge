#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M7b·动作面外挂 —— 锚点自检。

┌───────────────────────────────────────────────────────────────┐
│ 这个文件是干什么的                                             │
└───────────────────────────────────────────────────────────────┘
这个外挂是靠「运行时打补丁」给脑侧加本事的：import bridge 之后，在**内存里**
改那几个类的属性/方法，磁盘上的 bridge.py 一个字节都不动。

它活着的前提只有一个：**主链的内部结构没变**（类还在、方法还在、
prompt 里那几句关键话还在）。

所以启动之前先把要挂的锚点逐条查一遍 —— **少任何一条就拒绝启动**。

★ 为什么非要这么较真：
  「悄悄不生效」是这个项目最怕的失败模式。
  2026-09-29 那次 availableGeometry() 返回 0×0，导致一个像素都画不出来，
  而日志里「重绘 47 次、每次 25 ms」一切正常 —— 静默失败比当场崩掉危险得多。
  锚点对不上，就要当场喊出来。

用法：
    python3 外挂/动作面/自检.py             人看的清单
    python3 外挂/动作面/自检.py --json      机器看的 json
退出码：0 = 锚点齐全；1 = 有缺（外挂必须拒绝启动）
"""

import argparse
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
外挂目录 = os.path.dirname(os.path.abspath(__file__))


# ══════════════════════════ 检查器 ══════════════════════════

class 自检器:
    def __init__(self):
        self.通过 = []
        self.失败 = []
        self.注 = []
        self.组 = ""

    def 起组(self, 名):
        self.组 = 名
        self.通过.append(("组", 名))

    def 断言(self, 名, 条件, 实际=None, 备注=None):
        条 = {"组": self.组, "名": 名, "好": bool(条件), "备注": 备注}
        if 条件:
            self.通过.append(条)
        else:
            self.失败.append({**条, "实际": 实际})
        return bool(条件)

    def 记注释(self, 文本):
        self.注.append({"组": self.组, "文本": 文本})

    @property
    def 条数(self):
        return len([x for x in self.通过 if x != ("组", self.组) and not (isinstance(x, tuple))
                    and x.get("名")])


# ══════════════════════════ 正题 ══════════════════════════

def 跑自检(打日志=print):
    查 = 自检器()

    # ── 先看主链文件在不在（这条最要紧：改名了必须当场拒绝）──
    主链 = os.path.join(ROOT, "bridge.py")
    查.起组("A 主链文件与模块")
    在 = os.path.isfile(主链)
    查.断言("bridge.py 就在 REPO 根目录下", 在, 主链)
    if not 在:
        查.记注释(f"找不到 {主链}")
        return 查

    with open(主链, "rb") as f:
        指纹 = hashlib.sha256(f.read()).hexdigest()
    查.记注释(f"主链指纹 sha256 = {指纹[:16]}…（{os.path.getsize(主链)} 字节）")

    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    try:
        import bridge
    except Exception as e:
        # ★ 这一条就是 fail-closed 的入口：主链不在 / 坏了 → 直接判死
        查.断言("bridge 模块能导入", False, f"{type(e).__name__}: {e}")
        return 查
    查.断言("bridge 模块能导入", True)

    查.断言("bridge.主 是函数（外挂要调它进主循环）", callable(getattr(bridge, "主", None)))
    查.断言("bridge.时刻 是函数（外挂说人话要打时间戳）", callable(getattr(bridge, "时刻", None)))

    # ── B 任务栈：第 3 步要挂的东西全在这儿 ──
    查.起组("B 任务栈（第 3 步挂这里）")
    栈 = getattr(bridge, "任务栈", None)
    查.断言("bridge.任务栈 是类", isinstance(栈, type))
    if isinstance(栈, type):
        for 名 in ("启用", "_数", "接", "在跑", "_看完成了没", "_下发", "_挂探针", "_撤探针",
                   "_记", "_失败", "_整任务失败", "_整任务完成", "_补全步骤", "进度一句话"):
            查.断言(f"任务栈.{名}() 在", callable(getattr(栈, 名, None)))
        允许 = getattr(栈, "允许动作", None)
        查.断言("任务栈.允许动作 是 frozenset（那份「锁」还在）",
                isinstance(允许, frozenset), type(允许).__name__)
        if isinstance(允许, frozenset):
            查.记注释("基线允许动作：" + "、".join(sorted(允许)))
            野 = sorted({"合成", "箱子里取", "往箱子里放"} & set(允许))
            查.断言("基线里**没有**扩展动作（说明还没被谁补过，不会补重）",
                    not 野, 野)

    # ── C 指令层：第 4 步要挂的三条口令 ──
    查.起组("C 指令层（第 4 步挂这里）")
    指 = getattr(bridge, "指令层", None)
    查.断言("bridge.指令层 是类", isinstance(指, type))
    if isinstance(指, type):
        for 名 in ("解析", "_含", "_尾", "归一名字", "口语名", "物品名"):
            查.断言(f"指令层.{名} 在", hasattr(指, 名))
        表 = getattr(指, "物品名", None)
        if isinstance(表, dict):
            查.记注释(f"基线物品名字典 {len(表)} 条（第 2 步要外置成 data/items_map.json）")
            查.断言("基线物品名字典不是空的（外置之后要能覆盖它）", len(表) > 0)
        else:
            查.断言("指令层.物品名 是字典", False, type(表).__name__)

    # ── D 翻译器：第 4 步要挂 prompt 片段 ──
    查.起组("D 翻译器（第 4 步挂 prompt）")
    译 = getattr(bridge, "翻译器", None)
    查.断言("bridge.翻译器 是类", isinstance(译, type))
    if isinstance(译, type):
        for 名 in ("组Prompt", "收输出", "_数", "单步白名单"):
            查.断言(f"翻译器.{名} 在", hasattr(译, 名))

    # ── E prompt 里的"整句锚点"（第 4 步要整句替换，所以必须查源码文本）──
    查.起组("E prompt 整句锚点（第 4 步要替换它）")
    with open(主链, encoding="utf-8") as f:
        源码 = f.read()
    for 句子, 最少 in (("【任务书的步骤类型】", 1), ("只能用这九个词", 1)):
        n = 源码.count(句子)
        查.断言(f"主链源码里有「{句子}」（≥{最少} 次）", n >= 最少, f"实际 {n} 次")
        if 句子 == "只能用这九个词" and n == 2:
            查.记注释("这句子在主链里出现 2 次 —— 是 M5/M6 留下的重复行，"
                      "既有小毛病，外挂替换时会一起处理")

    # ── F 配置 ──
    查.起组("F 配置")
    配置路 = os.path.join(ROOT, "config.json")
    try:
        with open(配置路, encoding="utf-8") as f:
            配置 = json.load(f)
        好 = True
    except Exception as e:
        配置 = {}
        好 = False
        查.断言("config.json 能读", False, str(e))
    if 好:
        查.断言("config.json 能读", True)
        m7 = 配置.get("m7") or {}
        查.断言("config.json 里有 m7.expand_actions（外挂的那道开关）",
                isinstance(m7.get("expand_actions"), bool), m7.get("expand_actions"))
        查.断言("config.json 里有 m7.memory_enable（M7a 的开关还在）",
                "memory_enable" in m7)

    # ── G 手侧那只手真的在（跨进程交叉检查）──
    查.起组("G 手侧交叉检查（脑要挂本事，手得真的会）")
    手路 = os.path.join(ROOT, "node", "plugins", "body", "proto_body.js")
    if os.path.isfile(手路):
        with open(手路, encoding="utf-8") as f:
            手源 = f.read()
        for 词 in ("chest_take", "chest_put", "危险物品", "找箱子"):
            查.断言(f"身体插件里有「{词}」", 词 in 手源)
        查.记注释("这四条在说明：手侧已经按 M2 规矩把箱子本事放在插件里了，"
                  "脑侧外挂补上之后才有意义")
    else:
        查.断言("身体插件 proto_body.js 在", False, 手路)

    服路 = os.path.join(ROOT, "node", "server.js")
    if os.path.isfile(服路):
        with open(服路, encoding="utf-8") as f:
            服源 = f.read()
        查.断言("手侧主链有插件挂载点（身体插件.能力()）", "身体插件" in 服源 and "能力()" in 服源)
        查.断言("手侧主链的动词表**没有**为 chest_* 开 case（新能力不许进主链）",
                "case 'chest_take'" not in 服源 and "case 'chest_put'" not in 服源)

    # ── H 宪法没被削弱（外挂绝不碰这三条）──
    查.起组("H 宪法检查（外挂一个字都不许动这三条）")
    if isinstance(译, type):
        禁 = getattr(译, "禁止步骤", None)
        查.断言("翻译器.禁止步骤 里有「打」（宪法第②条）",
                isinstance(禁, (set, frozenset)) and "打" in 禁, 禁)
        攻 = getattr(译, "攻击类", None)
        查.断言("翻译器.攻击类 不是空的（宪法第①条）",
                isinstance(攻, (set, frozenset)) and len(攻) > 0, 攻)
        白 = getattr(译, "单步白名单", None)
        查.断言("翻译器.单步白名单 里**没有**攻击类动作",
                isinstance(白, (set, frozenset)) and not (set(白) & set(攻 or ())),
                sorted(set(白 or ()) & set(攻 or ())))

    # ── I 别重复打补丁 ──
    查.起组("I 补丁状态")
    查.断言("bridge 模块上还没有外挂的记号（没打过补丁）",
            not hasattr(bridge, "_动作面外挂"))

    # ── J~M 外置数据（第 2 步）：四份数据 + 跟主链/手侧的核对，全在 数据.py 里 ──
    try:
        if 外挂目录 not in sys.path:
            sys.path.insert(0, 外挂目录)
        import importlib
        数据模块 = importlib.import_module("数据")
        importlib.reload(数据模块)
        数据模块.核对(查, bridge)
    except Exception as e:
        查.起组("J 外置数据")
        查.断言("外置数据模块（数据.py）能加载", False, f"{type(e).__name__}: {e}")

    # ── N 补丁要挂的方法签名（第 3 步）──
    # 补丁是靠"换掉同名方法"工作的，而它得按**位置**拿到参数（步 / 任 / 现在 / s）。
    # 主链哪天给某个方法改个参数名、或者换了顺序，补丁就会静默错位 ——
    # 所以把参数名逐个钉住，对不上就拒绝启动。
    查.起组("N 补丁要挂的方法签名（对不上就拒绝启动）")
    if isinstance(栈, type):
        import inspect
        想要 = {
            "接": ["self", "名字", "步骤", "s"],
            "_看完成了没": ["self", "步", "s", "任"],
            "_下发": ["self", "步", "任", "现在", "s"],
            "_挂探针": ["self", "步骤", "s"],
        }
        for 名, 参 in 想要.items():
            函 = getattr(栈, 名, None)
            try:
                实 = list(inspect.signature(函).parameters) if callable(函) else None
            except (TypeError, ValueError):
                实 = None
            查.断言(f"任务栈.{名} 的参数名还是 {参}", 实 == 参, 实)
    # 第 4 步还要挂这两个（指令层口令 + prompt 包壳）
    指类, 译类 = getattr(bridge, "指令层", None), getattr(bridge, "翻译器", None)
    if 指类 is not None:
        函 = getattr(指类, "解析", None)
        实 = list(__import__("inspect").signature(函).parameters) if callable(函) else None
        查.断言("指令层.解析 的参数名还是 ['self', '说话人', '原文']",
                实 == ["self", "说话人", "原文"], 实)
    if 译类 is not None:
        函 = getattr(译类, "组Prompt", None)
        实 = list(__import__("inspect").signature(函).parameters) if callable(函) else None
        查.断言("翻译器.组Prompt 的参数名还是 ['self','s','用途','任务状况','说话人','原话']",
                实 == ["self", "s", "用途", "任务状况", "说话人", "原话"], 实)

    return 查


# ══════════════════════════ 输出 ══════════════════════════

def 打印(查):
    print("═══ M7b·动作面外挂 · 锚点自检 ═══")
    print(f"主链：{os.path.join(ROOT, 'bridge.py')}")
    print(f"外挂：{外挂目录}")
    print()
    组 = None
    for 条 in 查.通过:
        if isinstance(条, tuple) and 条[0] == "组":
            组 = 条[1]
            print(f"\n【{组}】")
            continue
        print(f"  ✅ {条['名']}")
    for 条 in 查.失败:
        if 组 != 条["组"]:
            pass
    if 查.失败:
        print("\n──────── 缺的锚点（这些不补齐，外挂一律拒绝启动）────────")
        for 条 in 查.失败:
            print(f"  ❌ 【{条['组']}】{条['名']}")
            if 条.get("实际") is not None:
                print(f"       实际：{条['实际']}")
    if 查.注:
        print("\n──────── 备注 ────────")
        for 条 in 查.注:
            print(f"  · {条['文本']}")
    总 = len([x for x in 查.通过 if isinstance(x, dict)]) + len(查.失败)
    print("\n" + "─" * 46)
    print(f"锚点 {总} 条：通过 {总 - len(查.失败)}，失败 {len(查.失败)}")
    if 查.失败:
        print("❌ 自检没过 —— 外挂拒绝启动。（这是故意的：宁可当场不干活，"
              "也不要悄悄少挂一个补丁。）")
    else:
        print("✅ 锚点齐全 —— 外挂可以挂上去了。")


def 主():
    ap = argparse.ArgumentParser(description="M7b 动作面外挂 · 锚点自检")
    ap.add_argument("--json", action="store_true", help="按 json 输出（给机器看）")
    ap.add_argument("--安静", action="store_true", help="只出结果，不出清单")
    参 = ap.parse_args()

    查 = 跑自检()
    总 = len([x for x in 查.通过 if isinstance(x, dict)]) + len(查.失败)
    if 参.json:
        print(json.dumps({
            "通过": [x["名"] for x in 查.通过 if isinstance(x, dict)],
            "失败": [{"组": x["组"], "名": x["名"], "实际": str(x.get("实际"))} for x in 查.失败],
            "备注": [x["文本"] for x in 查.注],
            "总": 总, "失败数": len(查.失败),
        }, ensure_ascii=False, indent=1))
    elif 参.安静:
        print(f"锚点 {总} 条：通过 {总 - len(查.失败)}，失败 {len(查.失败)}")
    else:
        打印(查)
    return 1 if 查.失败 else 0


if __name__ == "__main__":
    sys.exit(主())
