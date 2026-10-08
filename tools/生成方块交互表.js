/* 生成方块交互表.js —— 把 MC 的物理常识**查出来**，不猜。
 *
 * 主人 2026-10-08 晚 的指令原话：「物理常识是查出来的，不是猜出来的！」
 * 我们今天在草丛/泥土上栽的跟头，根子就是**在代码里硬造 MC 的规则** ✗
 *   （`石头系 = /(_ore|stone|...)/` 这种正则 —— 猜的，于是 grass_block 被要求镐子）
 *
 * 数据来源：**本机已装的 `minecraft-data`**（mineflayer 的依赖，1.21.1 官方数据）
 *   · `blocksByName[x].hardness`     方块硬度（0 = 一碰就碎）
 *   · `blocksByName[x].harvestTools` 这个方块**要什么工具才掉东西**（空 = 徒手就掉 ✓）
 *   · `blocksByName[x].material`     `mineable/pickaxe` 这类"最快用什么"（只影响速度 ✓）
 *
 * 产出：外挂/常识/方块交互表.json（常识树的**唯一数据源** ✓ 以后不许再在代码里写 if-else）
 *
 * 跑法：~/.local/node/bin/node tools/生成方块交互表.js
 */

const fs = require('fs');
const path = require('path');

const 根 = path.resolve(__dirname, '..');
const 出 = path.join(根, '外挂', '常识', '方块交互表.json');

const mcData = require(path.join(根, 'node', 'node_modules', 'minecraft-data'))('1.21.1');

/* 工具家族：harvestTools 给的是**物品 id**，翻成"要哪一类工具" */
const 家族 = [['_pickaxe', '镐子'], ['_axe', '斧头'], ['_shovel', '铲子'],
              ['_hoe', '锄头'], ['_sword', '剑'], ['_shears', '剪刀']];
function 认工具(物品名) {
  for (const [尾, 中文] of 家族) if (物品名.endsWith(尾)) return 中文;
  return 物品名;
}

/* 需要工具才掉东西的方块：把 id 集合翻成中文类别 */
const 需要 = {};
for (const 方块 of Object.values(mcData.blocksByName)) {
  const 集 = 方块.harvestTools;
  if (!集) continue;
  const 类 = new Set();
  for (const id of Object.keys(集)) {
    const 物 = mcData.items[Number(id)];
    if (物) 类.add(认工具(物.name));
  }
  if (类.size) 需要[方块.name] = [...类].sort();
}

/* 只保留"能挖"的方块 —— 空气/水/基岩这些没意义 */
const 表 = {};
const 统计 = { 方块: 0, 徒手: 0, 要工具: 0, 硬度0: 0 };
for (const 方块 of Object.values(mcData.blocksByName)) {
  if (!方块.diggable) continue;
  const 硬 = typeof 方块.hardness === 'number' ? 方块.hardness : null;
  const 要 = 需要[方块.name] || [];
  表[方块.name] = {
    硬: 硬,
    // 空数组 = **徒手就能挖且掉东西** ✓（这正是 grass_block 的真相）
    要: 要,
    类: (方块.material || '').replace(/^mineable\//, '') || null,
  };
  统计.方块++;
  if (要.length === 0) 统计.徒手++; else 统计.要工具++;
  if (硬 === 0) 统计.硬度0++;
}

const 出表 = {
  _来源: 'minecraft-data@本机 node_modules（mineflayer 依赖）',
  _版本: mcData.version.minecraftVersion,
  _生成: 'tools/生成方块交互表.js',
  _怎么读: '某方块：{ 硬: 硬度, 要: [需要什么工具才掉东西]（空=徒手就掉）, 类: 最快用什么 }',
  _样本: {
    grass_block: 表.grass_block, stone: 表.stone, oak_log: 表.oak_log,
    dirt: 表.dirt, sand: 表.sand, gravel: 表.gravel, cobblestone: 表.cobblestone,
  },
  方块: 表,
};
fs.mkdirSync(path.dirname(出), { recursive: true });
fs.writeFileSync(出, JSON.stringify(出表, null, 1), 'utf-8');

console.log(`✔ 写出 ${path.relative(根, 出)}`);
console.log(`  方块 ${统计.方块} ｜ 徒手就能挖 ${统计.徒手} ｜ 要工具才掉 ${统计.要工具} ｜ 硬度0 ${统计.硬度0}`);
for (const n of ['grass_block', 'dirt', 'sand', 'gravel', 'stone', 'cobblestone',
                 'oak_log', 'oak_leaves', 'coal_ore', 'iron_ore', 'crafting_table']) {
  const r = 表[n];
  console.log(`  ${n.padEnd(16)} 硬=${String(r && r.硬).padEnd(4)} 要=${(r && r.要.length) ? r.要.join('/') : '（徒手 ✓）'}`);
}
