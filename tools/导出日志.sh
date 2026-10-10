#!/bin/bash
# 导出小家伙的日志（一次性打包，给主人存档 / 给外人看证据）
#   用法：bash ~/cyberdyne-bridge/tools/导出日志.sh [输出目录]
set -u
SRC="$HOME/cyberdyne-bridge/logs"
STAMP=$(date +%Y%m%d-%H%M)
DEST="${1:-$HOME/Desktop/78/小家伙日志-$STAMP}"
mkdir -p "$DEST" || exit 1

# 1) 它自己的话（主链日志：视觉、动作、成功失败、说了什么）
cp -f "$SRC/大脑.log"        "$DEST/1-大脑-它自己的所见所说.log" 2>/dev/null
# 2) 手侧日志（mineflayer：连接、插件、命令回执）
cp -f "$SRC/手.log"          "$DEST/2-手-身体层.log"            2>/dev/null
# 3) 车钩日志（外挂列车：挂了哪几节车厢、热插拔）
cp -f "$SRC/外挂-车钩.log"   "$DEST/3-车钩-外挂列车.log"        2>/dev/null
# 4) ★ 决策日志（大模型每一次"自己定了个目标"、被拒、退避）
cp -f "$SRC/心跳.jsonl"      "$DEST/4-决策日志-大模型定过什么目标.jsonl" 2>/dev/null
# 5) 账本（每一次动作的原始账）
for f in "$SRC"/账本-*.jsonl; do
  [ -e "$f" ] || continue
  cp -f "$f" "$DEST/5-$(basename "$f")" 2>/dev/null
done
# 6) 看护（反射层：跑、吃、保命、还手）
cp -f "$SRC/看护.csv"        "$DEST/6-看护-反射层.csv"          2>/dev/null

# 说明书
{
  echo "这份日志是什么"
  echo "=============="
  echo
  echo "小家伙（Minecraft 玩家名 DeepSeek）跑起来之后的**全部原始记录**。"
  echo "不是事后补写的，是它跑的时候一行一行落盘的。"
  echo
  echo "文件清单"
  echo "--------"
  echo "1-大脑-它自己的所见所说.log"
  echo "    它自己的视角日志。每一拍记：站在哪、周围有什么、看得见什么、"
  echo "    自己给自己定了什么目标、每一步动作成没成、在游戏里说了什么。"
  echo "    ★ 想知道「它是不是脚本」，先看这个 ——"
  echo "      里面全是带【视觉】的现场播报，脚本不会每拍都重新看世界。"
  echo
  echo "2-手-身体层.log"
  echo "    身体层（Node/mineflayer）的日志：连服务器、加载插件、每条命令的回执。"
  echo "    挖没挖到、放没放成、为什么放不成 —— 真相在这一层。"
  echo
  echo "3-车钩-外挂列车.log"
  echo "    车厢调度：几点挂上哪几节车厢、换轨花了多少毫秒、有没有冲突告警。"
  echo "    这一层是「插件化」的证据 —— 能力是拼上去的，不是写死在主链里的。"
  echo
  echo "4-决策日志-大模型定过什么目标.jsonl          ★ 重点"
  echo "    ★★ 这就是「防止有人觉得我们是脚本」要的东西。"
  echo "    每一条是大模型**自己**做的决定，带原因、带时间戳："
  echo "      {\"事件\":\"自己定了个目标\",\"任务\":\"…\",\"为什么\":\"…\"}"
  echo "      {\"事件\":\"被校验拒了\",\"原因\":\"…\"}"
  echo "      {\"事件\":\"空转两次，退避\", …}"
  echo "    时间戳能跟录屏对上 —— 可以逐条核对「它在第几分几秒决定去干嘛」。"
  echo "    脚本不会有「自己定了个目标 + 为什么」这种带理由的决策记录。"
  echo
  echo "5-账本-*.jsonl"
  echo "    每一次动作的原始流水账（接单、步骤开始、完成、重试、失败）。"
  echo "    要给「到底做了哪些动作」较真，查这个。"
  echo
  echo "6-看护-反射层.csv"
  echo "    保命反射层：跑、吃、还手。这层是本地规则，不走大模型。"
  echo
  echo "怎么读时间"
  echo "----------"
  echo "    大脑/手/车钩 的日志是 [时:分] 或 [年-月-日 时:分:秒]；"
  echo "    决策日志和账本是 Unix 时间戳（t / 秒）。换算：  date -d @1790799447"
  echo
  echo "导出于：$(date '+%Y-%m-%d %H:%M:%S')"
} > "$DEST/00-看这里.txt"

echo "✅ 导出好了：$DEST"
ls -lh "$DEST" | tail -n +2
