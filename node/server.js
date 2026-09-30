#!/usr/bin/env node
/**
 * Cyberdyne-Bridge · M0 · 手在里面（Hand Inside）
 *
 * 职责边界（M0 只做这三件事，越级的一律不写）：
 *   1. 用原生 net 模块起一个本地接线口（Unix socket / TCP）等大脑来接；
 *   2. 用 mineflayer 把一个假人送进 MC 服务器，让他在里面站着；
 *   3. 定时把结构化状态推给大脑，事件发生时立刻推。
 *
 * 明确不做：寻路、攻击、挖掘、决策、记忆、平滑层、任何重型 MC AI 框架。
 *
 * 用法：  node server.js            （读上一层的 config.json）
 *         node server.js --help
 */

'use strict';

const net = require('net');
const fs = require('fs');
const path = require('path');
const mineflayer = require('mineflayer');

/* ─────────────────────────── 配置 ─────────────────────────── */

const ROOT = path.resolve(__dirname, '..');
const CONFIG_PATH = path.join(ROOT, 'config.json');

if (process.argv.includes('--help')) {
  console.log(`Cyberdyne-Bridge M0 · 手在里面

  node server.js              启动接线口并送假人进 MC
  node server.js --help       显示本帮助

配置见 ${CONFIG_PATH}`);
  process.exit(0);
}

const cfg = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
const m1 = cfg.m1 || {};
const m2 = cfg.m2 || {};
const m3 = cfg.m3 || {};
const m4 = cfg.m4 || {};

/* ── M1·手要认识的名单 ──
 * 判断"是不是敌人"不能只信 mineflayer 给的 e.type（不同版本口径不一样），
 * 名字兜底更稳：type 说是 hostile，或者名字在下面这张表里，都算。 */
const HOSTILE = new Set([
  'zombie', 'husk', 'drowned', 'skeleton', 'stray', 'bogged', 'wither_skeleton',
  'creeper', 'spider', 'cave_spider', 'witch', 'slime', 'magma_cube',
  'enderman', 'endermite', 'silverfish', 'phantom', 'pillager', 'vindicator',
  'evoker', 'illusioner', 'ravager', 'vex', 'blaze', 'ghast',
  'guardian', 'elder_guardian', 'shulker', 'zoglin', 'hoglin', 'piglin',
  'piglin_brute', 'zombified_piglin', 'warden', 'breeze', 'wither',
  'ender_dragon', 'giant',
]);

/* 能吃的。顺序 = 偏好：越靠前越先吃（熟食、金胡萝卜优先，腐肉垫底）。 */
const FOODS = [
  'golden_carrot', 'golden_apple', 'enchanted_golden_apple',
  'cooked_beef', 'cooked_porkchop', 'cooked_mutton', 'cooked_chicken',
  'cooked_rabbit', 'cooked_cod', 'cooked_salmon', 'bread', 'baked_potato',
  'mushroom_stew', 'beetroot_soup', 'rabbit_stew', 'suspicious_stew',
  'apple', 'carrot', 'melon_slice', 'sweet_berries', 'glow_berries',
  'pumpkin_pie', 'cookie', 'dried_kelp', 'tropical_fish',
  'beef', 'porkchop', 'mutton', 'chicken', 'rabbit', 'cod', 'salmon',
  'potato', 'honey_bottle', 'chorus_fruit',
  'rotten_flesh', 'spider_eye', 'poisonous_potato', 'pufferfish',
];
const FOOD_RANK = new Map(FOODS.map((n, i) => [n, i]));
const 口粮偏好 = m2.food_priority || ['cooked_beef', 'bread'];

/* ── M2·手上得有家伙才敢还手 ──
 * 顺序 = 越好越靠前，挑武器时按这个排。斧头也能打，所以一起收。 */
const WEAPONS = [
  'netherite_sword', 'diamond_sword', 'iron_sword', 'golden_sword',
  'stone_sword', 'wooden_sword', 'trident', 'mace',
  'netherite_axe', 'diamond_axe', 'iron_axe', 'golden_axe',
  'stone_axe', 'wooden_axe',
];
const 武器排名 = new Map(WEAPONS.map((n, i) => [n, i]));

/* ─────────────────────── 接线口（原生 net）─────────────────────── */

const isWindows = process.platform === 'win32';
const transport = (() => {
  if (cfg.transport === 'unix' || cfg.transport === 'tcp') return cfg.transport;
  return isWindows ? 'tcp' : 'unix';
})();

const socketPath = path.resolve(ROOT, cfg.unix_socket || './cyberdyne.sock');
const tcpHost = cfg.tcp_host || '127.0.0.1';
const tcpPort = cfg.tcp_port || 8765;

const clients = new Set();

function listen() {
  if (transport === 'unix') {
    // 上次没退干净会留下一个死 socket 文件，先清掉
    try { fs.unlinkSync(socketPath); } catch (e) { /* 不存在是正常的 */ }
  }
  const server = net.createServer((sock) => {
    clients.add(sock);
    log(`大脑接上了：${sock.remoteAddress || 'unix'}（当前 ${clients.size} 个连接）`);
    // ── M1·命令通道（脑 → 手）──
    // 大脑只往这条线里丢动作，手负责把动作翻成 mineflayer 的操控状态。
    // 手不做任何决策：这里看不到"该不该跑"，只看到"往哪跑、跑多久"。
    sock._buf = '';
    sock.on('data', (chunk) => {
      sock._buf += chunk.toString('utf8');
      // 行太长说明对面在灌垃圾，直接砍掉缓冲区，别让内存被喂爆
      if (sock._buf.length > 64 * 1024) {
        丢包(sock, '单行超过 64KB，疑似异常数据');
        sock._buf = '';
        return;
      }
      const 行们 = sock._buf.split('\n');
      sock._buf = 行们.pop();      // 最后一段可能是半行，留到下次
      for (const 行 of 行们) 收命令(sock, 行);
    });
    sock.on('error', () => clients.delete(sock));
    sock.on('close', () => {
      clients.delete(sock);
      log(`大脑断开了（剩 ${clients.size} 个连接）`);
      // 大脑全掉线了就停下所有动作 —— 没人看着的时候乱跑最危险
      if (clients.size === 0) { 大脑全走了(); log('大脑不在，先把动作全停了，原地待命。'); }
    });
    // 一接上就先送一份当前状态，避免大脑空等
    if (lastState) send(sock, lastState);
  });
  server.on('error', (err) => {
    log(`接线口起不来：${err.message}`);
    process.exit(1);
  });
  const target = transport === 'unix' ? socketPath : `${tcpHost}:${tcpPort}`;
  server.listen(transport === 'unix' ? socketPath : tcpPort,
                transport === 'unix' ? undefined : tcpHost,
                () => log(`接线口已就绪：${classify()} ${target}`));
  return server;
}

function classify() {
  return transport === 'unix' ? '[unix]' : '[tcp]';
}

function send(sock, obj) {
  try { sock.write(JSON.stringify(obj) + '\n'); } catch (e) { clients.delete(sock); }
}

function broadcast(obj) {
  if (clients.size === 0) return;
  const line = JSON.stringify(obj) + '\n';
  for (const sock of clients) {
    try { sock.write(line); } catch (e) { clients.delete(sock); }
  }
}

function log(msg) {
  // 手这边的日志只给人看，不混进协议流
  const t = new Date().toTimeString().slice(0, 8);
  console.log(`[${t}] [手] ${msg}`);
}

/* ─────────────────────────── 假人 ─────────────────────────── */

let bot = null;
let lastState = null;
let lastChat = null;
let seq = 0;

function startBot() {
  log(`把「${cfg.bot_name}」送进 ${cfg.mc_host}:${cfg.mc_port}（${cfg.mc_version}，离线模式）…`);

  bot = mineflayer.createBot({
    host: cfg.mc_host,
    port: cfg.mc_port,
    username: cfg.bot_name,
    version: cfg.mc_version,
    auth: 'offline',
    hideErrors: false,
  });

  bot.once('spawn', () => {
    log('他已经站在世界里了。');
    重连次数 = 0;
    if (重连定时器) { clearTimeout(重连定时器); 重连定时器 = null; }
    emit('event', { kind: 'spawn' });
  });

  bot.on('kicked', (reason) => {
    log(`被踢出来了：${typeof reason === 'string' ? reason : JSON.stringify(reason)}`);
    emit('event', { kind: 'kicked', detail: String(reason).slice(0, 300) });
  });

  bot.on('end', (reason) => {
    log(`连接结束：${reason}`);
    emit('event', { kind: 'end', detail: String(reason) });
    计划重连();
  });

  bot.on('error', (err) => {
    log(`出错：${err.message}`);
    emit('event', { kind: 'error', detail: err.message });
  });

  bot.on('death', () => {
    log('他倒下了。');
    死过 = true;
    死亡次数 += 1;                 // M4：脑靠这个数判断"这次追击该收手了"
    记一笔({ 事件: '我死了', 第几次: 死亡次数, 对方血: (() => {
      for (const 名 in 探针表) return 探针表[名];
      return null;
    })() });
    emit('event', { kind: 'death' });
    // 倒下了也得自己爬起来 —— 主人回来要看到的是一个活着的小家伙
    setTimeout(() => {
      try {
        if (bot && typeof bot.respawn === 'function') bot.respawn();
        else if (bot && bot._client) bot._client.write('client_command', { actionId: 0 });
        log('已经申请重生。');
      } catch (e) { log(`重生申请失败：${e.message}`); }
    }, 1500);
  });

  /* M4·「谁在打我」—— 协议里**不带**攻击者，只能靠两条事实拼出来：
   * ① 有人在我 4.5 格内挥了胳膊（animation 包，玩家挥手会广播给周围的人）；
   * ② 我掉血了，而附近正好有敌对玩家（兜底：万一挥手包丢了/被合批了）。
   * 两条都只记"这件事确实发生了"，至于要不要还手是大脑的事。 */
  bot.on('entitySwingArm', (e) => {
    if (!e || !e.position || !bot || !bot.entity) return;
    const 名 = e.username || e.name;
    if (!名 || 名 === cfg.bot_name) return;              // 我自己挥胳膊不算
    if (!算不算敌人(名, e)) return;                       // 朋友挥胳膊更不算
    if (e.position.distanceTo(bot.entity.position) > 4.5) return;
    被打记录 = { by: 名, t: Date.now() };
  });

  bot.on('health', () => {
    if (!bot || bot.health === undefined || !bot.entity) return;
    const 现在血 = bot.health;
    if (上次血量 !== null && 现在血 < 上次血量 - 0.4) {
      let 嫌疑 = null, 最近 = 5.0;
      for (const 名 in bot.players) {
        const pl = bot.players[名];
        if (!pl || !pl.entity || !pl.entity.position) continue;
        if (!算不算敌人(名, pl.entity)) continue;
        const d = pl.entity.position.distanceTo(bot.entity.position);
        if (d < 最近) { 最近 = d; 嫌疑 = 名; }
      }
      if (嫌疑) 被打记录 = { by: 嫌疑, t: Date.now() };
      // 账本：我自己掉血也算一条 —— 分析的时候要能算"换血"划不划算
      记一笔({ 事件: '我掉血', 从: Number(上次血量.toFixed(2)), 到: Number(现在血.toFixed(2)),
               掉: Number((上次血量 - 现在血).toFixed(2)), 打我: 嫌疑,
               对方血: (嫌疑 && typeof 探针表[嫌疑] === 'number') ? 探针表[嫌疑] : null });
    }
    上次血量 = 现在血;
  });

  // M2：重生了 = 家当全掉在死亡点。先报一声，再给应急包一次机会。
  bot.on('spawn', () => {
    if (死过) {
      重生时刻 = Date.now();
      应急失败次数 = 0;
      log('他重生了，看看背包里还剩什么。');
      emit('event', { kind: 'respawned' });
    }
    setTimeout(应急包维护, 1500);      // 等背包同步好再整理
  });

  bot.on('chat', (username, message) => {
    if (username === bot.username) return;
    log(`听见 ${username} 说：${message}`);
    lastChat = { from: username, text: message, t: Date.now() };
    emit('event', { kind: 'chat', from: username, text: message });
  });

  // M2：谁挨揍了。这条是"挥击到底打中没有"的证据。
  // ⚠ 但 entityHurt 本身**不能直接当命中用**：挨打动画的元数据会被重复推送，
  //   实测 7 次挥击能刷出 28 条事件。所以只有"我们刚挥完 400ms 内"的才算我们的命中。
  bot.on('entityHurt', (e) => {
    if (!e) return;
    const 我们的 = (Date.now() - 上次挥击) < 400 && e !== bot.entity;
    const 名 = e.username || e.name || e.displayName || e.type || '?';
    emit('event', {
      kind: 'hit',
      who: 名,
      self: e === bot.entity,
      ours: 我们的,
      hp: (typeof e.health === 'number' ? Number(e.health.toFixed(1)) : null),
    });
  });

  // 注：这里故意不报 entitySpawn / entityGone。
  // 状态里的 near 已经按距离列了身边的实体，Bridge 靠比对相邻两帧就能看出
  // 谁来了、谁走了、离多远。再单发一份事件只会让叙事重复两遍
  // （「有人进来了：FangKe」紧接着「视野里出现了 FangKe」），
  // 而且蝙蝠飞走、鱿鱼刷没会一路刷屏。少一条通道，少一处打架。
}

/* ─────────────────────── 状态采集与推送 ─────────────────────── */

/* ── M4.1·证据链（2026-10-01 的教训）──
 * 第一轮实测，重启脚本 `>` 把叙事日志截断吃掉了，跳劈 vs 平A 的对比做不出来。
 * 教训一句话：**别把证据寄托在叙事文字上。** 所以现在落两份机器可读的账本：
 *   ① logs/全程-YYYYMMDD.jsonl —— 每一帧状态快照（跟推给大脑的是同一份）
 *   ② logs/账本-YYYYMMDD.jsonl —— 挥击 / 掉血 / 死亡 三种结构化事件
 * 两份都是 **追加**（flags:'a'），重启不丢；文件名带日期，跨天不串。
 * 开关：config.json 的 m2.record_all（默认 true）。 */
const 记录开关 = (m2.record_all !== false);
let 全程流 = null, 账本流 = null;

/** 本地日期 YYYYMMDD。**别用 toISOString** —— 那是 UTC，本地是 10-01 的时候
 *  它会给出 09-30，跨天的时候两份账本会串到同一个文件里去。 */
function 今天() {
  const d = new Date();
  const 补 = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${补(d.getMonth() + 1)}${补(d.getDate())}`;
}

function 开流(前缀) {
  if (!记录开关) return null;
  try {
    const 日 = 今天();
    const 路 = path.join(ROOT, 'logs', `${前缀}-${日}.jsonl`);
    const 流 = fs.createWriteStream(路, { flags: 'a' });
    流.on('error', (e) => log(`账本 ${前缀} 写不了：${e.message}`));
    log(`证据链开写：${路}（追加）`);
    return 流;
  } catch (e) { log(`证据链开不了：${e.message}`); return null; }
}

/** 记一笔结构化事件。带 t（毫秒）—— 事后靠它把"挥击"和"掉血"对上。 */
function 记一笔(条目) {
  if (!账本流) return;
  try { 账本流.write(JSON.stringify(Object.assign({ t: Date.now() }, 条目)) + '\n'); }
  catch (e) { /* 写不进去也不能把主链带走 */ }
}

/** 记一次挥击，并在 600ms 后**单独**问一次对方血量，落一条「结算」。
 *
 * 为什么不让分析脚本自己按时间窗配对：连击节奏是 650ms 一下，而探针是
 * 500ms 一轮 —— 光靠时间戳根本分不清这一下掉的血是这一刀砍的还是上一刀。
 * （这件事是 tools/分析打击.py --自检 当场抓出来的。）
 * 所以伤害归属这件事**在手这边一次性做掉**：出手记账 → 600ms 后单问一次
 * → 差值就是这一刀的净伤害。一条 RCON 查询而已，便宜且不含糊。 */
/** 当场问一次某个实体的血量（服务端真话）。出手前后各问一次，差值就是这一刀
 *  的净伤害 —— **不依赖探针名单**，所以打僵尸打假人都能记账。 */
async function 问血量(名) {
  // 玩家名本身就是合法的实体选择器；僵尸那类**类型名不是** —— 得用 @e[type=...]。
  // （2026-10-01 验证据链时踩到：打僵尸那条账一直少"对方血"，就是这儿的原因。）
  const 候选 = [名, `@e[type=${名},limit=1]`];
  for (const 选择器 of 候选) {
    try {
      const 出 = await 探针问一次(`data get entity ${选择器} Health`);
      if (!出) continue;
      const 配 = 出.match(/(-?\d+(?:\.\d+)?)f?\s*$/);
      if (配) return parseFloat(配[1]);
    } catch (e) { /* 换下一个选择器再试 */ }
  }
  return null;
}

function 记挥击(动词, 目标名, 距离, 出手时) {
  记一笔({ 事件: '挥击', 动词, 目标: 目标名, 距离,
           对方血: 出手时, 我血: bot ? bot.health : null,
           我手: (bot && bot.heldItem) ? bot.heldItem.name : null });
  if (出手时 === null) return;
  setTimeout(async () => {
    try {
      const 之后 = await 问血量(目标名);
      if (之后 === null) return;
      记一笔({ 事件: '结算', 动词, 目标: 目标名, 距离,
               出手时: 出手时, 之后, 掉: Number((出手时 - 之后).toFixed(2)), 我血: bot ? bot.health : null });
    } catch (e) { /* 结算问不到就算了，别影响主链 */ }
  }, 600);
}

function 开证据链() {
  全程流 = 开流('全程');
  账本流 = 开流('账本');
}

/* ── M4c·三条事实通道 ──
 * 任务栈的"完成判据"必须看事实，不能认"命令发出去了"（这个项目反复吃过的亏）。
 * 三条都是**纯本地读取**（客户端世界 / 背包），不花服务器、不加依赖、不认识任务栈。 */
let 看的方块 = [];        // [[x,y,z], ...]
let 看的物品 = [];        // ['cobblestone', ...]
let 看熔炉 = null;        // {p:[x,y,z], 每_ms, 上次}
let 熔炉读数 = null;      // {输入, 燃料, 输出, 进度, 取不到?}

/** 绝对坐标 → Vec3（不 require vec3，用手里现成的实体位置偏出来） */
function 取坐标(p) {
  const q = bot.entity.position;
  return q.offset(p[0] - q.x, p[1] - q.y, p[2] - q.z);
}

function 方块快照() {
  if (!bot || !bot.entity || !看的方块.length) return null;
  const 出 = [];
  for (const p of 看的方块) {
    let 名 = null;
    try { const 块 = bot.blockAt(取坐标(p)); 名 = 块 ? 块.name : null; } catch (e) { 名 = null; }
    出.push({ p, name: 名 });
  }
  return 出;
}

function 物品快照() {
  if (!bot || !bot.inventory || !看的物品.length) return null;
  const 出 = {};
  try {
    // 特殊条目 "*" = 把背包里**所有**物品都报上来。
    // 用途：任务里"挖了才知道要拾什么"这类步骤 —— 先把全量给脑，它自己去对照。
    const 要全部 = 看的物品.indexOf('*') >= 0;
    for (const it of bot.inventory.items()) {
      if (要全部 || 看的物品.indexOf(it.name) >= 0) 出[it.name] = (出[it.name] || 0) + it.count;
    }
    for (const 名 of 看的物品) if (名 !== '*' && !(名 in 出)) 出[名] = 0;   // 没有的也报 0，别让脑去猜
  } catch (e) { return null; }
  return 出;
}

/** 熔炉探针：按需把炉子打开读一眼、读完立刻关。
 *  ⚠ 只在手**闲着**的时候读 —— 不能跟挥拳/吃东西抢窗口。
 *  人走远了就如实报"取不到"（那是事实不是错误），等待步骤会继续保持"未满足"。 */
async function 读熔炉() {
  if (!bot || !bot.entity || !看熔炉) return;
  const 坐标 = 看熔炉.p;
  let 距 = null;
  try { 距 = bot.entity.position.distanceTo(取坐标(坐标)); } catch (e) {}
  if (距 !== null && 距 > 4.5) { 熔炉读数 = { p: 坐标, 取不到: '太远了' }; return; }
  if (当前动作 !== 'idle') return;
  let 炉 = null;
  try {
    const 块 = bot.blockAt(取坐标(坐标));
    if (!块 || !/furnace|smoker/.test(块.name)) {
      熔炉读数 = { p: 坐标, 取不到: `那里是 ${块 ? 块.name : '空的'}` };
      return;
    }
    炉 = await bot.openFurnace(块);
    const 格 = (it) => (it ? { name: it.name, count: it.count } : null);
    熔炉读数 = {
      p: 坐标, 输入: 格(炉.inputItem()), 燃料: 格(炉.fuelItem()), 输出: 格(炉.outputItem()),
      进度: (typeof 炉.progress === 'number' ? Number(炉.progress.toFixed(3)) : null),
      燃料进度: (typeof 炉.fuel === 'number' ? Number(炉.fuel.toFixed(3)) : null),
      t: Date.now(),
    };
  } catch (e) {
    熔炉读数 = { p: 坐标, 取不到: e.message };
  } finally {
    try { if (炉 && typeof 炉.close === 'function') 炉.close(); } catch (e) {}
  }
}

/* ── M5.1·视觉：扫一眼周围，打包成**事实**（怎么说话是脑的事）──
 * 界限照旧：手只报事实、不写人话、不做判断。
 * 预算硬约束：半径默认 12、步长 2（≈700 次方块查询，客户端本地读，几毫秒），
 * 结果限量（方块类别最多 8 类、可交互方块最多 6 条、实体最多 10 条）。 */
let 扫描 = null;                    // 最近一次扫描结果（脑那边用完为止）
let 上次扫描 = 0;

const 兴趣方块 = new Set(['crafting_table', 'furnace', 'blast_furnace', 'smoker', 'chest',
  'barrel', 'bed', 'white_bed', 'torch', 'lantern', 'water', 'lava', 'farmland', 'wheat',
  'carrots', 'potatoes', 'oak_log', 'birch_log', 'spruce_log', 'iron_ore', 'coal_ore',
  'copper_ore', 'glass', 'oak_door', 'ladder', 'anvil', 'enchanting_table', 'crafting_table',
  'sugar_cane', 'pumpkin', 'melon', 'gravel', 'clay', 'snow', 'ice']);
const 危险方块 = new Set(['lava', 'fire', 'magma_block', 'sweet_berry_bush', 'cactus', 'powder_snow']);

function 扫环境(半径, 步长) {
  const 出 = { t: Date.now() };
  try {
    const p = bot.entity.position;
    半径 = Math.min(Math.max(Number(半径) || 12, 4), 24);
    步长 = Math.min(Math.max(Number(步长) || 2, 1), 4);
    出.半径 = 半径; 出.步长 = 步长;

    // 时间 / 天气（API 已核实：bot.time.timeOfDay、bot.isRaining、bot.thunderState）
    const 刻 = (bot.time && typeof bot.time.timeOfDay === 'number') ? bot.time.timeOfDay : null;
    出.刻 = 刻;
    // ⚠ 别写 `x || null` —— 第 0 天是 0，会被当成"没有"（实测踩过：日志里出现"第 ? 天"）
    出.白天 = (bot.time && typeof bot.time.isDay === 'boolean') ? bot.time.isDay
              : ((刻 === null) ? null : (刻 < 12300 || 刻 > 23850));
    出.第几天 = (bot.time && typeof bot.time.day === 'number') ? bot.time.day : null;
    出.天气 = (bot.thunderState > 0) ? '雷雨' : (bot.isRaining ? '下雨' : '晴');

    // 群系（API 已核实：block.biome.name）
    const 脚下 = bot.blockAt(p.offset(0, -1, 0));
    出.群系 = (脚下 && 脚下.biome && 脚下.biome.name) || null;
    出.脚下 = 脚下 ? 脚下.name : null;

    // 方块统计（抽样）
    const 计 = {}, 有意思 = [], 险 = [];
    const 地面计 = {};
    for (let dx = -半径; dx <= 半径; dx += 步长) {
      // ⚠ 只看"脚上下这几格"：原来 dy 从 -3 到 5 一路抽，结果整屏都是地下石头，
      // 摘要里除了 stone 什么都看不见（实测）。地面那层（dy=-1）**单独统计**，
      // 免得它把"周围有什么"的名单占满。
      for (let dy = 0; dy <= 2; dy += 1) {
        for (let dz = -半径; dz <= 半径; dz += 步长) {
          let b = null;
          try { b = bot.blockAt(p.offset(dx, dy, dz)); } catch (e) { continue; }
          if (!b || b.name === 'air' || b.name === 'cave_air' || b.name === 'void_air') continue;
          计[b.name] = (计[b.name] || 0) + 1;
          if (危险方块.has(b.name) && 险.length < 4) {
            险.push({ name: b.name, p: [Math.round(p.x + dx), Math.round(p.y + dy), Math.round(p.z + dz)] });
          }
          if (兴趣方块.has(b.name) && 有意思.length < 6) {
            有意思.push({ name: b.name, p: [Math.round(p.x + dx), Math.round(p.y + dy), Math.round(p.z + dz)] });
          }
        }
      }
    }
    出.方块 = Object.entries(计).sort((a, b) => b[1] - a[1]).slice(0, 8)
      .map(([name, count]) => ({ name, count }));
    // 地面：脚下那一层最多的是什么（"我站在什么上"）
    try {
      const 地 = {};
      for (let dx = -半径; dx <= 半径; dx += 步长) {
        for (let dz = -半径; dz <= 半径; dz += 步长) {
          const b = bot.blockAt(p.offset(dx, -1, dz));
          if (b && b.name !== 'air') 地[b.name] = (地[b.name] || 0) + 1;
        }
      }
      const 排行 = Object.entries(地).sort((a, b) => b[1] - a[1]);
      出.地面 = 排行.length ? 排行[0][0] : null;
    } catch (e) { 出.地面 = null; }
    出.可交互 = 有意思;
    出.危险 = 险;

    // 实体（复用同一份 entities，限量）
    const 实体 = [];
    for (const id in bot.entities) {
      const e = bot.entities[id];
      if (!e || !e.position || e === bot.entity) continue;
      const d = e.position.distanceTo(p);
      if (d > 半径) continue;
      const 名 = e.username || e.name || e.displayName || e.type;
      实体.push({ name: 名, kind: e.type, dist: Number(d.toFixed(1)),
                  pos: [Math.round(e.position.x), Math.round(e.position.y), Math.round(e.position.z)] });
    }
    实体.sort((a, b) => a.dist - b.dist);
    出.实体 = 实体.slice(0, 10);
    出.实体总数 = 实体.length;
    出.我 = [Math.round(p.x), Math.round(p.y), Math.round(p.z)];
  } catch (e) {
    出.出错 = e.message;
  }
  扫描 = 出;
  上次扫描 = Date.now();
  return 出;
}

/** 装备耐久（API 已核实：item.durabilityUsed / item.maxDurability 来自 prismarine-item） */
function 耐久快照() {
  const 出 = { held: null, armor: {} };
  const 看 = (it) => {
    if (!it) return null;
    const 用 = (typeof it.durabilityUsed === 'number') ? it.durabilityUsed : null;
    const 总 = it.maxDurability || null;
    return { name: it.name, 用, 总, 比例: (用 !== null && 总) ? Number((用 / 总).toFixed(3)) : null };
  };
  try {
    出.held = 看(bot.heldItem);
    // 护甲槽：头/胸/腿/脚（5~8 是标准的护甲槽位）
    const 槽 = { head: 5, torso: 6, legs: 7, feet: 8 };
    for (const k in 槽) {
      try { 出.armor[k] = 看(bot.inventory && bot.inventory.slots ? bot.inventory.slots[槽[k]] : null); }
      catch (e) { 出.armor[k] = null; }
    }
  } catch (e) { /* 读不到就空着 */ }
  return 出;
}

function snapshot() {
  const now = Date.now();
  const base = { type: 'state', t: now, seq: seq++, bot: cfg.bot_name };

  if (!bot || !bot.entity) {
    return Object.assign(base, { connected: false, pos: null, hp: null,
                                 near: [], look: null, msg: null });
  }

  const p = bot.entity.position;
  const radius = cfg.near_radius || 16;
  const 威胁半径 = m1.threat_radius || 8;
  const 掉落半径 = m2.drop_radius || 14;
  const 最远 = Math.max(radius, 威胁半径, 掉落半径);
  const near = [];
  const threats = [];
  const drops = [];
  for (const id in bot.entities) {
    const e = bot.entities[id];
    if (!e || !e.position || e === bot.entity) continue;
    const d = e.position.distanceTo(p);
    if (d > 最远) continue;
    const 名 = e.username || e.name || e.displayName || e.type;
    const 条目 = {
      name: 名,
      kind: e.type,
      dist: Number(d.toFixed(2)),
      pos: [Number(e.position.x.toFixed(1)),
            Number(e.position.y.toFixed(1)),
            Number(e.position.z.toFixed(1))],
    };
    if (d <= radius) near.push(条目);
    // M1：是不是敌人。type 说是 hostile，或者名字在名单里，都算。
    // M2：假想敌名单里的玩家也算 —— 只在测试时非空。
    // M3：朋友名单优先级最高，直接跳过，连算都不算。
    if (d <= 威胁半径 && (e.type === 'hostile' || 算不算敌人(名, e))) {
      threats.push(条目);
    }
    // M2：地上的掉落物（死过一次之后，家当全在这儿躺着）
    // 注：mineflayer 说 entity.objectType 已弃用，改用 displayName
    if (d <= 掉落半径 && (名 === 'item' || e.displayName === 'Item')) {
      let 是什么 = 'item';
      try {
        const 堆 = e.getDroppedItem && e.getDroppedItem();
        if (堆 && 堆.name) 是什么 = 堆.name;
      } catch (err) { /* 读不出来就当未知物品，位置照样有用 */ }
      drops.push({ name: 是什么, dist: 条目.dist, pos: 条目.pos });
    }
  }
  near.sort((a, b) => a.dist - b.dist);
  threats.sort((a, b) => a.dist - b.dist);
  drops.sort((a, b) => a.dist - b.dist);

  // M2：背包里有什么家伙
  const weapons = [];
  try {
    const 计 = new Map();
    for (const it of bot.inventory.items()) {
      if (武器排名.has(it.name)) 计.set(it.name, (计.get(it.name) || 0) + it.count);
    }
    for (const [名字, 数量] of 计) weapons.push({ name: 名字, count: 数量 });
    weapons.sort((a, b) => 武器排名.get(a.name) - 武器排名.get(b.name));
  } catch (e) { /* 背包没同步好，这帧就当没武器 */ }

  // M1：背包里有什么能吃的（脑要靠这个决定"吃了没得吃"）
  const foods = [];
  try {
    const 计数 = new Map();
    for (const it of bot.inventory.items()) {
      if (FOOD_RANK.has(it.name)) 计数.set(it.name, (计数.get(it.name) || 0) + it.count);
    }
    for (const [名字, 数量] of 计数) foods.push({ name: 名字, count: 数量 });
    foods.sort((a, b) => FOOD_RANK.get(a.name) - FOOD_RANK.get(b.name));
  } catch (e) { /* 背包还没同步好，这帧就当没有食物 */ }

  return Object.assign(base, {
    connected: true,
    pos: [Number(p.x.toFixed(2)), Number(p.y.toFixed(2)), Number(p.z.toFixed(2))],
    hp: bot.health,
    food: bot.food,
    onGround: bot.entity.onGround,
    look: { yaw: Number(bot.entity.yaw.toFixed(3)),
            pitch: Number(bot.entity.pitch.toFixed(3)) },
    near: near.slice(0, 8),
    threats: threats.slice(0, 4),
    foods,
    // ── M2 新增 ──
    players: 玩家们(),
    friends: Array.from(朋友),
    weapons: weapons.slice(0, 5),
    held: bot.heldItem ? bot.heldItem.name : null,
    drops: drops.slice(0, 6),
    hz: 当前采样率,
    plugins: {
      pathfinder: !!(寻路插件 && 寻路插件.可用()),
      body: !!(身体插件 && 身体插件.可用()),
    },
    watched: Object.keys(探针表).length ? 探针表 : null,
    respawned: Date.now() - 重生时刻 < 15000,
    // ── M4·猎手 ──
    deaths: 死亡次数,
    // ── M5·视觉与触觉要用的事实 ──
    scan: 扫描,                       // 最近一次 scan_environment 的结果（脑用完可清）
    durability: 耐久快照(),           // 手持 + 四件护甲的耐久
    // ── M4c·事实通道（没人盯就是 null，快照不白胖）──
    blocks: 方块快照(),
    items: 物品快照(),
    furnace: 熔炉读数,
    // ── M4b·绕路要用 ──
    stuck_count: 卡住次数,                                   // 只增不减
    stuck_ms: (卡住记录 ? Date.now() - 卡住记录.t : null),    // 距上次卡住多久
    stuck_dir: (卡住记录 ? 卡住记录.方向 : null),
    // 2.5 秒内的"谁打我"才算数 —— 不然它会记着一个早就不在场的名字
    attacked_by: (被打记录 && Date.now() - 被打记录.t < 2500) ? 被打记录.by : null,
    // ── M1 原有 ──
    acting: 当前动作,
    msg: lastChat,
  });
}

/* M4·猎手：谁算敌人。只此一处说了算 —— 快照里的 threats 和 players[].hostile
 * 都调它，所以"手认为的敌人"和"脑认为的敌人"永远一致。 */
function 算不算敌人(名, e) {
  if (朋友.has(名)) return false;                       // 朋友名单优先级最高
  if (HOSTILE.has(名)) return true;
  return !!e && e.type === 'player' && 假想敌.has(名);
}

// M3：所有在线玩家的位置（不受 near 半径限制）—— 跟随指令 / 主动锁定要用
function 玩家们() {
  const 出 = [];
  if (!bot || !bot.entity || !bot.players) return 出;
  const p = bot.entity.position;
  for (const 名 in bot.players) {
    const pl = bot.players[名];
    if (!pl || !pl.entity || !pl.entity.position) continue;
    const e = pl.entity;
    出.push({
      name: 名,
      dist: Number(e.position.distanceTo(p).toFixed(2)),
      pos: [Number(e.position.x.toFixed(1)),
            Number(e.position.y.toFixed(1)),
            Number(e.position.z.toFixed(1))],
      // M4·猎手：这个玩家算不算敌人，由手这边统一裁决（和 threats 用同一套名单），
      // 大脑只认这一个字段 —— 两边各写一套"谁是敌人"的规则，迟早会不一致。
      // 注意：和 threats 不同，这里**不受 8 格威胁半径限制**：主动锁定要在
      // 二十几格外就发现你，否则"主动"两个字无从谈起。
      hostile: 算不算敌人(名, e),
    });
  }
  出.sort((a, b) => a.dist - b.dist);
  return 出;
}

function emit(kind, payload) {
  broadcast(Object.assign({ type: kind, t: Date.now(), bot: cfg.bot_name }, payload));
}

/* ─────────────────── M1·命令通道：把动作翻成操控 ───────────────────
 * 手只认四个动词：retreat（往哪跑、跑多久）、eat、stop、ping。
 * 这里没有一行"该不该跑"的判断 —— 那是大脑的事。 */

let 当前动作 = 'idle';
let 动作定时器 = null;
let 重连定时器 = null;
let 重连次数 = 0;
let 主动退出 = false;
let 丢包计数 = 0;
let 丢包上次报告 = 0;
let 死过 = false;                  // M2：区分"首次出生"和"死后重生"

function 停动作() {
  if (动作定时器) { clearTimeout(动作定时器); 动作定时器 = null; }
  try {
    if (bot) {
      for (const c of ['forward', 'back', 'left', 'right', 'jump', 'sprint', 'sneak']) {
        bot.setControlState(c, false);
      }
    }
  } catch (e) { /* 人都不在了，无所谓 */ }
  当前动作 = 'idle';
}

function 回执(sock, cmd, ok, why, extra) {
  try {
    send(sock, Object.assign({ type: 'event', kind: 'cmdResult', cmd, ok,
                              why: why || null, t: Date.now() }, extra || {}));
  } catch (e) { /* 对面已经走了 */ }
}

// 异常数据包一律丢弃，只计数 + 最多每 10 秒告警一条，绝不因为一个烂包崩掉
function 丢包(sock, 原因) {
  丢包计数++;
  const 现在 = Date.now();
  if (现在 - 丢包上次报告 > 10000) {
    log(`丢了个不认识的包（${原因}），累计 ${丢包计数} 个。`);
    丢包上次报告 = 现在;
  }
  回执(sock, 'unknown', false, 原因, { dropped_total: 丢包计数 });
}

// 逃跑的前提是还活着：这几样东西踩上去就没了，宁可站着挨打也别过去
const 烫脚 = new Set(['lava', 'fire', 'soul_fire', 'magma_block', 'cactus', 'powder_snow']);

function 前方危险(nx, nz) {
  try {
    const p = bot.entity.position;
    const 身位 = bot.blockAt(p.offset(nx * 1.2, 0, nz * 1.2));
    const 脚下 = bot.blockAt(p.offset(nx * 1.2, -1, nz * 1.2));
    const 再下 = bot.blockAt(p.offset(nx * 1.2, -3, nz * 1.2));
    if (身位 && 烫脚.has(身位.name)) return true;
    if (脚下 && 烫脚.has(脚下.name)) return true;
    // 往下两格都还是空的 = 前面大概率是断崖
    if (脚下 && 脚下.name === 'air' && 再下 && 再下.name === 'air') return true;
    return false;
  } catch (e) {
    return false;   // 区块没加载好就别乱猜，按安全处理
  }
}

function 执行撤退(dx, dz, ms, sprint) {
  if (!bot || !bot.entity) return;
  插件让路();
  const 长 = Math.hypot(dx, dz) || 1;
  let nx = dx / 长, nz = dz / 长;

  if (前方危险(nx, nz)) {
    // 正前方不行就试着左右各偏 60° / 120°，找一条能走的路
    let 找到了 = false;
    for (const a of [Math.PI / 3, -Math.PI / 3, 2 * Math.PI / 3, -2 * Math.PI / 3]) {
      const tx = nx * Math.cos(a) - nz * Math.sin(a);
      const tz = nx * Math.sin(a) + nz * Math.cos(a);
      if (!前方危险(tx, tz)) { nx = tx; nz = tz; 找到了 = true; break; }
    }
    if (!找到了) {
      停动作();
      当前动作 = 'blocked';
      // M4b：绕不开也算"卡住" —— 脑那边只认这一条事实，不关心是墙还是岩浆
      卡住记录 = { t: Date.now(), 方向: 当前方向, 走了: 0 };
      if (Date.now() - 上次卡住记账 >= 2000) {
        上次卡住记账 = Date.now();
        卡住次数 += 1;
        记一笔({ 事件: '卡住', 方向: 当前方向, 走了: 0, 原因: '悬崖或岩浆' });
      }
      log('前面是悬崖或者岩浆，绕不开，先站着不动。');
      emit('event', { kind: 'blocked', why: 'no-way-out' });
      return;
    }
  }

  当前方向 = [Number(nx.toFixed(3)), Number(nz.toFixed(3))];   // M4b：卡住检测要用

  // ⚠ 2026-10-01 实测抓到的老 bug：**这里不能自己算 yaw**。
  // 只读标定（RCON 量位移）：发 (+1,0) 走 +x ✓、(-1,0) 走 -x ✓，
  // 但发 (0,+1) 实际走 -z、发 (0,-1) 实际走 +z —— **z 轴整体反了**。
  // 原因：mineflayer 内部 yaw 与 notchian yaw 差一个 π（见 physics.js 的
  // conv.toNotchianYaw），它的 lookAt 用 atan2(-dx, -dz)，而这里原来写的是
  // atan2(-nx, nz)（notchian 那一套）。x 轴在两种约定下恰好一致，所以
  // M1/M2 的"逃命"看着一直是对的 —— 直到 M4 让它直奔二十格外的目标才暴露。
  // 修法：不自己算角度，交给 lookAt，用库自己的换算，永远跟它的物理一致。
  const 我 = bot.entity.position;
  const 眼高 = bot.entity.eyeHeight || 1.6;
  try {
    bot.lookAt(我.offset(nx, 眼高, nz), true).catch(() => {});
    bot.setControlState('forward', true);
    bot.setControlState('sprint', !!sprint);
  } catch (e) { return; }
  if (动作定时器) clearTimeout(动作定时器);
  当前动作 = 'retreat';
  动作定时器 = setTimeout(() => { 停动作(); log('撤退结束，站住。'); }, ms);
}

function 执行进食(sock) {
  if (!bot || !bot.entity) return;
  插件让路();
  let 候选;
  try { 候选 = bot.inventory.items().filter((i) => FOOD_RANK.has(i.name)); }
  catch (e) { 回执(sock, 'eat', false, '背包读不到'); return; }
  if (!候选.length) { 回执(sock, 'eat', false, 'no-food'); return; }
  候选.sort((a, b) => FOOD_RANK.get(a.name) - FOOD_RANK.get(b.name));
  const 选 = 候选[0];
  当前动作 = 'eat';
  (async () => {
    try {
      await bot.equip(选, 'hand');
      // 饥饿值满的时候 consume() 会一直挂着不返回，必须加个上限
      await Promise.race([
        bot.consume(),
        new Promise((_, rj) => setTimeout(() => rj(new Error('吃太久，放弃')), 8000)),
      ]);
      log(`吃了一个 ${选.name}。`);
      回执(sock, 'eat', true, null, { item: 选.name, hp: bot.health, hunger: bot.food });
    } catch (e) {
      log(`没吃成：${e.message}`);
      回执(sock, 'eat', false, e.message, { item: 选.name });
    } finally {
      if (当前动作 === 'eat') 当前动作 = 'idle';
    }
  })();
}

function 收命令(sock, 行) {
  const 文本 = String(行).trim();
  if (!文本) return;
  let msg;
  try { msg = JSON.parse(文本); } catch (e) { 丢包(sock, '不是合法 JSON'); return; }
  if (!msg || typeof msg !== 'object' || Array.isArray(msg)) { 丢包(sock, '结构不对'); return; }
  // M2：动词可以叫 cmd 也可以叫 act（任务书里写的是 act，两种都收）
  const 动词 = typeof msg.cmd === 'string' ? msg.cmd
             : (typeof msg.act === 'string' ? msg.act : null);
  if (!动词) { 丢包(sock, '结构不对（缺 cmd / act）'); return; }
  // 账本：大脑下的每一条命令都留痕 —— 光有结果没有输入，事后没法复盘
  记一笔({ 事件: '命令', 动词, 目标: msg.target || null,
           时长: msg.ms || null, 方向: msg.dir || null,
           频率: (msg.hz === undefined ? null : msg.hz),
           文本: (动词 === 'say' ? String(msg.text || '').slice(0, 60) : null) });
  if (!bot || !bot.entity) { 回执(sock, 动词, false, '还没进世界'); return; }

  switch (动词) {
    // M1 的动词。move 是它的大名 —— retreat 留着当别名，老代码不会因为改名而断。
    case 'move':
    case 'retreat': {
      const dir = Array.isArray(msg.dir) ? msg.dir : null;
      const dx = Number(dir && dir[0]), dz = Number(dir && dir[1]);
      if (!Number.isFinite(dx) || !Number.isFinite(dz) || (dx === 0 && dz === 0)) {
        回执(sock, 动词, false, 'dir 得是两个不全为零的数'); return;
      }
      const 上限 = m1.command_max_ms || 5000;
      const ms = Math.min(Math.max(Number(msg.ms) || 1500, 200), 上限);
      执行撤退(dx, dz, ms, !!msg.sprint);
      回执(sock, 动词, true, null, { ms });
      break;
    }
    case 'eat':   执行进食(sock); break;
    case 'stop':  停动作(); 回执(sock, 'stop', true); break;
    // M4c：三条事实通道。**只加读事实的，不加动作动词**（动词表不膨胀）。
    case 'scan_environment': {
      // M5.1：扫一眼周围。**纯读**，不动世界、不改状态、不发服务器请求。
      const 出 = 扫环境(msg.半径, msg.步长);
      回执(sock, 'scan_environment', !出.出错, 出.出错 || null,
           { 方块类: (出.方块 || []).length, 实体: (出.实体 || []).length });
      break;
    }
    case 'scan_clear': {
      扫描 = null;                      // 脑那边用完就清，别让快照一直背着一份旧扫描
      回执(sock, 'scan_clear', true);
      break;
    }
    case 'watch_blocks': {
      看的方块 = Array.isArray(msg.list)
        ? msg.list.filter(Array.isArray).slice(0, 32)
            .map((p) => [Number(p[0]), Number(p[1]), Number(p[2])])
        : [];
      回执(sock, 'watch_blocks', true, null, { 盯着: 看的方块.length });
      break;
    }
    case 'watch_items': {
      看的物品 = Array.isArray(msg.list) ? msg.list.map(String).slice(0, 32) : [];
      回执(sock, 'watch_items', true, null, { 盯着: 看的物品.length });
      break;
    }
    case 'furnace_watch': {
      if (Array.isArray(msg.p) && msg.p.length >= 3) {
        看熔炉 = { p: [Number(msg.p[0]), Number(msg.p[1]), Number(msg.p[2])],
                   每_ms: Math.max(500, Number(msg.每_ms) || 2000), 上次: 0 };
      } else {
        看熔炉 = null; 熔炉读数 = null;
      }
      回执(sock, 'furnace_watch', true, null, { 盯着: 看熔炉 ? 看熔炉.p : null });
      break;
    }
    case 'ping':  回执(sock, 'ping', true, null, { seq: msg.seq }); break;
    case 'say': {
      const 文本 = String(msg.text == null ? '' : msg.text).slice(0, 200);
      if (!文本) { 回执(sock, 'say', false, 'text 不能为空'); return; }
      try { bot.chat(文本); 回执(sock, 'say', true, null, { text: 文本 }); }
      catch (e) { 回执(sock, 'say', false, e.message); }
      break;
    }
    case 'friend': {
      const 名 = String(msg.name == null ? '' : msg.name).slice(0, 40);
      if (!名) { 回执(sock, 'friend', false, 'name 不能为空'); return; }
      if (msg.remove) 朋友.delete(名); else 朋友.add(名);
      log(`友好名单${msg.remove ? '移除' : '加入'}：${名}（现在 ${朋友.size} 个）`);
      回执(sock, 'friend', true, null, { friends: Array.from(朋友) });
      break;
    }

    // ── M2 新增 ──
    case 'attack': {
      if (typeof msg.target !== 'string' || !msg.target) {
        回执(sock, 'attack', false, 'target 得是个名字'); return;
      }
      执行攻击(sock, msg.target, msg.ms);
      break;
    }
    case 'mode': {
      const 变了 = 设采样率(msg.hz);
      回执(sock, 'mode', true, null, { hz: 当前采样率, changed: 变了 });
      break;
    }
    case 'goto': {
      const p = Array.isArray(msg.p) ? msg.p
              : (Array.isArray(msg.pos) ? msg.pos : null);
      if (!p || p.length < 3 || p.slice(0, 3).some((v) => !Number.isFinite(Number(v)))) {
        回执(sock, 'goto', false, 'p 得是三个数'); return;
      }
      执行前往(sock, p.slice(0, 3).map(Number));
      break;
    }

    default: {
      // M4：新动作一律交给「身体插件」，主链的动词表不跟着膨胀。
      // 插件不在 / 没这个能力 → 老老实实退回老样子「不认识这个命令」。
      const 能力 = (身体插件 && typeof 身体插件.能力 === 'function') ? 身体插件.能力() : [];
      // M4.1：带头 target 的插件动作（歪打正着：跳劈就在这儿）先过"看得见"那道闸。
      // 插件自己管不了这件事 —— 它们拿到的只是 bot，不知道主链这条规矩。
      const 分发 = (出手前血) => {
        停动作();
        当前动作 = 动词;
        身体插件.执行(bot, 动词, msg)
          .then((r) => {
            // 账本：插件动作（跳劈就走这条）成功了才记账，600ms 后自动结算
            if (!(r && r.ok === false) && msg.target) {
              记挥击(动词, msg.target, (r && typeof r.dist === 'number') ? r.dist : null, 出手前血);
            } else if (r && r.取消 && msg.target) {
              记一笔({ 事件: '取消挥击', 动词, 目标: msg.target,
                       距离: (typeof r.dist === 'number') ? r.dist : null, 原因: r.取消 });
            }
            回执(sock, 动词, !(r && r.ok === false), (r && r.why) || null, r || {});
          })
          .catch((e) => 回执(sock, 动词, false, e.message))
          .finally(() => { if (当前动作 === 动词) 当前动作 = 'idle'; });
      };
      if (msg.target) {
        const 找 = 找目标(msg.target);
        if (找 && !看得见(找.e)) {
          回执(sock, 动词, false, '中间隔着方块，打不着', { blocked: 'no-sight' });
          return;
        }
      }
      if (身体插件 && typeof 身体插件.执行 === 'function' && 能力.indexOf(动词) >= 0) {
        // 先问一次出手前的血量，再动手（问不到也照样打，只是这条账少了"掉多少"）
        if (msg.target) 问血量(msg.target).then(分发).catch(() => 分发(null));
        else 分发(null);
      } else {
        丢包(sock, `不认识的命令「${String(动词).slice(0, 20)}」`);
      }
    }
  }
}

// M1·防卡死：小家伙掉线了自己爬回来，阶梯退避，别把服务器敲爆
function 计划重连() {
  if (主动退出 || 重连定时器) return;
  const 阶梯 = m1.reconnect_backoff_ms || [3000, 6000, 12000, 30000, 60000];
  const 等 = 阶梯[Math.min(重连次数, 阶梯.length - 1)];
  重连次数++;
  log(`小家伙掉线了，${Math.round(等 / 1000)} 秒后重连（第 ${重连次数} 次）`);
  emit('event', { kind: 'reconnect', after_ms: 等, attempt: 重连次数 });
  重连定时器 = setTimeout(() => {
    重连定时器 = null;
    try { if (bot) bot.removeAllListeners(); } catch (e) {}
    停动作();
    startBot();
  }, 等);
}

/* ─────────── M2·背包、反击、动态采样、寻路挂载点 ───────────
 * 手这边只增加"怎么做"，一条"该不该"的判断都不加。
 * 脑说打谁、脑说多快推、脑说去哪，手照做；做不了就老实说做不了。 */

let timer = null;                  // 推送定时器，采样率一变就换一个
let 当前采样率 = Math.max(0.2, Number(m2.hz_calm) || 1);
let 重生时刻 = 0;
// M4·猎手要用到的三样事实：死过几次、谁在打我、我上一拍的血
let 死亡次数 = 0;
let 被打记录 = null;
let 上次血量 = null;

/* ── M4b·卡住检测 ──
 * 手的职责只是"报事实"：这一拍我命令它往前走，它到底动了没有。
 * 判断（要不要绕、往哪绕）全在大脑那边 —— 边界不越位。
 * 为什么要单独检测：撞墙**不会**产生任何事件，move 命令发下去照样"成功"，
 * 只有位移能说明问题。 */
let 卡住记录 = null;      // {t, 方向, 走了}
let 卡住次数 = 0;         // 只增不减，脑靠它识别"又卡了一次"
let 上次卡住记账 = 0;
let 当前方向 = null;      // 最近一条 move 命令的方向
let 上一拍位置 = null;
let 上一拍时刻 = 0;
let 应急修理中 = false;
let 应急失败次数 = 0;
let 上次整理应急 = 0;

// 口粮偏好：config 里排在前面的优先，没上榜的按 FOODS 的名次兜底
function 口粮优先值(名) {
  const i = 口粮偏好.indexOf(名);
  return i >= 0 ? i : 100 + (FOOD_RANK.has(名) ? FOOD_RANK.get(名) : 999);
}

/* ── 应急包 ──
 * hotbar 从 0 数，默认第 8 号（最右边那格）当"保命口粮"。
 * 只在不对的时候才动手，所以每 10 秒查一次也很便宜。
 * 连续失败 3 次就放弃 —— 窗口点击一直失败还硬点，会把背包点乱。 */
const 应急格 = Math.min(Math.max(Number(m2.emergency_slot ?? 8), 0), 8);
const 应急窗口槽 = 36 + 应急格;      // 玩家背包窗口里 hotbar 是 36~44

function 应急包维护() {
  if (!bot || !bot.entity || 应急修理中 || 应急失败次数 >= 3) return;

  let 候选;
  try { 候选 = bot.inventory.items().filter((i) => FOOD_RANK.has(i.name)); }
  catch (e) { return; }
  if (!候选.length) return;                          // 背包里根本没吃的
  候选.sort((a, b) => 口粮优先值(a.name) - 口粮优先值(b.name));
  const 选 = 候选[0];

  let 现在;
  try { 现在 = bot.inventory.slots[应急窗口槽]; } catch (e) { return; }

  if (现在 && FOOD_RANK.has(现在.name)) {
    // 已经有口粮了。只有"手头这份比背包里最好的明显差"才值得折腾 ——
    // 每次升级都要点一次背包窗口，点多了容易把背包点乱，所以还要限流。
    if (口粮优先值(选.name) >= 口粮优先值(现在.name)) return;
    if (Date.now() - 上次整理应急 < 60000) return;
  }
  if (选.slot === 应急窗口槽) return;

  应急修理中 = true;
  上次整理应急 = Date.now();
  bot.moveSlotItem(选.slot, 应急窗口槽)
    .then(() => { 应急失败次数 = 0; log(`应急包补上了：${选.name}`); })
    .catch((e) => {
      应急失败次数++;
      log(`应急包没整理成（第 ${应急失败次数} 次）：${e.message}`);
      if (应急失败次数 >= 3) log('放弃整理应急包，免得一直点窗口反而把背包点乱。');
    })
    .finally(() => { 应急修理中 = false; });
}

/* ── 动态采样 ──
 * 脑说了算，手只负责换挡。范围锁死在 0.2~20Hz：
 * 万一哪天脑写错了推一个 1000Hz 过来，也不至于把机器点着。 */
function 设采样率(hz) {
  const 目标 = Math.min(Math.max(Number(hz) || 1, 0.2), 20);
  const 周期 = Math.max(Math.round(1000 / 目标), 50);
  if (timer && Math.abs(目标 - 当前采样率) < 0.01) return false;
  当前采样率 = 目标;
  if (timer) clearInterval(timer);
  timer = setInterval(() => {
    lastState = snapshot();
    // 证据链：落盘的那一份和推给大脑的是**同一帧**，事后重放不会有出入
    if (全程流) { try { 全程流.write(JSON.stringify(lastState) + '\n'); } catch (e) {} }
    broadcast(lastState);
  }, 周期);
  log(`采样率切成 ${目标}Hz（每 ${周期}ms 推一次）`);
  return true;
}

/* ── 寻路插件 ──
 * 可选外挂。目录不在、依赖没装、require 抛异常 —— 一律当"没装"处理，
 * 主链一行都不受影响。这就是"主链不动、外挂仓库"的字面实现。 */
let 寻路插件 = null;
let 找过插件了 = false;

function 装寻路插件() {
  if (找过插件了) return 寻路插件;
  找过插件了 = true;
  const 目录 = path.resolve(ROOT, 'node', m2.pathfinder_dir || './plugins/pathfinder');
  // 入口文件名先按任务书里说的 proto_pathfinder.js 找，找不到再退回 index.js
  const 候选 = [m2.pathfinder_entry || 'proto_pathfinder.js', 'index.js'];
  let 错误 = null;
  for (const 名 of 候选) {
    try {
      寻路插件 = require(path.join(目录, 名));
      错误 = null;
      break;
    } catch (e) {
      错误 = e;
      寻路插件 = null;
      if (e.code !== 'MODULE_NOT_FOUND') break;   // 装是装了，是它自己炸的，别再试下一个
    }
  }
  try {
    const 能用 = !!(寻路插件 && typeof 寻路插件.可用 === 'function' && 寻路插件.可用());
    if (能用) { log(`寻路插件挂上了：${寻路插件.名字 || 'pathfinder'}`); }
    else {
      寻路插件 = null;
      log(`没有可用的寻路插件（${(错误 && (错误.code || 错误.message)) || '依赖没装全'}）`
          + ` —— goto 会回退成「原地站着」，主链不受影响。`);
    }
  } catch (e) {
    寻路插件 = null;
    log(`寻路插件自检就炸了（${e.message}），当没装处理。`);
  }
  return 寻路插件;
}

// M4：身体插件（手 + 腿）。规矩和 pathfinder 一模一样：
// 自己一个目录、自己的 package.json；不在 / 加载炸 → 当没装，命令回退「不认识」。
let 身体插件 = null;
let 找过身体了 = false;

function 装身体插件() {
  if (找过身体了) return 身体插件;
  找过身体了 = true;
  const 目录 = path.resolve(ROOT, 'node', m4.body_dir || './plugins/body');
  const 候选 = [m4.body_entry || 'proto_body.js', 'index.js'];
  let 错误 = null;
  for (const 名 of 候选) {
    try {
      身体插件 = require(path.join(目录, 名));
      错误 = null;
      break;
    } catch (e) {
      错误 = e;
      身体插件 = null;
      if (e.code !== 'MODULE_NOT_FOUND') break;
    }
  }
  try {
    const 能用 = !!(身体插件 && typeof 身体插件.可用 === 'function' && 身体插件.可用());
    if (能用) {
      const 能力 = (typeof 身体插件.能力 === 'function' ? 身体插件.能力() : []) || [];
      log(`身体插件挂上了：${身体插件.名字 || 'body'}（会 ${能力.join('、')}）`);
    } else {
      身体插件 = null;
      log(`没有可用的身体插件（${(错误 && (错误.code || 错误.message)) || '依赖没装全'}）`
          + ` —— 挖/放/合成/跳劈这些命令会回退成「不认识」。`);
    }
  } catch (e) {
    身体插件 = null;
    log(`身体插件自检就炸了（${e.message}），当没装处理。`);
  }
  return 身体插件;
}

// 任何"自己动腿"的动作开始前，先把插件的腿打断 —— 两套腿同时迈会互相打架
function 插件让路() {
  if (寻路插件 && typeof 寻路插件.停 === 'function') {
    try { 寻路插件.停(bot); } catch (e) { /* 无所谓 */ }
  }
  if (身体插件 && typeof 身体插件.停 === 'function') {
    try { 身体插件.停(bot); } catch (e) { /* 无所谓 */ }
  }
}

/* ── 反击 ──
 * 只挥一下，不追砍。够不着就老实说够不着，让脑自己决定下一步。
 *
 * ⚠ 命中率的关键在这里：**边跑边挥是打不中的**。
 * 服务端判定攻击距离用的是它自己那份位置，而它在移动时会滞后 50~100ms。
 * 一个 4.3 格/秒的人在 100ms 里跑掉 0.43 格 —— 报 2.5 格、服务端看到的是 2.9 格，
 * 正好卡在 3 格的射程线上，于是大量挥空。所以挥之前必须先站住。 */
let 上次挥击 = 0;

/* M4.1·「看得见才准打」—— 主人 2026-10-01 抓到的作弊：
 * 隔着两格高的木板墙，它照样跳劈/平A。原因是**协议层的近战只查距离**：
 * bot.attack() 直接发攻击包，服务端那边只验证"你俩够不够近"（3 格），
 * 中间有没有墙根本不看（原版客户端是自己用准星射线挑目标的，绕过了那一步）。
 * 所以这一条只能我们自己在手这边补：眼睛 → 目标胸口拉一条线，逐格走一遍，
 * 撞到实心方块就说明打不着。 */
function 看得见(目标) {
  try {
    const 眼 = bot.entity.position.offset(0, bot.entity.eyeHeight || 1.62, 0);
    const 胸 = 目标.position.offset(0, (目标.height || 1.8) * 0.85, 0);
    const 向量 = 胸.minus(眼);
    const 距离 = 向量.norm();
    if (!(距离 > 0)) return true;
    const 步 = 0.25;
    for (let d = 步; d < 距离 - 0.2; d += 步) {
      const 点 = 眼.plus(向量.scaled(d / 距离));
      const 块 = bot.blockAt(点);
      // boundingBox === 'empty' 是空气/草/火把这类可穿过的；实心方块挡视线
      if (块 && 块.boundingBox && 块.boundingBox !== 'empty') return false;
    }
    return true;
  } catch (e) {
    return true;      // 区块没加载好就别乱判，按"看得见"处理（老行为）
  }
}

/** 找最近的同名实体。攻击和"看得见"检查共用一份 —— 免得两处各挑一个目标。 */
function 找目标(目标名) {
  if (!bot || !bot.entity) return null;
  const p = bot.entity.position;
  let 找到 = null, 最近 = Infinity;
  for (const id in bot.entities) {
    const e = bot.entities[id];
    if (!e || !e.position || e === bot.entity) continue;
    const 名 = e.username || e.name || e.displayName || e.type;
    if (名 !== 目标名) continue;
    const d = e.position.distanceTo(p);
    if (d < 最近) { 最近 = d; 找到 = e; }
  }
  return 找到 ? { e: 找到, dist: 最近 } : null;
}

function 执行攻击(sock, 目标名, ms) {
  if (!bot || !bot.entity) return;
  插件让路();
  (async () => {
    // ① 先握好家伙（背包正被应急包整理时就让一步，拿手上的先打）
    try {
      const 手上 = bot.heldItem;
      if ((!手上 || !武器排名.has(手上.name)) && !应急修理中) {
        const 候选 = bot.inventory.items().filter((i) => 武器排名.has(i.name));
        候选.sort((a, b) => 武器排名.get(a.name) - 武器排名.get(b.name));
        if (候选.length) await bot.equip(候选[0], 'hand');
      }
    } catch (e) { log(`换武器没换成，就用手上这个打：${e.message}`); }

    // ② 找最近的同名目标
    const 命中 = 找目标(目标名);
    if (!命中) { 回执(sock, 'attack', false, '视野里没有这个目标'); return; }
    const 目标 = 命中.e, 最近 = 命中.dist;
    // 第二道锁：朋友永远不打，哪怕大脑下错了命令
    if (朋友.has(目标名)) {
      log(`大脑让我打「${目标名}」，但他在友好名单里 —— 拒了。`);
      回执(sock, 'attack', false, '目标在友好名单里，拒打');
      return;
    }
    if (最近 > 4.0) {
      回执(sock, 'attack', false, `目标在 ${最近.toFixed(1)} 格外，够不着`);
      return;
    }
    // M4.1：隔着方块不许打（协议只查距离，不查中间有没有墙）
    if (!看得见(目标)) {
      log(`「${目标名}」在 ${最近.toFixed(1)} 格外，可中间隔着方块 —— 这一下我不挥。`);
      回执(sock, 'attack', false, '中间隔着方块，打不着', { blocked: 'no-sight' });
      return;
    }

    // ③ 站住 + 转身，等两件事实都发出去之后再挥
    停动作();
    try {
      const 瞄 = 目标.position.offset(0, (目标.height || 1.8) * 0.85, 0);
      await bot.lookAt(瞄, true);
    } catch (e) { /* 转不过去也照样挥，总比不挥强 */ }
    await new Promise((r) => setTimeout(r, 100));     // 让服务端看见"我站住了"

    // ④ 挥
    // ⚠ 2026-10-01：取血量必须放在这里 —— 下面的"目标倒下就别挥"要用它。
    // 一开始写在 bot.attack 之后，结果复检读到一个还没初始化的 const，
    // 日志里刷「这一下没挥成：Cannot access '出手前血' before initialization」。
    // 先用探针表里的现值占位（它是 500ms 一轮的，可能有点旧），
    // 紧接着换成**当场问一次**的真血 —— 账本要的是真血。
    let 出手前血 = (typeof 探针表[目标名] === 'number') ? 探针表[目标名] : null;
    try { 出手前血 = await 问血量(目标名); } catch (e) { /* 问不到就用旧的 */ }
    try {
      /* M4.1·出手前**再量一次**（2026-10-01 实测教训）：
       * 从"决定挥"到真的挥下去，中间隔着换武器 + 转身 + 等 100ms，
       * 实测里这三百多毫秒足够一个疾跑的目标跑出 3 格 —— 那一刀白挥。
       * 第一轮 229 次平A 里 138 次是这么空的（命中率被压到 14%）。 */
      const 现在距 = 目标.position ? 目标.position.distanceTo(bot.entity.position) : 最近;
      if (现在距 > 2.9) {
        记一笔({ 事件: '取消挥击', 动词: 'attack', 目标: 目标名,
                 距离: Number(现在距.toFixed(2)), 原因: '跑出打击范围' });
        回执(sock, 'attack', false, `目标跑到 ${现在距.toFixed(1)} 格外了，这一下不挥`,
             { blocked: 'out-of-reach' });
        return;
      }
      if (typeof 出手前血 === 'number' && 出手前血 <= 0) {
        记一笔({ 事件: '取消挥击', 动词: 'attack', 目标: 目标名,
                 距离: Number(现在距.toFixed(2)), 原因: '目标已经倒下' });
        回执(sock, 'attack', false, '目标已经倒下了，不挥空拳', { blocked: 'dead' });
        return;
      }
      bot.attack(目标);
      上次挥击 = Date.now();
      当前动作 = 'attack';
      记挥击('attack', 目标名, Number(最近.toFixed(2)), 出手前血);
      log(`挥了一下「${目标名}」（出手时 ${最近.toFixed(1)} 格）`);
      回执(sock, 'attack', true, null,
           { target: 目标名, dist: Number(最近.toFixed(2)),
             with: bot.heldItem ? bot.heldItem.name : null });
      setTimeout(() => { if (当前动作 === 'attack') 当前动作 = 'idle'; },
                 Math.min(Math.max(Number(ms) || 800, 100), 2000));
    } catch (e) {
      回执(sock, 'attack', false, e.message);
    }
  })();
}

function 执行前往(sock, 坐标, msg) {
  const 插 = 装寻路插件();
  if (!插) {
    停动作();
    回执(sock, 'goto', false, '没有寻路插件，回退成原地站着', { fallback: 'stand' });
    return;
  }
  停动作();
  if (typeof 插.停 === 'function') { try { 插.停(bot); } catch (e) { /* 无所谓 */ } }
  // near = 到点容差（格）。默认交给插件（2）；"走过去捡东西"这类要精确到位，
  // 脑那边会传 near:1 —— 不然它会停在 2 格外看着掉落物干等（实测踩过）。
  Promise.resolve(插.前往(bot, 坐标,
    { timeout_ms: m2.goto_timeout_ms || 30000,
      near: (msg && msg.near !== undefined) ? Number(msg.near) : undefined }))
    .then((r) => 回执(sock, 'goto', true, null, r || {}))
    .catch((e) => 回执(sock, 'goto', false, e.message));
}

// 大脑全掉线时：不但要停动作，采样率也得自己降回来（脑不在就别烧 CPU）
function 大脑全走了() {
  停动作();
  if (Math.abs(当前采样率 - (Number(m2.hz_calm) || 1)) > 0.01) {
    设采样率(m2.hz_calm || 1);
    log('大脑不在，采样率自动降回平静档。');
  }
  if (寻路插件 && typeof 寻路插件.停 === 'function') {
    try { 寻路插件.停(bot); } catch (e) { /* 无所谓 */ }
  }
}

/* ─────────── 可选：服务器探针（默认关） ───────────
 * MC 协议只把**自己**的血量推给你，别人的血量是不广播的。
 * 所以"想知道对手还剩多少血"这件事，只能另外问服务端。
 *
 * 这里开了一个可选的 RCON 探针：默认关着，只有 config 里显式 enable、
 * 并且显式列出要盯谁，才会去问。每次现连现断（1Hz，开销可以忽略），
 * 不留长连接、不留状态。纯 net 模块，不引入任何新依赖。 */

const 探针表 = {};                 // 名字 -> 血量

function 探针问一次(命令) {
  const p = m2.probe || {};
  return new Promise((resolve) => {
    let s;
    try {
      s = net.createConnection({ host: p.host || '127.0.0.1', port: p.port || 25575 });
    } catch (e) { return resolve(null); }
    let 缓冲 = Buffer.alloc(0), 阶段 = 0, 号 = 0, 完 = false;
    const 收 = (v) => { if (完) return; 完 = true; try { s.destroy(); } catch (e) {} resolve(v); };
    const 打包 = (类型, 正文) => {
      号++;
      const 文本 = Buffer.from(正文, 'utf8');
      const 体 = Buffer.alloc(8 + 文本.length + 2);
      体.writeInt32LE(号, 0); 体.writeInt32LE(类型, 4);
      文本.copy(体, 8); 体.writeInt16LE(0, 8 + 文本.length);
      const 头 = Buffer.alloc(4); 头.writeInt32LE(体.length, 0);
      return Buffer.concat([头, 体]);
    };
    s.setTimeout(3000, () => 收(null));
    s.on('error', () => 收(null));
    s.on('connect', () => s.write(打包(3, p.password || '')));
    s.on('data', (块) => {
      缓冲 = Buffer.concat([缓冲, 块]);
      while (缓冲.length >= 4) {
        const 长 = 缓冲.readInt32LE(0);
        if (缓冲.length < 4 + 长) return;
        const 体 = 缓冲.slice(4, 4 + 长);
        缓冲 = 缓冲.slice(4 + 长);
        if (体.readInt32LE(0) === -1) return 收(null);        // 密码不对
        if (阶段 === 0) { 阶段 = 1; s.write(打包(2, 命令)); }
        else return 收(体.slice(8, 体.length - 2).toString('utf8'));
      }
    });
  });
}

function 装探针() {
  const p = m2.probe || {};
  if (!p.enable || !(p.watch || []).length) {
    log('服务器探针关着（要看别人的血量才需要它）。');
    return null;
  }
  const 周期 = Math.max(Number(p.poll_ms) || 1000, 500);
  log(`服务器探针开了：每 ${周期}ms 问一次 [${p.watch.join(', ')}] 的血量。`);
  return setInterval(async () => {
    for (const 名 of p.watch) {
      const 出 = await 探针问一次(`data get entity ${名} Health`);
      if (!出) continue;
      const 配 = 出.match(/(-?\d+(?:\.\d+)?)f?\s*$/);
      if (配) {
        const 新血 = parseFloat(配[1]);
        const 旧血 = 探针表[名];
        if (typeof 旧血 === 'number' && Math.abs(新血 - 旧血) > 0.01) {
          记一笔({ 事件: '掉血', 目标: 名, 从: 旧血, 到: 新血,
                   掉: Number((旧血 - 新血).toFixed(2)) });
          if (新血 <= 0 && 旧血 > 0) 记一笔({ 事件: '目标倒下', 目标: 名 });
        }
        探针表[名] = 新血;
      }
    }
  }, 周期);
}

// 假想敌：只在测试时把某些玩家当成敌对生物，平时是空数组
const 假想敌 = new Set(m2.hostile_players || []);

/* ── M3·友好名单 ──
 * 名单里的名字永不进威胁列表，也永远不被攻击。
 * 两道锁：① 这里不进 threats；② 执行攻击() 里再挡一次。
 * 只靠一道锁是不够的 —— 万一哪天有人从别处喂了个目标名进来，第二道还能兜住。 */
const 朋友 = new Set(m3.friends || []);

/* ─────────────────────────── 启动 ─────────────────────────── */

const server = listen();
startBot();

// M4.1：先把证据链打开，再开始干活 —— 免得"开打之后才想起来没录"
开证据链();

// M4b：卡住采样器。250ms 一拍：这一拍命令它往前走、它却几乎没动 → 记一次卡住。
// M4c：熔炉探针的轮询（按它自己的节奏，默认 2 秒读一眼）
setInterval(() => {
  try {
    if (!看熔炉) return;
    if (Date.now() - 看熔炉.上次 < 看熔炉.每_ms) return;
    看熔炉.上次 = Date.now();
    读熔炉();
  } catch (e) { /* 探针绝不能把主链带走 */ }
}, 500);

setInterval(() => {
  try {
    if (!bot || !bot.entity) return;
    const 现在位 = bot.entity.position.clone();
    if (当前动作 === 'retreat' && 上一拍位置 && Date.now() - 上一拍时刻 >= 200) {
      const 走了 = 现在位.distanceTo(上一拍位置);
      if (走了 < 0.12) {
        // ⚠ 2026-10-01 验收当场抓到的假信号：**撞在活物身上也算"没动"**。
        // 玩家之间是有碰撞的 —— 它贴到靶子身上自然走不动，那不是墙。
        // 所以先看身边有没有别的实体：有就不算卡住（不记账、不计数）。
        let 身边有东西 = false;
        try {
          for (const id in bot.entities) {
            const e = bot.entities[id];
            if (!e || !e.position || e === bot.entity) continue;
            if (e.position.distanceTo(现在位) < 1.6) { 身边有东西 = true; break; }
          }
        } catch (err) { /* 读不到就当没有 */ }
        if (身边有东西) { 上一拍位置 = 现在位; 上一拍时刻 = Date.now(); return; }
        卡住记录 = { t: Date.now(), 方向: 当前方向, 走了: Number(走了.toFixed(2)) };
        // 2 秒最多记一次 + 计数 +1（脑靠"计数变了"识别新的一次卡住）
        if (Date.now() - 上次卡住记账 >= 2000) {
          上次卡住记账 = Date.now();
          卡住次数 += 1;
          记一笔({ 事件: '卡住', 方向: 当前方向, 走了: 卡住记录.走了 });
          log(`前面走不动了（这一拍只挪了 ${卡住记录.走了} 格），记一次卡住 #${卡住次数}。`);
        }
      }
    }
    上一拍位置 = 现在位;
    上一拍时刻 = Date.now();
  } catch (e) { /* 采样器绝不能把主链带走 */ }
}, 250);

// M2：采样率交给脑来拨，开机先走平静档
设采样率(当前采样率);

// M2/M4：开机就试着挂插件，这样状态里的 plugins 字段从一开始就是准的
装寻路插件();
装身体插件();

// 可选探针（默认关）
let 探针定时器 = null;

// M2：应急包定期自检 —— 不对才动手，所以每 10 秒查一次也很便宜
const 应急定时器 = setInterval(应急包维护,
  Math.max(2, Number(m2.emergency_check_sec) || 10) * 1000);

探针定时器 = 装探针();

function shutdown(sig) {
  log(`收到 ${sig}，收工。`);
  主动退出 = true;
  clearInterval(timer);
  if (探针定时器) clearInterval(探针定时器);
  clearInterval(应急定时器);
  if (重连定时器) clearTimeout(重连定时器);
  停动作();
  try { bot && bot.quit(); } catch (e) { /* 无所谓 */ }
  server.close(() => {
    if (transport === 'unix') { try { fs.unlinkSync(socketPath); } catch (e) {} }
    process.exit(0);
  });
  setTimeout(() => process.exit(0), 1500);
}
process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
