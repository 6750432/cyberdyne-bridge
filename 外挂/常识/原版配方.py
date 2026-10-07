#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""常识库·原版配方 —— 直接读服务端 jar 里那 1290 条配方（+ 147 个标签）。

┌───────────────────────────────────────────────────────────────────┐
│ 为什么放着 minecraft-data 不用，要自己拆 jar                      │
└───────────────────────────────────────────────────────────────────┘
`minecraft-data` 的 `recipes.json` **只有合成**（782 条），而原版有：

    crafting_shaped 634 ／ crafting_shapeless 253 ／ stonecutting 250
    ★ smelting 70 ／ blasting 24 ／ smoking 9 ／ campfire_cooking 9
    smithing_transform 9 ／ smithing_trim 18 ／ crafting_special 11

少了烧炼那一整类，「挖钻石」这条路就是断的：
    钻石镐 ← 钻石 ← 钻石矿（要铁镐）← 铁锭 ← **烧炼**生铁  ← 断在这儿

★ 而且 jar 版还更**干净**：`minecraft-data` 把「木镐」展开成了 11 条
  （每种木板一条，没有 tag），jar 版就一条 `wooden_pickaxe.json`，
  用料写的是 `#minecraft:planks` 这个**标签**。
  jar 里同时带着 `data/minecraft/tags/item/*.json`（147 个），
  所以「哪些木板可以互换」**由原版自己说了算**，不用我们去推。

┌───────────────────────────────────────────────────────────────────┐
│ 数据在哪                                                          │
└───────────────────────────────────────────────────────────────────┘
    runtime/server.jar                                   ← bundler（51 MB）
      └─ META-INF/versions/1.21.1/server-1.21.1.jar      ← 真身（12951 个条目）
           data/minecraft/recipe/*.json    1290 条
           data/minecraft/tags/item/*.json  147 个

★ 读它只用标准库 `zipfile` + `json` —— **依然零新依赖**。
★ 实测：读 + 解析全部 179 ms。所以解析结果**落盘缓存**（带 jar 指纹校验），
  第二次载入就是读一个 JSON。
"""

import io
import json
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
缓存目录 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "缓存")
缓存文件 = os.path.join(缓存目录, "原版配方.json")

# 只认这几种「能落成步骤」的加工方式。crafting_special_* 是特殊合成
# （染色、复制地图、烟花……），材料模型对不上，**明确跳过并记数**，不硬凑。
能用的方式 = {
    "minecraft:crafting_shaped": ("合成", False),
    "minecraft:crafting_shapeless": ("合成", False),
    "minecraft:smelting": ("烧炼", True),
    "minecraft:campfire_cooking": ("营火", True),
    "minecraft:blasting": ("高炉", True),
    "minecraft:smoking": ("烟熏", True),
    "minecraft:stonecutting": ("切石", True),
    "minecraft:smithing_transform": ("锻造", True),
}


def _剥(名):
    """`minecraft:oak_log` → `oak_log`"""
    if not isinstance(名, str):
        return None
    return 名.split(":", 1)[-1]


def _物(节点):
    """一个「用料槽」→ 具体物品名（`oak_planks`）或标签（`#planks`）。

    原版里一个槽可能是：
        "minecraft:stick"      （字符串）
        {"item": "…"}          （对象）
        {"tag": "…"}           （★ 标签 = 一族可互换的东西）
        [ {…}, {…} ]           （数组 = 任选其一，取第一个当代表）
    """
    if 节点 is None:
        return None
    if isinstance(节点, list):
        for x in 节点:
            r = _物(x)
            if r:
                return r
        return None
    if isinstance(节点, str):
        return _剥(节点)
    if isinstance(节点, dict):
        if "item" in 节点:
            return _剥(节点["item"])
        if "tag" in 节点:
            return "#" + (_剥(节点["tag"]) or "")
        if "id" in 节点:
            return _剥(节点["id"])
    return None


def _加(料, 名, n=1):
    if 名:
        料[名] = 料.get(名, 0) + n


def _解析一条(d):
    """一条原版配方 → 我们的形状。不认识的返回 None。"""
    t = d.get("type") or ""
    if t not in 能用的方式:
        return None
    方式, 需要设备 = 能用的方式[t]

    结 = d.get("result")
    产物 = _物(结 if not isinstance(结, dict) else {"id": 结.get("id") or 结.get("item")})
    产出数 = 1
    if isinstance(结, dict):
        产出数 = int(结.get("count") or 1)
    if not 产物:
        return None

    料 = {}
    形状 = None

    if t == "minecraft:crafting_shaped":
        图案 = d.get("pattern") or []
        键 = d.get("key") or {}
        形状 = list(图案)
        for 行 in 图案:
            for 字 in 行:
                if 字 and 字 != " ":
                    _加(料, _物(键.get(字)))
        if not 料:
            return None
    elif t == "minecraft:crafting_shapeless":
        for c in (d.get("ingredients") or []):
            _加(料, _物(c))
        if not 料:
            return None
    elif t in ("minecraft:smelting", "minecraft:campfire_cooking",
               "minecraft:blasting", "minecraft:smoking", "minecraft:stonecutting"):
        _加(料, _物(d.get("ingredient")))
        if not 料:
            return None
    elif t == "minecraft:smithing_transform":
        for k in ("template", "base", "addition"):
            _加(料, _物(d.get(k)))
        if not 料:
            return None

    return {
        "产物": 产物,
        "产出数": 产出数,
        "方式": 方式,
        "需要设备": 需要设备,          # 烧炼这类要熔炉/高炉/切石机
        "设备": {"烧炼": "furnace", "营火": "campfire", "高炉": "blast_furnace",
                "烟熏": "smoker", "切石": "stonecutter", "锻造": "smithing_table"
                }.get(方式),
        "要台子": bool(形状) and (len(形状) > 2 or max(len(r) for r in 形状) > 2),
        "材料": 料,
        **({"形状": 形状} if 形状 else {}),
    }


# ══════════════════════════ 找 jar ══════════════════════════

def 找jar():
    """找到服务端 bundler jar 里的**内层**真身。找不到就报清楚，不静默兜底。"""
    起 = os.path.join(ROOT, "runtime")
    外 = os.path.join(起, "server.jar")
    if not os.path.isfile(外):
        raise FileNotFoundError(f"找不到服务端 jar：{外}")
    指纹 = f"{os.path.getsize(外)}-{int(os.path.getmtime(外))}"
    return 外, 指纹


def _读jar(外):
    z = zipfile.ZipFile(外)
    内层 = [n for n in z.namelist()
           if n.startswith("META-INF/versions/") and n.endswith(".jar")]
    if not 内层:
        raise FileNotFoundError(f"{外} 里没有 META-INF/versions/*/*.jar —— 它可能不是 bundler")
    z2 = zipfile.ZipFile(io.BytesIO(z.read(内层[0])))

    标签 = {}
    for n in z2.namelist():
        if n.startswith("data/minecraft/tags/item/") and n.endswith(".json"):
            名 = n.split("/")[-1][:-5]
            try:
                d = json.loads(z2.read(n))
            except Exception:
                continue
            值 = []
            for v in (d.get("values") or []):
                if isinstance(v, str):
                    值.append(_剥(v))
                elif isinstance(v, dict) and "id" in v:
                    值.append(_剥(v["id"]))
            标签[名] = 值

    产物到配方, 跳过 = {}, {}
    for n in z2.namelist():
        if not (n.startswith("data/minecraft/recipe/") and n.endswith(".json")):
            continue
        try:
            d = json.loads(z2.read(n))
        except Exception:
            continue
        r = _解析一条(d)
        if r is None:
            跳过[d.get("type", "?")] = 跳过.get(d.get("type", "?"), 0) + 1
            continue
        产物到配方.setdefault(r["产物"], []).append(r)

    return {"配方": 产物到配方, "标签": 标签, "跳过": 跳过,
            "内层": 内层[0], "来源": 外}


# ══════════════════════════ 载入（带磁盘缓存） ══════════════════════════

_缓存 = None


def 载入(重载=False):
    """返回 {"配方": {产物: [r,…]}, "标签": {名: [物品,…]}, "跳过": {…}}。

    ★ 磁盘缓存按 jar 的「大小 + 修改时间」判新鲜度 —— jar 换了就自动重读。
      缓存故意放在 `外挂/常识/缓存/` 而不是仓库根，免得混进别的东西。
    """
    global _缓存
    if _缓存 is not None and not 重载:
        return _缓存

    外, 指纹 = 找jar()
    if not 重载 and os.path.isfile(缓存文件):
        try:
            with io.open(缓存文件, encoding="utf-8") as f:
                旧 = json.load(f)
            if 旧.get("指纹") == 指纹:
                _缓存 = 旧["数据"]
                _缓存["缓存命中"] = True
                return _缓存
        except Exception:
            pass

    d = _读jar(外)
    d["指纹"] = 指纹
    d["缓存命中"] = False
    try:
        os.makedirs(缓存目录, exist_ok=True)
        with io.open(缓存文件, "w", encoding="utf-8") as f:
            json.dump({"指纹": 指纹, "数据": d}, f, ensure_ascii=False)
    except Exception:
        pass                      # 存不下不影响用
    _缓存 = d
    return d


# ══════════════════════════ 命令行自检 ══════════════════════════

if __name__ == "__main__":
    import time
    t0 = time.time()
    d = 载入()
    t1 = time.time()
    print(f"来源：{os.path.relpath(d['来源'], ROOT)}")
    print(f"  └─ {d['内层']}")
    print(f"缓存命中：{d.get('缓存命中')}　耗时 {(t1 - t0) * 1000:.0f} ms")
    print(f"有配方的产物：{len(d['配方'])} 种")
    方式 = {}
    for 条们 in d["配方"].values():
        for r in 条们:
            方式[r["方式"]] = 方式.get(r["方式"], 0) + 1
    print("按加工方式：", dict(sorted(方式.items(), key=lambda x: -x[1])))
    print(f"标签：{len(d['标签'])} 个")
    print(f"跳过的类型：{d['跳过']}")
    print()
    print("═══ 拿关键几条看看 ═══")
    for 名 in ("wooden_pickaxe", "stone_pickaxe", "iron_ingot", "diamond_pickaxe", "stick"):
        条 = d["配方"].get(名) or []
        for r in 条[:2]:
            print(f"  {名:16s} [{r['方式']}] ← {r['材料']}"
                  f" ×{r['产出数']}" + ("（要台子）" if r["要台子"] else ""))
        if not 条:
            print(f"  {名:16s} （无）")
