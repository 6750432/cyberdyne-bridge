#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验收石镐.py —— 「从零造石镐」终极考核的验收器（做不了假的那种）。

为什么要有它
============
2026-10-08 我犯过一个错：日志里出现 `[14:09:42] 递给主人 1 个 stone_pickaxe`，
我就宣布验收通过 ✗ 真相是：**那把镐子是主人自己做的**，
三块圆石也是**主人亲手把泥土挖掉之后**小家伙才拿到的。

后来翻日志才发现，那句"成果"底下什么都没有：
整个 2.5MB 的大脑日志里，**成功的步骤只有一条** ——「dig」成了（挖掉=grass_block）。
它**一块石头都没挖过** ✗

所以这个脚本的规矩是（每一条都是拿那次教训换的）：
  ① **只认小家伙自己干的**：日志里必须有**它自己**挖石头的记录、
     它自己合成的记录、它自己递出去的记录 —— 不看"世界上有没有石镐"（那可能是主人做的）；
  ② **每步都要有结果行**：光有"我打算挖"不算，要有「成了（挖掉=X）」这种**结果**；
  ③ **不许有静默**：跑的过程中不该出现「等了 N 秒还没成（超时）」；
  ④ 原始证据行**全部打印出来**给人眼看 —— 结论要能被人复核，不是我说了算。

⚠ 必须说清的一件它**证明不了**的事：它只能证明"小家伙自己做了这些"，
  **证明不了"主人没出手"**。那一条只有主人能签字（脚本最后会明确要这句）。

跑法：
  python3 tools/验收石镐.py                # 默认看最近 60 分钟
  python3 tools/验收石镐.py --自 14:35     # 指定起点（考核一开始的时刻）
"""

import argparse
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
日志表 = ["logs/大脑.log", "logs/手.log", "logs/外挂-车钩.log"]

# 「它自己挖掉的」：石头这一家（石头挖掉掉的是 cobblestone ✓，深板岩同理）
石头产物 = ("stone", "cobblestone", "deepslate", "cobbled_deepslate")
# 结果行的两种签名（主链/车厢写日志的措辞可能不止一种，宁可多认几种）
结果签名 = [
    re.compile(r"「(?P<动词>[a-zA-Z_]+)」成了（(?P<详情>[^）]*)）"),
    re.compile(r"「(?P<动词>[a-zA-Z_]+)」成了"),
]


日志时间1 = re.compile(r"\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}):\d{2}\]")
日志时间2 = re.compile(r"\[(\d{2}:\d{2})\]")
今天 = time.strftime("%Y-%m-%d")


def 读全部(自=None):
    """把三份日志读进来，按**完整日期时间**过滤到「自」之后。返回 [(来源, 行)]。

    ⚠ 这里踩过一个坑：第一版只比 `HH:MM`，结果把**昨天**的日志也算了进来，
      ② 那一项于是报出 187 条"它自己合成过石镐" ✗ —— 全是幻影。
      日期必须一起比。（这就是 T3「口径不一致」：同一件事两处用不同口径。）
    """
    截止 = f"{今天} {自}:00" if 自 else None
    出 = []
    for 相对 in 日志表:
        路 = os.path.join(ROOT, 相对)
        if not os.path.exists(路):
            continue
        最后时间 = None
        with open(路, encoding="utf-8", errors="replace") as f:
            for 行 in f:
                m1 = 日志时间1.search(行)
                if m1:
                    最后时间 = f"{m1.group(1)} {m1.group(2)}:00"
                else:
                    m2 = 日志时间2.search(行)
                    if m2:
                        最后时间 = f"{今天} {m2.group(1)}:00"
                # 没有时间戳的行（探针那种）跟着上一条走 —— 它们本来就是上一句的续行
                时间 = 最后时间
                if 截止 and 时间 and 时间 < 截止:
                    continue
                出.append((os.path.basename(相对), 行.rstrip("\n")))
    return 出


def 找结果行(行表):
    出 = []
    for 源, 行 in 行表:
        for 式 in 结果签名:
            m = 式.search(行)
            if m:
                出.append({"源": 源, "行": 行, "动词": m.group("动词"),
                          "详情": m.groupdict().get("详情") or ""})
                break
    return 出


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--自", default=None, help="只看这个时刻（HH:MM）之后的日志")
    ap.add_argument("--分钟", type=int, default=60, help="没给 --自 时，默认看最近这么多分钟")
    参 = ap.parse_args()

    自 = 参.自
    if not 自:
        # 查时钟:允许 —— 这一处是给人看的时间标签（算 HH:MM），不是判据
        自 = time.strftime("%H:%M", time.localtime(time.time() - 参.分钟 * 60))

    行表 = 读全部(自)
    结果 = 找结果行(行表)
    全文 = "\n".join(行 for _, 行 in 行表)

    print("═" * 66)
    print(f"「从零造石镐」终极考核 —— 验收　（只看 {自} 之后的日志，共 {len(行表)} 行）")
    print("═" * 66)

    # ── ① 它自己挖到的石头 ──
    挖石 = [r for r in 结果 if r["动词"] == "dig"
            and any(名 in r["详情"] for 名 in 石头产物)]
    print(f"\n① 它自己挖到石头：{len(挖石)} 次（要 ≥3 才有三块圆石）")
    for r in 挖石[:8]:
        print(f"     {r['行'][:130]}")

    # ── ② 它自己合成的石镐 ──
    #   ⚠ 「计划里写着 24. 合成 stone_pickaxe」**不算数** —— 那是"打算做"，不是"成了"。
    #     第一版就是被这种行骗了（报出 187 条"合成过"）✗ 只认**结果行**。
    合 = [r for r in 结果 if r["动词"] in ("craft", "合成") and "stone_pickaxe" in r["详情"]]
    if not 合:      # 措辞可能不一样 —— 但**必须带"做成了"的意思**，光提名不算
        合 = [{"行": 行} for _, 行 in 行表
              if "stone_pickaxe" in 行
              and re.search(r"(「craft」成了|合成成功|做好了|造好了|完成合成)", 行)]
    print(f"\n② 它自己合成石镐：{'有' if 合 else '没找到'}（{len(合)} 条）")
    for r in 合[:5]:
        print(f"     {r['行'][:130]}")

    # ── ③ 它自己递出去 ──
    递 = [r for r in 结果 if r["动词"] == "给" and "stone_pickaxe" in r["详情"]]
    if not 递:
        递 = [{"行": 行} for _, 行 in 行表
              if re.search(r"递给主人\s*\d+\s*个\s*stone_pickaxe", 行)]
    print(f"\n③ 它自己把石镐交到主人手上：{'有' if 递 else '没找到'}（{len(递)} 条）")
    for r in 递[:5]:
        print(f"     {r['行'][:130]}")

    # ── ④ 静默：跑的过程中不该有超时 ──
    超时 = [行 for _, 行 in 行表 if "还没成（超时）" in 行 or "还没成(超时)" in 行]
    print(f"\n④ 静默/卡死：超时 {len(超时)} 次（要 0）")
    for 行 in 超时[:5]:
        print(f"     {行[:130]}")

    # ── ⑤ 每步都有结果行（T2 的底线）──
    #    「打算做」不算数，要有「成了」这种结果。链子大约 8~12 步。
    步数 = len(结果)
    print(f"\n⑤ 有结果行的步骤：{步数} 条（石镐这条链子大约 8~12 步）")

    # ── 判 ──
    过 = (len(挖石) >= 3 and bool(合) and bool(递) and not 超时 and 步数 >= 8)
    print("\n" + "─" * 66)
    print(f"  ① 自己挖到 ≥3 块石头：{'✔' if len(挖石) >= 3 else '✗'}　（{len(挖石)}）")
    print(f"  ② 自己合成石镐：　　{'✔' if 合 else '✗'}")
    print(f"  ③ 自己交到主人手上：{'✔' if 递 else '✗'}")
    print(f"  ④ 全程无超时/静默：{'✔' if not 超时 else '✗'}　（超时 {len(超时)} 次）")
    print(f"  ⑤ 每步都有结果行：　{'✔' if 步数 >= 8 else '✗'}　（{步数} 条）")
    print("─" * 66)
    print(f"  脚本判定：{'✅ 过关' if 过 else '❌ 不过关（有 ✗）'}")
    print()
    print("  ⚠ 这个脚本**证明不了**「主人没出手」—— 它只能证明小家伙自己做了什么。")
    print("    那一条要主人亲口签字：")
    print("       「这次我全程没有出手（没替它挖、没给它东西、没替它合成）。」")
    print("    没有这句话，上面所有 ✔ 都只能算「小家伙参与过」，不能算「它自己做到的」。")
    print("═" * 66)
    return 0 if 过 else 1


if __name__ == "__main__":
    sys.exit(main())
