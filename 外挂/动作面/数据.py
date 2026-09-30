#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M7b·动作面外挂 —— 外置数据的加载与校验（第 2 步）。

┌───────────────────────────────────────────────────────────────┐
│ 为什么要有这个文件                                             │
└───────────────────────────────────────────────────────────────┘
主人在第 2 步的要求：把词表和 prompt 片段从代码里剥离出来。

  data/items_map.json      物品口语名 → MC 物品名
  prompts/步骤清单.txt       【任务书的步骤类型】那一行
  prompts/动作词表.txt       prompt 里「只能用这 N 个词」的那 N 个词
  prompts/危险物品.txt       绝对不碰的东西（fail-closed）

★ 但"剥离"不等于"搬个家就完事"。数据一旦离开代码，就会**跟代码漂移**：
  改了主链的动作表、忘了改 txt；改了手侧的危险物品名单、忘了改这边。
  漂移的后果是静默的 —— 小家伙以为自己做得到，其实做不到。

  所以这个模块的看家本事是**核对**：每一条都拿"真相"去比。
    · 物品名 / 危险物品  → 拿 minecraft-data 的 pc/<版本>/items.json 比
      （这份 json 就是手侧 require('minecraft-data') 读的同一份，已实测
        两边都报 1333 个物品，见 2026-10-01 第 2 步报告）
    · 动作词表[基础]     → 拿主链 `任务栈.允许动作` 这个 frozenset 比
    · 步骤清单[基础]     → 拿动作词表[基础] 比（两边得对得上）
    · 危险物品           → 拿手侧 proto_body.js 里那份 Set 比
  任何一条对不上：**当场报错**，不静默、不"凑合能用"。

用法：
    python3 外挂/动作面/数据.py            人看的摘要
    python3 外挂/动作面/数据.py --json     机器看
"""

import argparse
import json
import os
import re
import sys

外挂目录 = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(外挂目录))

数据文件 = os.path.join(外挂目录, "data", "items_map.json")
prompt目录 = os.path.join(外挂目录, "prompts")
手侧插件 = os.path.join(ROOT, "node", "plugins", "body", "proto_body.js")


class 数据错(Exception):
    """数据有问题 —— 加载失败，外挂必须拒绝启动。"""


# ══════════════════════════ 一、基础读取 ══════════════════════════

def 读配置():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def 版本():
    """MC 版本 —— 跟手侧同一个出处（config.json 的 mc_version，
    手侧 node/server.js 也是读这个喂给 mineflayer 的）。"""
    return str(读配置().get("mc_version") or "1.21.1")


_物品表缓存 = {}


def 物品表(版=None):
    """手侧 minecraft-data 里这个版本的**全部物品名**。

    直接读 node_modules 里那份 json —— 不启 node 子进程（零依赖、毫秒级）。
    实测过：这份 json 和 `require('minecraft-data')('1.21.1')` 报的都是 1333 个。
    """
    版 = 版 or 版本()
    if 版 in _物品表缓存:
        return _物品表缓存[版]
    路 = os.path.join(ROOT, "node", "node_modules", "minecraft-data",
                      "minecraft-data", "data", "pc", 版, "items.json")
    if not os.path.isfile(路):
        raise 数据错(f"找不到 minecraft-data 的物品表：{路}\n"
                     f"  （这份数据是手侧认名字的依据；没有它就没法校验）")
    with open(路, encoding="utf-8") as f:
        表 = json.load(f)
    名 = {x["name"] for x in 表 if isinstance(x, dict) and x.get("name")}
    if len(名) < 100:
        raise 数据错(f"物品表只有 {len(名)} 条，看着不像完整的 items.json")
    _物品表缓存[版] = 名
    return 名


def _读分段文本(路, 默认节="全部"):
    """读 prompts 里那种带 [小节] 的 txt。返回 {小节名: [行…]}。

    # 开头的行是注释；[xxx] 开一个新小节。
    ★ 没有小节的文件（比如 危险物品.txt，本来就是一行一个名字）也能读 ——
      小节头之前的内容归到 `默认节` 里。2026-10-01 第一版没留这个后门，
      直接报「'tnt' 行不在任何 [小节] 里」，当场抓到。
    """
    if not os.path.isfile(路):
        raise 数据错(f"找不到 {路}")
    出, 当前 = {}, 默认节
    with open(路, encoding="utf-8") as f:
        for 行 in f:
            秃 = 行.strip()
            if not 秃 or 秃.startswith("#"):
                continue
            if 秃.startswith("[") and 秃.endswith("]"):
                当前 = 秃[1:-1].strip()
                出.setdefault(当前, [])
                continue
            出.setdefault(当前, []).append(秃)
    return {k: v for k, v in 出.items()}


# ══════════════════════════ 二、加载 ══════════════════════════

def 载入():
    """把四份外置数据读进来。读不了 / 结构不对 → 抛 数据错。"""
    if not os.path.isfile(数据文件):
        raise 数据错(f"找不到 {数据文件}")
    with open(数据文件, encoding="utf-8") as f:
        物 = json.load(f)
    映射 = 物.get("映射")
    if not isinstance(映射, dict) or not 映射:
        raise 数据错(f"{os.path.basename(数据文件)} 里没有「映射」这一节")

    步骤 = _读分段文本(os.path.join(prompt目录, "步骤清单.txt"))
    词表 = _读分段文本(os.path.join(prompt目录, "动作词表.txt"))
    危险段 = _读分段文本(os.path.join(prompt目录, "危险物品.txt"))

    return {
        "物品映射": {str(k): str(v) for k, v in 映射.items()},
        "步骤清单": {"基础": " ".join(步骤.get("基础") or []),
                     "扩展": " ".join(步骤.get("扩展") or [])},
        "动作词表": {"基础": [w for w in (词表.get("基础") or [])],
                     "扩展": [w for w in (词表.get("扩展") or [])]},
        # 危险物品那个文件没有小节，整个文件就是一行一个名字
        "危险物品": sorted({w for 段 in 危险段.values() for w in 段}),
        "版本": 版本(),
    }


# ══════════════════════════ 三、核对 ══════════════════════════

def 手侧危险物品():
    """从手侧插件源码里把那份 Set 抠出来（新能力在插件里，这就是"真相"）。"""
    if not os.path.isfile(手侧插件):
        return None
    with open(手侧插件, encoding="utf-8") as f:
        源 = f.read()
    配 = re.search(r"const\s+危险物品\s*=\s*new\s+Set\(\[(.*?)\]\)", 源, re.S)
    if not 配:
        return None
    return sorted(set(re.findall(r"'([^']+)'", 配.group(1))))


def 核对(查, bridge=None):
    """加载 + 核对（外挂启动/自检走这条）。

    bridge 传进来就用它核动作词表；不传就自己 import。
    """
    if bridge is None:
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        try:
            import bridge as _b
            bridge = _b
        except Exception as e:
            # ★ 主链不在就得**好好说话**，不许甩一段 traceback 了事。
            #   2026-10-01 复验 fail-closed 时，数据.py 甩了个 ModuleNotFoundError
            #   出来 —— 虽然退出码是对的，但"喊清楚缺了什么"才算合格。
            查.起组("J 外置数据")
            查.断言("主链 bridge 能导入（校验物品名要拿它比基线）",
                    False, f"{type(e).__name__}: {e}")
            return None

    try:
        数 = 载入()
    except 数据错 as e:
        查.起组("J 外置数据")
        查.断言("四份外置数据能加载", False, str(e))
        return None
    except Exception as e:
        查.起组("J 外置数据")
        查.断言("四份外置数据能加载", False, f"{type(e).__name__}: {e}")
        return None

    核对数据(查, 数, bridge)
    return 数


def 核对数据(查, 数, bridge):
    """★ 真正干活的那一半：拿**已经载入的**数据逐条核对。

    单独拆出来是为了能测"校验本身灵不灵" —— 测数据.py 会故意喂一份坏数据进来，
    看这些断言会不会真的报错。（"测试通过 ≠ 测试有意义"。这个函数是那个教训的产物。）
    """
    真 = 物品表()

    # ── J 物品映射 ──
    查.起组("J 物品映射（data/items_map.json）")
    查.断言(f"物品映射读进来了（{len(数['物品映射'])} 条）", len(数["物品映射"]) > 0)
    坏的 = sorted({k: v for k, v in 数["物品映射"].items() if v not in 真}.items())
    查.断言(f"每一条的值都是真 MC 物品名（拿 {数['版本']} 的物品表核）",
            not 坏的, 坏的[:5])
    查.断言("口语名和 MC 名都不是空的", all(k.strip() and v.strip()
                                          for k, v in 数["物品映射"].items()))
    # ★ 反向核对：不能比基线**少**，同名不能**改值**
    基线 = dict(getattr(bridge.指令层, "物品名", {}) or {})
    if 基线:
        丢的 = sorted(set(基线) - set(数["物品映射"]))
        查.断言(f"没丢基线的映射（基线 {len(基线)} 条一条都不能少）", not 丢的, 丢的)
        改的 = sorted(k for k in set(基线) & set(数["物品映射"])
                      if 基线[k] != 数["物品映射"][k])
        查.断言("跟基线同名的，值必须一模一样（要改值得先说清楚）", not 改的,
                [(k, 基线[k], 数["物品映射"][k]) for k in 改的])
        查.记注释(f"物品映射：基线 {len(基线)} 条 + 新增 "
                  f"{len(数['物品映射']) - len(set(基线) & set(数['物品映射']))} 条 "
                  f"= 共 {len(数['物品映射'])} 条")

    # ── K 危险物品 ──
    查.起组("K 危险物品（prompts/危险物品.txt）")
    危 = 数["危险物品"]
    查.断言(f"危险物品读进来了（{len(危)} 条）", len(危) > 0)
    坏危 = sorted(set(危) - 真)
    查.断言("每一条都是真 MC 物品名（写错一个字母 = 那道闸对它完全失效）",
            not 坏危, 坏危)
    手 = 手侧危险物品()
    if 手 is None:
        查.断言("能读到手侧插件里那份名单", False, 手侧插件)
    else:
        查.断言(f"跟手侧那份完全一致（手侧 {len(手)} 条）",
                sorted(危) == sorted(手),
                {"只有脑侧有": sorted(set(危) - set(手)),
                 "只有手侧有": sorted(set(手) - set(危))})

    # ── L 动作词表 ──
    查.起组("L 动作词表（prompts/动作词表.txt）")
    词基 = 数["动作词表"]["基础"]
    词扩 = 数["动作词表"]["扩展"]
    查.断言(f"基础词表 {len(词基)} 个词", len(词基) > 0)
    看家 = set(getattr(bridge.任务栈, "允许动作", set()))
    禁 = set(getattr(bridge.翻译器, "禁止步骤", set()))
    if 看家:
        # ★ 关系不是"一模一样"：任务栈自己认「打」(反射层/猎手要用)，
        #   但 prompt 里**绝不许**教 LLM 写「打」—— 宪法第②条。
        #   所以正确的等式是：prompt 词表 = 任务栈允许动作 减去 禁止步骤。
        #   2026-10-01 第一版写成"完全一致"，被这条自己揪出来了。
        该有 = 看家 - 禁
        查.断言(f"基础词表 = 主链允许动作({len(看家)}) 减去禁止步骤({len(禁)})"
                f" = {len(该有)} 个",
                set(词基) == 该有,
                {"只在词表里": sorted(set(词基) - 该有),
                 "只在主链里": sorted(该有 - set(词基))})
        查.断言("宪法禁止的步骤**不在**基础词表里（prompt 绝不教 LLM 写「打」）",
                not (set(词基) & 禁), sorted(set(词基) & 禁))
        查.记注释("主链允许动作 " + "、".join(sorted(看家))
                  + "；其中 " + "、".join(sorted(禁)) + " 不许进 prompt（宪法）")
    查.断言("扩展词表正好是动作面那三个",
            set(词扩) == {"合成", "箱子里取", "往箱子里放"}, 词扩)
    查.断言("扩展词表里的词，基础词表里没有（不重复）",
            not (set(词扩) & set(词基)), sorted(set(词扩) & set(词基)))

    # ── M 步骤清单 ──
    查.起组("M 步骤清单（prompts/步骤清单.txt）")
    步基 = 数["步骤清单"]["基础"]
    步扩 = 数["步骤清单"]["扩展"]
    查.断言("基础步骤清单不是空的", bool(步基.strip()))
    查.断言("扩展步骤清单不是空的", bool(步扩.strip()))
    漏 = sorted(w for w in 词基 if w not in 步基)
    查.断言("基础词表里每个词都在步骤清单里出现过（两份文件不许打架）", not 漏, 漏)
    漏2 = sorted(w for w in 词扩 if w not in 步扩)
    查.断言("扩展词表里每个词也都在扩展步骤清单里", not 漏2, 漏2)
    查.记注释("开关打开时用的那一行 = 【基础】+「 / 」+【扩展】，"
              f"拼出来 {len(步基 + ' / ' + 步扩)} 字")

    return 数


# ══════════════════════════ 四、单独跑 ══════════════════════════

def 主():
    ap = argparse.ArgumentParser(description="M7b 动作面外挂 · 外置数据加载与校验")
    ap.add_argument("--json", action="store_true", help="按 json 输出")
    参 = ap.parse_args()

    sys.path.insert(0, 外挂目录)
    import 自检 as 自检模块

    查 = 自检模块.自检器()
    数 = 核对(查)
    总 = len([x for x in 查.通过 if isinstance(x, dict)]) + len(查.失败)

    if 参.json:
        print(json.dumps({
            "通过": [x["名"] for x in 查.通过 if isinstance(x, dict)],
            "失败": [{"组": x["组"], "名": x["名"], "实际": str(x.get("实际"))}
                    for x in 查.失败],
            "备注": [x["文本"] for x in 查.注],
            "总": 总, "失败数": len(查.失败)}, ensure_ascii=False, indent=1))
    else:
        print("═══ 外置数据 · 加载与核对 ═══")
        if 数:
            print(f"MC 版本：{数['版本']}（跟手侧同一个出处 config.json/mc_version）")
            print(f"物品映射：{len(数['物品映射'])} 条")
            print(f"危险物品：{len(数['危险物品'])} 条")
            print(f"动作词表：基础 {len(数['动作词表']['基础'])} 个 / "
                  f"扩展 {len(数['动作词表']['扩展'])} 个")
        print()
        for 条 in 查.通过:
            if isinstance(条, dict):
                print(f"  ✅ {条['名']}")
        for 条 in 查.失败:
            print(f"  ❌ 【{条['组']}】{条['名']}　实际：{条.get('实际')}")
        for 条 in 查.注:
            print(f"  · {条['文本']}")
        print("\n" + "─" * 46)
        print(f"核对 {总} 条：通过 {总 - len(查.失败)}，失败 {len(查.失败)}")
        print("✅ 外置数据没问题。" if not 查.失败
              else "❌ 有对不上的 —— 外挂必须拒绝启动。")
    return 1 if 查.失败 else 0


if __name__ == "__main__":
    sys.exit(主())
