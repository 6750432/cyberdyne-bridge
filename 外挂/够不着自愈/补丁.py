#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""够不着自愈车厢 —— 手说「够不着」，就替它**走过去再来**，而不是傻站在重试。

English: Turns a hand-side "out of reach" refusal into a next step. The hand already
returns machine-readable fields (够不着 / 距); this carriage reads them, inserts a
`走到` step right before the current one, resets that step's retry counters, and lets
the main chain's own loop do the walking and the retrying.

中文
====
主人 2026-10-09 点出来的通用法则
--------------------------------
**在手的交互距离都是 4.5 格** ✓ —— 挖、放、用、熔炉、箱子，全都一样。

手侧已经把这条法则做成了尺子（`够得着吗()` ✓ 只实现这一处 ✓），
放东西之前先量一把；超了就给回执带上**机器可读**的字段：

    { ok: false, 够不着: true, 距: 5.2, 取消: '够不着',
      why: '那地方在 5.2 格外，够不着（手最多伸 4.5 格）—— 得先走近点' }

⭐ 可**没有任何代码读它** ✗ —— 跟「障碍自愈」当初那个病一模一样：
   手把答案说出来了，脑那边一个字没接 ✓
   于是主链只会「1 秒后退避重试」→ 原地再够一次 → 再被拒 → 试满 3 次判整任务失败 ✗

这节车厢做的就是那一环：**把"理由"变成"下一步"** ✓
  · 包 `叙事者.看回执` —— 回执里带 `够不着` 时 →
  · **插一步「走到落点旁边」到当前那一步之前** ✓（别动主链一个字 ✓）
  · 把当前步的重试计数清零 → 主链自己的循环会走完、再放一次 ✓

为什么不另起一条短活（跟「障碍自愈」那样）✗
------------------------------------------
「障碍自愈」挖的是**别人的**东西（挡路的那块），跟当前任务无关，
所以派一条独立短活、挖完再回来是对的 ✓
可「够不着」是**当前这一步本身**没做成 —— 派新活会把整条任务顶掉 ✗
（`任务栈.接()` 是**替换**语义，实打实会丢掉进度 ✗）
所以这里走「就地插一步」：任务还是那条任务，只是**先走几步再放** ✓

规矩
====
1. **只认 `够不着: true`** ✓ —— 别的失败理由一个字都不碰（不许瞎插步 ✗）
2. **只插在"发得出去的那个动作"前面** ✓ —— 回执的 cmd 必须对得上当前那一步
   （`place→放` / `use→放` / `furnace_put→熔炉放料` …✓），对不上就什么都不做 ✓
3. **同一格 2 秒内只插一次** ✓（手侧每 200ms 回一次同样的拒绝 ✗ 不去重会疯 ✗）
4. **一条任务最多插 3 次** ✓ —— 插完还是够不着，就把话语权交回主链判失败 ✓
   （绝不自己造死循环 ✗）
5. **脚底下拿不准就不插** ✗ —— 候选位必须在雷达里**看得见**（本格空气 + 下面有地）✓
   看不见就**照实说**、交回主链 ✓（宁可主链失败，也不要它一头撞进墙里 ✗）
6. 卸下一字不差还原 ✓
"""

import time
import weakref

_日志 = None
# ★★★ 2026-10-09：账本从 `{id(类): 原函数}` 换成**按类对象本身记** ✗
#   踩到的坑：`id()` 会被**复用** —— 上一个类被回收后，新类的 id 可能撞上同号 ✓
#   于是新类一进来就以为"我已经在岗了" → **拒绝装** ✗
#   表现就是"那道闸时灵时不灵"（用例 I1/A3 一起把它抓出来了 ✓）
#   规矩：**存身份，不存号码** ✓（WeakKeyDictionary 还顺手不拦住类的回收 ✓）
_原件 = weakref.WeakKeyDictionary()   # 类 -> {"回执": 原函数} / {"下发": 原函数}
_上次 = {}          # (cmd, 坐标) -> 上次插步的时刻（去重用）
_插了几次 = {}      # 任务 id -> 插了几次
_共插过 = 0
_绕了几次 = 0        # "挖还是绕"判成绕的次数（只为了报数好看 ✓）

空气名 = ("air", "cave_air", "void_air")


def _说(文):
    if _日志:
        try:
            _日志(文)
            return
        except Exception:
            pass
    print(文, flush=True)


def _活实例(bridge, 类名):
    """拿主链那个**活着的**实例（跟「障碍自愈」同一套写法 ✓）。"""
    try:
        类 = getattr(bridge, 类名, None)
        活 = list(getattr(类, "车钩活着的实例", []) or [])
        return 活[-1] if 活 else None
    except Exception:
        return None


# ── 哪个 cmd 的回执，该插到哪一步前面 ──
#   左：手侧回执的 cmd ✓  右：任务栈里那一步的「动作」✓
动作对得上 = {
    "place": ("放",),
    "use": ("放",),
    "furnace_put": ("熔炉放料",),
    "furnace_take": ("熔炉取成品",),
    "chest_take": ("拾",),
    "chest_put": ("放",),
}


def _数(值):
    try:
        return float(值)
    except Exception:
        return None


def _键(坐标):
    try:
        return (int(round(float(坐标[0]))), int(round(float(坐标[1]))),
                int(round(float(坐标[2]))))
    except Exception:
        return None


def _同(a, b, 容=0.5):
    try:
        return all(abs(float(a[i]) - float(b[i])) < 容 for i in range(3))
    except Exception:
        return False


def _当前步(栈):
    """返回 (任务, 第几步, 那一步)；任务没在跑就返回 (None, None, None)。"""
    任 = getattr(栈, "任务", None)
    if not isinstance(任, dict) or 任.get("状态") != "跑":
        return None, None, None
    步骤 = 任.get("步骤")
    if not isinstance(步骤, list) or not 步骤:
        return None, None, None
    try:
        第 = int(任.get("第几步") or 0)
    except Exception:
        return None, None, None
    if not (0 <= 第 < len(步骤)) or not isinstance(步骤[第], dict):
        return None, None, None
    return 任, 第, 步骤[第]


def _雷达表(状态):
    """{坐标: 方块名} —— 雷达这一拍看见了什么 ✓"""
    出 = {}
    for 条 in ((状态 or {}).get("blocks") or []):
        if not isinstance(条, dict):
            continue
        p = 条.get("p")
        if isinstance(p, (list, tuple)) and len(p) >= 3:
            try:
                k = (int(p[0] // 1), int(p[1] // 1), int(p[2] // 1))
            except Exception:
                continue
            出[k] = str(条.get("name") or "")
    return 出


def _是空的(名):
    return 名 is None or str(名) in 空气名


def _落脚点(状态, 落点):
    """从雷达里挑一个「站在那儿够得着落点」的位子。

    ★ 规矩（拿血换的）：**脚底下拿不准就不插** ✗
      候选位必须在雷达里**看得见**：本格是空气 ✓ 而且**下面那一格有地** ✓
      （不猜、不赌 —— 宁可交回主链失败，也不要它一头撞进墙里 ✗）
    """
    我 = (状态 or {}).get("pos")
    表 = _雷达表(状态)
    if not (isinstance(我, (list, tuple)) and len(我) >= 3):
        return None, "这一拍没拿到我自己的位置"
    我 = [float(我[0]), float(我[1]), float(我[2])]
    落 = [float(落点[0]), float(落点[1]), float(落点[2])]
    y = int(落[1] // 1)
    最好, 最好分 = None, None
    没读数 = 0
    for dx in (-1, 0, 1):
        for dz in (-1, 0, 1):
            if not dx and not dz:
                continue                     # 不用走过去的地方不算
            x = int(落[0] // 1) + dx
            z = int(落[2] // 1) + dz
            本 = 表.get((x, y, z), "__没读数__")
            if 本 == "__没读数__":
                没读数 += 1
                continue
            if not _是空的(本):
                continue                     # 那格有东西 → 站不进去（要么先挖，不归我管）
            # ⚠ 下面那格**必须也在表里、而且有地** ✓
            #   没读数 = 拿不准 → 不站 ✓（是空气 = 会掉下去 → 也不站 ✓）
            下 = 表.get((x, y - 1, z), "__没读数__")
            if 下 == "__没读数__" or _是空的(下):
                continue
            距 = ((落[0] - x) ** 2 + (落[2] - z) ** 2) ** 0.5
            走 = ((x - 我[0]) ** 2 + (z - 我[2]) ** 2) ** 0.5
            分 = (走, 距)
            if 最好分 is None or 分 < 最好分:
                最好, 最好分 = [x, y, z], 分
    if 最好 is not None:
        return 最好, None
    # ★ 一个能站的都没有 → **照实说**，交回主链 ✓（不插步、不瞎猜 ✗）
    return None, (f"雷达里落点四周没有一个「本格空 + 下面有地」的位子"
                  f"（没读数的 {没读数} 格、其余被占着）—— 我不瞎插步，交回主链")


def 处理回执(bridge, 状态=None, e=None):
    """回执里的**理由** → 变成**下一步** ✓

    两类（2026-10-09 一起收进来 —— 同一个病根"手把答案说了、脑没人读" ✓）：
      · `够不着: true`      → 插一步「走到落点旁边」（手把距离算好了 ✓）
      · `cmd == goto` 失败  → **挖过去还是绕过去**（主人点名的那条判断 ✓）
    """
    e = e or {}
    try:
        if e.get("够不着"):
            return _管够不着(bridge, 状态, e)
        if str(e.get("cmd") or "") == "goto" and e.get("ok") is False:
            return _管走不通(bridge, 状态, e)
    except Exception as ex:
        print(f"[够不着自愈] 处理回执出岔子（不影响主链）：{ex}", flush=True)
    return None


def _管够不着(bridge, 状态, e):
    """手说「够不着」→ 在当前那一步前面插一步「走到落点旁边」✓"""
    global _共插过
    命令 = str(e.get("cmd") or "")
    该动作 = 动作对得上.get(命令)
    if not 该动作:
        return None                      # 不认识的 cmd，一个字都不碰 ✓
    栈 = _活实例(bridge, "任务栈")
    if 栈 is None:
        return None                      # 没有活的任务栈 = 没有"当前那一步"，交回主链 ✓
    任, 第几, 步 = _当前步(栈)
    if 任 is None:
        return None
    if 步.get("动作") not in 该动作:
        return None                      # 规矩 2：回执跟当前那一步对不上 → 不碰 ✓
    位 = 步.get("p")
    if not (isinstance(位, (list, tuple)) and len(位) >= 3):
        return None
    键 = _键(位)
    if 键 is None:
        return None
    # ── 规矩 4：一条任务最多插 3 次（绝不自己造死循环 ✓）──
    任id = str(任.get("id") or "")
    次 = int(_插了几次.get(任id, 0))
    if 次 >= 3:
        return (f"「{命令}」够不着 @{list(键)} —— 这条任务我已经插过 {次} 次步了，"
                f"不再插 ✗ 交回主链判失败 ✓")
    # ── 规矩 3：同一格 2 秒内只插一次 ──
    现在 = time.time()
    if 现在 - _上次.get((命令, 键), -999.0) < 2.0:
        return None
    走到哪, 为什么 = _落脚点(状态, 位)
    if 走到哪 is None:
        _上次[(命令, 键)] = 现在        # 记一笔，别每 200ms 重复说同一句
        return f"「{命令}」够不着 @{list(键)}（{e.get('距')} 格）—— {为什么}"
    # ── 插一步：**放在当前那一步之前** ✓ ──
    新步 = {"动作": "走到", "p": list(走到哪), "到点": 1.5}
    任["步骤"].insert(第几, 新步)
    # ★ 把当前步的**重试账、超时表**全部清零 ✓
    #   不清的话：`重试` 还攒着刚才那几次失败 → 走完再放一次就被判整任务失败 ✗
    #   （这几项就是主链 `_下一步()` 干的事，我照抄一份放在这儿 ✓）
    任["重试"] = 0
    任["重试到"] = 0.0
    任["下发过"] = False
    任["步骤开始"] = time.time()
    try:
        栈.上次下发 = 0.0
    except Exception:
        pass
    _上次[(命令, 键)] = 现在
    _插了几次[任id] = 次 + 1
    _共插过 += 1
    return (f"★ 够不着自愈：「{命令}」在 {e.get('距')} 格外够不着 @{list(键)} —— "
            f"我先走到 {list(走到哪)} 再试（本条任务第 {次 + 1} 次插步，共 {_共插过} 次）")


def _管走不通(bridge, 状态, e):
    """路走不通（`goto` 失败）→ 问一句「挖过去还是绕过去」，把决策做出来 ✓

    主人 2026-10-09 点名：「寻路『挖过去还是绕过去』」
    ★ 决策那件事**只做一份实现** ✓（`生存常识.挖还是绕()` ✓ 谁要谁调 ✓ 不抄第二遍 ✓）
      这里只管接线：拿到决定 → 挖过去就**换掉**当前那一步 ✓ 绕过去就什么都不做 ✓
    """
    global _共插过, _绕了几次
    e = e or {}
    if str(e.get("why") or "") == "no-way-out":
        return None          # 手侧那句是"悬崖/岩浆，绕不开"—— 它自己会重新找路 ✓
    栈 = _活实例(bridge, "任务栈")
    if 栈 is None:
        return None
    任, 第几, 步 = _当前步(栈)
    if 任 is None or 步.get("动作") != "走到":
        return None          # 回执跟当前那一步对不上 → 一个字都不碰 ✓
    if 步.get("到点") is not None:
        return None          # ⚠ 带 `到点` 的走位是"挪到旁边去放东西"之类 ✓
        #                       那种不该被换成挖隧道 ✗（它只要挪一两格）
    位 = 步.get("p")
    if not (isinstance(位, (list, tuple)) and len(位) >= 3):
        return None
    键 = _键(位)
    if 键 is None:
        return None
    现在 = time.time()
    if 现在 - _上次.get(("goto", 键), -999.0) < 5.0:
        return None          # 同一个目标 5 秒内只算一次（手侧会连着重回失败 ✓）
    生 = _找生存常识()
    if 生 is None:
        return None          # 找不到那份实现 → 什么都不做（绝不自己抄一份 ✗）
    决定, 因, 步表 = 生.挖还是绕(状态, list(位), 背包=_背包(状态))
    if 决定 != "挖过去" or not 步表:
        _上次[("goto", 键)] = 现在
        _绕了几次 += 1
        return f"路走不通 @{list(键)} —— {因}（第 {_绕了几次} 次判成绕）"
    # ── 挖过去：**换掉**当前那一步（连它自带的「走到目标」一起）✓ ──
    #   ⚠ 是"换"不是"插" ✗ —— 插的话：挖完隧道又回头走那条走不通的老路 ✓ 白忙 ✓
    新 = [dict(x) for x in 步表]
    新.append(dict(步))
    任["步骤"][第几:第几 + 1] = 新
    # ── 重试账 / 超时表清零（跟「够不着」那条同一个道理 ✓）──
    任["重试"] = 0
    任["重试到"] = 0.0
    任["下发过"] = False
    任["步骤开始"] = time.time()
    try:
        栈.上次下发 = 0.0
    except Exception:
        pass
    _上次[("goto", 键)] = 现在
    _共插过 += 1
    return (f"★ 挖还是绕：路走不通 @{list(键)} —— **挖过去** ✓ "
            f"{因}（换成 {len(新)} 步的隧道）")


def _找生存常识():
    """鸭子类型地找「生存常识」那节车厢的 `挖还是绕` ✓（不抄第二遍 ✓）"""
    import sys as _sys
    for m in list(_sys.modules.values()):
        try:
            if callable(getattr(m, "挖还是绕", None)):
                return m
        except Exception:
            continue
    return None


def _背包(状态):
    """从状态帧里凑出"背包里有什么"（生存常识那套形状：{名字: 数量}）✓"""
    出 = {}
    try:
        for k, v in ((状态 or {}).get("items") or {}).items():
            try:
                出[str(k)] = float(v)
            except Exception:
                出[str(k)] = 1.0
    except Exception:
        pass
    return 出


def 清任务(bridge, 任id=None):
    """任务结束/换轨时清掉这一条的插步账 ✓（不写进磁盘，纯内存 ✓）"""
    try:
        if 任id is None:
            _插了几次.clear()
        else:
            _插了几次.pop(str(任id), None)
    except Exception:
        pass


def 装上(bridge, 日志=None, **kw):
    """两个补丁点，**各管各的幂等** ✓

    ⚠⚠ 这里我栽过一次 ✗：第一版把两个补丁点的幂等**挂在同一个标记**上 ——
      卸下时把 `任务栈._下发` 还回去了、可叙事者那个标记清了 ✓
      再装上时叙事者那半边说"已经装过了" → 提前 return →
      **那道坐标闸再也装不上** ✗（表现是"审计的闸时灵时不灵"）
      用例 I1 当场把它抓出来了 ✓
    规矩：**一个补丁点一个标记** ✓ 谁在岗谁记账 ✓（一眼看得出有没有套两层 ✓）
    """
    global _日志
    _日志 = 日志
    打 = []
    清账("装上")          # ★ 从零开始（不许把上一趟的账带进来 ✗）

    # ── 补丁点①：叙事者.看回执（把理由变成下一步）──
    叙类 = getattr(bridge, "叙事者", None)
    if 叙类 is None:
        return {"好": False, "为什么": "找不到 叙事者 类", "打了": []}
    原 = getattr(叙类, "看回执", None)
    装过叙 = bool(getattr(叙类, "_够不着自愈装了", False))
    if not callable(原):
        return {"好": False, "为什么": "叙事者.看回执 不是函数", "打了": []}
    if not 装过叙:
        _原件.setdefault(叙类, {})["回执"] = 原

        def 看回执(self, e):
            原(self, e)                      # 原来那条路一个字不改 ✓
            try:
                说明 = 处理回执(bridge, getattr(self, "最后状态", None), e)
                if 说明:
                    _说(f"[够不着自愈] {说明}")
                    try:
                        self.说(f"[{time.strftime('%H:%M')}] {说明}", 紧急=True)
                    except Exception:
                        pass
            except Exception as ex:
                print(f"[够不着自愈] 出岔子（不影响主链）：{ex}", flush=True)

        叙类.看回执 = 看回执
        叙类._够不着自愈装了 = True
        打.append("叙事者.看回执()  ← 读到「够不着」/「路走不通」就把理由变成下一步"
                  "（原来那条路一个字不改）")

    # ── 补丁点②：任务栈._下发（坐标体检）──
    #   ★★★ 2026-10-09「硬编码坐标审计」抓到的那一条，在这儿收口 ✓
    #   主链 bridge.py 有 12 处 `... or [0, 0, 0]` 的兜底 ✗ ——
    #   本意是"防止 None 崩"，可它把**"我不知道坐标"变成了"那就去世界原点"** ✗
    #   `[0,0,0]` 不是"没有"，它是一个**看起来很正常的坐标值** ✓ —— 最坏的情况是：
    #   一步走到/挖/放的坐标缺失 → 兜底成原点 → **它真往原点跑** ✗
    #   （这是"fail-closed 写成 fail-open"的经典样子 ✓）
    #
    #   ⚠ 为什么不去改主链那 12 处 ✗：**红线是 bridge.py 一个字节不许动** ✓
    #     而且那 12 处有一半只是"拿去查表/查方块名"（无害）✓
    #     真正要命的只有**会变成动作的**那几处 ✓
    #   ⚠ 为什么不在 `处理回执` 里拦 ✗：回执是**事后**的（命令已经发出去了）✗
    #     要拦就得拦在**下发之前** ✓ —— 所以包 `任务栈._下发` ✓
    #
    #   规矩：**没有坐标就什么动作都不发，而且出声** ✓（绝不静默跑到原点 ✗）
    栈类 = getattr(bridge, "任务栈", None)
    _原下发 = getattr(栈类, "_下发", None) if 栈类 is not None else None
    # ⚠ 判据用**账本身份比对** ✓（我第一版用"壳上打个标记"，可卸下时那个标记
    #   搬不回原件 → 重装时旧标记还挂在上一次那层壳上 → **拒绝再包** ✗
    #   账本这一条是"自证"的：`_原件` 里登记的就是我包的那一层 ✓
    #   而且**绝不套两层**（第二次进来时它一定在账本里 ✓）
    #   ⚠⚠ 判据的**方向**我第一版写反了 ✗ ——
    #     账本里存的是**原件**（换回去要用的那个）✓
    #     所以「账本里记的 == 类上现在这个」= **我从没装过** ✓
    #     反过来写（"账本里记的不是类上这个"）→ 第一次装完之后恒真 → **次次都再包一层** ✗
    #     用例 A3 当场抓出来 ✓（差一点又让"套两层"混过去 ✓）
    _已经包过 = (栈类 in _原件 and _原件[栈类].get("下发") is not _原下发)
    if callable(_原下发) and not _已经包过:
        _原件.setdefault(栈类, {})["下发"] = _原下发

        def _下发(self, 步, 任, 现在, s):
            try:
                需要坐标 = 步.get("动作") in ("走到", "挖", "放", "熔炉放料", "熔炉取成品")
                if 需要坐标:
                    我 = (s or {}).get("pos")
                    if not (isinstance(我, (list, tuple)) and len(我) >= 3):
                        # 一帧里只说一次（别每 200ms 刷屏）
                        说过 = (s or {}).get("_漏坐标已报")
                        if not 说过:
                            try:
                                s["_漏坐标已报"] = True
                            except Exception:
                                pass
                            print(f"[够不着自愈] ★★ 这一拍**状态帧里没有我的坐标** —— "
                                  f"主链那 12 处 `or [0,0,0]` 兜底会把「不知道」变成"
                                  f"「去世界原点」✗ 所以「{步.get('动作')}」这一步"
                                  f"**一个动作都不发**（宁可站着 ✓）", flush=True)
                        return False
                    # ⚠ 判据是「**状态帧**里压根没有坐标」✗ —— **不是**「坐标等于某个数」✗
                    #   （`[0,0,0]` 是个**合法坐标**：真的是世界原点那一格，就该去 ✓
                    #    不能因为它长得像兜底值就拦 ✓ 这是"哨兵和合法值共用一个数"的老坑 ✓）
            except Exception as ex:
                print(f"[够不着自愈] 坐标体检出岔子（不影响主链）：{ex}", flush=True)
            return _原下发(self, 步, 任, 现在, s)

        栈类._下发 = _下发
        打.append("任务栈._下发()  ← 坐标体检：这一拍状态帧里没有我的坐标 → "
                  "不发动作、当场出声（绝不静默往世界原点跑 ✗）")

    return {"好": True, "为什么": "", "打了": 打}


def 卸下(bridge):
    global _日志
    叙类 = getattr(bridge, "叙事者", None)
    原 = _原件.pop(id(叙类), None) if 叙类 is not None else None
    if not 原:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    叙类.看回执 = 原
    栈类 = getattr(bridge, "任务栈", None)
    原信 = _原件.get(id(栈类)) or {}
    if isinstance(原信, dict) and callable(原信.get("下发")):
        栈类._下发 = 原信["下发"]
    try:
        del 叙类._够不着自愈装了
    except AttributeError:
        pass
    _上次.clear()
    _插了几次.clear()
    _日志 = None
    return {"好": True, "为什么": "", "打了": ["还原 叙事者.看回执()"]}


def 清账(为什么=""):
    """把"这一趟"的账全清干净 ✓（装上/卸下都调它 ✓）

    ★ 为什么要有它：我用例里逮到过"状态跨组串味" ✗ ——
      上一组插满 3 次的账，被下一组接着用 → 下一组怎么插都插不动 ✓
      看着像"产品坏了"，其实是**账没清** ✓
      规矩：**装上和卸下都从零开始** ✓（车厢本来就是"拔掉等于没装过" ✓）
    """
    global _共插过, _绕了几次
    _上次.clear()
    _插了几次.clear()
    _共插过 = 0
    _绕了几次 = 0


def 卸下(bridge):
    global _日志
    打 = []
    叙类 = getattr(bridge, "叙事者", None)
    原 = _原件.pop(叙类, None) if 叙类 is not None else None
    if isinstance(原, dict) and callable(原.get("回执")):
        叙类.看回执 = 原["回执"]
        打.append("还原 叙事者.看回执()")
    try:
        del 叙类._够不着自愈装了
    except Exception:
        pass
    栈类 = getattr(bridge, "任务栈", None)
    原2 = _原件.pop(栈类, None) if 栈类 is not None else None
    if isinstance(原2, dict) and callable(原2.get("下发")):
        # ⚠ 还得把「这层壳」的标记一起带走 ✗ ——
        #   不然再装上时那句 `_已经包过` 会看到旧壳上的标记 → **拒绝再包** ✗
        #   （用例里就是同名的假类被反复装卸，标记留在**类属性**上绕了一圈 ✓）
        #   规矩：**卸下要卸干净 —— 连"我装过"这件事也搬回去** ✓
        栈类._下发 = 原2["下发"]
        打.append("还原 任务栈._下发()")
    清账("卸下")
    _日志 = None
    if not 打:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    return {"好": True, "为什么": "", "打了": 打}


def 同步实例(bridge, 日志=None, 车钩=None):
    """本车厢**不持有任务进度** —— 进度在主链的任务栈里，所以热插拔不丢东西。"""
    try:
        if 日志 and _插了几次:
            日志(f"够不着自愈：这条任务已经插过步的有 {len(_插了几次)} 条")
    except Exception:
        pass
    return {"好": True, "为什么": "无状态，随便拔", "打了": []}
