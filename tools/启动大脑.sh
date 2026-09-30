#!/bin/bash
# 起"脑"（Python 反射层）。纯标准库，不连任何云端 API。
cd "$(dirname "$0")/.." || exit 1
exec nice -n 15 ionice -c3 python3 -u bridge.py "$@"
