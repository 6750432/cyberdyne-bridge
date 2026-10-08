#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验闸三有牙.py —— 证明「准真实路径测试」真的会叫。

为什么要有这个
==============
主人的 T4：「**測試沒覆蓋真實路徑**」。
  但还有个更阴的坑：**测试跑了、也过了，可它其实什么也拦不住** ✗
  标准是：**把真程序的护栏故意改坏，测试必须当场叫**。
  改坏了它还不叫 → 那是块没牙的橡皮图章 ✗ 比没测试更坏（给人虚假的安全感）。

做法（全是本机、不连服务器）
  ① 只有三种变异，每种**只改一行**，改的是真代码里那三处「資訊有卻不用」的护栏；
  ② 每一处替换前先数一下**必须命中且只命中 1 次**（命中 0 次 = 我记错了代码，
     命中 >1 次 = 我改的面太宽，两种情况都立刻中止 ✗）；
  ③ 变异副本写到 `node/测试/.临时变异/` 里 —— 放这儿是为了让它还能
     `require('vec3')`（node 会往上层目录找 node_modules）；
  ④ 拿 `PROTO_BODY_PATH` 指过去跑测试，**期望它失败**；
     而且失败名单里必须**出现该场景的用例名**（别的原因挂了不算数）；
  ⑤ 跑完全清场，绝不碰真插件。

跑法： cd ~/cyberdyne-bridge && python3 node/测试/验闸三有牙.py
"""

import os
import pathlib
import shutil
import subprocess
import sys

基地 = pathlib.Path(__file__).resolve().parents[2]          # ~/cyberdyne-bridge
真插件 = 基地 / 'node' / 'plugins' / 'body' / 'proto_body.js'
测试件 = 基地 / 'node' / '测试' / '准真实路径.test.js'
变异铺 = 基地 / 'node' / '测试' / '.临时变异'
节点 = os.path.expanduser('~/.local/node/bin/node')

# (变异名, 原来那一行, 换成什么, 应该叫出来的用例名)
变异表 = [
    ('① 跳跃不查头顶',
     'if (头顶 && 通得过.indexOf(头顶.name) < 0) {',
     'if (false) {',
     'A 跳跃：头顶堵着'),
    ('② 放置不查目标格',
     "if (位.name !== 'air' && 位.name !== 'cave_air') {",
     'if (false) {',
     'B 放置：目标格被占'),
    ('③ 挖不查是不是空气',
     "if (块.name === 'air' || 块.name === 'cave_air' || 块.name === 'void_air') {",
     'if (false) {',
     'C 挖掘：那一格明确是空气'),
]


def 跑测试(插件路径):
    """跑一遍测试，回 (通过吗, 整段输出)。"""
    环境 = dict(os.environ, PROTO_BODY_PATH=str(插件路径))
    出 = subprocess.run([节点, '--test', str(测试件)],
                        cwd=str(基地), env=环境, capture_output=True, text=True, timeout=300)
    全文 = (出.stdout or '') + (出.stderr or '')
    return 出.returncode == 0, 全文


def main():
    if not 真插件.exists():
        print(f'✗ 找不到真插件：{真插件}')
        return 2

    原文 = 真插件.read_text(encoding='utf-8')

    # ── 第一关：先确认原版是**绿的**，不然"变异后变红"说明不了任何事 ──
    绿, 全文 = 跑测试(真插件)
    if not 绿:
        print('✗ 原版就没过，先修真插件或者修测试：')
        print('\n'.join(行 for 行 in 全文.splitlines() if 行.startswith('not ok'))[:2000])
        return 1
    print(f'✔ 基准：原版测试全绿（{真插件.relative_to(基地)}）')
    print()

    变异铺.mkdir(parents=True, exist_ok=True)
    成绩 = []
    try:
        for 名, 旧, 新, 该叫的用例 in 变异表:
            处数 = 原文.count(旧)
            if 处数 != 1:
                print(f'✗【{名}】这段代码在真插件里出现 {处数} 次（必须正好 1 次）——')
                print(f'   我记错了代码，或者改的面太宽。这一条**没验成**，不算通过。')
                成绩.append((名, '没验成', f'命中 {处数} 次'))
                continue

            副本 = 变异铺 / 'proto_body.mut.js'
            副本.write_text(原文.replace(旧, 新), encoding='utf-8')

            绿, 全文 = 跑测试(副本)
            失败名单 = [行 for 行 in 全文.splitlines() if 行.startswith('not ok')]
            咬中了 = any(该叫的用例 in 行 for 行 in 失败名单)

            if 绿:
                print(f'✗【{名}】改坏了护栏，测试竟然**还是全绿** —— 这块橡皮图章没牙！')
                成绩.append((名, '没牙', '改了却不叫'))
            elif not 咬中了:
                print(f'✗【{名}】测试是红了，但挂的不是该挂的那条（可能是别的原因）：')
                for 行 in 失败名单[:4]:
                    print(f'     {行}')
                成绩.append((名, '咬错了', '挂的不是该挂的用例'))
            else:
                咬了的 = [行 for 行 in 失败名单 if 该叫的用例 in 行]
                print(f'✔【{名}】改坏后测试当场叫了：{咬了的[0].strip()}')
                成绩.append((名, '有牙', ''))

            # ★ 每次都要把副本跟"上一条变异"分开，别串味
            副本.unlink()
    finally:
        shutil.rmtree(变异铺, ignore_errors=True)   # 清场，绝不留痕

    print()
    好的 = [s for s in 成绩 if s[1] == '有牙']
    print(f'══ 牙口：{len(好的)}/{len(变异表)} ══')
    for 名, 果, 附 in 成绩:
        记号 = {'有牙': '✔', '没牙': '✗', '咬错了': '✗', '没验成': '⚠'}[果]
        print(f'  {记号} {名}　{果}　{附}')
    if len(好的) != len(变异表):
        print('\n✗ 有变异没被咬住 → 闸三**还不算过关**。')
        return 1
    print('\n✔ 三处护栏、三条用例，改一处叫一条 —— 闸三有牙。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
