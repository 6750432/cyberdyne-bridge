#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M7a·记忆的离线回归。

为什么离线先验：记忆的错都是"安静地错"—— 记错了地方、把计数丢在内存里、
把 LLM 的记忆当成指令使唤…… 在游戏里看不出来，等到它半夜跑去挖别人家墙角才发现。
这里用手工造的扫描/任务/聊天事件把每条规则单独拧出来验：

  地点：写入 / 同类近距合并（见过+1）/ 不重复记
  事件：任务完成与失败各写一张；失败额外写"未了事"
  人：只记事实（说话/打我），**不许记关系**；别把自己记进去
  未了事：失败写了、办成了要划掉
  检索：附近 / 未了事 / 这个人 / 最近，且 prompt 段落有硬上限
  淘汰：容量满了只留"最该留"的，文件不无限涨
  红线：★ 记忆不是指令（本类里没有任何命令通道）
        ★ 不许发明关系（不出现"敌人/朋友"这种标签）
        ★ 不存聊天原文（记说话只收名字）

用法： python3 tools/测记忆.py [-v]
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
通过, 失败 = [], []
详细 = False
说 = lambda *a, **k: None


def 断言(名, 条件, 实际=None):
    行 = f"{'✅' if 条件 else '❌'} {名}" + (f"　实际：{实际}" if (实际 is not None and not 条件) else "")
    (通过 if 条件 else 失败).append(行)
    if 详细 or not 条件:
        print(行)


def 造记忆(目录=None, **改):
    m7 = dict(CFG["m7"])
    m7.update(改)
    目录 = 目录 or tempfile.mkdtemp(prefix="测记忆-")
    return bridge.记忆(m7, 说, 目录), 目录


def 造扫描(方块们):
    return {"t": _虚拟[0] * 1000, "我": [0, 78, 0], "地面": "stone",
            "可交互": [{"name": n, "p": list(p)} for n, p in 方块们],
            "危险": [], "方块": [{"name": "stone", "count": 10}], "实体": []}


各级目录 = []


def 用例_地点写入与合并():
    记, 目录 = 造记忆(); 各级目录.append(目录)
    记.看扫描(造扫描([("furnace", (20, 78, -20)), ("chest", (21, 78, -20))]))
    断言("扫一圈 → 地点卡写进去了（熔炉+箱子）",
         len(记.卡["地点"]) == 2, [c.get("类型") for c in 记.卡["地点"]])
    记.看扫描(造扫描([("crafting_table", (30, 78, 30))]), 我=[0, 78, 0])
    断言("带上「我在哪」时，连脚下是什么地也记一条",
         any("地面" in str(c.get("类型")) for c in 记.卡["地点"]),
         [c.get("类型") for c in 记.卡["地点"]])
    断言("卡片里有坐标、来源、见过次数",
         记.卡["地点"][0].get("坐标") and 记.卡["地点"][0].get("来源") == "扫描"
         and 记.卡["地点"][0].get("见过") == 1, 记.卡["地点"][0])
    # 同一点再扫一次：合并（见过 +1），不新增
    记.看扫描(造扫描([("furnace", (20, 78, -20))]))
    炉 = [c for c in 记.卡["地点"] if c["类型"] == "furnace"][0]
    断言("★ 同一个地方再扫到 → 合并（见过 +1），不重复记", 炉["见过"] == 2, 炉["见过"])
    断言("★ 合并之后熔炉还是一条（不是两条）",
         len([c for c in 记.卡["地点"] if c["类型"] == "furnace"]) == 1,
         [c["类型"] for c in 记.卡["地点"]])
    # 远一点的地方要单独记
    记.看扫描(造扫描([("furnace", (120, 78, -120))]))
    断言("隔得远的地方 → 另记一条（不算同一个）",
         len([c for c in 记.卡["地点"] if c["类型"] == "furnace"]) == 2)


def 用例_落盘与重载():
    记, 目录 = 造记忆(); 各级目录.append(目录)
    记.看扫描(造扫描([("furnace", (20, 78, -20))]))
    记.记人("mintstar", "说话")
    记.记人("mintstar", "说话")
    记.记人("mintstar", "打我")
    # 重新加载一份（模拟重启）
    记2 = bridge.记忆(dict(CFG["m7"]), 说, 目录)
    人 = [c for c in 记2.卡["人"] if c["名字"] == "mintstar"][0]
    断言("★ 重启之后计数还在（更新也要落盘）",
         int(人.get("说话") or 0) == 2 and int(人.get("打我") or 0) == 1, 人)
    炉 = [c for c in 记2.卡["地点"] if c["类型"] == "furnace"][0]
    断言("★ 重启之后地点还是合并成一条（见过次数不丢）", 炉["见过"] == 1, 炉)


def 用例_人不记关系也不记自己():
    记, 目录 = 造记忆(); 各级目录.append(目录)
    记.记人("mintstar", "打我")
    卡 = 记.卡["人"][0]
    断言("人卡只存事实字段（名字/说话/打我/时间）",
         set(卡.keys()) <= {"名字", "第一次见", "最后见", "说话", "打我", "给东西", "世界"},
         卡.keys())
    断言("★ 宪法②：人卡里没有「关系」这种标签",
         not any(k in 卡 for k in ("关系", "敌人", "朋友", "友好")), 卡)
    记.记初见("XiaoJiaHuo")
    断言("★ 不把自己记进人卡", all(c["名字"] != "XiaoJiaHuo" for c in 记.卡["人"]),
         [c["名字"] for c in 记.卡["人"]])
    文 = 记.这个人("mintstar")
    断言("问「这个人是谁」只回事实（说过几次话/打过几次）",
         "打过我" in 文 and "跟我说过" in 文, 文)


def 用例_事件与未了事():
    记, 目录 = 造记忆(); 各级目录.append(目录)
    记.记任务("挖 3 格再回来", "完", 坐标=[10, 78, 10])
    断言("任务完成 → 事件卡", any(e["类型"] == "任务完成" for e in 记.卡["事件"]))
    断言("完成的任务不进「未了事」", not 记.卡["未了事"])
    记.记任务("挖基岩", "败", 停在=2, 共=5, 原因="挖不动", 坐标=[20, 77, -18])
    断言("任务失败 → 事件卡（标为重要）",
         any(e["类型"] == "任务失败" and e.get("重要") for e in 记.卡["事件"]))
    断言("★ 任务失败 → 额外写一张「未了事」", len(记.卡["未了事"]) == 1, 记.卡["未了事"])
    断言("未了事记着：停在第几步、什么原因、在哪儿",
         记.卡["未了事"][0].get("停在") == 2 and 记.卡["未了事"][0].get("原因") == "挖不动"
         and 记.卡["未了事"][0].get("坐标"), 记.卡["未了事"][0])
    文 = 记.未了事()
    断言("未了事能念出来（给 prompt 用）", "挖基岩" in 文 and "第 2 步" in 文, 文)
    # 办成了 → 划掉
    记.记任务("挖基岩", "完")
    断言("★ 同一件事办成了 → 从「未了事」里划掉", not 记.卡["未了事"], 记.卡["未了事"])


def 用例_检索与prompt段():
    记, 目录 = 造记忆(); 各级目录.append(目录)
    记.看扫描(造扫描([("furnace", (20, 78, -20)), ("iron_ore", (200, 64, 200))]))
    记.记任务("挖矿", "败", 停在=1, 共=4, 原因="被打断 41 秒", 坐标=[20, 77, -18])
    记.记人("mintstar", "说话")
    记.记事件("被打", "被 PreyBot 打了", [0, 78, 0], 重要=True)
    近 = 记.附近([0, 78, 0], 半径=64)
    断言("附近检索：只报范围里的", "furnace" in 近 and "iron_ore" not in 近, 近)
    断言("附近检索有上限（≤5 条）", 近.count("、") <= 5, 近)
    段 = 记.一段([0, 78, 0], 谁="mintstar", 用途="心跳")
    断言("【记忆】段里有未了事 / 附近 / 人的事实 / 最近经历",
         all(k in 段 for k in ("没干完", "我记得周围", "跟我说过", "最近经历")), 段)
    断言("★ 心跳用途下，未了事后面带一句「你自己看着办」（不硬来）",
         "别硬来" in 段 or "接着干" in 段, 段)
    断言("★ 记忆段有硬上限（≤300 字）", len(段) <= 300, len(段))
    念 = 记.念一遍()
    断言("「你记得什么」念得出人话（≤220 字）", len(念) > 0 and len(念) <= 220, len(念))
    空, 目录2 = 造记忆(); 各级目录.append(目录2)
    断言("空记忆也念得出来（不崩）", "什么都没记住" in 空.念一遍(), 空.念一遍())
    断言("空记忆时不往 prompt 里塞空段", 空.一段([0, 78, 0]) == "", 空.一段([0, 78, 0]))


def 用例_淘汰():
    记, 目录 = 造记忆(容量={"地点": 5, "事件": 6, "人": 2, "未了事": 3})
    各级目录.append(目录)
    for i in range(12):
        _虚拟[0] += 1
        记.记地点(f"矿·测试{i}", [i * 20, 64, 0])
    断言("★ 地点超容量 → 只留容量那么多", len(记.卡["地点"]) <= 5, len(记.卡["地点"]))
    for i in range(12):
        _虚拟[0] += 1
        记.记事件("普通", f"第{i}件小事")
    断言("★ 事件超容量 → 只留容量那么多", len(记.卡["事件"]) <= 6, len(记.卡["事件"]))
    记.记事件("失败", "重要的失败", 重要=True)
    断言("★ 重要的事优先留（失败不会被普通小事挤掉）",
         any(e.get("重要") for e in 记.卡["事件"]), 记.卡["事件"][:2])
    行数 = len(open(os.path.join(目录, "地点.jsonl"), encoding="utf-8").readlines())
    断言("★ 压缩之后文件也小下去了（不无限涨）", 行数 <= 5 + 1, 行数)


def 用例_红线():
    """★★ M7 三条宪法：记忆不是指令 / 不许发明关系 / 不存聊天原文。"""
    import inspect, ast as _ast
    源 = inspect.getsource(bridge.记忆)
    树 = _ast.parse(源)          # ★ 用语法树查，别拿字符串 grep ——
    #   我第一次就是被自己的文档字符串误伤的（类注释里写着"这个类没有 self.发"）。
    手法 = [n.func.attr for n in _ast.walk(树)
            if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)]
    断言("★ 宪法①：记忆类里没有任何命令通道（不许拿记忆下达动作）",
         not (set(手法) & {"发", "执行", "跑", "命令"}), sorted(set(手法)))
    字段 = [n.value for n in _ast.walk(树)
            if isinstance(n, _ast.Constant) and isinstance(n.value, str)]
    断言("★ 宪法①b：记忆类里不出现 cmd / act 这类协议字段",
         not (set(字段) & {"cmd", "act"}), sorted(set(字段) & {"cmd", "act"}))
    断言("★ 宪法②：记忆类里不出现敌人/朋友这类关系标签",
         not (set(字段) & {"敌人", "朋友", "友好", "关系"}), sorted(set(字段) & {"敌人", "朋友"}))
    签名 = str(inspect.signature(bridge.记忆.记人))
    断言("★ 宪法③：记人只收名字与字段名（收不到聊天原文）",
         "话" not in 签名.replace("说话", ""), 签名)
    记住话 = inspect.getsource(bridge.记忆.记人)
    断言("★ 宪法③：人卡写入的字段里没有「原文/话」这类内容字段",
         "原文" not in 记住话 and "内容" not in 记住话, 记住话[:80])


def 用例_开关():
    记, 目录 = 造记忆(memory_enable=False); 各级目录.append(目录)
    记.看扫描(造扫描([("furnace", (20, 78, -20))]))
    记.记任务("测试", "败", 停在=1, 共=2, 原因="x")
    记.记人("mintstar", "说话")
    断言("★ 总开关关掉 → 一个字都不记",
         not any(记.卡.values()), {k: len(v) for k, v in 记.卡.items()})
    记2, 目录2 = 造记忆(memory_in_prompt=False); 各级目录.append(目录2)
    记2.记地点("furnace", [1, 78, 1])
    断言("memory_in_prompt=false → 只在本地记，不往 prompt 里塞",
         记2.卡["地点"] and 记2.一段([0, 78, 0]) == "", 记2.一段([0, 78, 0]))
    断言("★ M7b 动作面默认是锁着的",
         CFG["m7"]["expand_actions"] is False, CFG["m7"]["expand_actions"])


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
        for d in 各级目录:
            shutil.rmtree(d, ignore_errors=True)
    print(f"\n通过 {len(通过)} 条，失败 {len(失败)} 条。")
    if 失败:
        print("\n失败明细：")
        for 行 in 失败:
            print("  " + 行)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
