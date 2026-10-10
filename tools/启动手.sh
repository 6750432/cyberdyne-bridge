#!/bin/bash
# 起"手"（Node/mineflayer）。nice 15 + ionice 空闲档：
# 这台机器的系统盘是机械硬盘，小家伙不能跟主人的程序抢 IO。
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.local/node/bin:$PATH"
# ★★★ 2026-10-09：**日志归这个脚本自己管** ✓
#   现场：我手动起手时没写重定向 → 它的日志落进了 /tmp/手起2.log ✗，
#   而项目眼睛盯着的是 logs/手.log ✗ —— 于是「手活着但日志一片死寂」，害我查了半天 ✓
#   规矩（还是那一条）：**起法只有一处实现** ✓ —— 谁调这个脚本，日志都落在同一个地方 ✓
#   （`exec >>` 是在**继承来的 fd 上**再指一次同一个文件 ✓ 不会写两遍 ✓）
mkdir -p logs
exec >> logs/手.log 2>&1
echo "───────── $(date '+%F %T') 手起来了（pid $$ 的壳，node 随后 exec）─────────"
exec nice -n 15 ionice -c3 node node/server.js
