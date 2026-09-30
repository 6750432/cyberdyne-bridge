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
#
# ⚠⚠ 2026-10-01 血的教训（第一次实机验收时踩的）：
#   这一版第一稿把模式变量写成中文 `模式="外挂"` —— bash 里**中文变量名不合法**，
#   它把 `模式="外挂"` 当成"要去执行一个叫 模式=外挂 的命令"，于是变量**根本没设上**。
#   后果：`if [ "$模式" = "看" ]` 判假 → **本来只想"看一眼"，却把脑给停了**。
#   小家伙当了 40 秒没脑的鱼。
#   ★ 修法：全用 ASCII 变量名（MODE）；并且给 `--看` 加一道**兜底判断** ——
#     参数不是已知的三个之一就直接退出，绝不落进"停进程"那条路。

cd "$(dirname "$0")/../.." || exit 1
ROOT="$(pwd)"

# ── 参数：只认这三个，别的**一律退出**（绝不默认去停进程）──
MODE="外挂"
case "$1" in
  "")        MODE="外挂" ;;
  "--基线")  MODE="基线" ;;
  "--看")    MODE="看" ;;
  *)
    echo "★ 不认识的参数：$1"
    echo "  只认：--基线 / --看 /（空）"
    echo "  ★ 拒绝执行 —— 绝不因为参数看不懂就去停进程。"
    exit 2
    ;;
esac
set -u

# ★★ 2026-10-01 实机踩的大坑：用 `ps ... args | awk /bridge\.py/` 找脑，
#    在外挂模式下**一个都找不到** —— 因为：
#      ① 外挂跑的是 `python3 -u 外挂/动作面/大脑外挂.py`，命令行里根本没有 bridge.py；
#      ② 沙盒 locale 是 C，ps 会把中文路径显示成 ??????，正则更匹配不上。
#    后果：启动器以为没脑在跑 → 反复起新的 → **三个脑抢同一个 socket**。
#    现在改成直接读 /proc/<pid>/cmdline（原始字节，按 utf-8 解），locale 影响不到。
脑进程() {
  python3 - <<'PY'
import os
for 名 in sorted(os.listdir('/proc'), key=lambda x: int(x) if x.isdigit() else 0):
    if not 名.isdigit():
        continue
    try:
        行 = ' '.join(x.decode('utf-8', 'replace')
                     for x in open(f'/proc/{名}/cmdline', 'rb').read().split(b'\0') if x)
        通 = open(f'/proc/{名}/comm').read().strip()
    except Exception:
        continue
    if 通 == 'python3' and ('bridge.py' in 行 or '大脑外挂.py' in 行):
        print(名)
PY
}

看状态() {
  local pids hands
  pids=$(脑进程 | tr '\n' ' ')
  echo "  脑（python3 bridge.py）：${pids:-（没有在跑）}"
  hands=$(ps -eo pid,comm --no-headers | awk '$2=="node" {print $1}' | tr '\n' ' ')
  echo "  手（node）：${hands:-（没有在跑）}"
  echo -n "  config 开关："
  python3 -c "import json;print(json.load(open('config.json',encoding='utf-8'))['m7']['expand_actions'])"
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
停了=0
for p in $(脑进程); do
  kill "$p" 2>/dev/null && echo "  停了脑 pid $p" && 停了=1
done
[ "$停了" = "0" ] && echo "  （没有脑在跑，跳过）"
sleep 2

echo "—— 日志轮转（**不截断**，上一轮的日志是唯一证据）——"
mkdir -p logs/历史
[ -s logs/大脑.log ] && mv logs/大脑.log "logs/历史/大脑-$(date +%Y%m%d-%H%M%S).log" && echo "  旧的挪进 logs/历史/"

echo "—— 起新的（$MODE）——"
if [ "$MODE" = "基线" ]; then
  setsid nohup tools/启动大脑.sh > logs/大脑.log 2>&1 < /dev/null &
else
  setsid nohup bash 外挂/动作面/启动.sh > logs/大脑.log 2>&1 < /dev/null &
fi
sleep 8

echo "—— 现在的样子 ——"
看状态
echo "  大脑日志：$ROOT/logs/大脑.log"
