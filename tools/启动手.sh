#!/bin/bash
# 起"手"（Node/mineflayer）。nice 15 + ionice 空闲档：
# 这台机器的系统盘是机械硬盘，小家伙不能跟主人的程序抢 IO。
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.local/node/bin:$PATH"
exec nice -n 15 ionice -c3 node node/server.js
