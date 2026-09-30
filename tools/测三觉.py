#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M5/M6·三觉与双向翻译器的离线回归。

为什么离线先验：三觉是"事实 → 人话"的翻译，翻译器是 LLM 的**唯一出入口** ——
这两样出错，表现都是"它偶尔说了句怪话"，在游戏里根本查不出来。
这里用手工造的帧 + 造的 LLM 输出，把每条规矩单独拧出来验：

  视觉：摘要限量（≤8 行 / ≤600 字）、该有的都有
  听觉：上下文窗限量、指令要标出来
  触觉：疼 / 饿 / 装备快坏 / 卡住 / 挨打 / 天黑 → 都能翻译成"感受"
  上行：prompt 里有三段 + 铁规矩，且总长有硬上限
  下行：★ 安全宪法两条 + 非严格 JSON + 坐标越界 + 步骤越界 → 全部拒绝
  心跳：默认关；六个点火条件缺一不可；预算与空转退避生效

用法： python3 tools/测三觉.py [-v]
退出码：0 = 全过；1 = 有失败。
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time as _时间

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_虚拟 = [1000.0]
_时间.time = lambda: _虚拟[0]
sys.path.insert(0, ROOT)
import bridge  # noqa: E402

CFG = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
日志目录 = tempfile.mkdtemp(prefix="测三觉-")
通过, 失败 = [], []
详细 = False
说 = lambda *a, **k: None


def 断言(名, 条件, 实际=None):
    行 = f"{'✅' if 条件 else '❌'} {名}" + (f"　实际：{实际}" if (实际 is not None and not 条件) else "")
    (通过 if 条件 else 失败).append(行)
    if 详细 or not 条件:
        print(行)


def 造帧(我=(0, 78, 0), 血=20.0, 饿=20, 物品=None, 武器=(("iron_sword", 1),),
         耐久=None, 卡住次数=0, 打我=None, 扫=None, 玩家=(), 食物=(("cooked_beef", 3),)):
    return {
        "type": "state", "pos": list(我), "hp": float(血), "food": 饿,
        "weapons": [{"name": n, "count": c} for n, c in 武器],
        "foods": [{"name": n, "count": c} for n, c in 食物],
        "items": 物品 if 物品 is not None else {"iron_sword": 1, "iron_pickaxe": 1},
        "durability": 耐久 or {"held": {"name": "iron_sword", "用": 10, "总": 250, "比例": 0.04},
                               "armor": {"torso": {"name": "iron_chestplate", "用": 5, "总": 240, "比例": 0.02}}},
        "stuck_count": 卡住次数, "stuck_ms": None, "attacked_by": 打我,
        "scan": 扫, "players": [{"name": n, "dist": d, "pos": [0, 78, 0]} for n, d in 玩家],
        "threats": [], "drops": [], "friends": [], "blocks": None, "furnace": None,
    }


def 造扫描(刻=18000, 白天=False):
    return {"t": _虚拟[0] * 1000, "刻": 刻, "白天": 白天, "第几天": 3, "天气": "晴",
            "群系": "plains", "脚下": "grass_block", "我": [0, 78, 0],
            "方块": [{"name": "stone", "count": 84}, {"name": "dirt", "count": 31},
                     {"name": "oak_log", "count": 4}],
            "可交互": [{"name": "furnace", "p": [20, 78, -20]},
                       {"name": "chest", "p": [21, 78, -20]}],
            "危险": [{"name": "lava", "p": [6, 70, 0]}],
            "实体": [{"name": "mintstar", "kind": "player", "dist": 4.0, "pos": [4, 78, 0]},
                     {"name": "zombie", "kind": "hostile", "dist": 9.0, "pos": [9, 78, 0]}],
            "实体总数": 2}


def 造三觉(**改):
    m5 = dict(CFG["m5"])
    m5.update(改)
    return bridge.三觉(m5, 说, lambda o: None)


def 造翻译(允许动作=frozenset(), **改):
    m5 = dict(CFG["m5"])
    m5.update(改)
    return bridge.翻译器(m5, 说, 日志目录, 任务栈=None, 三觉=造三觉(),
                        允许动作=允许动作 or bridge.任务栈.允许动作)


# ────────────────────────── 用例 ──────────────────────────
def 用例_视觉():
    觉 = 造三觉()
    文 = 觉.视觉(造帧(扫=造扫描()))
    断言("视觉摘要里有时间/昼夜/天气", "深夜" in 文 and "晴" in 文, 文[:80])
    断言("视觉摘要里有资源统计", "stone×84" in 文, 文[:120])
    断言("视觉摘要里有可交互方块（熔炉/箱子）", "furnace" in 文 and "chest" in 文, 文[:160])
    断言("视觉摘要里有实体（玩家与敌对）", "mintstar" in 文 and "zombie" in 文, 文[:200])
    断言("视觉摘要里有危险（岩浆）", "lava" in 文, 文[:200])
    断言("★ 摘要限量：≤8 行", len(文.split("\n")) <= 8, len(文.split("\n")))
    断言("★ 摘要限量：≤600 字", len(文) <= 600, len(文))
    断言("没扫过的时候它会老实说没看过", "没看过" in 觉.视觉(造帧()), 觉.视觉(造帧()))


def 用例_听觉():
    觉 = 造三觉(chat_window=3)
    for i in range(5):
        觉.记聊天("mintstar", f"第{i}句", 是指令=False)
    断言("★ 听觉窗只留最近 N 条（不会无限长）", len(觉.聊天窗) == 3, len(觉.聊天窗))
    觉.记聊天("mintstar", "跟我来", 是指令=True)
    文 = 觉.听觉()
    断言("听得见最后一句", "跟我来" in 文, 文)
    断言("指令会标出来（跟闲聊区分开）", "指令" in 文, 文)
    空 = 造三觉()
    断言("没人说话时老实说没人说话", "没人说话" in 空.听觉(), 空.听觉())


def 用例_触觉():
    觉 = 造三觉()
    文 = 觉.触觉(造帧(血=4.0, 饿=6, 物品={}, 武器=(), 打我="PreyBot", 卡住次数=2))
    断言("血少 → 疼（说人话，不报数字堆）", "快不行了" in 文, 文)
    断言("饿 → 肚子饿", "肚子饿" in 文, 文)
    断言("没武器 → 手里没家伙", "没家伙" in 文, 文)
    断言("没镐子 → 说出来", "没有镐子" in 文, 文)
    断言("被打了 → 说得清是谁", "PreyBot" in 文, 文)
    坏 = 觉.触觉(造帧(耐久={"held": {"name": "iron_sword", "比例": 0.91},
                        "armor": {"torso": {"name": "iron_chestplate", "比例": 0.8}}}))
    断言("装备快坏 → 说出来（剑与甲）", "快断了" in 坏 and "护甲快坏" in 坏, 坏)
    黑 = 觉.触觉(造帧(扫=造扫描(刻=18000, 白天=False), 物品={"iron_sword": 1}))
    断言("天黑没光 → 说出来", "没有光源" in 黑, 黑)
    # 卡住次数涨了才算
    a = 造三觉()
    a.触觉(造帧(卡住次数=1))
    涨 = a.触觉(造帧(卡住次数=3))
    断言("卡住次数涨了 → 说卡住过", "卡住" in 涨, 涨)
    # 闲着没事干
    闲 = 造三觉(无聊秒=60)
    闲.记空闲(True)
    _虚拟[0] += 61
    文 = 闲.触觉(造帧(), "没有任务")
    断言("★ 平静且没任务够久 → 感受里出现「闲着没事干」（心跳信号）", "闲" in 文, 文)
    闲.记空闲(False)
    断言("一忙起来就不喊闲了", "闲" not in 闲.触觉(造帧(), "没有任务"))


def 用例_上行prompt():
    觉 = 造三觉()
    翻 = 造翻译(允许动作=bridge.任务栈.允许动作)
    翻.三觉 = 觉
    觉.记聊天("mintstar", "你在干嘛", 是指令=False)
    文 = 翻.组Prompt(造帧(扫=造扫描()), 用途="翻译", 任务状况="没有任务")
    断言("prompt 里有【视觉】【听觉】【触觉】三段",
         all(k in 文 for k in ("【视觉】", "【听觉】", "【触觉】")), 文[:200])
    断言("prompt 里写明铁规矩（不许攻击 / 输出 JSON）",
         "不能直接攻击" in 文 and "JSON" in 文, 文[:300])
    断言("prompt 里给了任务书的步骤类型清单", "wait_until" in 文, 文[-300:])
    断言("★ prompt 有硬上限（超额截断）",
         len(翻.组Prompt(造帧(扫=造扫描()), 任务状况="x" * 3000, 原话="y" * 3000)) <= 1200,
         len(翻.组Prompt(造帧(扫=造扫描()), 任务状况="x" * 3000, 原话="y" * 3000)))
    心 = 翻.组Prompt(造帧(扫=造扫描()), 用途="心跳", 任务状况="没有任务")
    断言("心跳用的 prompt 说明「可以什么都不做」", "什么都不做" in 心, 心[-200:])


def 用例_下行fail_closed():
    """★★ 安全宪法：不许直连攻击、不许生成「打」步骤。"""
    翻 = 造翻译()
    帧 = 造帧(扫=造扫描())

    # 宪法①：攻击类动作
    for 坏 in ('{"act":"attack","target":"mintstar"}',
               '{"act":"jumpattack","target":"mintstar"}',
               '{"act":"strike","target":"mintstar"}'):
        动作, 任务, 原因 = 翻.收输出(坏, 帧)
        断言(f"★ 宪法①：拒绝攻击类动作（{坏[:22]}…）", 动作 is None and 任务 is None, 原因)

    # 宪法②：任务里不许有「打」
    坏任务 = json.dumps({"任务": {"名字": "打他", "步骤": [
        {"动作": "走到", "p": [1, 78, 1]}, {"动作": "打", "名": "mintstar"}]}}, ensure_ascii=False)
    动作, 任务, 原因 = 翻.收输出(坏任务, 帧)
    断言("★ 宪法②：任务书里出现「打」→ 整份作废", 任务 is None and 动作 is None, 原因)

    # 其他 fail-closed
    动作, 任务, 原因 = 翻.收输出('```json\n{"act":"say","text":"hi"}\n```', 帧)
    断言("markdown 代码块 → 拒", 动作 is None, 原因)
    动作, 任务, 原因 = 翻.收输出('我觉得应该这样：{"act":"say","text":"hi"}', 帧)
    断言("不是严格 JSON（前后有字）→ 拒", 动作 is None, 原因)
    动作, 任务, 原因 = 翻.收输出('{"act":"teleport","p":[0,78,0]}', 帧)
    断言("白名单外的动作 → 拒", 动作 is None, 原因)
    动作, 任务, 原因 = 翻.收输出('{"act":"goto","p":[999,78,999]}', 帧)
    断言("坐标太远（>64 格）→ 拒", 动作 is None, 原因)
    动作, 任务, 原因 = 翻.收输出('{"act":"goto","p":[0,999,0]}', 帧)
    断言("y 越界 → 拒", 动作 is None, 原因)
    动作, 任务, 原因 = 翻.收输出(json.dumps(
        {"任务": {"名字": "太长", "步骤": [{"动作": "走到", "p": [i, 78, 0]} for i in range(9)]}},
        ensure_ascii=False), 帧)
    断言("步骤超过上限（9 > 6）→ 拒", 任务 is None, 原因)
    动作, 任务, 原因 = 翻.收输出(json.dumps(
        {"任务": {"名字": "乱来", "步骤": [{"动作": "启动进程", "命令行": "rm -rf /"}]}},
        ensure_ascii=False), 帧)
    断言("步骤动作不在 M4c 允许清单 → 拒", 任务 is None, 原因)

    # 合法的要放行
    好 = json.dumps({"任务": {"名字": "去挖矿", "为什么": "天黑了想砍树",
                             "步骤": [{"动作": "走到", "p": [10, 78, 10], "到点": 2.5},
                                      {"动作": "挖", "p": [10, 77, 10]},
                                      {"动作": "拾", "物品": "cobblestone", "数量": 1}]}},
                    ensure_ascii=False)
    动作, 任务, 原因 = 翻.收输出(好, 帧)
    断言("合法任务书 → 放行，且步骤原样通过",
         任务 is not None and len(任务.get("步骤") or []) == 3, 原因 or 任务)
    动作, 任务, 原因 = 翻.收输出('{"act":"say","text":"我去看看"}', 帧)
    断言("白名单内的单步动作 → 放行", 动作 is not None and 动作.get("act") == "say", 原因)
    # 挖不动的方块（有扫描数据时能拦）
    扫 = 造扫描()
    扫["可交互"].append({"name": "bedrock", "p": [3, 77, 3]})
    动作, 任务, 原因 = 翻.收输出(json.dumps(
        {"任务": {"名字": "挖基岩", "步骤": [{"动作": "挖", "p": [3, 77, 3]}]}},
        ensure_ascii=False), 造帧(扫=扫))
    断言("扫描说那格是 bedrock → 拒", 任务 is None, 原因)


def 用例_心跳():
    """六个点火条件缺一不可 + 预算 + 空转退避。"""
    栈 = bridge.任务栈({**CFG["m4"], "task_enable": True}, 说, lambda o: None, 日志目录)
    觉 = 造三觉()
    翻 = 造翻译()
    m6 = dict(CFG["m6"])
    m6["enable"] = True
    收到 = {"prompt": None}
    def 假问云(prompt, 用途="通用"):
        收到["prompt"] = prompt
        return json.dumps({"任务": {"名字": "去砍树", "为什么": "天黑了",
                                   "步骤": [{"动作": "走到", "p": [10, 78, 10], "到点": 2.5}]}},
                          ensure_ascii=False)
    心 = bridge.心跳(m6, 说, 翻, 栈, 觉, 假问云, 日志目录)
    帧 = 造帧(玩家=(("mintstar", 5.0),))
    断言("★ 默认配置是关的（主人钦定）", CFG["m6"]["enable"] is False)
    断言("★ 频率默认 60 秒", CFG["m6"]["心跳秒"] == 60)

    m6关 = dict(m6); m6关["enable"] = False
    心关 = bridge.心跳(m6关, 说, 翻, 栈, 觉, 假问云, 日志目录)
    断言("关着的时候绝不点火", 心关.该点(帧, "平静") is False)

    断言("条件都满足 → 该点火", 心.该点(帧, "平静") is True)
    断言("反射层不平静 → 不点", 心.该点(帧, "逃跑") is False)
    断言("主人不在线 → 不点", 心.该点(造帧(玩家=()), "平静") is False)
    觉.记聊天("mintstar", "在吗")
    断言("刚有人说话 → 不点（别抢话）", 心.该点(帧, "平静") is False)
    _虚拟[0] += 30
    断言("安静够了 → 可以点", 心.该点(帧, "平静") is True)

    好 = 心.点(帧, "平静")
    断言("点火一次：任务栈接到「去砍树」", 栈.在跑() and 栈.任务["名字"] == "去砍树", 好)
    断言("★ 心跳的 prompt 里带着三觉", all(k in (收到["prompt"] or "") for k in ("【视觉】", "【听觉】", "【触觉】")),
         (收到["prompt"] or "")[:120])
    断言("有任务在跑时不再点火", 心.该点(帧, "平静") is False)
    断言("心跳有记账（logs/心跳.jsonl）",
         os.path.exists(os.path.join(日志目录, "心跳.jsonl")))

    # 预算闸门
    栈.中止("测试")
    m6窄 = dict(m6); m6窄["每小时上限"] = 1
    心窄 = bridge.心跳(m6窄, 说, 翻, 栈, 觉, 假问云, 日志目录)
    心窄.点(帧, "平静")
    _虚拟[0] += 120
    断言("★ 预算闸门：一小时只允许 1 次 → 第二次不点", 心窄.该点(帧, "平静") is False)

    # 空转退避：连续两次拿不出东西（问云返回空）
    空 = bridge.心跳(m6, 说, 翻, 栈, 觉, lambda p, 用途="通用": "", 日志目录)
    空.点(帧, "平静"); _虚拟[0] += 120
    空.点(帧, "平静")
    断言("★ 空转两次 → 退避（不再点火）", 空.该点(帧, "平静") is False or 空.退避到 > _虚拟[0],
         空.退避到 - _虚拟[0])


def main():
    global 详细
    p = argparse.ArgumentParser()
    p.add_argument("-v", "--详细", action="store_true")
    a = p.parse_args()
    详细 = a.详细
    try:
        for 函数 in list(globals().values()):
            if callable(函数) and getattr(函数, "__name__", "").startswith("用例_"):
                函数()
    finally:
        shutil.rmtree(日志目录, ignore_errors=True)
    print(f"\n通过 {len(通过)} 条，失败 {len(失败)} 条。")
    if 失败:
        print("\n失败明细：")
        for 行 in 失败:
            print("  " + 行)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
