/* 收东西 —— 引擎：mineflayer-collectblock（MIT ✓）
 *
 * ★ 主人 2026-10-09：「编译成我们现在这种架构，**可以多路也可以替换**
 *   （**开关其中一个就行**的那种）」✓
 *   所以这一节是「**能力** collect」✓ 它下面可以挂好几个**引擎** ✓
 *   用哪个写在 config 的 `引擎` 字段里 ✓ —— 换引擎、关掉，都不用改一行代码 ✓
 *
 * 它干的活：`{cmd:"collect", 物品:"oak_log", 数量:3}`
 *   自己找最近的 → 走过去 → 挖掉 → 把掉落物捡进包 → 直到够数或找不到了
 *   （不是"挖一步、拾一步、走一步"拼的 ✗ —— 那是我们今天反复坏掉的那条链 ✗）
 */
'use strict';

let 日志 = () => {};
const 名字 = 'collectblock';
let 可用 = false;
let 装的原因 = '还没试';

function 装(bot, log) {
  日志 = log || (() => {});
  try {
    const 包 = require('mineflayer-collectblock');
    bot.loadPlugin(包.plugin);
    可用 = true;
    装的原因 = '装上了 ✓';
    日志(`  [collect] 引擎 collectblock 挂上了 ✓（MIT ✓ 自己会走位+挖+捡 ✓）`);
    return true;
  } catch (e) {
    可用 = false;
    // ★ 开着的引擎装不上 → **必须出声** ✗（静默退化是头号敌人 ✗）
    装的原因 = `装不上：${e && (e.code || e.message)}`;
    日志(`  ★ [collect] 引擎 collectblock **装不上** ✗ —— ${装的原因}`);
    return false;
  }
}

function 能用() { return 可用; }

/* 找最近的同名方块（找不到就给个能看懂的理由 ✓ 不许"就是没找到"✗） */
function 找一块(bot, 物品) {
  let 数据 = null;
  try { 数据 = require('minecraft-data')(bot.version); } catch (e) { 数据 = null; }
  const 定 = 数据 && 数据.blocksByName && 数据.blocksByName[物品];
  if (!定) return { 块: null, 为什么: `我不认识「${物品}」这种东西` };
  let 块 = null;
  try { 块 = bot.findBlock({ matching: 定.id, maxDistance: 48 }); } catch (e) { 块 = null; }
  if (!块) return { 块: null, 为什么: `48 格内我没看到「${物品}」` };
  return { 块, 为什么: null };
}

async function 执行(bot, a) {
  const 物品 = String(a.物品 || a.item || '');
  const 要 = Math.max(1, parseInt(a.数量 || a.count || 1, 10) || 1);
  if (!物品) return { ok: false, why: '要给我一个物品名（物品:"oak_log"）' };
  if (!可用) return { ok: false, why: `collect 引擎没装上（${装的原因}）` };
  const 引擎 = bot.collectBlock;
  if (!引擎 || typeof 引擎.collect !== 'function') {
    return { ok: false, why: 'collectBlock 不在 bot 上（插件没挂成功 ✗）' };
  }

  let 收 = 0;
  const 上限 = Math.min(24, 要 * 4);          // 防死循环：找一块失败也算一次 ✓
  for (let i = 0; i < 上限 && 收 < 要; i++) {
    const { 块, 为什么 } = 找一块(bot, 物品);
    if (!块) return { ok: 收 > 0, 收, why: 为什么, 数量: 收 };
    try {
      await 引擎.collect(块, { ignoreNoPath: true });
      收 += 1;
    } catch (e) {
      // ★ 收不到就**如实报** ✗ —— 不许当成收够了 ✓
      return { ok: 收 > 0, 收, why: `收「${物品}」的时候断了：${e && e.message}`, 数量: 收 };
    }
  }
  if (收 < 要) return { ok: false, 收, why: `只收到 ${收} 个「${物品}」，要 ${要} 个（找不到了）`, 数量: 收 };
  return { ok: true, 收, 数量: 收, 物品 };
}

module.exports = { 名字, 装, 能用, 执行, 命令: ['collect'] };
