'use strict';
/**
 * Cyberdyne-Bridge · 身体插件（手 + 腿）
 *
 * ── 为什么单独一个插件 ──
 * 主链只干三件事：接 bot、接 socket、守安全护栏。
 * 所有「Minecraft 动作的细节」都往插件里堆，主链的动词表才不会越长越糊。
 *
 * 边界：
 *   M1–M3 的动词留在主链（它们被基准录像锁住了，动一下就得重录基准）；
 *   **M4 起的新动作一律进这个插件。**
 *
 * 规矩（和 pathfinder 插件一模一样）：
 *   · 自己一个目录、自己的 package.json
 *   · 主链 try 一下 require；不在 / 加载炸 → 当没装，命令回退「不认识」
 *   · 只被主链调用，不开 socket、不碰状态推送、不抢定时器
 *
 * ★ 全部本地确定性逻辑，**不经过任何大模型**。
 *
 * 能力清单：
 *   腿：sneak 潜行 / jump 跳跃 / jumpattack 跳劈（MC 暴击 ×1.5）/ swimdown 游泳下降
 *   手：dig 挖 / place 放 / craft 合成 / use 使用（箱子·按钮·门）
 */

let Vec3 = null;
try { Vec3 = require('vec3').Vec3; } catch (e) { Vec3 = null; }

const 能力表 = ['sneak', 'jump', 'jumpattack', 'swimdown',
                'dig', 'place', 'craft', 'use', 'furnace_put', 'furnace_take',
                'chest_take', 'chest_put'];

/* 绝对坐标 → Vec3。优先用 vec3，取不到就用一个相对偏移凑一个出来
 * （bot.entity.position 本身就是 Vec3，offset 出来的也是） */
function 取坐标(bot, p) {
  if (Vec3) return new Vec3(p[0], p[1], p[2]);
  const q = bot.entity.position;
  return q.offset(p[0] - q.x, p[1] - q.y, p[2] - q.z);
}

function 等(ms) { return new Promise((r) => setTimeout(r, ms)); }

function 钳(v, 小, 大, 缺省) {
  const n = Number(v);
  if (!Number.isFinite(n)) return 缺省;
  return Math.min(Math.max(n, 小), 大);
}

/* 这些挖了没意义或者会出乱子 —— 直接拒 */
const 不许挖 = new Set([
  'bedrock', 'barrier', 'light', 'moving_piston', 'structure_void',
  'command_block', 'chain_command_block', 'repeating_command_block',
  'structure_block', 'jigsaw', 'end_portal', 'end_portal_frame', 'nether_portal',
]);

/* ★ M4c 补丁①：方块 → 需要哪一类工具。只列"不给工具就挖不动"的 ——
 * 石头系（含矿、砖、混凝土…）必须有镐子，不然挖了也不掉东西；
 * 木头/泥土/沙子徒手能挖，所以不列（不拦）。 */
const 石头系 = /(_ore|stone|deepslate|cobblestone|bricks|concrete|obsidian|netherrack|furnace|anvil|terracotta|sandstone|prismarine|basalt|blackstone|tuff|calcite|dripstone|quartz|_block$)/;
function 该用什么工具(名) {
  if (石头系.test(名) && !/leaves|wool|_log|_wood/.test(名)) return 'pickaxe';
  return null;
}
function 是这类工具(名, 类) {
  return typeof 名 === 'string' && 名.endsWith('_' + 类);
}
const 工具名 = { pickaxe: '镐子', axe: '斧头', shovel: '铲子' };

/* 所有"自己动腿"的动作开始前，先把控制状态清干净 ——
 * M2.1 的教训：边跑边挥打不中，边跑边挖也挖不准。 */
function 清控制(bot) {
  for (const c of ['forward', 'back', 'left', 'right', 'jump', 'sprint', 'sneak']) {
    try { bot.setControlState(c, false); } catch (e) { /* 无所谓 */ }
  }
}

function 找最近(bot, 名, 上限) {
  let 目标 = null, 最近 = Infinity;
  const p = bot.entity.position;
  for (const id in bot.entities) {
    const e = bot.entities[id];
    if (!e || !e.position || e === bot.entity) continue;
    const 谁 = e.username || e.name || e.displayName || e.type;
    if (谁 !== 名) continue;
    const d = e.position.distanceTo(p);
    if (d < 最近) { 最近 = d; 目标 = e; }
  }
  if (!目标 || 最近 > 上限) return { 目标: null, 距离: 最近 };
  return { 目标, 距离: 最近 };
}

/* ══════════════════════════ 腿 ══════════════════════════ */

// 潜行。MC 机制：潜行时**不会从方块边缘掉下去** —— 所以这也是个安全动作。
async function 潜行(bot, a) {
  if (a.on === true) { bot.setControlState('sneak', true); return { ok: true, 潜行: '一直开着' }; }
  if (a.on === false) { bot.setControlState('sneak', false); return { ok: true, 潜行: '松开' }; }
  const ms = 钳(a.ms, 200, 8000, 1200);
  清控制(bot);
  bot.setControlState('sneak', true);
  await 等(ms);
  bot.setControlState('sneak', false);
  return { ok: true, 毫秒: ms };
}

// 跳跃。count 可以连跳。
async function 跳跃(bot, a) {
  const 次 = 钳(a.count, 1, 5, 1);
  for (let i = 0; i < 次; i++) {
    bot.setControlState('jump', true);
    await 等(100);
    bot.setControlState('jump', false);
    if (i < 次 - 1) await 等(260);
  }
  return { ok: true, 次数: 次 };
}

// 游泳下降。MC 里"水里按住潜行键"= 下沉，"按住跳跃键"= 上浮。
async function 下潜(bot, a) {
  const 在水里 = bot.entity.isInWater || bot.entity.isInLava;
  if (!在水里) return { ok: false, why: '我不在水里，按潜行键是没用的' };
  const ms = 钳(a.ms, 200, 8000, 1500);
  清控制(bot);
  const 起 = bot.entity.position.y;
  bot.setControlState('sneak', true);
  await 等(ms);
  bot.setControlState('sneak', false);
  // 「下沉了多少」要真的是差值 —— 之前直接返回了最终 y，那是在谎报
  return { ok: true, 毫秒: ms, 下沉了多少: Number((起 - bot.entity.position.y).toFixed(2)) };
}

/**
 * 跳劈 —— MC 的暴击。
 *
 * 暴击条件（服务端判）：**正在下坠的过程中命中**，伤害 ×1.5。
 * 所以顺序不能错：先跳 → 等它真的开始往下掉 → 这时候才挥。
 * 跳起来立刻挥是没用的，那还是普通伤害。
 *
 * 顺带一个 M2.1 的教训：**挥之前必须站住**，边跑边挥打不中。
 */
async function 跳劈(bot, a) {
  const 名 = a.target;
  if (!名) return { ok: false, why: '要告诉我打谁（target）' };

  const { 目标, 距离 } = 找最近(bot, 名, 3.2);
  if (!目标) {
    return { ok: false, why: Number.isFinite(距离)
      ? `目标在 ${距离.toFixed(1)} 格外，跳劈够不着（最多 3.2）`
      : '视野里没有这个目标' };
  }

  清控制(bot);
  await 等(60);

  bot.setControlState('jump', true);
  await 等(90);
  bot.setControlState('jump', false);

  // 等它真的在往下掉 —— 这一步是暴击的成败所在。
  // MC 的暴击条件里有一条是 **fallDistance > 0**（已经掉了多少格），
  // 刚过顶点 1 毫秒时那个数还是 0，加上网络延迟，服务端看到的是"还在上升"，
  // 于是这一下就被判成普通伤害（实测：5.9 而不是 9）── 所以要多等一会儿。
  let 下坠了 = false;
  for (let i = 0; i < 40; i++) {
    await 等(15);
    try {
      if (!bot.entity.onGround && bot.entity.velocity.y < -0.05) { 下坠了 = true; break; }
    } catch (e) { break; }
  }
  if (!下坠了) return { ok: false, why: '这一跳没等来下坠（可能被天花板挡住了）' };

  // 再给它 130ms 落一段：一是让 fallDistance 攒起来，
  // 二是给服务端追上客户端的时间 —— 两条都为了让它真的算暴击。
  await 等(130);
  try {
    if (bot.entity.onGround || bot.entity.velocity.y >= 0) {
      return { ok: false, why: '还没挥它就落地了（这地方太矮，跳不出暴击）' };
    }
  } catch (e) { /* 读不到速度就硬挥 */ }

  try {
    await bot.lookAt(目标.position.offset(0, (目标.height || 1.8) * 0.85, 0), true);
  } catch (e) { /* 转不过去也照样挥 */ }

  /* M4.1·出手前**再量一次**（2026-10-01 实测教训）：
   * 从"决定跳劈"到"真的挥下去"中间隔着转身、起跳、等它下坠 —— 三百多毫秒。
   * 会跑的目标早就跑出 3 格了，那一刀服务端判"够不着"，等于白挥。
   * 实测：97 次跳劈里有 23 次是这么白挥掉的。宁可少挥这一下，也别白费一个冷却。 */
  const 现在距 = (目标.position && bot.entity.position)
    ? 目标.position.distanceTo(bot.entity.position) : 距离;
  if (目标.isValid === false) {
    return { ok: false, why: '目标已经不在了（倒下了或者走了），不挥空拳',
             dist: Number(现在距.toFixed(2)), 取消: '目标没了' };
  }
  if (现在距 > 3.0) {
    return { ok: false, why: `这半秒里目标跑到 ${现在距.toFixed(1)} 格外了，这一下不挥`,
             dist: Number(现在距.toFixed(2)), 取消: '跑出范围' };
  }
  bot.attack(目标);
  return { ok: true, target: 名, dist: Number(现在距.toFixed(2)), 暴击: true };
}

/* ══════════════════════════ 手 ══════════════════════════ */

async function 挖(bot, a) {
  if (!Array.isArray(a.p) || a.p.length < 3) {
    return { ok: false, why: '要给我一个坐标 p:[x,y,z]' };
  }
  const 块 = bot.blockAt(取坐标(bot, a.p));
  if (!块) return { ok: false, why: '那个位置读不到方块（区块没加载？）' };
  if (块.name === 'air' || 块.name === 'cave_air' || 块.name === 'void_air') {
    return { ok: false, why: '那里是空气' };
  }
  if (不许挖.has(块.name)) return { ok: false, why: `「${块.name}」不能挖` };

  // ★ 安全护栏：不许挖自己正脚下那块 —— 挖完自己就掉下去了
  const 脚 = bot.blockAt(bot.entity.position.offset(0, -1, 0));
  if (脚 && 脚.position.equals(块.position) && !a.允许挖脚下) {
    return { ok: false, why: '那是我正脚下那块，挖了我自己就掉下去了' };
  }

  /* ★ M4c 补丁①：工具前置校验（Pre-flight Check，fail-closed）
   * 实测事故：它"手里攥着煤在挖石头" —— equipForBlock 静默失败，然后硬挖被服务端中止，
   * 表现是 `Digging aborted` 刷屏、任务永远超时。
   * 规矩：**挖之前先查有没有对应的工具；没有就直接拒，绝不硬上**。 */
  const 要 = 该用什么工具(块.name);
  if (要) {
    const 手 = bot.inventory.items().filter((i) => 是这类工具(i.name, 要));
    if (!手.length) {
      return { ok: false, why: `我手里没有${工具名[要]}，挖不了「${块.name}」`
               + `（手上是 ${bot.heldItem ? bot.heldItem.name : '空的'}）`,
               取消: '缺工具' };
    }
    // 挑一把最好的换上（按材质）
    const 排名 = (n) => ['wooden', 'stone', 'iron', 'golden', 'diamond', 'netherite']
      .findIndex((m) => n.startsWith(m));
    手.sort((a, b) => 排名(b.name) - 排名(a.name));
    try { await bot.equip(手[0], 'hand'); } catch (e) { /* 换不上下面会再验一次 */ }
    const 现在手 = bot.heldItem ? bot.heldItem.name : '';
    if (!是这类工具(现在手, 要)) {
      return { ok: false, why: `工具没换上（手上还是 ${现在手 || '空的'}），我不硬挖`,
               取消: '换不上工具' };
    }
  }

  清控制(bot);
  const t0 = Date.now();
  await bot.dig(块);
  return { ok: true, 挖掉: 块.name, 毫秒: Date.now() - t0, 位置: 块.position.toArray() };
}

async function 放(bot, a) {
  if (!Array.isArray(a.p) || a.p.length < 3) {
    return { ok: false, why: '要给我一个坐标 p:[x,y,z]' };
  }
  const 位 = bot.blockAt(取坐标(bot, a.p));
  if (!位) return { ok: false, why: '那个位置读不到方块' };
  if (位.name !== 'air' && 位.name !== 'cave_air') {
    return { ok: false, why: `那里不是空的（是 ${位.name}）` };
  }
  // ★ 「背包里有」≠「手上拿着」—— M2.1 攻击那次的同一个坑。
  //   /give 出来的东西多半落在主背包里，不换到手上，服务端会直接拒放。
  let 手上 = bot.heldItem;
  const 是方块 = (i) => { try { return bot.isBlock(i); } catch (e) { return true; } };
  if (a.item) {
    const 想放 = bot.inventory.items().find((i) => i.name === a.item);
    if (!想放) return { ok: false, why: `背包里没有「${a.item}」` };
    if (!手上 || 手上.name !== a.item) { await bot.equip(想放, 'hand'); 手上 = bot.heldItem; }
  } else if (!手上 || !是方块(手上)) {
    const 候选 = bot.inventory.items().filter(是方块);
    if (!候选.length) return { ok: false, why: '背包里一个方块都没有，没东西可放' };
    await bot.equip(候选[0], 'hand');
    手上 = bot.heldItem;
  }
  if (!手上) return { ok: false, why: '没能把方块拿到手上' };
  if (!是方块(手上)) return { ok: false, why: `手上拿的 ${手上.name} 不是方块` };

  // 找一个贴着目标位置的实心面当参考。
  // ★ 六个面挨个试：放不下去的原因很多（面朝向、能不能看见、服务端那一侧的判定），
  //   与其猜，不如都试一遍，并且把每一次的拒绝理由攒起来 —— 失败了要能看出为什么。
  const 六面 = [[0, -1, 0], [0, 1, 0], [1, 0, 0], [-1, 0, 0], [0, 0, 1], [0, 0, -1]];
  const 拒过 = [];
  for (const [dx, dy, dz] of 六面) {
    const 邻 = bot.blockAt(取坐标(bot, [a.p[0] + dx, a.p[1] + dy, a.p[2] + dz]));
    if (!邻) continue;
    if (邻.name === 'air' || 邻.name === 'cave_air' || 邻.name === 'water') continue;
    if (邻.boundingBox === 'empty') continue;
    try {
      清控制(bot);
      // 先看过去再放 —— 有些服务端会按视线方向判定
      try { await bot.lookAt(位.position.offset(0.5, 0.5, 0.5), true); } catch (e) {}
      await 等(90);
      // ⚠ 法向量是「从参考方块**指向**目标位置」，不是我算的那个「从目标指向参考」。
      //   传反了它会跑到对称的位置去放（实测日志里出现过 at (7,...) 这种鬼坐标）。
      await bot.placeBlock(邻, 取坐标(bot, [-dx, -dy, -dz]));
      return { ok: true, 放的是: 手上.name, 位置: a.p, 用的面: [dx, dy, dz] };
    } catch (e) {
      拒过.push(`面(${dx},${dy},${dz}) ${String(e.message).slice(0, 42)}`);
    }
  }
  if (!拒过.length) return { ok: false, why: '六面全是空的，没有可以靠着放的地方' };
  return { ok: false, why: `六个面都试过了，全被拒：${拒过.slice(0, 3).join(' ｜ ')}` };
}

async function 合成(bot, a) {
  const 名 = a.item;
  if (!名) return { ok: false, why: '要告诉我要合成什么（item）' };
  const 数 = 钳(a.count, 1, 64, 1);

  let 物品定义 = null, 数据 = null;
  try {
    数据 = require('minecraft-data')(bot.version);
    物品定义 = 数据.itemsByName[名];
  } catch (e) { /* 下面靠物品名兜底 */ }
  if (!物品定义) return { ok: false, why: `我不认识「${名}」这个东西` };

  // 先试手工合成（2×2），不行再找工作台
  let 配方表 = bot.recipesFor(物品定义.id, null, 1, null);
  let 工作台 = null;
  if (!配方表.length) {
    try {
      工作台 = bot.findBlock({ matching: 数据.blocksByName.crafting_table.id, maxDistance: 4 });
    } catch (e) { 工作台 = null; }
    if (!工作台) return { ok: false, why: `合成「${名}」要工作台，可我附近 4 格内没找到` };
    配方表 = bot.recipesFor(物品定义.id, null, 1, 工作台);
  }
  if (!配方表.length) return { ok: false, why: `材料不够，合不出「${名}」` };

  清控制(bot);
  await bot.craft(配方表[0], 数, 工作台);
  return { ok: true, 合成: 名, 数量: 数, 用了工作台: !!工作台 };
}

async function 使用(bot, a) {
  if (!Array.isArray(a.p) || a.p.length < 3) {
    return { ok: false, why: '要给我一个坐标 p:[x,y,z]' };
  }
  const 块 = bot.blockAt(取坐标(bot, a.p));
  if (!块) return { ok: false, why: '那个位置读不到方块' };
  if (块.name === 'air') return { ok: false, why: '那里是空气' };
  const 距离 = bot.entity.position.distanceTo(块.position);
  if (距离 > 4.5) return { ok: false, why: `方块在 ${距离.toFixed(1)} 格外，够不着（最多 4.5）` };
  清控制(bot);
  await bot.activateBlock(块);
  return { ok: true, 用了: 块.name, 距离: Number(距离.toFixed(2)) };
}

/* ══════════════════════════ 出口 ══════════════════════════ */

const 表 = {
  sneak: 潜行, jump: 跳跃, jumpattack: 跳劈, swimdown: 下潜,
  dig: 挖, place: 放, craft: 合成, use: 使用,
  furnace_put: 熔炉放料, furnace_take: 熔炉取成品,
  chest_take: 箱子里取, chest_put: 往箱子里放,
};

/* ══════════════════════════ 熔炉（M4c）══════════════════════════
 * 任务栈要"把矿石放进去、等它烧完、再把铁锭拿出来"，这三件事里
 * 前一件和最后一件得有个"手"来做 —— 就是这两个能力。
 * 零新依赖：mineflayer 自带 bot.openFurnace。
 * ⚠ 实测要点：putInput/putFuel 要的是**数字 type**（不是物品名）。
 */
function 近处炉子(bot, p) {
  try {
    const 块 = bot.blockAt(取坐标(bot, p));
    if (!块) return { 错: '那个坐标读不到方块（区块没加载？）' };
    if (!/furnace|smoker/.test(块.name)) return { 错: `那里是「${块.name}」，不是熔炉` };
    const 距 = bot.entity.position.distanceTo(块.position);
    if (距 > 4.5) return { 错: `离熔炉 ${距.toFixed(1)} 格，够不着（最多 4.5）` };
    return { 块 };
  } catch (e) { return { 错: e.message }; }
}

async function 熔炉放料(bot, a) {
  if (!Array.isArray(a.p) || a.p.length < 3) return { ok: false, why: '要给我熔炉坐标 p:[x,y,z]' };
  const 找 = 近处炉子(bot, a.p);
  if (找.错) return { ok: false, why: 找.错 };
  let 炉 = null;
  try {
    炉 = await bot.openFurnace(找.块);
    const 要放 = a.输入 || null, 要烧 = a.燃料 || null;
    const 拿 = (名) => bot.inventory.items().find((i) => i.name === 名);
    if (要放) {
      const 有 = 拿(要放.name);
      if (!有) return { ok: false, why: `背包里没有「${要放.name}」` };
      await 炉.putInput(有.type, null, Math.min(要放.count || 1, 有.count));
    }
    if (要烧) {
      const 有 = 拿(要烧.name);
      if (!有) return { ok: false, why: `背包里没有燃料「${要烧.name}」` };
      await 炉.putFuel(有.type, null, Math.min(要烧.count || 1, 有.count));
    }
    const 格 = (it) => (it ? { name: it.name, count: it.count } : null);
    return { ok: true, 输入: 格(炉.inputItem()), 燃料: 格(炉.fuelItem()) };
  } catch (e) {
    return { ok: false, why: e.message };
  } finally {
    try { if (炉 && typeof 炉.close === 'function') 炉.close(); } catch (e) {}
  }
}

async function 熔炉取成品(bot, a) {
  if (!Array.isArray(a.p) || a.p.length < 3) return { ok: false, why: '要给我熔炉坐标 p:[x,y,z]' };
  const 找 = 近处炉子(bot, a.p);
  if (找.错) return { ok: false, why: 找.错 };
  let 炉 = null;
  try {
    炉 = await bot.openFurnace(找.块);
    const 出 = 炉.outputItem();
    if (!出) return { ok: false, why: '输出槽是空的（还没烧完）', 取消: '输出槽空' };
    const 名 = 出.name, 数 = 出.count;
    await 炉.takeOutput();
    return { ok: true, 拿到: 名, 数量: 数 };
  } catch (e) {
    return { ok: false, why: e.message };
  } finally {
    try { if (炉 && typeof 炉.close === 'function') 炉.close(); } catch (e) {}
  }
}

/* ══════════════════════════ 箱子（M7b）══════════════════════════
 * 任务栈要"把东西存回去 / 从箱子里拿东西"，就得有这两个能力。
 * 零新依赖：mineflayer 自带 openBlock + window.withdraw/deposit。
 * ⚠ 实测要点：withdraw/deposit 要的是**数字 type**（不是物品名）。
 * ★ 安全：危险物品（TNT/打火石/岩浆桶…）一律不碰 —— fail-closed，说清原因。
 */
const 危险物品 = new Set(['tnt', 'flint_and_steel', 'lava_bucket', 'fire_charge',
  'end_crystal', 'respawn_anchor', 'command_block', 'chain_command_block',
  'repeating_command_block', 'barrier', 'structure_block', 'jigsaw', 'light',
  'bedrock', 'debug_stick']);

function 找箱子(bot, p) {
  try {
    const 块 = bot.blockAt(取坐标(bot, p));
    if (!块) return { 错: '那个坐标读不到方块（区块没加载？）' };
    if (!/(chest|barrel|shulker_box|ender_chest)/.test(块.name)) {
      return { 错: `那里是「${块.name}」，不是箱子` };
    }
    const 距 = bot.entity.position.distanceTo(块.position);
    if (距 > 4.5) return { 错: `离箱子 ${距.toFixed(1)} 格，够不着（最多 4.5）` };
    return { 块 };
  } catch (e) { return { 错: e.message }; }
}

async function 箱子里取(bot, a) {
  if (!Array.isArray(a.p) || a.p.length < 3) return { ok: false, why: '要给我箱子坐标 p:[x,y,z]' };
  const 名 = a.物品 || a.item;
  if (!名) return { ok: false, why: '要告诉我要拿什么（物品）' };
  if (危险物品.has(名)) return { ok: false, why: `「${名}」这种危险东西我不碰`, 取消: '危险物品' };
  const 找 = 找箱子(bot, a.p);
  if (找.错) return { ok: false, why: 找.错 };
  let 箱 = null;
  try {
    箱 = await bot.openBlock(找.块);
    const 有 = 箱.containerItems().filter((i) => i.name === 名);
    if (!有.length) return { ok: false, why: `箱子里没有「${名}」` };
    const 总数 = 有.reduce((s, i) => s + i.count, 0);
    const 要 = Math.min(Math.max(Number(a.数量) || 1, 1), 总数);
    await 箱.withdraw(有[0].type, null, 要);
    return { ok: true, 拿到: 名, 数量: 要 };
  } catch (e) {
    return { ok: false, why: e.message };
  } finally { try { if (箱 && typeof 箱.close === 'function') 箱.close(); } catch (e) {} }
}

async function 往箱子里放(bot, a) {
  if (!Array.isArray(a.p) || a.p.length < 3) return { ok: false, why: '要给我箱子坐标 p:[x,y,z]' };
  const 名 = a.物品 || a.item;
  if (!名) return { ok: false, why: '要告诉我要放什么（物品）' };
  if (危险物品.has(名)) return { ok: false, why: `「${名}」这种危险东西我不碰`, 取消: '危险物品' };
  const 找 = 找箱子(bot, a.p);
  if (找.错) return { ok: false, why: 找.错 };
  let 箱 = null;
  try {
    箱 = await bot.openBlock(找.块);
    const 有 = bot.inventory.items().filter((i) => i.name === 名);
    if (!有.length) return { ok: false, why: `背包里没有「${名}」` };
    const 总数 = 有.reduce((s, i) => s + i.count, 0);
    const 保留 = Math.max(0, Number(a.保留) || 0);
    const 该放 = Math.min(Math.max(Number(a.数量) || 总数, 1), Math.max(总数 - 保留, 0));
    if (该放 <= 0) return { ok: false, why: `要保留 ${保留} 个，那就不用放了` };
    await 箱.deposit(有[0].type, null, 该放);
    return { ok: true, 放了: 名, 数量: 该放, 背包还剩: 总数 - 该放 };
  } catch (e) {
    return { ok: false, why: e.message };
  } finally { try { if (箱 && typeof 箱.close === 'function') 箱.close(); } catch (e) {} }
}

module.exports = {
  名字: 'body',

  /** 主链靠它判断"这个插件到底能不能用" */
  可用() { return true; },

  /** 主链靠它知道有哪些动词该交给我 */
  能力() { return 能力表.slice(); },

  /**
   * 执行一个动词。
   * 返回 Promise<{ok, why?, ...}>。**永远不抛异常** —— 主链那边会当命令结果处理。
   */
  执行(bot, 动词, 参数) {
    const 做 = 表[动词];
    if (!做) return Promise.resolve({ ok: false, why: `身体插件不会「${动词}」` });
    if (!bot || !bot.entity) return Promise.resolve({ ok: false, why: '还没进世界' });
    return Promise.resolve()
      .then(() => 做(bot, 参数 || {}))
      .catch((e) => ({ ok: false, why: `${动词} 炸了：${e.message}` }));
  },

  /** 让路：主链要自己动腿时先把我的控制状态松开 */
  停(bot) {
    try { 清控制(bot); } catch (e) { /* 无所谓 */ }
  },
};
