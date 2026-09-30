#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M7b·动作面外挂 —— 脑侧入口（主链零改动的那个「外挂」）。

┌───────────────────────────────────────────────────────────────┐
│ 一句话说明它凭什么不动主链                                     │
└───────────────────────────────────────────────────────────────┘
Python 是动态语言：`import bridge` 之后，可以在**内存里**改那几个类的属性和
方法。磁盘上的 bridge.py 一个字节都不动，小家伙就多出三种本事。
这就是「外挂」的 Python 版，对应手侧 node/plugins/ 那套规矩。

┌───────────────────────────────────────────────────────────────┐
│ 它干四件事，顺序不能乱                                         │
└───────────────────────────────────────────────────────────────┘
  ① import bridge                 只导入，不触发 主()，不连 socket
  ② 跑自检                          锚点逐条查；少一条就拒绝启动
  ③ 读 config.json 的 m7.expand_actions
       false → **一个补丁都不打**，直接进主链（行为 = 基线，逐字节相同）
       true  → 打补丁（第 3/4 步才实现；现在还没写，所以一律拒绝启动）
  ④ bridge.主()                    进主循环

★ 为什么「开关开着但补丁没写」要**拒绝启动**而不是照常跑基线：
  照常跑基线就是「悄悄不生效」—— 你以为开了，其实什么都没发生。
  这个项目最怕这种失败。宁可当场停下来喊人。

用法：
    python3 外挂/动作面/大脑外挂.py                 正常起（开关关着 = 基线）
    python3 外挂/动作面/大脑外挂.py --自检           只查锚点，不起主循环
    python3 外挂/动作面/大脑外挂.py --自检 --json     同上，机器看的
    python3 外挂/动作面/大脑外挂.py --假装开关开      演练：开关开着但补丁没写 → 必须拒
退出码：
    0 = 主循环正常退出
    2 = 自检没过
    3 = 开关开着但补丁还没实现（拒绝启动）
    4 = 找不到主链
"""

import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
外挂目录 = os.path.dirname(os.path.abspath(__file__))
日志目录 = os.path.join(ROOT, "logs")          # logs/ 已经在 .gitignore 里
日志文件 = os.path.join(日志目录, "外挂-动作面.log")

# 外挂自己认的命令行开关 —— 传主链之前必须摘掉，免得主链看不懂
自己的开关 = ("--自检", "--json", "--假装开关开", "--安静", "--演练")


def 记(文本, 屏幕=True):
    """外挂自己的日志。**不写进主链的账本**，两本账分开。"""
    行 = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {文本}"
    try:
        os.makedirs(日志目录, exist_ok=True)
        with open(日志文件, "a", encoding="utf-8") as f:
            f.write(行 + "\n")
    except Exception:
        pass
    if 屏幕:
        print(行, flush=True)


def 读开关(假装=False):
    """开关的**唯一出处**是 config.json 的 m7.expand_actions。"""
    路 = os.path.join(ROOT, "config.json")
    try:
        with open(路, encoding="utf-8") as f:
            配置 = json.load(f)
    except Exception as e:
        记(f"读不到 config.json（{e}）—— 按「关」处理（fail-closed）")
        return False, f"配置读不到：{e}"
    m7 = 配置.get("m7") or {}
    开 = bool(m7.get("expand_actions", False))
    if 假装:
        return True, "命令行 --假装开关开（演练用，config.json 没动）"
    return 开, "config.json 的 m7.expand_actions"


def 打补丁():
    """第 3/4 步才会实现这里。现在**故意留空并明确报错**。

    留着这个空函数、而不是直接删掉，是为了让"还没实现"这件事在代码里
    一眼看得见 —— 谁要往上加补丁，加在这儿。
    """
    return [], ["合成 / 箱子里取 / 往箱子里放（第 3 步）",
                "三条口令 + prompt 片段（第 4 步）"]


def 主():
    ap = argparse.ArgumentParser(description="M7b 动作面外挂（脑侧）",
                                 add_help=True)
    ap.add_argument("--自检", action="store_true", help="只跑锚点自检，不起主循环")
    ap.add_argument("--json", action="store_true", help="自检按 json 输出")
    ap.add_argument("--假装开关开", dest="假装开关开", action="store_true",
                    help="演练：把开关当成开着的（config.json 不动）")
    ap.add_argument("--安静", action="store_true", help="少说话")
    ap.add_argument("--演练", action="store_true",
                    help="一路走到交棒前就停（**不起主循环、不连 socket**）—— 验收用")
    参, 剩下 = ap.parse_known_args()

    # ── ① 先确认主链文件真的在（这是 fail-closed 的第一道）──
    主链路 = os.path.join(ROOT, "bridge.py")
    if not os.path.isfile(主链路):
        记(f"★ 找不到主链：{主链路}")
        记("★ 外挂拒绝启动 —— 我不猜它在哪，也不去别处import一个同名模块。")
        print(f"\n❌ 找不到主链 {主链路}", file=sys.stderr)
        print("   外挂拒绝启动。（这是故意的：主链不在，挂上去也没有意义。）",
              file=sys.stderr)
        return 4

    # ── ② 自检 ──
    sys.path.insert(0, 外挂目录)
    import importlib
    自检模块 = importlib.import_module("自检")
    importlib.reload(自检模块)
    查 = 自检模块.跑自检()
    总 = len([x for x in 查.通过 if isinstance(x, dict)]) + len(查.失败)

    if 参.自检:
        if 参.json:
            print(json.dumps({
                "通过": [x["名"] for x in 查.通过 if isinstance(x, dict)],
                "失败": [{"组": x["组"], "名": x["名"], "实际": str(x.get("实际"))}
                        for x in 查.失败],
                "备注": [x["文本"] for x in 查.注],
                "总": 总, "失败数": len(查.失败)}, ensure_ascii=False, indent=1))
        else:
            自检模块.打印(查)
        return 1 if 查.失败 else 0

    if 查.失败:
        自检模块.打印(查)
        记(f"★ 自检没过（{len(查.失败)} 条缺）—— 外挂拒绝启动。")
        for 条 in 查.失败:
            记(f"    缺：【{条['组']}】{条['名']}（实际：{条.get('实际')}）")
        return 2

    记(f"锚点自检通过：{总} 条全 ✅")
    for 条 in 查.注:
        记("  · " + 条["文本"], 屏幕=False)

    # ── ③ 看开关 ──
    开, 出处 = 读开关(假装=参.假装开关开)
    记(f"动作面开关 = {'开' if 开 else '关'}（出处：{出处}）")

    # ── ③.5 报一下外置数据的家底（第 2 步：数据都搬到 data/ 和 prompts/ 了）──
    try:
        import importlib
        数据模块 = importlib.import_module("数据")
        importlib.reload(数据模块)
        数 = 数据模块.载入()
        记(f"外置数据：物品映射 {len(数['物品映射'])} 条 / "
            f"危险物品 {len(数['危险物品'])} 条 / "
            f"动作词表 基础 {len(数['动作词表']['基础'])} + 扩展 {len(数['动作词表']['扩展'])} 个 / "
            f"MC {数['版本']}")
        记(f"（出处：{os.path.relpath(数据模块.数据文件, ROOT)} 和 "
            f"{os.path.relpath(数据模块.prompt目录, ROOT)}/）", 屏幕=False)
    except Exception as e:
        记(f"★ 外置数据读不了（{type(e).__name__}: {e}）—— 拒绝启动。")
        return 2

    if not 开:
        记("开关关着 → 一个补丁都不打，按基线跑（行为与基线逐字节相同）")
        打了, 缺的 = [], []
    else:
        打了, 缺的 = 打补丁()
        if 缺的:
            记("★ 开关开着，可补丁还没实现 —— 外挂拒绝启动。")
            for x in 缺的:
                记(f"    还没写：{x}")
            print("\n❌ 开关是真开着的，但外挂的补丁一条都没写（第 1 步只做自检）。",
                  file=sys.stderr)
            print("   拒绝启动 —— 照常跑基线就等于「你以为开了，其实什么都没发生」。",
                  file=sys.stderr)
            return 3
        记(f"补丁已打上：{len(打了)} 处")
        for x in 打了:
            记("  + " + x, 屏幕=False)

    # ── ④ 进主循环（这就是和主链唯一的接触面）──
    if 参.演练:
        # ★ 为什么要有这个开关：脑只能有一个。真在跑的那个不能被打扰，
        #   而"开关关着到底会不会打补丁"这件事又必须验。演练模式一路走到
        #   交棒前，把结论打出来，然后停 —— 不连 socket、不抢方向盘。
        记(f"【演练】到这里为止：锚点 {总} 条全过、开关处理完毕、补丁 {len(打了)} 处。"
            f"**没有起主循环，没有连 socket。**")
        return 0

    记("交棒给主链 bridge.主()")
    import bridge
    bak = sys.argv
    try:
        sys.argv = [主链路] + [a for a in 剩下 if a not in 自己的开关]
        return bridge.主() or 0
    finally:
        sys.argv = bak


if __name__ == "__main__":
    sys.exit(主())
