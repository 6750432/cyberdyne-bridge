'use strict';
/**
 * Cyberdyne-Bridge · 可选寻路外挂（proto_pathfinder.js）
 *
 * 这是「主链不动、外挂仓库」这句话的字面实现：
 *
 *   · 它住在自己的目录 node/plugins/pathfinder/ 里，有自己的 package.json
 *     和自己的 node_modules。主链的 package.json 一个字都没改。
 *   · 主链开机时 try 一下 require。目录不在、依赖没装、加载抛异常 ——
 *     一律当"没装"处理，goto 自动回退成「原地站着」，主链一行都不受影响。
 *   · 它只被主链调用，自己不开 socket、不碰状态推送、不抢定时器。
 *
 * 依赖：mineflayer-pathfinder（只装在这个目录里）
 */

let 缓存 = null;
let 装过插件的bot = null;
let 上次被停 = false;   // 见 前往() 里的说明：上一次是不是被 stop 掉的

function 取依赖() {
  if (!缓存) 缓存 = require('mineflayer-pathfinder');
  return 缓存;
}

module.exports = {
  名字: 'mineflayer-pathfinder',

  /** 主链用它来判断"这个插件到底能不能用"。加载不了就返回 false，不抛。 */
  可用() {
    try {
      const d = 取依赖();
      return !!(d && d.pathfinder && d.goals && d.Movements);
    } catch (e) {
      return false;
    }
  },

  /**
   * 前往一个坐标。返回 Promise：
   *   成功 → { dist }   （离目标还有多远）
   *   失败 → reject     （超时、或者被 stop 掉）
   */
  前往(bot, 坐标, 选项) {
    const { pathfinder, Movements, goals } = 取依赖();
    if (!bot || !bot.entity) return Promise.reject(new Error('还没进世界'));

    if (装过插件的bot !== bot) {
      bot.loadPlugin(pathfinder);
      装过插件的bot = bot;
    }

    const 移动 = new Movements(bot);
    // M2 只要求"走过去"，不要求"改造世界"：
    // 不许挖、不许搭柱、不许跑酷，最多允许从 4 格高的地方跳下去。
    移动.canDig = false;
    移动.allow1by1towers = false;
    移动.allowParkour = false;
    移动.allowSprinting = true;
    移动.maxDropDown = 4;
    bot.pathfinder.setMovements(移动);

    const 容差 = (选项 && 选项.near) || 2;          // 走到 ±2 格就算到了
    const 超时 = (选项 && 选项.timeout_ms) || 30000;
    const 目标 = new goals.GoalNear(坐标[0], 坐标[1], 坐标[2], 容差);

    // ⚠ 2026-10-01 验收抓到的 bug：`stop()` 会让 goto 的承诺**正常兑现**，
    // 于是「半路被新命令打断」被当成了「到地方了」—— 日志里刷了一屏
    // 「到地方了。离目标还有 0.0 格」。半路被停就该老实说被停。
    // 做法：停的时候留个标记，**下一次**前往接手时读走它（就是它把上一次停掉的）。
    const 被停 = 上次被停;
    上次被停 = false;
    let 表 = null;
    const 限时 = new Promise((_, rj) => {
      表 = setTimeout(() => {
        try { bot.pathfinder.stop(); } catch (e) { /* 无所谓 */ }
        rj(new Error(`走了 ${Math.round(超时 / 1000)} 秒还没到，放弃`));
      }, 超时);
    });
    return Promise.race([bot.pathfinder.goto(目标), 限时])
      .then(() => {
        if (被停) throw new Error('这条路被新命令打断了，重新算');
        const p = bot.entity.position;
        return { dist: Number(Math.hypot(p.x - 坐标[0], p.z - 坐标[2]).toFixed(2)) };
      })
      .finally(() => { if (表) clearTimeout(表); });
  },

  /** 让路：主链要自己做动作时必须先把它停下，不然两条腿会互相打架。 */
  停(bot) {
    上次被停 = true;
    try { if (bot && bot.pathfinder) bot.pathfinder.stop(); } catch (e) { /* 无所谓 */ }
  },
};
