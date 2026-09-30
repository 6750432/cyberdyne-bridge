#!/bin/bash
# M7b·动作面外挂 —— 一键回退（出任何事就跑这一个命令）
#
#   bash 外挂/动作面/回退.sh
#
# 干三件事：
#   ① config.json 的 m7.expand_actions 关掉（先备份）
#   ② 用**主链原入口**把脑起回来（外挂的补丁一个都不打）
#   ③ 自己核对一遍：开关关了没、脑是不是基线入口起的、补丁还在不在
#
# ★ 为什么"关开关 + 换入口"两道都要：
#   光关开关不够 —— 已经在跑的脑是**启动那一刻**读的开关，
#   改文件不会影响它。必须重启脑才真的退回去。
#
# ★ 这一条**永远不动 bridge.py**。最狠的一招（万一磁盘上的主链也被搞了）是：
#      cd ~/cyberdyne-bridge && git reset --hard 基线-M1-M7a
#   但正常情况下永远用不着 —— 因为外挂从设计上就没碰过那个文件。

cd "$(dirname "$0")/../.." || exit 1
ROOT="$(pwd)"

echo "════ M7b 动作面外挂 · 回退 ════"

echo "—— ① 关开关（先备份 config.json）——"
mkdir -p "$HOME/cyberdyne-快照"
cp -p config.json "$HOME/cyberdyne-快照/config.json.回退前-$(date +%Y%m%d-%H%M%S)"
python3 - <<'PY'
import json, io
p = "config.json"
c = json.load(io.open(p, encoding="utf-8"))
旧 = (c.get("m7") or {}).get("expand_actions")
(c.setdefault("m7", {}))["expand_actions"] = False
io.open(p, "w", encoding="utf-8").write(json.dumps(c, ensure_ascii=False, indent=2) + "\n")
print(f"  m7.expand_actions：{旧} → False")
PY

echo "—— ② 换回主链原入口重启脑 ——"
bash 外挂/动作面/重启脑.sh --基线

echo "—— ③ 自己核对 ——"
开关=$(python3 -c "import json;print(json.load(open('config.json',encoding='utf-8'))['m7']['expand_actions'])")
[ "$开关" = "False" ] && echo "  ✅ 开关 = False" || echo "  ❌ 开关还是 $开关"
if grep -q "外挂·动作面" logs/大脑.log 2>/dev/null; then
  echo "  ❌ 脑日志里还有外挂的痕迹 —— 可能没退干净"
else
  echo "  ✅ 脑日志里没有外挂的启动横幅（走的是主链原入口）"
fi
echo -n "  bridge.py 指纹："
sha256sum bridge.py | cut -c1-16
echo "  （基线是 2499f81f807431b0；对不上就说明磁盘上的主链被动过 —— 立刻喊人）"
echo
echo "回退完成。小家伙现在跑的是纯基线。"
