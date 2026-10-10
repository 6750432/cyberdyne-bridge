"""贯通审计车厢 —— 「需要空间信息的决策」到底有几次真查了空间信息？

English: Coverage audit for spatial decisions. For every dispatched action it
checks whether the state frame actually carried the spatial facts that action
needs, counts "needed" vs "consulted", and shouts when the ratio drops below 1.0
naming the exact decision point that was skipped.

中文：主人 2026-10-08 清单里的 **P1-1 閘一**。

    「統計『需要空間資訊的決策次數』vs『實際查快取的次數』，
      **比值必須 = 1.0**，不足即報警並指出漏在哪個決策點。」

为什么这一闸值得单独立一个车厢
==============================
今天（2026-10-08）一整天的 bug，全都长成同一个样子：

    · 跳起来撞天花板，日志上却报「成功了」
    · 对着空气挥镐挥了 60 秒
    · 挖回来 6 个泥土（自己的坐标差一格）
    · 求解器以为它一无所有（背包快照被覆盖了）

它们的共同点**不是"算错了"，是"该看的东西没看"** —— 主人的 T1「資訊有卻不用」。

单看某一个决策点，很容易觉得"这里当然会查吧"。可是没人**数**过。
这一闸就是那个"数"：每下发一个动作，就问一句
**「这个动作需要的空间信息，这一帧里到底有没有？」**，
没有就记一笔，并且**点名**是哪个决策点漏的。

判据（每个动作需要什么）
------------------------
    挖          → `blocks`（那格叫什么）或 `scan.石头`，至少一样
    放          → `blocks`（身边四格哪格是空的）
    拾          → `drops`（掉落物在哪儿）
    熔炉放料/取成品 → `furnace`
    打          → 目标实体（`scan.实体` / 玩家列表）
    走到/合成/说/给/等 → 不需要（寻路插件自己看可走性；其余与空间无关）

做不到的事，照实说
------------------
这一闸**只能测「信息到没到」**，测不出「到了之后用没用」✗
后者要靠 `外挂/测空间决策.py` 那张静态表 + 一个个决策点的行为断言。
两件事合起来才算把 T1 摁住。
"""

名字 = "贯通审计"

# 动作 → 这一帧里必须有哪几样空间信息（任一样**非空**就算查了）
需要什么 = {
    "挖": (("blocks", "scan.石头"), "那格叫什么"),
    "放": (("blocks",), "身边四格哪格是空的"),
    "拾": (("drops",), "掉落物在哪儿"),
    "熔炉放料": (("furnace",), "炉子在哪儿、里面有什么"),
    "熔炉取成品": (("furnace",), "炉子在哪儿、里面有什么"),
    "打": (("scan.实体", "玩家"), "目标实体在哪儿"),
}

_账 = {"需要": 0, "查了": 0, "漏": {}, "按动作": {}}
上次报 = [0.0]
_报间隔 = 30.0          # 秒：别刷屏
_日志 = None


def _取(s, 路):
    """按 'a.b' 取嵌套字段。"""
    值 = s
    for 段 in 路.split("."):
        if not isinstance(值, dict):
            return None
        值 = 值.get(段)
    return 值


def _有东西(值):
    if 值 is None:
        return False
    if isinstance(值, (list, tuple, str)):
        return len(值) > 0
    if isinstance(值, dict):
        return len(值) > 0
    return True


def _记(文):
    if _日志:
        try:
            _日志(文)
            return
        except Exception:
            pass
    print(f"[贯通审计] {文}", flush=True)


def 记一笔(动作, s):
    """下发一个动作时叫一次。返回 True=这一帧信息齐 / False=漏了 / None=这个动作不需要。"""
    要 = 需要什么.get(str(动作))
    if not 要:
        return None
    样们, 说 = 要
    _账["需要"] += 1
    _账["按动作"][动作] = _账["按动作"].get(动作, 0) + 1
    齐 = any(_有东西(_取(s, 路)) for 路 in 样们)
    if 齐:
        _账["查了"] += 1
    else:
        _账["漏"][动作] = _账["漏"].get(动作, 0) + 1
        _记(f"★ 漏了：动作「{动作}」需要【{说}】，可这一帧里 "
            f"{'、'.join(样们)} 全是空的 —— 这个决策点没查空间信息！")
    return 齐


def 贯通率():
    """需要 vs 查了。返回 (比值, 需要数, 查了数)。一个都没需要时返回 1.0（没漏就是满分）。"""
    n = _账["需要"]
    if not n:
        return 1.0, 0, 0
    return _账["查了"] / float(n), n, _账["查了"]


def 报表(强制=False):
    率, n, 查 = 贯通率()
    import time as _t
    if not 强制 and _t.time() - 上次报[0] < _报间隔:
        return 率
    上次报[0] = _t.time()
    漏 = "、".join(f"{k}×{v}" for k, v in sorted(_账["漏"].items())) or "（无）"
    _记(f"贯通率 {率:.4f}（需要 {n} 次 / 查了 {查} 次）｜ 漏的决策点：{漏}")
    if 率 < 1.0:
        _记("★ **比值不到 1.0** —— 上面点名的决策点就是漏在哪。"
            "（主人 2026-10-08：閘一，比值必须 = 1.0）")
    return 率


def 装上(bridge, 日志=None, **kw):
    global _日志
    _日志 = 日志
    栈类 = getattr(bridge, "任务栈", None)
    if 栈类 is None:
        return {"好": False, "为什么": "找不到 bridge.任务栈", "打了": []}
    if id(栈类) in _原件:
        return {"好": True, "为什么": "我已经在岗了，不重复套壳", "打了": []}
    原 = getattr(栈类, "_下发", None)
    if not callable(原):
        return {"好": False, "为什么": "任务栈上没有 _下发()", "打了": []}
    _原件[id(栈类)] = 原

    def 新下发(self, 步, 任, 现在, s):
        try:
            记一笔((步 or {}).get("动作"), s)
            报表()
        except Exception as e:
            _记(f"记账时出岔子（不影响主链）：{type(e).__name__}: {e}")
        return 原(self, 步, 任, 现在, s)

    栈类._下发 = 新下发
    return {"好": True, "为什么": "贯通审计上岗：每个动作都问一句「这一帧的空间信息齐不齐」",
            "打了": ["任务栈._下发()  ← 贯通率计数"]}


def 卸下(bridge):
    栈类 = getattr(bridge, "任务栈", None)
    原 = _原件.pop(id(栈类), None) if 栈类 is not None else None
    if not 原:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    栈类._下发 = 原
    return {"好": True, "为什么": "贯通审计下班", "打了": ["任务栈._下发"]}


def 同步实例(bridge, 日志=None, 车钩=None):
    率, n, 查 = 贯通率()
    if 日志:
        日志(f"贯通审计：贯通率 {率:.4f}（需要 {n} / 查了 {查}）")
    return {"好": True, "为什么": f"无状态账本，随时可拔（当前贯通率 {率:.4f}）", "打了": []}


_原件 = {}
