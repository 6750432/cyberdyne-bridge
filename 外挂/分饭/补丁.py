"""分饭车厢 —— 让它学会分主人点吃的，**前提是自己够吃**。

English: Shares food with the player on request, but only the surplus above a
personal reserve. When there is not enough left, it says so plainly instead of
handing over its last meal.

中文：2026-10-07 主人的要求 ——「让他学会分我点吃的，前提是自己够吃」。

守三条：
  ① **够吃才分**：包里吃的总数减去「保留份数」（默认 4）才是能分的。
     不够就当场说明白（还剩几份、要留几份），**绝不打肿脸充胖子**。
  ② **可着最富余的那一种分**，不把某一种分光 —— 免得留下个位数又不够吃。
  ③ 口令**不走大模型**：主人说「分我点吃的」直接变成一条任务书。
     这就是「本地优先」该有的样子。

它挂在主链自己的钩子上（允许动作 / _挂探针 / _下发 / _看完成了没 / 指令层.解析）；
手侧靠身体插件新加的「递」能力真正把东西丢出去 —— **丢在地上让对方捡**，
这比"塞进对方背包"稳得多，也更像人干的事。

★ 为什么算账放在 `_下发` 而不是口令里：**指令层拿不到状态帧**，
   看不见背包就没法判「自己够不够吃」。口令只负责听懂，
   真正的账在每一拍下发前、拿着 `s` 当场算。
"""
import time

名字 = "分饭"

# 主食优先，越靠前越"顶饱"。
食物 = ("cooked_beef", "cooked_porkchop", "cooked_mutton", "cooked_chicken",
        "cooked_rabbit", "cooked_salmon", "cooked_cod", "bread", "baked_potato",
        "golden_apple", "apple", "carrot", "potato", "beetroot", "melon_slice",
        "sweet_berries", "dried_kelp", "rabbit_stew", "mushroom_stew",
        "beetroot_soup", "pumpkin_pie", "cookie")

# 主人说这几句，就是「分我点吃的」。
分饭词 = ("分我点吃的", "分我吃的", "给我点吃的", "给点吃的", "分点吃的给我",
          "给我点饭", "分我点饭", "我饿了", "赏我点吃的", "给我吃的",
          "分我点东西吃", "有吃的吗", "要吃的")

默认可分几份 = 3
_原 = {}
_数 = None
_日志 = None


def _记(文):
    if _日志:
        try:
            _日志(文)
        except Exception:
            pass
    print(f"[分饭] {文}", flush=True)


def _取(键, 兜底):
    """读配置。⚠ 车钩传进来的「数」是**外置数据字典**（不是函数）——
    两种写法都兜住，免得像第一版那样静默拿默认值还以为读到了。"""
    try:
        if _数 is None:
            return int(兜底)
        v = _数.get(键, 兜底) if isinstance(_数, dict) else _数(键, 兜底)
        return int(float(v))
    except Exception:
        return int(兜底)


def 算分多少(栈, s, 保留=None, 一次=None):
    """算出「分什么、分几份」。返回 (物品名, 份数) 或 (None, 回绝的话)。"""
    留 = 保留 if 保留 is not None else _取("保留份数", 4)
    份 = 一次 if 一次 is not None else _取("一次分几份", 默认可分几份)

    有 = []
    for 名 in 食物:
        try:
            n = int(栈._物品数量(s, 名) or 0)
        except Exception:
            n = 0
        if n > 0:
            有.append([名, n])
    if not 有:
        return None, "我包里一口吃的都没有 —— 等我打点猎去"
    总数 = sum(n for _, n in 有)
    能分 = 总数 - int(留)
    有.sort(key=lambda x: -x[1])              # 可着最富余的那种分
    if 能分 <= 0:
        return None, (f"我这儿统共就 {总数} 份吃的（{有[0][0]}×{有[0][1]}）—— "
                      f"我自己得留 {留} 份，不够分给你。等我再多打点猎")
    要 = max(1, min(int(份), int(能分), 64))
    return 有[0][0], 要


def 装上(bridge, 数=None, 日志=None, **kw):
    global _数, _日志
    _数, _日志 = 数, 日志
    栈 = getattr(bridge, "任务栈", None)
    指 = getattr(bridge, "指令层", None)
    if 栈 is None or 指 is None:
        return {"好": False, "为什么": "找不到 bridge.任务栈 / bridge.指令层", "打了": []}
    if id(栈) in _原:
        # ★ 装上必须幂等 —— 套两层壳会自己把自己拦住（挖空守卫那边踩过）
        return {"好": True, "为什么": "我已经在岗了，不重复套壳", "打了": []}
    缺 = [n for n in ("_挂探针", "_下发", "_看完成了没")
          if not callable(getattr(栈, n, None))]
    if not callable(getattr(指, "解析", None)):
        缺.append("指令层.解析")
    if 缺:
        return {"好": False, "为什么": f"主链上找不到 {('、'.join(缺))}，版本对不上", "打了": []}

    _原[id(栈)] = {"_挂探针": 栈._挂探针, "_下发": 栈._下发, "_看完成了没": 栈._看完成了没}
    _原["允许动作"], _原["解析"] = 栈.允许动作, 指.解析
    栈.允许动作 = frozenset(set(栈.允许动作) | {"给"})

    # ── ① 探针：把要分的那一样吃的盯上 ──
    def _挂探针(self, 步骤, s):
        r = _原[id(栈)]["_挂探针"](self, 步骤, s)
        try:
            if any(步.get("动作") == "给" for 步 in 步骤):
                # ⚠ 2026-10-07 实测：主链平时**不盯背包**，`items` 就是个空字典，
                #   于是它明明有 4 块熟牛肉，却回了一句「我包里一口吃的都没有」。
                #   要分饭就必须先把背包全量盯上（"*" = 背包全部物品）。
                self.发({"cmd": "watch_items", "list": ["*"]})
        except Exception as e:
            _记(f"挂探针时出岔子（不影响主链）：{e}")
        return r

    # ── ② 下发前**当场**算账（口令那边没有状态帧，算不了）──
    def _下发(self, 步, 任, 现在, s):
        if 步.get("动作") != "给":
            return _原[id(栈)]["_下发"](self, 步, 任, 现在, s)
        # ⚠ 不能用 `任 = 任 or (self.任务 or {})` —— 传进来的**空字典是 falsy**，
        #   会被悄悄换成一个临时新字典，写进去的回绝理由/基准全飞到垃圾堆里（踩过）。
        任 = 任 if isinstance(任, dict) else None
        if 任 is None:
            任 = self.任务 if isinstance(self.任务, dict) else {}
        if not isinstance((s or {}).get("items"), dict) or not (s or {}).get("items"):
            # 看不见背包 → 让手侧盯上全量，**下一拍再算**。
            # 宁可晚一拍，也绝不冤枉自己："明明有饭却说没有"是最丢人的失败。
            try:
                self.发({"cmd": "watch_items", "list": ["*"]})
            except Exception:
                pass
            _记("看不见背包（items 是空的）—— 已让手侧盯上全量，下一拍再算")
            return False
        if 任.get("分饭_回绝"):
            return False                     # 已经回绝过，别再念叨
        # ★★ 2026-10-07：步骤里**已经写明了**「给什么、给几个」→ 直接递。
        #   "够吃才分"那套账只对**分口粮**成立；主人要的是工具（石镐），
        #   不能拿吃饭的规矩去卡它。
        if 步.get("物品"):
            名0, 数0 = str(步["物品"]), int(float(步.get("数量") or 1))
            try:
                self.发({"cmd": "递", "物品": 名0, "数量": float(数0),
                         "谁": str(步.get("谁") or "")})
            except Exception as e:
                _记(f"递东西没发出去：{e}")
                return False
            _记(f"递给主人 {数0} 个 {名0}")
            return True
        名, 多少 = 算分多少(self, s, 一次=步.get("数量"))
        if 名 is None:
            任["分饭_回绝"] = 多少
            try:
                self.说(f"[{time.strftime('%H:%M')}] {多少}", 紧急=True)
            except Exception:
                pass
            _记(f"回绝了：{多少}")
            return False
        步["物品"], 步["数量"] = 名, 多少
        try:
            self.发({"cmd": "递", "物品": 名, "数量": float(多少),
                     "谁": str(步.get("谁") or "")})
        except Exception as e:
            _记(f"递东西没发出去：{e}")
            return False
        _记(f"分出去 {多少} 个 {名}")
        return True

    # ── ③ 完成判据：背包里少掉要分的数量就算成；回绝过的直接算完 ──
    def _看完成了没(self, 步, s, 任=None):
        if 步.get("动作") != "给":
            return _原[id(栈)]["_看完成了没"](self, 步, s, 任)
        # ⚠ 不能用 `任 = 任 or (self.任务 or {})` —— 传进来的**空字典是 falsy**，
        #   会被悄悄换成一个临时新字典，写进去的回绝理由/基准全飞到垃圾堆里（踩过）。
        任 = 任 if isinstance(任, dict) else None
        if 任 is None:
            任 = self.任务 if isinstance(self.任务, dict) else {}
        if 任.get("分饭_回绝"):
            return True, None
        名 = str(步.get("物品") or "")
        要 = float(步.get("数量") or 1)
        if not 名:
            return False, None               # 还没算账，等下一拍
        try:
            今 = float(self._物品数量(s, 名))
        except Exception:
            return False, None
        基 = 任.get("分饭_之前")
        if 基 is None:
            任["分饭_之前"] = 今
            return False, None
        return 今 <= float(基) - 要, None

    # ── ④ 口令：「分我点吃的」→ 一条任务书，**不问大模型** ──
    def 新解析(self, 说话人, 原文=""):
        原 = str(原文 or "").strip()
        if 原 and any(w in 原 for w in 分饭词):
            _记(f"听懂口令「{原}」→ 分饭给 {说话人}")
            return {"act": "task", "名字": f"分点吃的给{说话人 or '他'}",
                    "步骤": [{"动作": "给", "数量": 默认可分几份,
                              "谁": str(说话人 or "")}]}
        return _原["解析"](self, 说话人, 原文)

    栈._挂探针, 栈._下发, 栈._看完成了没 = _挂探针, _下发, _看完成了没
    指.解析 = 新解析
    return {"好": True,
            "为什么": "分饭上岗：够吃才分、可着最富余的那样分、不够就当场说明白",
            "打了": ["任务栈.允许动作  ← 多了「给」",
                     "任务栈._挂探针()", "任务栈._下发()", "任务栈._看完成了没()",
                     "指令层.解析()  ← 口令「分我点吃的」"]}


def 卸下(bridge):
    栈 = getattr(bridge, "任务栈", None)
    指 = getattr(bridge, "指令层", None)
    原 = _原.get(id(栈)) if 栈 is not None else None
    if 栈 is not None and 原:
        for n in ("_挂探针", "_下发", "_看完成了没"):
            setattr(栈, n, 原[n])
        if _原.get("允许动作") is not None:
            栈.允许动作 = _原["允许动作"]
    if 指 is not None and _原.get("解析") is not None:
        指.解析 = _原["解析"]
    _原.pop(id(栈), None)
    _原.pop("允许动作", None)
    _原.pop("解析", None)
    return {"好": True, "为什么": "分饭下班：任务栈和指令层都还回原样",
            "打了": ["允许动作", "三个钩子", "指令层.解析"]}


def 同步实例(bridge, 日志=None, 车钩=None):
    """无状态：分饭的账当场算、不存东西，所以热插拔一点不丢。"""
    return {"好": True, "为什么": "无状态：账当场算，不存东西，随便拔", "打了": []}
