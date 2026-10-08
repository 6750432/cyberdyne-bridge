"""挖空守卫 —— 让雷达始终盯住「正在挖的那一格」。

English: Radar keeper for dig steps. It re-aims the hand-side block watch at the
block currently being mined, refuses to swing at a block already known to be
air, debounces repeated digs on the same coordinate, and stops burning a full
60 s timeout once a coordinate has failed three times.

中文：2026-10-07 主人现场抓包的 bug —— 小家伙对着**空气**挥了 60 秒镐子，
重试还对着同一个点继续挥。

根因不是重试逻辑，是**雷达压根没盯那一格**：
主链 `bridge.py:1503` 只把步骤表里**前 16 个**挖点喂给手侧（`方块[:16]`），
而那条上地表的阶梯有 **19 个**挖点 —— 第 17 个往后探针永远是 `None`，
`_看完成了没` 就永远判「没挖完」，于是死磕到超时。

本车厢只做四件事，全都挂在主链自己现成的钩子上：
  ① **雷达锁定**：判「挖」时若那一格不在快照里 → 立刻把雷达重新指向它；
  ② **挖前校验**：目标已经是 air → 这一拍不下发，绝不挥空镐；
  ③ **防抖**：同一坐标 1 秒内只发一次 dig；
  ④ **三次撒手**：同一坐标发了 3 次还没好 → 把这一步的超时压到 0.5 秒，
     让主链自己的「试满 3 次就放弃」逻辑**立刻**生效，而不是干耗 3 分钟。

它**不新增动作**、**不改主链一个字**，拔掉就恢复原样。
"""
import time

名字 = "挖空守卫"
_态表 = {}      # id(任务栈类) → 状态
_原件 = {}      # id(任务栈类) → 装之前存下的原函数
_原收输出 = {}  # 装之前那一层 翻译器.收输出（卸下要还回去）

空气名 = ("air", "cave_air", "void_air")


def _态(栈类):
    return _态表.setdefault(id(栈类), {"挖点": [], "上次发": {}, "上次走": {}, "发了几次": {}, "上次喂": 0.0})


def _键(步):
    p = 步.get("p")
    if not isinstance(p, (list, tuple)) or len(p) < 3:
        return None
    try:
        return (int(round(float(p[0]))), int(round(float(p[1]))), int(round(float(p[2]))))
    except Exception:
        return None


def _喂雷达(自己, 坐标表):
    """把雷达（手侧 watch_blocks）指向这些坐标 —— 当前那一格排最前。

    手侧上限是 32 格（`node/server.js:923` `slice(0, 32)`），主链自己只用了 16。
    """
    好 = [p for p in 坐标表 if isinstance(p, (list, tuple)) and len(p) >= 3]
    if not 好:
        return 0
    try:
        自己.发({"cmd": "watch_blocks",
                "list": [[float(v) for v in p[:3]] for p in 好[:32]]})
    except Exception as e:
        print(f"[挖空守卫] 喂雷达没成功（不影响主链）：{e}", flush=True)
        return 0
    return len(好[:32])


_数 = None      # 车钩传进来的「读配置」小工具


def _取(键, 兜底):
    try:
        return float(_数(键, 兜底)) if _数 else float(兜底)
    except Exception:
        return float(兜底)


def 装上(bridge, 数=None, 日志=None, **kw):
    global _数
    _数 = 数
    栈类 = getattr(bridge, "任务栈", None)
    if 栈类 is None:
        return {"好": False, "为什么": "找不到 bridge.任务栈", "打了": []}
    原挂 = getattr(栈类, "_挂探针", None)
    原看 = getattr(栈类, "_看完成了没", None)
    原发 = getattr(栈类, "_下发", None)
    原超 = getattr(栈类, "_这步超时", None)
    缺 = [n for n, f in (("_挂探针", 原挂), ("_看完成了没", 原看),
                          ("_下发", 原发), ("_这步超时", 原超)) if not callable(f)]
    if 缺:
        return {"好": False, "为什么": f"任务栈上找不到 {('、'.join(缺))}，主链版本对不上", "打了": []}
    if id(栈类) in _原件:
        # ★★ 2026-10-07 测试逼出来的真缺陷：**装上必须幂等**。
        #   否则重复装上会套两层壳 —— 外层刚记完「这一格发过了」，
        #   内层立刻判「1 秒内发过」→ 自己把自己拦死，一个 dig 都发不出去。
        return {"好": True, "为什么": "我已经在岗了，不重复套壳", "打了": []}
    _原件[id(栈类)] = {"_挂探针": 原挂, "_看完成了没": 原看, "_下发": 原发, "_这步超时": 原超}

    # ── ① 雷达锁定：接单时就把「当前要挖的那一格」顶到最前面 ──
    def _挂探针(self, 步骤, s):
        try:
            态 = _态(栈类)
            态["挖点"] = [[float(v) for v in 步["p"][:3]] for 步 in 步骤
                          if 步.get("动作") == "挖"
                          and isinstance(步.get("p"), (list, tuple)) and len(步["p"]) >= 3]
            态["上次发"], 态["上次走"] = {}, {}
            态["发了几次"], 态["上次喂"] = {}, 0.0
            任 = self.任务 or {}
            表 = 任.get("步骤") or 步骤
            第 = int(任.get("第几步") or 0)
            if 态["挖点"]:
                当前 = None
                if 0 <= 第 < len(表) and 表[第].get("动作") == "挖":
                    当前 = 表[第].get("p")
                if 当前 is None:
                    当前 = 态["挖点"][0]
                喂了 = _喂雷达(self, [当前] + 态["挖点"])
                if 喂了 > 16:
                    print(f"[挖空守卫] 这一趟有 {len(态['挖点'])} 个挖点，"
                          f"主链只喂得下 16 个 —— 我把雷达改成 {喂了} 格，"
                          f"并且把当前那一格顶到了最前面。", flush=True)
        except Exception as e:
            print(f"[挖空守卫] 挂探针时出岔子（不影响主链）：{e}", flush=True)
        return 原挂(self, 步骤, s)

    # ── ② 雷达没盯 → 立刻指过去；③ 顺手把「发了几次」清干净 ──
    def _看完成了没(self, 步, s, 任=None):
        好, 原因 = 原看(self, 步, s, 任)
        try:
            k = _键(步) if 步.get("动作") == "挖" else None
            p = 步.get("p")
            名 = self._方块名(s, p) if isinstance(p, (list, tuple)) else None
            if k is not None:
                # ★★★ 2026-10-08 实机抓到的 T2「静默失败」：
                #   计划里写死挖 [-164,77,158]，而那一格**扫描那一刻就已经是空气** ——
                #   主链的判据「读到 air = 挖完了」于是立刻判定完成，它连一步都没走、
                #   也没掉出任何东西，整条链"顺利"往下走，最后卡在「拾」上干等 60 秒。
                #   规矩：**第一次看见这格时它就是空气 → 它是陈坐标，永远不算完成。**
                #   （真挖的格，第一次看见时必然是块；只有扫描过期的格才会"初见即空"。）
                初见 = f"_挖初见_{k}"
                if isinstance(任, dict) and 初见 not in 任:
                    任[初见] = 名
                期望 = str(步.get("方块") or "")
                if 好 and 期望 and 任.get(初见) != 期望:
                    print(f"[挖空守卫] ★ 第 {k} 格：我要挖「{期望}」，"
                          f"可这一格**从没见过它是「{期望}」**（我现在看到的是"
                          f"「{任.get(初见)}」）—— 这是陈坐标，挖了也不是我要的东西。"
                          f"这一趟不算数，让它失败重规划。", flush=True)
                    return False, None
                if 好 and isinstance(任, dict) and 任.get(初见) in 空气名:
                    print(f"[挖空守卫] ★ 第 {k} 格**初见即空** —— 这是陈坐标"
                          f"（扫描时它还在，现在已经没了）。这一趟不算数，让它失败重规划。",
                          flush=True)
                    return False, None
                if 好 and not _态(栈类)["发了几次"].get(k):
                    print(f"[挖空守卫] ★ 第 {k} 格判定「挖完了」，可一次 dig 都没发过 —— "
                          f"陈坐标。这一趟不算数。", flush=True)
                    return False, None
            if 好:
                if k is not None:
                    _态(栈类)["发了几次"].pop(k, None)
                return 好, 原因
            if k is None:
                return 好, 原因
            p = 步.get("p")
            if self._方块名(s, p) is not None:
                return 好, 原因                      # 雷达有读数，主链自己会判 air
            态 = _态(栈类)
            现在 = time.time()
            if 现在 - 态["上次喂"] > 0.5:
                态["上次喂"] = 现在
                _喂雷达(self, [p] + 态.get("挖点", []))
                print(f"[挖空守卫] ★ 雷达原来没盯 {k} —— 已经重新指过去，下一拍就有读数了",
                      flush=True)
        except Exception as e:
            print(f"[挖空守卫] 判完成时出岔子（不影响主链）：{e}", flush=True)
        return 好, 原因

    # ── ② 挖前校验 + ③ 防抖 ──
    def _下发(self, 步, 任, 现在, s):
        # ★★★ 2026-10-08：**先按当帧扫描把坐标换新的，再判是不是空气**。
        #   原来改写写在更内层（生存常识），可这道「别挥空镐」的闸在外层先跑，
        #   一句 `return False` 就把改写那一步跳过去了 —— 计划里的陈坐标永远换不掉。
        #   （手侧实机：计划挖 [-170,76,159]，那格早是空气；当帧扫描说木头在 [-179,75,153]）
        try:
            if 步.get("动作") == "挖" and 步.get("方块"):
                想 = str(步.get("方块"))
                近的 = [c for c in ((s or {}).get("scan", {}).get("可交互") or [])
                       if isinstance(c, dict) and str(c.get("name")) == 想
                       and isinstance(c.get("p"), (list, tuple)) and len(c["p"]) >= 3]
                # ⚠ 石头类不在「可交互」名单里（手侧单开了一项 `scan.石头`）——
                #   只查 可交互 的话，挖石头永远换不了新坐标（实机第 5 步就是这么卡的）。
                if not 近的:
                    _石 = ((s or {}).get("scan", {}) or {}).get("石头")
                    if (isinstance(_石, dict) and str(_石.get("name")) == 想
                            and isinstance(_石.get("p"), (list, tuple))
                            and len(_石["p"]) >= 3):
                        近的 = [{"p": _石["p"]}]
                if 近的:
                    新位 = [float(v) for v in 近的[0]["p"][:3]]
                    老 = 步.get("p")
                    老 = ([float(v) for v in 老[:3]]
                          if isinstance(老, (list, tuple)) and len(老) >= 3 else None)
                    同 = (老 is not None and all(abs(新位[i] - 老[i]) < 0.5 for i in range(3)))
                    if not 同:
                        # ⚠ 前面那步「走到」通常是**同一个坐标**（先靠近再挖）——
                        #   只改挖的不改走的，它就会走到老地方、在新地方挖，够不着 ✗
                        if 老 is not None and isinstance(任, dict):
                            for _b in (任.get("步骤") or []):
                                _q = _b.get("p") if isinstance(_b, dict) else None
                                if (isinstance(_q, (list, tuple)) and len(_q) >= 3
                                        and all(abs(float(_q[i]) - 老[i]) < 0.5 for i in range(3))):
                                    _b["p"] = list(新位)
                        步["p"] = 新位
                        _态(栈类)["发了几次"].pop(_键(步), None)
                        _态(栈类)["上次发"].pop(_键(步), None)
                        print(f"[挖空守卫] 挖「{想}」的坐标是陈的（{老}）—— "
                              f"换成当帧扫描里的 {新位}", flush=True)
        except Exception as e:
            print(f"[挖空守卫] 换坐标时出岔子（不影响主链）：{e}", flush=True)
        try:
            # ★★★ 需求一：**目标驱动**。挖步骤带着"要什么"（`方块`），
            #   执行时拿**当帧**扫描重新搜一遍；整片扫描里压根没有那样东西
            #   → 说明它得先去别处找（或先撸树），**立刻失败**，
            #   让心跳拿新状态重新规划 —— 绝不抱着陈坐标空挥到超时。
            if 步.get("动作") == "挖" and 步.get("方块"):
                想 = str(步.get("方块"))
                扫 = (s or {}).get("scan") or {}
                可有 = [c for c in (扫.get("可交互") or [])
                       if isinstance(c, dict) and str(c.get("name")) == 想]
                石 = 扫.get("石头")
                if isinstance(石, dict) and str(石.get("name")) == 想:
                    可有.append(石)
                老 = 步.get("p")
                老在近处 = False
                if isinstance(老, (list, tuple)) and len(老) >= 3:
                    for c in 可有:
                        q = c.get("p")
                        if (isinstance(q, (list, tuple)) and len(q) >= 3
                                and all(abs(float(q[i]) - float(老[i])) < 0.5 for i in range(3))):
                            老在近处 = True
                            break
                if not 可有 and not 老在近处:
                    _态(栈类)["找不到_" + 想] = int(_态(栈类).get("找不到_" + 想, 0)) + 1
                    print(f"[挖空守卫] ★ 当帧扫描里**压根没有「{想}」** —— "
                          f"这个坐标是陈的，我不挥。让它失败重规划。", flush=True)
                    return False
        except Exception as e:
            print(f"[挖空守卫] 目标驱动检查出岔子（不影响主链）：{e}", flush=True)
        try:
            if 步.get("动作") == "挖":
                p = 步.get("p")
                if isinstance(p, (list, tuple)) and len(p) >= 3:
                    if self._方块名(s, p) in 空气名:
                        return False                 # 已经是空气了，别挥空镐
                    k = _键(步)
                    态 = _态(栈类)
                    if 现在 - 态["上次发"].get(k, -999.0) < 1.0:
                        return False                 # ★ 同一格 1 秒内只发一次
                    态["上次发"][k] = 现在
                    态["发了几次"][k] = 态["发了几次"].get(k, 0) + 1
        except Exception as e:
            print(f"[挖空守卫] 下发前检查出岔子（不影响主链）：{e}", flush=True)
        # ★★ 同一个病根，`走到` 也得管：主链在「卡住」时会**每拍重下 goto**，
        #   而每重下一次都会把正在跑的那条路掐断（手侧日志刷「这条路被新命令打断了」）
        #   → 越卡越重下、越重下越卡。给它一个下限：同一目标 N 秒内只发一次。
        try:
            if 步.get("动作") == "走到":
                k = _键(步)
                态 = _态(栈类)
                间隔 = _取("走到防抖秒", 4.0)
                if 现在 - 态["上次走"].get(k, -9999.0) < 间隔:
                    return False
                态["上次走"][k] = 现在
        except Exception as e:
            print(f"[挖空守卫] 走到防抖出岔子（不影响主链）：{e}", flush=True)
        return 原发(self, 步, 任, 现在, s)

    # ── ④ 三次撒手：别再干等 60 秒 ──
    def _这步超时(self, 步):
        基 = 原超(self, 步)
        try:
            # ★★★ 2026-10-08 实机抓到的**死锁**：
            #   `_下发` 看雷达说那格是空气 → 不挥镐；
            #   `_看完成了没` 看初见即空 → 永远不算完成。
            #   两条规矩单独都对，合起来 = **干等 60 秒什么都不干**（手侧一条 dig 都没收到）。
            #   陈坐标要**立刻失败**，让心跳拿新帧重规划 —— 这就是「超时即 raise」那条闸。
            if 步.get("动作") == "挖" and 步.get("方块"):
                k = _键(步)
                任 = self.任务 if isinstance(getattr(self, "任务", None), dict) else {}
                初见 = 任.get(f"_挖初见_{k}")
                if 初见 is not None and str(初见) != str(步.get("方块")):
                    print(f"[挖空守卫] ★ {k} 是陈坐标（初见「{初见}」，我要「{步.get('方块')}」）"
                          f"—— **立刻判失败**，不干等 {float(基) / 1000:.0f} 秒", flush=True)
                    return 0.5
        except Exception:
            pass
        try:
            if 步.get("动作") == "挖" and float(基) > 1.0 and not 步.get("超时_ms"):
                k = _键(步)
                n = _态(栈类)["发了几次"].get(k, 0)
                if n >= 3:
                    print(f"[挖空守卫] ★ {k} 发了 {n} 次还没好 —— 不再干等 "
                          f"{float(基) / 1000:.0f} 秒，立刻交给主链判失败", flush=True)
                    return 0.5
        except Exception:
            pass
        return 基

    # ★★★ 2026-10-08「悄悄早退」专治：
    #   实机铁证：车厢在「分支探针」之后**再也不打任何日志** ——
    #   既没「推演出 N 步」也没「定位失败」。真相是它的逻辑**抛了异常**，
    #   而主链那边有 26 处吞异常（红线，不能改），于是一声不响地没了 ✗
    #   本车厢**挂得最晚 = 在最外层**，正好在这儿接住：
    #   谁炸了、炸在哪一行，**带堆栈出声**，绝不静默。
    译 = getattr(bridge, "翻译器", None)
    原收输出 = getattr(译, "收输出", None) if 译 is not None else None
    if callable(原收输出):
        _原收输出["f"] = 原收输出
        def 新收输出(self, 文本, s, 用途="翻译"):
            try:
                return _原收输出["f"](self, 文本, s, 用途=用途)
            except Exception as e:
                import traceback
                print(f"★★ [挖空守卫] 推演链路上有人炸了（{type(e).__name__}: {e}）"
                      f" —— **这就是「悄悄早退」的真相**：\n"
                      f"{traceback.format_exc()}", flush=True)
                return None, None, f"推演链路炸了：{type(e).__name__}: {e}"

        译.收输出 = 新收输出

    栈类._挂探针, 栈类._看完成了没 = _挂探针, _看完成了没
    栈类._下发, 栈类._这步超时 = _下发, _这步超时
    return {"好": True, "为什么": "雷达看门狗上岗：空气不挥、同格不连发、三次就撒手",
            "打了": ["任务栈._挂探针", "任务栈._看完成了没", "任务栈._下发", "任务栈._这步超时"]}


def 卸下(bridge):
    栈类 = getattr(bridge, "任务栈", None)
    原 = _原件.pop(id(栈类), None) if 栈类 is not None else None
    if not 原:
        return {"好": True, "为什么": "本来就没装", "打了": []}
    for 名, 函 in 原.items():
        setattr(栈类, 名, 函)
    译 = getattr(bridge, "翻译器", None)
    if 译 is not None and _原收输出.get("f") is not None:
        译.收输出 = _原收输出.pop("f")
    _态表.pop(id(栈类), None)
    return {"好": True, "为什么": "雷达交还给主链，我不看门了", "打了": list(原)}


def 同步实例(bridge, 日志=None, 车钩=None):
    """本车厢**不持有任务进度** —— 进度在主链的任务栈里，所以热插拔不丢东西。

    这里只是报一句现状，方便主人从车钩日志里看出它在干嘛。
    """
    try:
        栈类 = getattr(bridge, "任务栈", None)
        态 = _态表.get(id(栈类), {})
        记 = (态.get("发了几次") or {})
        if 日志 and 记:
            日志(f"挖空守卫：正在盯着 {len(记)} 格（每格都记着发了几次 dig）")
    except Exception:
        pass
    return {"好": True, "为什么": "无状态，随便拔", "打了": []}
