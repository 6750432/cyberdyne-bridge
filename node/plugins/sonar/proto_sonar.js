#!/usr/bin/env node
'use strict';
/**
 * 声呐外挂 · 手侧探针草案（K 系列 K1）
 *
 * 定位
 *   挂在 mineflayer 机器人上，把三个原生声音事件收进来，做「自听过滤 → 去重 →
 *   分级 → 方位/距离」四道加工，然后按「要命声即刻、其余合并」上报给主链。
 *   与 Python 核心（声呐.py）口径逐字对齐——同一份事件流应得同一个回放指纹。
 *
 * mineflayer 原生事件（不用改框架）
 *   soundEffectHeard(soundName, position, volume, pitch)          具名音效
 *   hardcodedSoundEffectHeard(soundId, soundCategory, pos, vol, pitch)  硬编码音效
 *   noteHeard(block, instrument, pitch)                            音符盒
 *   position 为声源世界坐标（协议 1/8 格精度）
 *
 * 本文件可跑：
 *   node proto_sonar.js --demo      # 假事件流自测（不连服务器）
 *   node proto_sonar.js --finger    # 只打回放指纹（与 Python 对答案用）
 *
 * 真机用法（回宿舍后）
 *   const { SonarProbe } = require('./proto_sonar.js');
 *   const 探针 = new SonarProbe({ pos: [0,64,0], yaw: 0 });
 *   探针.attach(bot);                       // 挂三个事件
 *   bot.on('spawn', () => 探针.syncFromBot(bot));   // 同步站位/朝向
 *   探针.on('urgent', f => { /* 反射档即刻处理 * / });
 *   探针.on('frame',  f => { /* 状态帧低频推送 * / });
 *
 * 待办（真机实测项，标记 TODO 的地方）
 *   1. bot.entity.yaw 的弧度 ↔ 度数换算方向（先按「yaw 增大 = 顺时针」假设，需实测校）
 *   2. hardcodedSoundEffectHeard 的 soundId → 音名的映射表（可从 minecraft-data 补）
 *   3. 音量/音高换算与服务器双路合并（同一声可能两条事件）
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

// ── 口径（与雷达 / 声呐.py 同一套）──
const 方位名 = ['前', '左前', '左', '左后', '后', '右后', '右', '右前'];
const 环名 = ['0-10', '10-20', '20-30', '30-40', '40-50'];
const 自听前缀 = ['entity.player.', 'entity.item.', 'item.'];
const 自听后缀 = ['.step', '.break', '.place', '.hit', '.fall', '.dig'];

function 找速查() {
  const 这里 = __dirname;
  const 候选 = ['声音速查_1.21.1.json', 'sounds_1.21.1.json'];
  for (const n of 候选) {
    const p = path.join(这里, n);
    if (fs.existsSync(p)) return p;
    const p2 = path.join(这里, '..', n);
    if (fs.existsSync(p2)) return p2;
  }
  return null;
}

let _表 = null;
function 载速查() {
  if (_表 === null) {
    const p = 找速查();
    if (!p) { console.warn('[声呐] 找不到声音速查表，全部按情报处理'); _表 = {}; }
    else _表 = JSON.parse(fs.readFileSync(p, 'utf8')).表;
  }
  return _表;
}
function 查(名) { return 载速查()[名] || null; }
function 分级(名) { const t = 查(名); return t ? t.档 : '情报'; }
function 威胁(名) { const t = 查(名); return t ? t.威胁 : 1; }

/**
 * 坐标归一化 —— 关键容错。
 * mineflayer 事件传的是 Vec3 对象（{x,y,z}，且 .length 是方法不是数字），
 * 不是数组；直接取 坐标[0] 会拿到 undefined → NaN → 方位判定崩。
 * 这里统一三种形态：[x,y,z] / {x,y,z} / 空（退回站位）。
 */
function 归座标(c, 兜底) {
  let 出;
  if (c === null || c === undefined) {
    出 = [Number(兜底[0]), Number(兜底[1]), Number(兜底[2])];
  } else if (Array.isArray(c)) {
    出 = [Number(c[0]), Number(c[1]), Number(c[2])];
  } else if (typeof c.x === 'number') {
    出 = [Number(c.x), Number(c.y), Number(c.z)];
  } else {
    出 = [Number(c[0]), Number(c[1]), Number(c[2])];
  }
  if (出.some(Number.isNaN)) 出 = [Number(兜底[0]), Number(兜底[1]), Number(兜底[2])];
  return 出;
}

class SonarProbe {
  constructor(opts = {}) {
    this.站位 = opts.站位 || [0, 0, 0];
    this.朝向 = ((opts.朝向 || 0) % 360 + 360) % 360;
    this.自听半径 = opts.自听半径 ?? 3.0;
    this.去重窗格 = opts.去重窗格 ?? 2.0;
    this.去重窗刻 = opts.去重窗刻 ?? 2;
    this.警戒刻 = opts.警戒刻 ?? 6;

    this.刻 = 0;
    this.事件 = [];
    this.警戒 = new Map();
    this.指纹 = crypto.createHash('sha1');
    this.统计 = { 入表: 0, 自听过滤: 0, 忽略: 0, 去重合并: 0 };
    this._挂 = null;
    this._监听 = { urgent: [], frame: [] };
  }

  // ── 真机挂载 ──
  attach(bot) {
    this._挂 = bot;
    bot.on('soundEffectHeard', (名, 坐标, 音量, 音高) => {
      const f = this.听(名, 坐标, 音量, 音高);
      if (f) this._推(f);
    });
    bot.on('hardcodedSoundEffectHeard', (_id, _类, 坐标, 音量, 音高) => {
      // TODO: id → 音名映射（minecraft-data 的 sounds.json 可补全）
      // 暂时用占位名，正式版换成映射结果
      const f = this.听('hardcoded.' + _id, 坐标, 音量, 音高);
      if (f) this._推(f);
    });
    bot.on('noteHeard', (_块, 乐器, 音高) => {
      const 坐标 = _块 && _块.position ? [_块.position.x, _块.position.y, _块.position.z] : this.站位;
      const f = this.听('block.note_block.' + 乐器, 坐标, 1.0, 音高);
      if (f) this._推(f);
    });
    bot.on('spawn', () => this.syncFromBot(bot));
    return this;
  }

  syncFromBot(bot) {
    if (bot && bot.entity && bot.entity.position) {
      const p = bot.entity.position;
      this.站位 = [p.x, p.y, p.z];
      // TODO: 实测确认 yaw 方向约定（MC yaw 弧度，-180..180，通常 +y 为南）
      if (typeof bot.entity.yaw === 'number') {
        this.朝向 = ((bot.entity.yaw * 180 / Math.PI) % 360 + 360) % 360;
      }
    }
    return this;
  }

  on(事件, 回调) { (this._监听[事件] || []).push(回调); return this; }
  _推(f) {
    if (f.档 === '反射') this._监听.urgent.forEach(cb => cb(f));
  }

  // ── 加工 ──
  方位距离(坐标, 站位, 朝向) {
    const [px, , pz] = 站位 || this.站位;
    const θ = (朝向 === undefined ? this.朝向 : 朝向) * Math.PI / 180;
    const dx = 坐标[0] - px, dz = 坐标[2] - pz;
    const c = Math.cos(θ), s = Math.sin(θ);
    const f = dx * c - dz * s;
    const l = -dx * s - dz * c;
    const φ = ((Math.atan2(l, f) * 180 / Math.PI) % 360 + 360) % 360;
    const k = Math.floor(((φ + 22.5) % 360) / 45);
    const d = Math.hypot(dx, dz);
    return { 方位: 方位名[k], 环: 环名[Math.min(Math.floor(d / 10), 4)], 距离: Math.round(d * 100) / 100 };
  }

  _是自听(名, 坐标) {
    const [px, py, pz] = this.站位;
    const d3 = Math.sqrt((坐标[0] - px) ** 2 + (坐标[1] - py) ** 2 + (坐标[2] - pz) ** 2);
    if (d3 >= this.自听半径) return false;
    if (自听前缀.some(x => 名.startsWith(x))) return true;
    if (名.startsWith('block.') && 自听后缀.some(x => 名.endsWith(x))) return true;
    return false;
  }

  听(名, 坐标, 音量 = 1.0, 音高 = 1.0, 时刻 = null) {
    坐标 = 归座标(坐标, this.站位);
    const 刻 = 时刻 === null ? ++this.刻 : 时刻;
    if (时刻 !== null) this.刻 = Math.max(this.刻, 刻);

    if (this._是自听(名, 坐标)) { this.统计.自听过滤++; return null; }

    const 档 = 分级(名);
    if (档 === '忽略') { this.统计.忽略++; return null; }

    const { 方位, 环, 距离 } = this.方位距离(坐标);
    const 条 = 查(名) || {};

    for (let i = this.事件.length - 1; i >= Math.max(0, this.事件.length - 12); i--) {
      const e = this.事件[i];
      if (e.音名 === 名 && e.方位 === 方位 && e.环 === 环 && Math.abs(刻 - e.时刻) <= this.去重窗刻) {
        e.次数++; e.时刻 = 刻; e.音量 = 音量; this.统计.去重合并++;
        this._刷警戒(名, 档, 方位, 环, 距离, 坐标, 刻);
        return e;
      }
    }

    const 备注 = this._拼备注(条, 方位, 环, 距离, 音量);
    const f = {
      类型: '声呐·' + 档, 坐标: [坐标[0], 坐标[1], 坐标[2]], 来源: '声呐', 备注,
      音名: 名, 档, 威胁: 条.威胁 ?? 1, 方位, 环, 距离, 时刻: 刻, 次数: 1, 音量,
    };
    this.事件.push(f);
    this.统计.入表++;
    this.指纹.update([名, 方位, 环, 档, String(刻)].join('|') + '\n', 'utf8');
    this._刷警戒(名, 档, 方位, 环, 距离, 坐标, 刻);
    return f;
  }

  _拼备注(条, 方位, 环, 距离, 音量) {
    const 段 = [`${条.人话 || '未知声音'} · ${方位} ${环} 格 · 距 ${距离}`];
    if (条.威胁) 段.push(`威胁 ${条.威胁}`);
    if (Number(音量) > 1.0) 段.push('响');
    if (条.备注) 段.push(条.备注);
    return 段.join(' ｜ ');
  }

  _刷警戒(名, 档, 方位, 环, 距离, 坐标, 刻) {
    if (档 !== '警惕') return;
    this.警戒.set(名, { 到期: 刻 + this.警戒刻, 方位, 环, 距离, 坐标: [坐标[0], 坐标[1], 坐标[2]], 档 });
  }

  推进(刻数 = 1) { this.刻 += 刻数; return this.刻; }

  警戒态() {
    const 出 = [];
    for (const [名, v] of [...this.警戒.entries()]) {
      const 剩 = v.到期 - this.刻;
      if (剩 <= 0) { this.警戒.delete(名); continue; }
      const 条 = 查(名) || {};
      出.push({ 音名: 名, 类型: '警戒·' + (条.人话 || 名), 方位: v.方位, 环: v.环, 距离: v.距离, 剩余刻: 剩, 备注: 条.备注 || '' });
    }
    return 出.sort((a, b) => b.剩余刻 - a.剩余刻);
  }

  状态帧() {
    const 取档 = d => this.事件.filter(e => e.档 === d).slice(-6);
    return { 刻度: this.刻, 警戒: this.警戒态(), 反射: 取档('反射'), 警惕: 取档('警惕'), 情报: 取档('情报'), 统计: this.统计, 指纹: this.指纹.digest('hex').slice(0, 16) };
  }

  指纹值() { return this.指纹.digest('hex').slice(0, 16); }
}

// ── 自测 / 对答案 ──
function 基准事件流() {
  const p = new SonarProbe({ 站位: [0, 64, 0], 朝向: 0 });
  p.听('entity.creeper.primed', [13, 64, -7]);
  p.听('entity.generic.explode', [6, 64, 4], 2.0);
  p.听('block.stone.break', [28, 64, -10]);
  p.听('entity.player.attack.strong', [0, 64, 0]);   // 自听 → 过滤
  p.听('block.gravel.step', [30, 64, 12]);
  p.听('entity.zombie.ambient', [-9, 64, 14]);
  return p;
}

function demo() {
  console.log('── 手侧探针 · 假事件流自测 ──');
  const p = new SonarProbe({ 站位: [0, 64, 0], 朝向: 0 });
  const 流 = [
    ['entity.creeper.primed', [13, 64, -7]],
    ['entity.generic.explode', [6, 64, 4], 2.0],
    ['block.stone.break', [28, 64, -10]],
    ['entity.player.attack.strong', [0, 64, 0]],
    ['block.gravel.step', [30, 64, 12]],
    ['entity.zombie.ambient', [-9, 64, 14]],
  ];
  for (const [名, 坐标, 音量] of 流) {
    const f = p.听(名, 坐标, 音量 === undefined ? 1.0 : 音量);
    console.log(f ? `  [${String(f.时刻).padStart(3)}] ${f.类型}：${f.备注}` : `  (过滤) ${名}`);
  }
  console.log('\n── 警戒态 ──');
  p.警戒态().forEach(w => console.log('  ', JSON.stringify(w, null, 0)));
  console.log('\n── 统计 ──', JSON.stringify(p.统计));
  console.log('回放指纹：', p.指纹值());
  console.log('（Python 核心基准指纹应为 9b665f3496c078c1）');
}

if (require.main === module) {
  const a = process.argv.slice(2);
  if (a.includes('--finger')) {
    console.log(基准事件流().指纹值());
  } else if (a.includes('--demo')) {
    demo();
  } else {
    console.log('用法：node proto_sonar.js --demo | --finger');
  }
}

module.exports = { SonarProbe, 查, 分级, 威胁, 归座标, 方位名, 环名 };
