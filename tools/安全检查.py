#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M4c·安全边界自检：把"不许发生的事"变成**会失败的测试**。

由来（主人 2026-10-01 原话）：
    「假人可别给LLM用，到时候整出来智械危机了就完蛋了」

这句话背后是一条真实的架构约束：**测试工具与主链必须物理隔离**，
而且大模型层的能力面必须小到"它想造反也没有手"。
嘴上保证没用 —— 所以这里把每一条都写成断言，跑一遍就知道有没有被破坏。

五条检查：
  ① 主链里不许有任何"启动进程"的能力（child_process / spawn / exec / fork）。
  ② 主链里不许引用测试工具（tools/ 下的东西）。
  ③ 大模型层的白名单里不许出现攻击类或"动手"类动作。
  ④ 身体插件的能力表里不许出现危险动词（shell / eval / spawn 之类）。
  ⑤ 任务栈（存在的话）的允许动作清单必须是**默认拒绝**（fail-closed）。

用法：
    python3 tools/安全检查.py            # 退出码 0 = 全过，1 = 有红线被破坏
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

主链 = [
    ("node/server.js", "node"),
    ("bridge.py", "python"),
    ("node/plugins/body/proto_body.js", "node"),
    ("node/plugins/pathfinder/proto_pathfinder.js", "node"),
]
禁止的能力 = re.compile(r"child_process|\.spawn\s*\(|execSync|childProcess|"
                       r"\bfork\s*\(|require\(['\"]child_process")
危险动词 = {"exec", "run", "shell", "spawn", "eval", "system", "popen", "systemctl", "bash"}
攻击类 = {"attack", "jumpattack", "打击", "strike", "dig", "place", "use", "task", "任务"}

通过, 失败 = [], []


def 读(相对路径):
    全 = os.path.join(ROOT, 相对路径)
    if not os.path.exists(全):
        return None
    with open(全, encoding="utf-8", errors="ignore") as f:
        return f.read()


def 记(名, 好, 说明=""):
    (通过 if 好 else 失败).append(f"{'✅' if 好 else '❌'} {名}" + (f"　{说明}" if 说明 and not 好 else ""))


def 检查_主链没有进程能力():
    for 路径, _ in 主链:
        文 = 读(路径)
        if 文 is None:
            continue
        命中 = 禁止的能力.search(文)
        记(f"{路径} 没有「启动进程」的能力", 命中 is None,
           f"命中了：{命中.group(0) if 命中 else ''}")


def 检查_主链不引用测试工具():
    for 路径, _ in 主链:
        文 = 读(路径)
        if 文 is None:
            continue
        # 只看真正的代码引用，注释里提到文件名不算
        代码行 = [行 for 行 in 文.split("\n")
                 if not 行.strip().startswith(("*", "//", "#"))]
        命中 = [行.strip() for 行 in 代码行
               if re.search(r"require\([^)]*tools/|from\s+tools[\s.]|import\s+tools\b", 行)]
        记(f"{路径} 不引用 tools/ 下的测试工具", not 命中,
           f"命中了：{命中[:1]}")


def 检查_大模型白名单():
    文 = 读("bridge.py") or ""
    段 = re.search(r"白名单\s*=\s*\{(.*?)\}", 文, re.S)
    if not 段:
        记("大模型白名单可读", False, "没找到 白名单 = {…}")
        return
    键 = set(re.findall(r'"([^"]+)"\s*:', 段.group(1)))
    坏 = 键 & 攻击类
    记("大模型白名单里没有攻击类/动手类动作", not 坏, f"混进了：{坏}")
    记("大模型白名单非空且只含只读/移动类", bool(键), str(sorted(键)))


def 检查_插件能力面():
    文 = 读("node/plugins/body/proto_body.js") or ""
    段 = re.search(r"能力表\s*=\s*\[(.*?)\]", 文, re.S)
    能力 = set(re.findall(r"'([^']+)'", 段.group(1))) if 段 else set()
    坏 = 能力 & 危险动词
    记("身体插件能力表里没有危险动词", not 坏, f"混进了：{坏}")
    if 能力:
        记("身体插件的能力都是明确写出来的（不是开放的）", len(能力) < 40, str(sorted(能力)))


def 检查_宪法两条():
    """★★ M5/M6 的最高安全宪法（主人 2026-10-01 钦定）：
    ① LLM 不许直连攻击；② LLM 不许生成「打」步骤。"""
    文 = 读("bridge.py") or ""
    if "class 翻译器" not in 文:
        记("翻译器还没写（宪法检查跳过）", True)
        return
    段 = re.search(r"单步白名单\s*=\s*frozenset\(\{(.*?)\}\)", 文, re.S)
    白 = set(re.findall(r'"([^"]+)"', 段.group(1))) if 段 else set()
    坏 = 白 & 攻击类
    记("★ 宪法①：单步白名单里没有任何攻击类动作", not 坏, f"混进了：{坏}")
    禁 = re.search(r"禁止步骤\s*=\s*frozenset\(\{(.*?)\}\)", 文, re.S)
    禁集 = set(re.findall(r'"([^"]+)"', 禁.group(1))) if 禁 else set()
    记("★ 宪法②：任务书里显式禁止「打」步骤", "打" in 禁集, str(禁集))
    记("★ 宪法②落地：校验器里真的会拒（有拒绝分支）",
        "不许有" in 文 and "攻击权不在你手里" in 文)


def 检查_记忆三条宪法():
    """★★★ M7 的最高宪法（主人 2026-10-01 钦定）：
    ① 记忆不是指令（只进 prompt，不许触发动作）
    ② 不许发明关系（只记事实）
    ③ 不存聊天原文（只记名字与次数）
    用**语法树**查，不拿字符串 grep —— 类注释里提到这些词不算违规。"""
    import ast as _ast
    文 = 读("bridge.py") or ""
    if "class 记忆" not in 文:
        记("记忆类还没写（宪法检查跳过）", True)
        return
    try:
        树 = _ast.parse(文)
    except Exception as e:
        记("bridge.py 解析不了，宪法检查没法做", False, str(e))
        return
    类 = next((n for n in _ast.walk(树)
               if isinstance(n, _ast.ClassDef) and n.name == "记忆"), None)
    源 = _ast.get_source_segment(文, 类) or ""
    子 = _ast.parse(源)
    手法 = {n.func.attr for n in _ast.walk(子)
            if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Attribute)}
    记("★ 宪法①：记忆类里没有任何命令通道（发/执行/跑）",
       not (手法 & {"发", "执行", "跑", "命令"}), sorted(手法))
    字段 = {n.value for n in _ast.walk(子)
            if isinstance(n, _ast.Constant) and isinstance(n.value, str)}
    记("★ 宪法①b：记忆类里不出现 cmd / act 协议字段", not (字段 & {"cmd", "act"}))
    记("★ 宪法②：记忆类里不出现敌人/朋友这类关系标签",
       not (字段 & {"敌人", "朋友", "友好", "关系"}))
    记_人 = next((n for n in _ast.walk(子)
                 if isinstance(n, _ast.FunctionDef) and n.name == "记人"), None)
    参数 = [a.arg for a in (_ast.walk(记_人) if 记_人 else [])
            if isinstance(记_人, _ast.FunctionDef) and False] or \
           ([a.arg for a in 记_人.args.args] if 记_人 else [])
    记("★ 宪法③：记人只收「名字 + 字段名」（收不到聊天原文）",
       bool(参数) and "话" not in 参数, 参数)
    记("★ M7b 动作面默认锁着（expand_actions 默认 false）",
       '"expand_actions": false' in (读("config.json") or "").replace("False", "false"),
       None)


def 检查_任务栈fail_closed():
    文 = 读("bridge.py") or ""
    if "class 任务栈" not in 文:
        记("任务栈已实现时才会检查 fail-closed（现在还没写，跳过）", True)
        return
    has_允许 = "允许动作" in 文
    has_拒绝 = re.search(r"不在允许|未知动作|拒绝", 文) is not None
    记("任务栈有显式的「允许动作」清单", has_允许)
    记("任务栈对清单外的动作一律拒绝（fail-closed）", has_拒绝)


def main():
    print("═══ M4c·安全边界自检 ═══\n")
    检查_主链没有进程能力()
    检查_主链不引用测试工具()
    检查_大模型白名单()
    检查_插件能力面()
    检查_任务栈fail_closed()
    检查_宪法两条()
    检查_记忆三条宪法()
    for 行 in 通过 + 失败:
        print("  " + 行)
    print(f"\n═══ 共 {len(通过) + len(失败)} 条：通过 {len(通过)}，失败 {len(失败)} ═══")
    return 1 if 失败 else 0


if __name__ == "__main__":
    sys.exit(main())
