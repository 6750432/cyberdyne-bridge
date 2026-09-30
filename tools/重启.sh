#!/bin/bash
# 重启"手"和"脑"。
#
# ⚠ 这里绝不用 pkill -f / pgrep -f：命令里带着 "bridge.py" 这种字串时，
#   pkill 会把调用它的那个 shell 自己也一起杀掉（我在这上面栽过三次）。
#   改成看 comm 字段的精确进程名，就不会误伤。
#
# 用法：  bash tools/重启.sh                 正常启动（用 config 里的心跳）
#         bash tools/重启.sh --心跳秒 20      临时改心跳，方便盯测试
#         bash tools/重启.sh --只读           只看不控

cd "$(dirname "$0")/.." || exit 1
mkdir -p logs

# ⚠ bash 里一律用 ASCII 变量名 —— local 名字=... 会直接报 not a valid identifier
kill_match() {
  local cname="$1" cpat="$2"
  for p in $(ps -eo pid,comm,args --no-headers | awk -v n="$cname" -v m="$cpat" '$2==n && $0 ~ m {print $1}'); do
    kill "$p" 2>/dev/null && echo "  停了 $cname (pid $p)"
  done
}

echo "—— 停旧的 ——"
kill_match node 'server\.js'
kill_match python3 'bridge\.py'
sleep 2

echo "—— 起新的 ——"
rm -f cyberdyne.sock
# ⚠ 2026-10-01：**日志要轮转，不能截断**。原来这里是 `> logs/大脑.log`，
# 每次重启都把上一轮的叙事日志吃掉 —— 而那份日志正是实测的唯一证据。
# （代价：M4·猎手第一轮的完整日志就是这么没的，只能靠聊天里贴过的片段回忆。）
mkdir -p logs/历史
for f in logs/大脑.log node/bridge.log; do
  [ -s "$f" ] && mv "$f" "logs/历史/$(basename "$f" .log)-$(date +%Y%m%d-%H%M%S).log"
done
setsid nohup tools/启动手.sh > node/bridge.log 2>&1 < /dev/null &
sleep 8
setsid nohup tools/启动大脑.sh "$@" > logs/大脑.log 2>&1 < /dev/null &
sleep 6

echo "—— 现在的样子 ——"
ps -eo pid,ni,pcpu,rss,args --no-headers \
  | awk '$0 ~ /server\.js/ || $0 ~ /bridge\.py/ {print "  " $1, "nice=" $2, "cpu=" $3"%", "rss=" int($4/1024) "MB"}' \
  | grep -v awk
echo "  大脑日志：$PWD/logs/大脑.log"
