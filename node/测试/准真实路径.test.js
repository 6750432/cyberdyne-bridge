/* 準真實路徑測試（主人 2026-10-08 清单 P1-3「閘三」）
 *
 * 为什么要有这个
 * ==============
 * 主人的 T4：「**測試沒覆蓋真實路徑**」。
 *   当天的活例子：`Vec3` 那个 bug 只有拿**真的 Vec3** 跑才会炸，
 *   用普通的 `{x,y,z}` 假对象测，一路绿灯 ✗
 *   另一个：`Math.round` / `Math.floor` 差一格，假 bot 不 care，实机全歪 ✗
 *
 * 规矩（三条）
 *   ① 假 bot，**不连服务器**；
 *   ② 凡是"空间"的东西一律用**真 `vec3` 模块** —— 坐标运算、`offset()`、
 *      `.equals()`、`distanceTo()` 全走真的，**不许自己糊一个 {x,y,z}**；
 *   ③ 直接 `require` 真插件 `plugins/body/proto_body.js` 调它的 `执行()`，
 *      **不复制它的逻辑** —— 复制了测的就是复印件，不是真程序。
 *
 * 跑法： cd ~/cyberdyne-bridge && ~/.local/node/bin/node --test node/测试/准真实路径.test.js
 */

const test = require('node:test');
const assert = require('node:assert');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const Vec3 = require(path.join(ROOT, 'node', 'node_modules', 'vec3'));   // ★ 真 Vec3
/* 默认测**真插件**。只有"验牙"脚本（验闸三有牙.py）会用环境变量指过来，
 * 让测试去跑一份**被故意改坏**的副本 —— 用来证明这测试真的会叫。 */
const 插件路径 = process.env.PROTO_BODY_PATH
  || path.join(ROOT, 'node', 'plugins', 'body', 'proto_body.js');
const 身体 = require(插件路径);

/* ── 假 bot：够用就行，但"空间部分"全是真的 ──
 * 方块表用 "x,y,z" 当键；不给就是空气（读不到）。
 * 站位固定 (-168.5, 81, 148.5) —— 跟实机那次同一个位置，feet 在小数点 .5 上，
 * 正好能测出"floor 还是 round"的差别。 */
function 造假bot({ 站位 = [-168.5, 81, 148.5], 方块 = {}, 背包 = [] } = {}) {
  const 位置 = new Vec3(站位[0], 站位[1], 站位[2]);          // ★ 真 Vec3
  const bot = {
    entity: { position: 位置, isInWater: false, isInLava: false },
    blockAt(p) {
      const x = Math.floor(p.x), y = Math.floor(p.y), z = Math.floor(p.z);
      const 名 = 方块[[x, y, z].join(',')];
      if (!名) return null;
      return { name: 名, position: new Vec3(x, y, z), boundingBox: 'block' };
    },
    inventory: { items: () => 背包.slice() },
    heldItem: null,
    记录: { 按键: [], 挖了: [], 换手: [] },
    setControlState(键, 开) { bot.记录.按键.push([键, 开]); },
    equip(件) { bot.记录.换手.push(件.name); bot.heldItem = 件; return Promise.resolve(); },
    dig(块) { bot.记录.挖了.push(块.name); return Promise.resolve(true); },
    lookAt() { return Promise.resolve(); },
    placeBlock() { return Promise.resolve(); },
    isBlock() { return true; },
  };
  return bot;
}
const 背包里有 = (...名) => 名.map((n) => ({ name: n, count: 1, type: 1, metadata: null }));

/* ══════════ 场景 A：跳跃 ══════════ */

test('A 跳跃：头顶堵着 → 拒，并说清楚撞的是什么（T1 資訊有卻不用 ②）', async () => {
  const bot = 造假bot({
    方块: { '-169,83,148': 'stone' },   // ★ 身体占 脚/脚+1，跳起来顶到 脚+2
  });
  const r = await 身体.执行(bot, 'jump', { count: 1 });
  assert.strictEqual(r.ok, false, '头顶堵着还跳了 ✗ —— 实机就是"按了也白按，日志还报成功"');
  assert.match(String(r.why), /撞头/, '拒了但没说清楚会撞什么：' + r.why);
  assert.strictEqual(bot.记录.按键.length, 0, '拒了却还是按了 jump 键 ✗');
});

test('A2 跳跃：头顶是空气 → 正常跳（不许误伤）', async () => {
  const bot = 造假bot({});
  const r = await 身体.执行(bot, 'jump', { count: 1 });
  assert.notStrictEqual(r.ok, false, '头顶是空的却不让跳 ✗ 误伤了：' + (r && r.why));
  assert.ok(bot.记录.按键.some(([k, v]) => k === 'jump' && v === true), '居然没按 jump 键');
});

/* ══════════ 场景 B：放置 ══════════ */

test('B 放置：目标格被占 → 拒，绝不硬放（T1 資訊有卻不用 ③）', async () => {
  const bot = 造假bot({
    方块: { '-167,81,148': 'cobblestone' },
    背包: 背包里有('crafting_table'),
  });
  const r = await 身体.执行(bot, 'place', { p: [-167, 81, 148], item: 'crafting_table' });
  assert.strictEqual(r.ok, false, '目标格有东西还放了 ✗');
  assert.match(String(r.why), /不是空的/, '拒了但理由不对：' + r.why);
});

test('B2 放置：目标格是空气 + 旁边有实心面 → 真放下去（不许误伤）', async () => {
  const bot = 造假bot({
    方块: { '-167,81,148': 'air',               // ★ 目标格：得明确是空气，不能是"读不到"
            '-167,80,148': 'cobblestone' },    // ★ 正下方那块，当靠着放的参考面
    背包: 背包里有('crafting_table'),
  });
  const r = await 身体.执行(bot, 'place', { p: [-167, 81, 148], item: 'crafting_table' });
  assert.notStrictEqual(r.ok, false, '该放下的没放下 ✗ 误伤了：' + (r && r.why));
  assert.strictEqual(r.放的是, 'crafting_table', '放下去的不是我要的那件：' + r.放的是);
});

/* ══════════ 场景 C：挖掘（含拾取链的入口）══════════ */

test('C 挖掘：那一格明确是空气 → 拒，不能对着空气挥（实机挥了 60 秒）', async () => {
  const bot = 造假bot({ 方块: { '-168,81,151': 'air' } });
  const r = await 身体.执行(bot, 'dig', { p: [-168, 81, 151] });
  assert.strictEqual(r.ok, false, '对着空气挖了 ✗');
  assert.match(String(r.why), /空气/, '拒了但理由不对：' + r.why);
  assert.strictEqual(bot.记录.挖了.length, 0, '拒了却还是挥了 ✗');
});

test('C0 挖掘：那一格读不到（区块没加载）→ 拒，且理由跟"空气"分得清', async () => {
  const bot = 造假bot({});
  const r = await 身体.执行(bot, 'dig', { p: [900, 81, 900] });
  assert.strictEqual(r.ok, false, '读不到的格子也敢挖 ✗');
  assert.match(String(r.why), /读不到/, '拒了但理由不对：' + r.why);
});

test('C2 挖掘：真石头 + 背包含木镐 → 换上镐子放行（真工具路径）', async () => {
  const bot = 造假bot({
    方块: { '-169,81,150': 'stone' },
    背包: 背包里有('wooden_pickaxe'),
  });
  const r = await 身体.执行(bot, 'dig', { p: [-169, 81, 150] });
  assert.notStrictEqual(r.ok, false, '有镐子却不让挖石头 ✗ 误伤了：' + (r && r.why));
  assert.deepStrictEqual(bot.记录.换手, ['wooden_pickaxe'], '没换镐子就下手了 ✗');
  assert.deepStrictEqual(bot.记录.挖了, ['stone'], '挖的不是那块石头');
});

test('C3 挖掘：真石头 + 背包里没镐子 → 拒（fail-closed，10-08 实机那个）', async () => {
  const bot = 造假bot({
    方块: { '-169,81,150': 'stone' },
    背包: 背包里有('oak_log'),                 // 有木头、没镐子
  });
  const r = await 身体.执行(bot, 'dig', { p: [-169, 81, 150] });
  assert.strictEqual(r.ok, false, '没镐子还硬挖 ✗ —— 实机就是这么刷 Digging aborted 到超时的');
  assert.match(String(r.why), /镐子/, '拒了但没说缺什么：' + r.why);
  assert.strictEqual(bot.记录.挖了.length, 0, '拒了却还是挥了 ✗');
});

test('C4 挖掘：正脚下那块 → 拒（挖了自己掉下去）', async () => {
  const bot = 造假bot({ 方块: { '-169,80,148': 'stone' } });
  const r = await 身体.执行(bot, 'dig', { p: [-169, 80, 148] });
  assert.strictEqual(r.ok, false, '挖自己脚下了 ✗');
  assert.match(String(r.why), /脚/, '拒了但理由不对：' + r.why);
});

/* ══════════ 场景 D：接口本身 ══════════ */

test('D 插件自检：跳跃/放置/挖掘三个能力都报出来', () => {
  const 能力 = 身体.能力();
  for (const c of ['jump', 'place', 'dig']) {
    assert.ok(能力.indexOf(c) >= 0, `身体插件少了能力「${c}」`);
  }
});
