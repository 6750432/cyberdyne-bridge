#!/bin/bash
# M7b·动作面外挂 —— 只重启「脑」，不动「手」
#
# 为什么只重启脑：
#   手（node/server.js）握着到 Minecraft 的连接。重启它会掉线、小家伙要重新登录。
#   而脑只是通过 unix socket 跟手说话 —— 换一个脑，手一点感觉都没有。
#   ★ 所以**绝不能 rm cyberdyne.sock**：那个 socket 是手在监听，删了手就废了。
#     （tools/重启.sh 里会 rm，那是因为它把手和脑一起停了。）
#
# 用法：
#   bash 外挂/动作面/重启脑.sh            用**外挂**起（开关开着才有补丁）
#   bash 外挂/动作面/重启脑.sh --基线      用**主链原入口**起（回退走这条）
#   bash 外挂/动作面/重启脑.sh --看        只看现在的状态，不动任何东西

cd "$(dirname "$0")/../.." || exit 1
ROOT="$(pwd)"
模式="外挂"
case "$1" in
  --基线) 模式="基线" ;;
  --看)   模式="看" ;;
esac

# ⚠ bash 里一律用 ASCII 变量名（中文变量名会被当成命令去执行，踩过）
脑进程() {
  ps -eo pid,comm,args --no-headers | awk '$2=="python3" && /bridge\.py/ && !/awk/ {print $1}'
}

看状态() {
  local pids
  pids=$(脑进程 | tr '\n' ' ')
  echo "  脑（python3 bridge.py）：${pids:-（没有在跑）}"
  local hands
  hands=$(ps -eo pid,comm --no-headers | awk '$2=="node" {print $1}' | tr '\n' ' ')
  echo "  手（node）：${hands:-（没有在跑）}"
  echo -n "  config 开关："
  python3 -c "import json;print(json.load(open('config.json',encoding='utf-8'))['m7']['expand_actions'])"
  if [ -f logs/大脑.log ]; then
    echo "  脑日志最后两行："
    tail -2 logs/大脑.log | sed 's/^/    /'
  fi
}

if [ "$模式" = "看" ]; then
  echo "—— 现在的样子 ——"
  看状态
  exit 0
fi

echo "—— 停旧的脑（手不动）——"
for p in $(脑进程); do
  kill "$p" 2>/dev/null && echo "  停了脑 pid $p"
done
sleep 2

echo "—— 日志轮转（**不截断**，上一轮的日志是唯一证据）——"
mkdir -p logs/历史
[ -s logs/大脑.log ] && mv logs/大脑.log "logs/历史/大脑-$(date +%Y%m%d-%H%M%S).log" && echo "  旧的挪进 logs/历史/"

echo "—— 起新的（$模式）——"
if [ "$模式" = "基线" ]; then
  setsid nohup tools/启动大脑.sh > logs/大脑.log 2>&1 < /dev/null &
else
  setsid nohup bash 外挂/动作面/启动.sh > logs/大脑.log 2>&1 < /dev/null &
fi
sleep 8

echo "—— 现在的样子 ——"
看状态
echo "  大脑日志：$ROOT/logs/大脑.log"
