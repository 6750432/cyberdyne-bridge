#!/bin/bash
# 外挂列车 —— 启动 / 重启 / 看状态
#
# 跟老的 `外挂/动作面/重启脑.sh` 的区别：
#   老的：只起「动作面」一节，写死。
#   这个：起**车钩**，车厢按 `外挂/编组.json` 挂 —— 起完之后还能
#         用 `外挂/车钩ctl.py` 热挂/热摘，不用再重启脑。
#
# ★ 只重启「脑」，不动「手」：手握着到 Minecraft 的连接，脑只是通过
#   unix socket 跟它说话。换脑，手一点感觉都没有。
# ★ **绝不能 rm cyberdyne.sock** —— 那个 socket 是手在监听，删了手就废了。
#
# 用法：
#   bash 外挂/启动列车.sh              重启成列车（按编组.json）
#   bash 外挂/启动列车.sh --空车        重启成**空车**（一节不挂，裸脑）
#   bash 外挂/启动列车.sh --编组 动作面,受限脚本   指定这趟挂什么
#   bash 外挂/启动列车.sh --基线        用主链原入口起（回退走这条）
#   bash 外挂/启动列车.sh --看          只看现在的样子，**绝不动任何进程**
#
# ⚠ 历史教训（必须继承，别重犯）：
#   ① bash 里**中文变量名不合法**：`模式="外挂"` 会被当成命令，变量根本没设上，
#      结果「只想看一眼」的那次判假 → 把脑给停了。（2026-10-01 实机踩过）
#      → 全用 ASCII 变量名，并且参数不认识就**直接退出**。
#   ② 用 `ps | awk /bridge.py/` 找脑在外挂模式下**一个都找不到**，会重复起，
#      最后三个脑抢同一个 socket。（2026-10-01 踩过）
#      → 改成读 /proc/<pid>/cmdline 的原始字节。

cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"

MODE="列车"
GROUP=""
case "$1" in
  "")       MODE="列车" ;;
  "--空车") MODE="空车" ;;
  "--基线") MODE="基线" ;;
  "--看")   MODE="看" ;;
  "--编组")
    if [ -z "${2:-}" ]; then
      echo "★ --编组 后面要跟车厢名（逗号分隔），比如 --编组 动作面,受限脚本"
      exit 2
    fi
    MODE="列车"; GROUP="$2" ;;
  *)
    echo "★ 不认识的参数：$1"
    echo "  只认：--空车 / --基线 / --看 / --编组 <名单> /（空）"
    echo "  ★ 拒绝执行 —— 绝不因为参数看不懂就去停进程。"
    exit 2
    ;;
esac
set -u

# ── 认脑：读 /proc 原始字节，locale 影响不到 ──
# 三种起法都认：主链原入口 / 老的动作面外挂 / 新的车钩
脑进程() {
  python3 - <<'PY'
import os
for name in sorted(os.listdir('/proc'), key=lambda x: int(x) if x.isdigit() else 0):
    if not name.isdigit():
        continue
    try:
        line = ' '.join(x.decode('utf-8', 'replace')
                        for x in open(f'/proc/{name}/cmdline', 'rb').read().split(b'\0') if x)
        comm = open(f'/proc/{name}/comm').read().strip()
    except Exception:
        continue
    if comm == 'python3' and ('bridge.py' in line or '大脑外挂.py' in line
                              or '车钩.py' in line):
        print(name)
PY
}

看状态() {
  local pids hands
  pids=$(脑进程 | tr '\n' ' ')
  echo "  脑：${pids:-（没有在跑）}"
  hands=$(ps -eo pid,comm --no-headers | awk '$2=="node" {print $1}' | tr '\n' ' ')
  echo "  手（node）：${hands:-（没有在跑）}"
  echo -n "  config 开关：动作面="
  python3 -c "import json;print(json.load(open('config.json',encoding='utf-8'))['m7']['expand_actions'],end='')"
  echo -n "  受限剧本="
  python3 -c "import json;print(json.load(open('config.json',encoding='utf-8'))['m7'].get('受限剧本'))"
  if [ -S 外挂/车钩.sock ]; then
    echo "  车钩插座：在（脑是列车模式起的，可以热插拔）"
  else
    echo "  车钩插座：**不在**（脑不是列车模式 → 热插拔用不了）"
  fi
  if [ -f logs/大脑.log ]; then
    echo "  脑日志最后两行："
    tail -2 logs/大脑.log | sed 's/^/    /'
  fi
}

if [ "$MODE" = "看" ]; then
  echo "—— 现在的样子（--看 模式：绝对不动任何进程）——"
  看状态
  exit 0
fi

echo "—— 停旧的脑（手不动）——"
STOPPED=0
for p in $(脑进程); do
  kill "$p" 2>/dev/null && echo "  停了脑 pid $p" && STOPPED=1
done
[ "$STOPPED" = "0" ] && echo "  （没有脑在跑，跳过）"
sleep 2

echo "—— 日志轮转（**不截断**，上一轮的日志是唯一证据）——"
mkdir -p logs/历史
[ -s logs/大脑.log ] && mv logs/大脑.log "logs/历史/大脑-$(date +%Y%m%d-%H%M%S).log" \
  && echo "  旧的挪进 logs/历史/"

echo "—— 起新的（$MODE${GROUP:+ · 编组=$GROUP}）——"
if [ "$MODE" = "基线" ]; then
  setsid nohup tools/启动大脑.sh > logs/大脑.log 2>&1 < /dev/null &
elif [ "$MODE" = "空车" ]; then
  setsid nohup python3 -u 外挂/车钩.py --空车 > logs/大脑.log 2>&1 < /dev/null &
elif [ -n "$GROUP" ]; then
  setsid nohup python3 -u 外挂/车钩.py --编组 "$GROUP" > logs/大脑.log 2>&1 < /dev/null &
else
  setsid nohup python3 -u 外挂/车钩.py > logs/大脑.log 2>&1 < /dev/null &
fi
sleep 9

echo "—— 现在的样子 ——"
看状态
echo
echo "  大脑日志：$ROOT/logs/大脑.log"
echo "  车钩日志：$ROOT/logs/外挂-车钩.log"
echo
echo "  想热插拔就用：python3 外挂/车钩ctl.py 编组"
