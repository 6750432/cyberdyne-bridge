#!/bin/bash
# M7b·动作面外挂 —— 脑侧启动器
#
# 为什么另起一个启动器，而不去改 tools/启动大脑.sh：
#   那个是**基线入口**，改了它主链就不干净了。这个脚本跟它唯一的区别
#   就是最后跑的是"外挂"（外挂内部再去调 bridge.主()）。
#
# 用法：
#   bash 外挂/动作面/启动.sh            # 前台起（开关关着 = 基线行为）
#   bash 外挂/动作面/启动.sh --自检      # 只查锚点
#   bash 外挂/动作面/启动.sh --演练      # 走到交棒前就停
#
# ★ 两条铁律写在这儿，免得以后忘：
#   1. **脑只能有一个。** 已经在跑的时候这里会拒绝启动 —— 两个脑抢同一个
#      socket，行为会变得没法解释。
#   2. 主链 bridge.py 一个字节都不许动。这个目录里所有东西都是"挂在外面"的。

cd "$(dirname "$0")/../.." || exit 1
ROOT="$(pwd)"

# ── 铁律 1：脑只能有一个 ──
# 用 comm=="python3" 精确匹配，避免 pgrep -f / awk 匹配到自己（这坑踩过）
# ⚠ bash 里**不能用中文变量名**（locale 是 C）—— 我第一版写成 `在跑=$(…)`，
#   bash 把它当命令去执行，结果护栏变成"永远拒绝启动"的假阳性。
#   2026-10-01 当场抓到，改成 ASCII 名。
RUNNING=$(
  # ★ 判据与 重启脑.sh 完全一致：读 /proc，不看 ps 的 args
  #   （外挂模式下命令行里没有 bridge.py，而且 locale=C 会把中文路径显示成 ??????
  #     —— 2026-10-01 实机就因为这两条同时成立，护栏失效、起了三个脑）
  python3 - <<'PY' | tr '\n' ' '
import os
for 名 in sorted(os.listdir('/proc')):
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
)
if [ -n "$RUNNING" ]; then
  echo "★ 已经有一个脑在跑了（pid：$RUNNING）—— 拒绝再起一个。"
  echo "  要先停的话：bash tools/重启.sh      （它会把手和脑一起重启）"
  exit 9
fi

echo "启动器：外挂·动作面（主链 bridge.py 一个字节都没动）"
echo "工作目录：$ROOT"
exec nice -n 15 ionice -c3 python3 -u "$ROOT/外挂/动作面/大脑外挂.py" "$@"
