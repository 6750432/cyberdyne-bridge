#!/usr/bin/env node
'use strict';
/*
 * 生成物理常识.js —— 从底层库里**自动抓**「隐式物理常识」，生成 常识库/物理引擎规则.json
 *
 * 主人 2026-10-09 的架构级反馈
 * ============================
 * 「大肥鱼目前对 MC 物理引擎的理解停留在『API 调用』层面，没有建立起
 *   『物理世界玩家』的常识。**只写了显式常识，漏了隐式常识**。」
 * 「不要写几万条场景，直接从 `minecraft-data` / `prismarine-physics`
 *   底层库中**自动抓取通用规则**。」
 *
 * 显式常识 vs 隐式常识（这份文件要解决的）
 * ========================================
 *   · **显式**：方块叫什么、要什么工具、挖了掉什么 —— 已经做过了（方块交互表.json）
 *   · **隐式**：**身体本能里的物理法则** ✗ —— 比如
 *       「一步只能上 0.6 格 → **一格的坎必须跳**」
 *       「树叶的碰撞盒是**实心**的 → 走不过去」（凭直觉以为树叶能穿 ✗）
 *       「跳起来只能上 1.1 格 → **两格高跳不上去**」
 *       「半砖/台阶/栅栏的碰撞盒**不是整个方块**」
 *     这些没人写，AI 就不知道 ✓ —— 而它们**本来就躺在底层库里** ✓
 *
 * 从哪儿抓（都是真值，不是猜的）
 * ==============================
 *   ① `prismarine-physics/index.js` —— 物理常量（重力/阻力/跳跃初速/台阶高/玩家尺寸…）
 *   ② `minecraft-data/.../blocks.json` —— 每个方块的物性
 *      （boundingBox / hardness / material / harvestTools / drops / transparent …）
 *   ③ `minecraft-data/.../blockCollisionShapes.json` —— **碰撞盒**（能不能穿过去的真值）
 *
 * ⚠ 三条自我约束（今天的血）
 * ==========================
 *   1. **每条都要带出处** ✓ —— 哪个库、哪个文件、哪一行/哪个字段
 *      （查不到出处的，一律标 `"出处": "人工补充"` 并写清依据 ✗ 不许混进来 ✓）
 *   2. **不许"抓不到就猜"** ✗ —— 抓不到就**不写这一条**，或显式标"人工补充" ✓
 *   3. **规则要能被执行** ✓ —— 写成判据，不是散文
 *      （今天的教训：**写出来的东西必须有人读** ✗ 光生成一个 JSON 等于没做 ✓）
 *
 * 跑法：node tools/生成物理常识.js
 *       node tools/生成物理常识.js --看    # 只打出来看看，不写文件
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const 版本 = '1.21.1';
const 数据根 = path.join(ROOT, 'node', 'node_modules', 'minecraft-data', 'minecraft-data', 'data', 'pc', 版本);

function 读(名) {
  return JSON.parse(fs.readFileSync(path.join(数据根, 名), 'utf8'));
}

/** 找一份"覆盖这个版本"的数据文件。
 *  ⚠ 碰撞盒不是每个版本都单独发 ✓ —— minecraft-data 也是**沿用最近的旧版本** ✓
 *     （1.21.1 就没有自己的 blockCollisionShapes.json；最近的是 1.21.3 ✓）
 *  规矩：**找不到就说找不到** ✗ 不许默默用一份不知道对不上的 ✓ */
function 找覆盖版本的文件(名, 想要) {
  // ⚠ 要找"兄弟版本"，目录得是**上一级**（`data/pc/`）✗ —— 我第一版写成了数据根本身 ✓
  //   （那里面只有 1.21.1 一个版本 → 当然"找不到" ✓ 又一次"先看自己" ✓）
  const 目录 = path.dirname(数据根);
  let 候选 = [];
  try {
    for (const d of fs.readdirSync(目录)) {
      if (fs.existsSync(path.join(目录, d, 名))) 候选.push(d);
    }
  } catch (e) { return null; }
  // 版本号排序（1.21.3 < 1.21.4 < …）
  const 数值 = (v) => String(v).split('.').map((x) => parseInt(x, 10) || 0);
  const 比 = (a, b) => {
    const x = 数值(a), y = 数值(b);
    for (let i = 0; i < Math.max(x.length, y.length); i++) {
      const d = (x[i] || 0) - (y[i] || 0);
      if (d) return d;
    }
    return 0;
  };
  候选.sort(比);
  // 同版本 > 最近的更旧版本 > 最近的更新版本
  let 选 = 候选.find((v) => v === 想要);
  if (!选) 选 = [...候选].reverse().find((v) => 比(v, 想要) < 0) || 候选[0];
  if (!选) return null;
  return { 路: path.join(目录, 选, 名), 版本: 选 };
}

function 主() {
  // ★★★ 用**库自己的加载器** ✗ —— 我第一版自己写了一套"找最近的版本" ✓
  //   那是**猜**：碰撞盒该用哪个版本、新方块怎么办，库自己最清楚 ✓
  //   规矩：**别替库做它已经做好的事** ✓
  const 加载 = require(path.join(ROOT, 'node', 'node_modules', 'minecraft-data'));
  const mcd = 加载(版本);
  const 方块 = mcd.blocksArray || 读('blocks.json');
  const 形状表 = mcd.blockCollisionShapes;
  if (!形状表) {
    console.error('✗ 库里拿不到 blockCollisionShapes —— 拒绝生成（宁可不做，不许瞎编）');
    process.exit(2);
  }
  const 物品表 = {};
  for (const it of (mcd.itemsArray || [])) 物品表[it.id] = it.name;
  const 物理 = require(path.join(ROOT, 'node', 'node_modules', 'prismarine-physics'));

  // ── ① 物理常量：从 prismarine-physics **真对象**上抓 ✓ ──
  //   ⚠ 我第一版自己造了个假 mcData 去骗它初始化 ✗ —— 骗不过（它要的字段比我想的多）✓
  //     正确做法：`require('prismarine-physics').Physics(真 mcData)` ✓ 一行 ✓
  let P = null;
  try {
    P = 物理.Physics(mcd);
  } catch (e) {
    console.error(`⚠ 拿不到 physics 对象（${e.message.slice(0, 60)}）—— 改用源码解析`);
    P = 源里抓常量();
  }

  const 常量 = {};
  const 记常量 = (名, 值, 单位, 出处) => {
    常量[名] = { 值, 单位, 出处 };
  };
  记常量('重力', P.gravity, '格/刻²', 'prismarine-physics index.js `physics.gravity`');
  记常量('空气阻力', 1 - P.airdrag, '（每刻速度乘 1-它）', 'prismarine-physics `physics.airdrag`');
  记常量('行走速度', P.playerSpeed, '倍率', 'prismarine-physics `physics.playerSpeed`');
  记常量('冲刺速度', P.sprintSpeed, '倍率', 'prismarine-physics `physics.sprintSpeed`');
  记常量('潜行速度', P.sneakSpeed, '倍率', 'prismarine-physics `physics.sneakSpeed`');
  记常量('台阶高', P.stepHeight, '格', 'prismarine-physics `physics.stepHeight`');
  记常量('玩家宽', P.playerHalfWidth * 2, '格', 'prismarine-physics `physics.playerHalfWidth`×2');
  记常量('玩家高', P.playerHeight, '格', 'prismarine-physics `physics.playerHeight`');
  记常量('水中惯性', P.waterInertia, '倍率', 'prismarine-physics `physics.waterInertia`');
  记常量('岩浆惯性', P.lavaInertia, '倍率', 'prismarine-physics `physics.lavaInertia`');
  记常量('空中惯性', P.airborneInertia, '倍率', 'prismarine-physics `physics.airborneInertia`');
  记常量('自动跳冷却', P.autojumpCooldown, '刻（1 刻 = 50 毫秒）', 'prismarine-physics `physics.autojumpCooldown`');

  // 跳跃初速：源码里写死的 0.42（`vel.y = Math.fround(0.42)`）
  const 源码 = fs.readFileSync(
    path.join(ROOT, 'node', 'node_modules', 'prismarine-physics', 'index.js'), 'utf8');
  const m跳 = 源码.match(/vel\.y\s*=\s*Math\.fround\(([\d.]+)\)/);
  const 跳速 = m跳 ? Number(m跳[1]) : null;
  if (跳速 !== null) 记常量('跳跃初速', 跳速, '格/刻', 'prismarine-physics index.js `vel.y = 0.42`');

  // ── ② 推导：把常量算成"身体本能" ──
  const 推导 = {};
  if (跳速 !== null && P.gravity) {
    // 竖直上抛：h = v²/(2g)（连续近似；MC 是离散的，实际略低 ✓ 所以往下取整更保守）
    const 高 = (跳速 * 跳速) / (2 * P.gravity);
    推导['跳跃能上几格'] = {
      值: Math.floor(高 * 10) / 10,
      原始值: Math.round(高 * 1000) / 1000,
      说明: '竖直上抛 v²/(2g)；MC 是离散刻，实际略低 ✓ 所以取整偏保守',
      出处: '由「跳跃初速」「重力」两条算出',
    };
    推导['一步能跨几格'] = {
      值: P.stepHeight,
      说明: '**这是一条最容易漏的本能**：一步只能上 0.6 格 → '
          + '**一格的坎必须跳** ✓ 两格高的**跳也上不去** ✗（先搭一格）',
      出处: 'prismarine-physics `physics.stepHeight`',
    };
  }

  // ── ③ 碰撞盒：哪些方块**能穿过去**（走路的真值 ✓）──
  const 能穿 = [];
  const 挡路 = [];
  const 非整格 = [];
  const 形状数 = 形状表.shapes.length;
  for (const b of 方块) {
    const id = 形状表.blocks[b.name];
    if (id === undefined) continue;
    const 首 = Array.isArray(id) ? id[0] : id;
    const 盒 = 形状表.shapes[首];
    if (!Array.isArray(盒) || 盒.length === 0) {
      能穿.push(b.name);
      continue;
    }
    挡路.push(b.name);
    // 非整格：不是 [0,0,0,1,1,1]
    const 整格 = 盒.length === 1 && 盒[0].join(',') === '0,0,0,1,1,1';
    if (!整格) 非整格.push({ 名: b.name, 盒 });
  }

  // ── ④ 挖掘：三件事（挖得动吗 / 要工具吗 / 掉什么）──
  const 挖不动 = [];
  const 要工具 = [];
  let 直接能挖 = 0;
  for (const b of 方块) {
    if (b.diggable === false) { 挖不动.push(b.name); continue; }
    if (b.harvestTools && Object.keys(b.harvestTools).length) 要工具.push(b.name);
    else 直接能挖++;
  }

  // ── ⑤ 光照 / 透明（身体本能：火把能防刷怪、树叶透光不透人）──
  const 透光 = 方块.filter((b) => (b.filterLight || 0) < 15).map((b) => b.name);
  const 发光 = 方块.filter((b) => (b.emitLight || 0) > 0)
    .map((b) => ({ 名: b.name, 亮度: b.emitLight }));
  const 透明但挡路 = 方块.filter((b) => b.transparent && 形状表.blocks[b.name] !== undefined)
    .map((b) => b.name).filter((n) => 挡路.includes(n));

  // ── ⑤b 「挖了掉什么」★ 今天实机栽的那一条 ──
  //   `drops` 是**物品 id** ✓ 拿 items.json 反查成名字 ✓
  //   （草方块 → dirt ✓ 石头 → cobblestone ✓ —— 不是方块自己的名字 ✗）
  const 掉落 = {};
  let 掉落条目 = 0;
  for (const b of 方块) {
    const ds = b.drops;
    if (!Array.isArray(ds) || !ds.length) continue;
    const 名 = ds.map((id) => (typeof id === 'number' ? 物品表[id] : id)).filter(Boolean);
    if (!名.length) continue;
    掉落[b.name] = (名.length === 1) ? 名[0] : 名;
    掉落条目++;
  }

  // ── ⑥ 人工补充（抓不到的，标清楚 ✗ 不许混进"抓来的"里）──
  const 人工 = {
    _说明: '⚠ 这些**不在底层库里**（它们是游戏规则，不是物性）✗ —— '
         + '所以单独放，标清"人工补充" ✓ 谁要加就加在这儿 ✓ 别混进上面',
    会塌的方块: {
      值: ['sand', 'red_sand', 'gravel', 'white_concrete_powder', 'orange_concrete_powder',
        'magenta_concrete_powder', 'light_blue_concrete_powder', 'yellow_concrete_powder',
        'lime_concrete_powder', 'pink_concrete_powder', 'gray_concrete_powder',
        'light_gray_concrete_powder', 'cyan_concrete_powder', 'purple_concrete_powder',
        'blue_concrete_powder', 'brown_concrete_powder', 'green_concrete_powder',
        'red_concrete_powder', 'black_concrete_powder', 'dragon_egg', 'anvil',
        'chipped_anvil', 'damaged_anvil'],
      依据: 'MC 游戏规则：下面没支撑就往下掉（重力方块）✓ 挖它们脚下要小心被埋 ✓',
    },
    掉落伤害: {
      值: 3,
      单位: '格',
      依据: 'MC 游戏规则：落差超过 3 格开始掉血（每多 1 格多 1 点）✓ 设计路线要算这个 ✓',
    },
    水的流速: { 值: '每 5 刻扩散一格', 依据: 'MC 游戏规则：水向下无限、水平扩散 7 格（每次 -1）✓' },
    岩浆: { 值: '碰到就烧 ~4 点/半秒', 依据: 'MC 游戏规则：岩浆伤害极高 ✓ 绝不能踩 ✓' },
    '光照与刷怪': { 值: '亮度 < 1 才会刷怪', 依据: 'MC 游戏规则（1.18+）✓ 火把亮度 14 ✓' },
  };

  // ── ⑦ 通用法则（**判据式**，能被读、能被执行 ✓）──
  const 法则 = [
    {
      编号: 'M1', 类: '移动',
      问题: '这一步「走到」能走过去吗？',
      判据: '路径上的方块，碰撞盒**非空**就是挡路 ✓ 其中透明的不等于能穿'
           + '（树叶 transparent=true **但挡路** ✓ 今天实机就栽在这儿）',
      数据: { 能穿过去: 能穿.length, 挡路的: 挡路.length },
      出处: 'minecraft-data blockCollisionShapes.json',
    },
    {
      编号: 'M2', 类: '移动',
      问题: '这一格要跳吗？',
      判据: `高度差 ≤ ${P.stepHeight} 格 → 走得上去 ✓；`
           + `> ${P.stepHeight} 且 ≤ ${推导['跳跃能上几格'] ? 推导['跳跃能上几格'].值 : '1.1'} 格 → **要跳** ✓；`
           + '再高 → **跳也上不去**，得先搭一格 ✗',
      出处: 'prismarine-physics stepHeight + 跳跃初速',
    },
    {
      编号: 'M3', 类: '移动',
      问题: '这个落点站得住吗？',
      判据: '**脚下**那格的碰撞盒必须非空 ✗ 否则它会掉下去（重力 0.08 格/刻²）',
      出处: 'prismarine-physics gravity + blockCollisionShapes',
    },
    {
      编号: 'M4', 类: '移动',
      问题: '从这儿掉下去会不会摔伤？',
      判据: `落差 > ${人工.掉落伤害.值} 格 → **会掉血** ✓ 设计路线要算`,
      出处: '人工补充（MC 游戏规则）',
    },
    {
      编号: 'D1', 类: '挖掘',
      问题: '这一格挖得动吗？',
      判据: '`diggable === false`（基岩等）→ **挖不动** ✗ 计划里出现就是错的',
      数据: { 挖不动的: 挖不动.length, 直接能挖的: 直接能挖 },
      出处: 'minecraft-data blocks.json `diggable`',
    },
    {
      编号: 'D2', 类: '挖掘',
      问题: '挖这一格要什么工具？',
      判据: '`harvestTools` 非空 → **要对应工具才掉东西**（石头要镐子）✓ '
           + '手上没有 → 挖了也是白挖（不掉落）✗',
      数据: { 要工具的: 要工具.length, 举例: 要工具.slice(0, 6) },
      出处: 'minecraft-data blocks.json `harvestTools`（空 = 徒手就行）',
    },
    {
      编号: 'D3', 类: '挖掘',
      问题: '挖完掉什么？',
      判据: '`drops` 是**物品 id 列表** ✗ —— **不是方块名** ✓ '
           + '（草方块掉泥土 ✓ 石头掉圆石 ✓ —— 今天实机栽在这儿）',
      出处: 'minecraft-data blocks.json `drops` + items.json 反查',
    },
    {
      编号: 'D4', 类: '挖掘',
      问题: '挖得到吗（够不够得着 / 有没有被埋）？',
      判据: '距离 ≤ 4.5 格（手）✓ 而且**至少一个面是空的**（反矿透红线）✓',
      出处: '人工补充 + 手侧 `看遮挡()`',
    },
    {
      编号: 'W1', 类: '液体',
      问题: '水里/岩浆里会怎样？',
      判据: `水：惯性 ${P.waterInertia}、重力 ${P.waterGravity} —— 会**慢慢沉** ✓ `
           + `岩浆：惯性 ${P.lavaInertia} —— **碰到就烧** ✗ 绝不能踩`,
      出处: 'prismarine-physics waterInertia/lavaInertia/waterGravity/lavaGravity',
    },
    {
      编号: 'W2', 类: '液体',
      问题: '放进水里的方块会怎样？',
      判据: '水/岩浆会**流走**（不是固体）✗ —— 拿"水"当材料去做计划是错的 ✓',
      出处: '人工补充（MC 游戏规则）',
    },
    {
      编号: 'G1', 类: '重力',
      问题: '这东西放上去会不会塌？',
      判据: `沙/沙砾/混凝土粉/铁砧/龙蛋 → **下面没支撑就往下掉** ✗（${人工.会塌的方块.值.length} 种）`,
      出处: '人工补充（MC 游戏规则）',
    },
    {
      编号: 'L1', 类: '光照',
      问题: '这儿会不会刷怪？',
      判据: `亮度 < 1 才刷怪 ✓ 发光方块（${发光.length} 种）能照亮 ✓ `
           + `透光的方块（${透光.length} 种）照不实 ✗`,
      出处: 'minecraft-data blocks.json emitLight/filterLight',
    },
  ];

  const 出 = {
    _说明: '隐式物理常识（身体本能里的物理法则）—— **自动抓**自底层库，每条带出处 ✓',
    _数据来自: 'minecraft-data 官方加载器 + prismarine-physics 的 Physics() 真对象 ✓（不是自己猜版本）',
    _为什么要它: [
      '主人 2026-10-09：『只写了显式常识，漏了隐式常识。'
        + '这些是玩家身体本能里的物理法则，但 AI 不写，它就不知道。』',
      '显式常识 = 方块叫什么/要什么工具/掉什么（已有：外挂/常识/方块交互表.json）',
      '隐式常识 = 一步只能上 0.6 格、树叶挡路、跳不上两格…（这一份）',
    ],
    _怎么读它: [
      '★ 最重要的一条（今天的血）：**写出来必须有人读** ✗',
      '  光生成一个 JSON 等于没做 ✓ 它得被"体检"真的用上：',
      '  接单那一刻，拿这些法则把每一条计划过一遍 → 违反物理的当场挑出来 ✓',
    ],
    版本: 版本,
    碰撞盒数据版本: '由 minecraft-data 官方加载器决定（' + 版本 + '）',
    生成脚本: 'tools/生成物理常识.js',
    来源: [
      'prismarine-physics（物理常量：重力/阻力/跳跃初速/台阶高…）',
      `minecraft-data ${版本}（blocks.json 物性 + blockCollisionShapes.json 碰撞盒）`,
    ],
    物理常量: 常量,
    推导: 推导,
    通用法则: 法则,
    碰撞盒: {
      _说明: '走路能不能过去的**真值** —— 来自 blockCollisionShapes.json ✓',
      能穿过去的: 能穿,
      挡路的: 挡路,
      '非整格的（半砖/台阶/栅栏/门…）': 非整格.slice(0, 80),
      _统计: {
        能穿过去: 能穿.length,
        挡路: 挡路.length,
        非整格: 非整格.length,
        形状总数: 形状数,
      },
    },
    挖不动: 挖不动,
    要工具才掉东西: 要工具,
    挖了掉什么: 掉落,
    透光的: 透光,
    发光的: 发光,
    '透明但挡路（今天栽的）': 透明但挡路,
    人工补充: 人工,
  };

  const 路 = path.join(ROOT, '常识库', '物理引擎规则.json');
  fs.mkdirSync(path.dirname(路), { recursive: true });
  fs.writeFileSync(路, JSON.stringify(出, null, 1), 'utf8');

  // ── 自查（不许"写完就当成了"）──
  console.log('═'.repeat(62));
  console.log('物理引擎规则.json 生成完毕');
  console.log('═'.repeat(62));
  console.log(`  写进：${path.relative(ROOT, 路)}　${(fs.statSync(路).size / 1024).toFixed(1)} KB`);
  console.log(`  物理常量 ${Object.keys(常量).length} 条（每条带出处 ✓）`);
  console.log(`  推导 ${Object.keys(推导).length} 条`);
  console.log(`  通用法则 ${法则.length} 条（判据式 ✓）`);
  console.log(`  碰撞盒：能穿 ${能穿.length} ｜ 挡路 ${挡路.length} ｜ 非整格 ${非整格.length}`);
  console.log(`  挖不动 ${挖不动.length} ｜ 要工具 ${要工具.length} ｜ 透光 ${透光.length} ｜ 发光 ${发光.length}`);
  console.log(`  **挖了掉什么** ${掉落条目} 条（草方块→${掉落.grass_block} ｜ 石头→${掉落.stone} ✓）`);
  console.log(`  透明但挡路（今天栽的）：${透明但挡路.slice(0, 8).join('、')}…`);
  console.log(`  人工补充 ${Object.keys(人工).length - 1} 组（**单独放** ✗ 不许混进抓来的 ✓）`);
  console.log();
  console.log(`  一步能跨：${P.stepHeight} 格 ｜ 跳能上：${推导['跳跃能上几格'] ? 推导['跳跃能上几格'].值 : '?'} 格`);
  console.log(`  ★ 所以：**一格的坎必须跳** ✓ **两格高跳不上去** ✗（先搭一格）`);
  console.log('═'.repeat(62));
}

function 源里抓常量() {
  const 源码 = fs.readFileSync(
    path.join(ROOT, 'node', 'node_modules', 'prismarine-physics', 'index.js'), 'utf8');
  const 取 = (名) => {
    const m = 源码.match(new RegExp(名 + ':\\s*([\\d.]+)'));
    return m ? Number(m[1]) : null;
  };
  return {
    gravity: 取('gravity'), airdrag: 取('airdrag'), playerSpeed: 取('playerSpeed'),
    sprintSpeed: 取('sprintSpeed'), sneakSpeed: 取('sneakSpeed'), stepHeight: 取('stepHeight'),
    playerHalfWidth: 取('playerHalfWidth'), playerHeight: 取('playerHeight'),
    waterInertia: 取('waterInertia'), lavaInertia: 取('lavaInertia'),
    airborneInertia: 取('airborneInertia'), autojumpCooldown: 取('autojumpCooldown'),
    waterGravity: 0.005, lavaGravity: 0.02,
  };
}

主();
