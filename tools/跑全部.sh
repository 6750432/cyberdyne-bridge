#!/usr/bin/env bash
# 跑全部.sh —— 一条命令跑完整套闸门（主人 2026-10-08 清单 P1-3）
#
# 为什么要它
# ==========
# 之前是"想起来哪个跑哪个"，结果 `测动作面.py`（99 条）和 `测数据.py`（56 条）
# **一直没进过合计** —— 报「441 条 0 失败」的时候，那 155 条压根没跑过 ✗
# 这就是 T4「測試沒覆蓋真實路徑」的同族病：**没跑的测试，等于没有**。
#
# ★ 三条硬规矩（都是拿血换的）
#   ① 退出码非 0 却解析出「0 失败」→ **必须大声报**，不许安静地印 0 失败 ✗
#      （解析不出汇总格式 ≠ 没失败；这是我自己的 T3 病）
#   ② 每个文件都要印出**解析到多少条**，人一眼能看出"这条到底跑没跑"
#   ③ 审计型的（空间决策表）单列，不混进通过数
#
# 跑法： bash tools/跑全部.sh
#        bash tools/跑全部.sh --快   （跳过 JS 那条）
# 退出码：0 全过 / 1 有失败

set -o pipefail
cd "$(dirname "$0")/.." || exit 3
NODE=$HOME/.local/node/bin/node

# 断言型：格式 A「N 过 / M 失败」、格式 B「共 N 条：通过 P，失败 Q」，两种都认
TESTS=(
  外挂/测车钩.py
  外挂/测任务书.py
  外挂/测生存常识.py
  外挂/测挖空守卫.py
  外挂/测物理体检.py
  外挂/测分饭.py
  外挂/测贯通审计.py
  外挂/测视线遮挡.py
  外挂/测回执探针.py
  外挂/测就地取材.py
  外挂/测声呐耳朵.py
  外挂/测工具查表.py
  外挂/测障碍自愈.py
  外挂/测够不着自愈.py
  外挂/测手上一件事.py
  外挂/常识/测常识.py
  外挂/动作面/测动作面.py
  外挂/动作面/测数据.py
  tools/彩排-够不着.py      # ★ 端到端彩排：真任务栈 + 假出口（不是替身 ✓）
)
# 审计型：只报「已接/缺口」，不参与通过数
AUDITS=(外挂/测空间决策.py)

total_pass=0
total_fail=0
bad_files=()

echo "══════════ 赛博戴恩桥 · 全套闸门 ══════════"

for t in "${TESTS[@]}"; do
  if [ ! -f "$t" ]; then
    echo "  ⚠ 缺文件：$t"
    bad_files+=("$t 缺文件")
    continue
  fi
  out=$(timeout 900 python3 "$t" 2>&1)
  rc=$?
  # ── 解析汇总行（★ 两种语序都要认：「0 失败」和「失败 0」）──
  #    踩过的坑：只认「失败 0」→ 格式 A 一行都匹配不到 → $line 是空的 →
  #    被当成"解析不到"⚠。上次是靠 cat -A 打印原文才看出来的，别再猜。
  line=$(printf '%s\n' "$out" | sed -r 's/\x1b\[[0-9;]*m//g' \
          | grep -E '[0-9]+[ ]*失败[ ]*$|失败[ ]*[0-9]+[ ]*$' | tail -1)
  p=0; f=0
  if printf '%s' "$line" | grep -qE '共 [0-9]+ 条：通过'; then
    p=$(printf '%s' "$line" | sed -nE 's/.*通过[ ]*([0-9]+).*/\1/p')
    f=$(printf '%s' "$line" | sed -nE 's/.*失败[ ]*([0-9]+)[ ]*$/\1/p')
  elif printf '%s' "$line" | grep -qE '[0-9]+[ ]*过[ ]*/[ ]*[0-9]+[ ]*失败'; then
    p=$(printf '%s' "$line" | sed -nE 's/.*[^0-9]([0-9]+)[ ]*过[ ]*\/.*/\1/p')
    f=$(printf '%s' "$line" | sed -nE 's/.*([0-9]+)[ ]*失败[ ]*$/\1/p')
  fi
  p=${p:-0}; f=${f:-0}
  total_pass=$((total_pass + p))
  total_fail=$((total_fail + f))

  if [ "$rc" -eq 0 ] && [ "$p" -gt 0 ]; then
    echo "  ✔ $(basename "$t")　${p} 条过"
  elif [ "$rc" -ne 0 ] && [ "$f" -eq 0 ]; then
    # ★★ 第一号硬规矩：退出码说错了，就绝不能印「0 失败」
    echo "  ✗ $(basename "$t")　**有失败，但汇总格式没认出来**（退出码 $rc）—— 别信下面这个 0"
    bad_files+=("$t")
    printf '%s\n' "$out" | grep -E '❌|\[挂\]|✗ |AssertionError|Traceback' | head -6 | sed 's/^/       /'
  elif [ "$rc" -ne 0 ]; then
    echo "  ✗ $(basename "$t")　${p} 过 / ${f} 失败（退出码 $rc）"
    bad_files+=("$t")
    printf '%s\n' "$out" | grep -E '❌|\[挂\]|✗ ' | head -6 | sed 's/^/       /'
  else
    # 退出码 0 却一条也没解析出来 —— 可能是"空跑"，也报出来
    echo "  ⚠ $(basename "$t")　退出码 0，但**一条断言都没解析到** —— 它真跑了吗？"
    bad_files+=("$t 没解析到断言")
  fi
done

for t in "${AUDITS[@]}"; do
  if [ ! -f "$t" ]; then echo "  ⚠ 缺文件：$t"; continue; fi
  out=$(timeout 900 python3 "$t" 2>&1)
  n_jie=$(printf '%s\n' "$out" | grep -oE '已接[：:][^0-9]*[0-9]+' | grep -oE '[0-9]+$' | tail -1)
  n_que=$(printf '%s\n' "$out" | grep -oE '缺口[：:][^0-9]*[0-9]+' | grep -oE '[0-9]+$' | tail -1)
  # ⚠ 变量名必须 ASCII —— 这里我连踩两次：先写 `接=`，改成 `接上的=` 还是中文 ✗
  echo "  ▤ $(basename "$t")　审计表：已接 ${n_jie:-?} 条 ｜ 缺口 ${n_que:-?} 处（不参与通过数）"
done

# ── JS 那条：主链的"手"是 JS 写的，光测 Python 盖不住它 ──
#   ★ 2026-10-09：从一个文件改成**一份清单** ✓
#     起因：我加了 `声呐紧急通道.test.js`（「叮」要走紧急通道那条链），
#     可这里写死了 `准真实路径.test.js` 一个名字 ✗ → 新那一条**压根不会跑** ✓
#     "没跑的测试，等于没有" —— 这就是本脚本开头那条硬规矩的同族病 ✓
JS_TESTS=(
  node/测试/准真实路径.test.js
  node/测试/声呐紧急通道.test.js
  node/测试/身边四格.test.js
)
if [ "$1" != "--快" ]; then
  if [ -x "$NODE" ]; then
    for jt in "${JS_TESTS[@]}"; do
      if [ ! -f "$jt" ]; then echo "  ⚠ 缺文件：$jt"; bad_files+=("$jt 缺文件"); continue; fi
      out=$(timeout 300 "$NODE" --test "$jt" 2>&1)
      rc=$?
      jsn=$(printf '%s\n' "$out" | sed -nE 's/^# pass ([0-9]+)$/\1/p' | tail -1)
      jsf=$(printf '%s\n' "$out" | sed -nE 's/^# fail ([0-9]+)$/\1/p' | tail -1)
      jsn=${jsn:-0}; jsf=${jsf:-0}
      total_pass=$((total_pass + jsn))
      total_fail=$((total_fail + jsf))
      if [ "$rc" -eq 0 ]; then
        echo "  ✔ $(basename "$jt")　${jsn} 条过（假 bot，不连服务器）"
      else
        echo "  ✗ $(basename "$jt")　${jsn} 过 / ${jsf} 失败"
        bad_files+=("$(basename "$jt")")
        printf '%s\n' "$out" | grep '^not ok' | head -6 | sed 's/^/       /'
      fi
    done
  else
    echo "  ⚠ 找不到 node：$NODE　（JS 那两条跳过了）"
    bad_files+=("JS 没跑")
  fi
fi

# ── 红线：主链一个字节都不许动 ──
hash=$(sha256sum bridge.py | cut -c1-16)
echo
if [ "$hash" = "2499f81f807431b0" ]; then
  echo "  ✔ 红线　bridge.py 指纹 $hash（没动过）"
else
  echo "  ✗ 红线　bridge.py 指纹变了！现在是 $hash"
  bad_files+=("红线破了")
fi

echo "═══════════════════════════════════════════"
echo "合计：${total_pass} 条过 / ${total_fail} 条失败"
if [ ${#bad_files[@]} -eq 0 ]; then
  echo "✔ 全套过关。"
  exit 0
fi
echo "✗ 有问题的："
for b in "${bad_files[@]}"; do echo "    · $b"; done
exit 1
