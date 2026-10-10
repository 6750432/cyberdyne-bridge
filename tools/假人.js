#!/usr/bin/env node
/**
 * M4b 测试用「假人」—— 第二个无头 mineflayer 客户端，专门给小家伙当靶子。
 *
 * 为什么需要它：验收「隔墙追人」要有个人站在墙那边。让主人自己站过去当然也行，
 * 但那样每次验收都得喊人；假人一秒钟就能摆好，而且是**可重复**的。
 *
 * 它只做一件事：连进来、站着不动（跟着 RCON 的 tp 走）。
 * 别的一概不做 —— 测试工具就该哑巴一点。
 *
 * 用法：
 *   NODE_PATH=node/node_modules node tools/假人.js PreyBot
 *   （主机/端口/版本都从 config.json 读，和手用的是同一份）
 */
'use strict';

const fs = require('fs');
const path = require('path');
const mineflayer = require('mineflayer');

const ROOT = path.resolve(__dirname, '..');
const cfg = JSON.parse(fs.readFileSync(path.join(ROOT, 'config.json'), 'utf8'));
const 名字 = process.argv[2] || 'PreyBot';
// M4c 验收用：`--打 <目标名>` → 它主动挥拳（给反射层的"挨打应战"当触发器）。
// 默认不开：测试工具该哑巴的时候就得哑巴。
const 打模式 = process.argv.includes('--打');
const 打谁 = 打模式 ? (process.argv[process.argv.indexOf('--打') + 1] || cfg.bot_name) : null;

const bot = mineflayer.createBot({
  host: cfg.mc_host,
  port: cfg.mc_port,
  username: 名字,
  version: cfg.mc_version,
  auth: 'offline',
  hideErrors: false,
});

bot.once('spawn', () => {
  console.log(`[假人] ${名字} 站进去了，坐标 ${bot.entity.position}`);
});

bot.on('death', () => {
  console.log(`[假人] ${名字} 倒下了，1.5 秒后自动重生。`);
  setTimeout(() => { try { bot.respawn(); } catch (e) {} }, 1500);
});

bot.on('kicked', (r) => console.log(`[假人] 被踢：${r}`));
bot.on('error', (e) => console.log(`[假人] 出错：${e.message}`));
bot.on('end', (r) => { console.log(`[假人] 掉线：${r}`); process.exit(0); });

// 站着不动：把控制状态焊死
setInterval(() => {
  for (const c of ['forward', 'back', 'left', 'right', 'jump', 'sprint', 'sneak']) {
    try { bot.setControlState(c, false); } catch (e) {}
  }
}, 1000);

// 打人模式：3 格以内就挥一拳（节奏 600ms，跟剑的蓄力上限对齐）
if (打模式) {
  console.log(`[假人] 打人模式：目标「${打谁}」`);
  setInterval(() => {
    try {
      if (!bot.entity) return;
      let 目标 = null, 最近 = 3.0;
      for (const id in bot.entities) {
        const e = bot.entities[id];
        if (!e || !e.position || e === bot.entity) continue;
        const 名 = e.username || e.name || e.displayName || e.type;
        if (名 !== 打谁) continue;
        const d = e.position.distanceTo(bot.entity.position);
        if (d < 最近) { 最近 = d; 目标 = e; }
      }
      if (目标) {
        bot.lookAt(目标.position.offset(0, (目标.height || 1.8) * 0.85, 0), true).catch(() => {});
        bot.attack(目标);
      }
    } catch (e) { /* 打不到就算了 */ }
  }, 600);
}
