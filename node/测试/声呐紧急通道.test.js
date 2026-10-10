#!/usr/bin/env node
'use strict';
/*
 * 声呐「要立刻上路」的那条通道 —— 离线断言。
 *
 * 为什么要有它（2026-10-09 查出来的真缺口）
 * ======================================
 * 主人点名：「盲挖中听见『叮』→ 立刻插队去挖」✓
 * 可这条链**在手侧就断了** ✗：
 *   · `block.lava.pop`（冒泡那声「叮」）在速查表里是「警惕」档（危险轻重 ✓）
 *   · 而 `_推()` 原来**只推「反射」档**（三条：龙息爆炸 / TNT / 爆炸）✗
 *   · 于是「叮」只会攒进 `声呐窗`（随状态帧一起报）✓
 *   · 可**脑侧压根没人读 `scan.声呐`** ✗（搜过整个 bridge.py，一个字节都没有 ✓）
 *   → 实机上「叮」**根本到不了脑** ✗ 更别提"插队去挖" ✓
 *
 * 规矩：**要立刻办的声音，就走立刻的通道** ✓ 别指望"别人会去翻那个窗口" ✗
 * （速查表**不改** —— 档位是"危险轻重"，通道是"要不要马上办"，两件事 ✓）
 *
 * 跑法：node --test node/测试/声呐紧急通道.test.js
 */
const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');

const { SonarProbe } = require(path.join(__dirname, '..', 'plugins', 'sonar', 'proto_sonar.js'));

function 造探针() {
  const p = new SonarProbe({ 站位: [0, 64, 0], 朝向: 0 });
  const 收到 = [];
  p.on('urgent', (f) => 收到.push(f));
  return { p, 收到 };
}

/* ⚠ 这里要看清**两段**（我第一版用例就栽在这儿 ✗）：
 *   · `听()`      = **加工**（分级/去重/方位）—— 它**不自己推** ✗
 *   · `_推()`     = **上路**（按档位决定走哪条通道）—— 真机上由 `attach()` 调 ✓
 *   所以离线要"两段都走一遍"才等于实机 ✓（这也是它接得住 attach 的前提）
 */
function 听见(p, 名, 坐标, 音量 = 1.0) {
  const f = p.听(名, 坐标, 音量);
  if (f) p._推(f);
  return f;
}

test('S1 ★★★ 听见「叮」（block.lava.pop）→ **当场走紧急通道**（不等状态帧）', () => {
  const { p, 收到 } = 造探针();
  const f = 听见(p, 'block.lava.pop', [6, 64, -4]);
  assert.ok(f, '这声「叮」被整条丢掉了 ✗');
  assert.strictEqual(收到.length, 1, '「叮」没走紧急通道 ✗ 实机上它到不了脑 ✓');
  assert.strictEqual(收到[0].音名, 'block.lava.pop');
  assert.ok(Array.isArray(收到[0].坐标), '没带声源坐标 —— 脑那边没法"挖过去" ✗');
});

test('S2 ★★★ 岩浆另外两条（ambient / extinguish）也走紧急通道', () => {
  const { p, 收到 } = 造探针();
  听见(p, 'block.lava.ambient', [6, 64, -4]);
  听见(p, 'block.lava.extinguish', [7, 64, -4]);
  assert.strictEqual(收到.length, 2, `只到了 ${收到.length} 条 ✗`);
});

test('S3 ★★ 别的声音**不许**被顺手塞进紧急通道（否则就成刷屏了 ✗）', () => {
  const { p, 收到 } = 造探针();
  听见(p, 'entity.zombie.ambient', [-9, 64, 14]);
  听见(p, 'block.stone.break', [28, 64, -10]);
  听见(p, 'block.gravel.step', [30, 64, 12]);
  assert.strictEqual(收到.length, 0, `有 ${收到.length} 条别的动静混进来了 ✗`);
});

test('S4 ★★★ 原来那三条「反射」档照旧走紧急通道（不许被改坏）', () => {
  const { p, 收到 } = 造探针();
  听见(p, 'entity.tnt.primed', [4, 64, 0]);
  听见(p, 'entity.generic.explode', [6, 64, 4], 2.0);
  assert.strictEqual(收到.length, 2, '反射档那三条被改坏了 ✗');
});

test('S5 ★★ 紧急通道是**加**出去的：警戒态 / 事件表 / 指纹一个字没变', () => {
  // ⚠⚠ **`状态帧()` 自己就会把指纹 digest 掉**（`指纹.digest()` 是一次性的 ✗）
  //   → 同一个探针上「先读指纹、再读状态帧」**必然抛** "Digest already called" ✓
  //   我连试两版才看清：这不是我读错顺序，是**产品那条一次性约束** ✓
  //   规矩：**一个探针上，指纹和状态帧各读一次、但只有一次机会** ✓
  //   （两个探针各读各的，互不影响 ✓）
  const p1 = new SonarProbe({ 站位: [0, 64, 0], 朝向: 0 });
  听见(p1, 'block.lava.pop', [6, 64, -4]);
  const 帧1 = p1.状态帧();          // ← 指纹就在这一份里（读第二回必抛 ✗）

  const p2 = new SonarProbe({ 站位: [0, 64, 0], 朝向: 0 });
  听见(p2, 'block.lava.pop', [6, 64, -4]);
  const 帧2 = p2.状态帧();

  assert.deepStrictEqual(帧1.警惕, 帧2.警惕, '事件表被改坏了 ✗');
  assert.strictEqual(帧1.指纹, 帧2.指纹, '指纹不稳 ✗');
  // 「叮」在速查表里仍是「警惕」档（危险轻重那件事**没改** ✓）
  const 条 = 帧1.警惕.find((x) => x.音名 === 'block.lava.pop');
  assert.ok(条, '「叮」没进警戒态 ✗（警戒那一路是给"别靠近"用的，不该丢 ✓）');
  assert.strictEqual(条.档, '警惕');
});

test('S6 ★★★ 手侧基准指纹没变（与 Python 核心对答案的那把尺子）', () => {
  const p = new SonarProbe({ 站位: [0, 64, 0], 朝向: 0 });
  听见(p, 'entity.creeper.primed', [13, 64, -7]);
  听见(p, 'entity.generic.explode', [6, 64, 4], 2.0);
  听见(p, 'block.stone.break', [28, 64, -10]);
  听见(p, 'entity.player.attack.strong', [0, 64, 0]);
  听见(p, 'block.gravel.step', [30, 64, 12]);
  听见(p, 'entity.zombie.ambient', [-9, 64, 14]);
  assert.strictEqual(p.指纹值(), '9b665f3496c078c1', '基准指纹变了 ✗（Python 核心对不上答案了）');
});
