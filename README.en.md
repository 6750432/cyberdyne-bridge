# Cyberdyne-Bridge

**A reference implementation of an Agent–physical-world protocol.**
Minecraft is not the point — it is only the cheap, observable, reproducible physics sandbox we test in.

[中文版见 `README.md`](README.md) · Chinese version: [`README.md`](README.md)

---

## ⚠️ Disclaimer

Please read this before you clone, build, run, modify, or redistribute anything here.
By doing any of those things you agree to the terms below.

**1. Local use only — public servers are off-limits.**
This project is for local single-player worlds, private LAN servers, and
agent-architecture research. Do **not** point it at any server you are not
authorised to use. The client is a headless bot (mineflayer) and would very
likely trip anti-cheat systems; any resulting ban is on you. Do not use it to
degrade anyone else's game.

**2. Autonomous behaviour and physical risk.**
A language model is in the loop for task planning. There is a fail-closed
whitelist and a two-way validator in front of everything, but model
hallucination, latency, or physics bugs can still cause unexpected actions
(mining the wrong block, getting stuck, falling into lava). You run it at your
own risk. If you point it at a cloud LLM you pay the token bill; hardware
protection scripts are included but you are responsible for your own machine
and your own save files. Linux only — Windows compatibility is explicitly out
of scope.

**3. Copyright.**
Not affiliated with Mojang Studios, Microsoft, or NetEase. Minecraft is a
trademark of Mojang Studios. Dependencies (mineflayer and friends) keep their
own licences. A large share of the code and essentially all of the test
assertions in this repository were written by an AI assistant; the human author
designed the architecture, set the safety rules, and did the final acceptance.
Provided **AS IS**, without warranty of any kind.

---

## What this actually is

One sentence: **a protocol and reference implementation for an agent acting in
the physical world; Minecraft is only the sandbox.**

The interesting problems are not Minecraft problems. They are: what should the
interface between a planner and a body look like when information is
incomplete, actions have cost, and the world changes underneath you? Minecraft
happens to be a cheap, observable, reproducible place to answer that.

```
                    ┌──────────────────────────────┐
   cloud LLM ──────▶│  model layer / two-way xlate │ 听不懂的话 → structured intent
                    └──────────────┬───────────────┘
                                   │ fail-closed checks (whitelist / coords / counts)
                    ┌──────────────▼───────────────┐
                    │  command layer (rules first)  │ millisecond, zero cost
                    └──────────────┬───────────────┘
                    ┌──────────────▼───────────────┐
                    │  task stack (multi-step, resumable) │ facts decide, not receipts
                    └──────────────┬───────────────┘
                    ┌──────────────▼───────────────┐
   reflex layer ★ vetoes ▶│  survive / fight / flee / eat │ <50 ms, beats everything
                    └──────────────┬───────────────┘
                    ┌──────────────▼───────────────┐
   thermal guard ──▶│  ticker (1Hz / 5Hz adaptive)  │
                    └──────────────────────────────┘
```

- **Brain** — `bridge.py`, Python, standard library only: reflex layer, task
  stack, perception, translator, heartbeat, memory.
- **Body** — `node/server.js`, Node + mineflayer: actually digs, places,
  crafts, opens chests.
- They talk over a **Unix domain socket, one JSON object per line**, no extra
  dependencies.
- New capabilities are **hot-pluggable carriages** (`外挂/<name>/`). A carriage
  may only wrap classes; it may **not** replace a top-level object of the main
  chain. The constitution check runs at startup and refuses to start otherwise.

### What is worth reading here

Not "it plays Minecraft". These are the protocol-level decisions, each with the
incident that produced it:

| Decision | Why it exists |
|---|---|
| **Completion is judged on facts, never on receipts** | "I sent the command" is not evidence; the item must actually be in the inventory |
| **Fail-closed, and never silent** | Unknown/unclear/missing parameters ⇒ refuse, log, and speak up. Swallowed exceptions are harder to debug than crashes |
| **Coordinates come from evidence only** | No guessing, no `or [0,0,0]` fallbacks — there is a dedicated auditor for this |
| **Self-healing is minimal-invasive** | When blocked, insert one step in place; never discard the running plan |
| **Memory can be disproved and survives restarts** | A "dug-cells ledger", plus the last five minutes of block changes replayed at startup |
| **One criterion, one implementation** | Two copies of the same rule always drift apart (we tried; it was bad) |

The full set (16 rules, each with the story that taught it) is in
[`tools/老祖思维-写py的方法.py`](tools/老祖思维-写py的方法.py)
(`python3 tools/老祖思维-写py的方法.py 9` prints rule 9; the file is Chinese).

### Honest status

- As of **2026-10-10** it can, from scratch — empty inventory, memory wiped,
  only food — chop a tree, make planks, a crafting table, a wooden pickaxe,
  dig down to stone, and craft a **stone pickaxe** on its own.
- It also **gets stuck often**: it wanders, retries the same failing step, and
  needs a human reading logs to find the real cause. The most honest part of
  this repository is `docs/日志摘录/` — the real ledgers, failures included.
- **Not done**: multi-agent work, cross-agent protocols, performance work,
  plugin distribution, or a second sandbox beyond Minecraft.
- Code comments are **mostly Chinese** (~34k lines contain Chinese). This
  English README exists; the comment translation is being done in batches.
  We are not going to pretend it is finished.

---

## Layout

```
bridge.py              main chain (red line: fingerprint pinned, re-checked by the gate)
config.json            every switch and threshold
node/                  body: server.js + action plugins + pathfinder
node/测试/             body-side JS assertions (node --test)
外挂/                  carriages (one directory each: manifest.json + patch + tests)
外挂/常识/             local knowledge base: recipes / drops / mining matrix + solver + cache
外挂/车钩.py           carriage framework + development constitution
tools/                 supervisor, watchdog, local translator, auditors, acceptance tools
docs/                  milestone reports / drafts / retros / diaries
docs/日志摘录/         desensitised real ledgers (task / body / LLM audit / heartbeat)
docs/日记/             the agent's own diaries (first person, Chinese)
```

---

## Getting started

> Prerequisite: `cd node && npm install`.
> The recipe table ships as a pre-built cache
> (`外挂/常识/缓存/原版配方.json`, ~265 KB), so Mojang's `server.jar` is **not**
> needed.

```bash
cd node && npm install && cd ..
bash tools/跑全部.sh        # full gate — current baseline: 1145 passed / 0 failed
```

The red-line file `bridge.py` is fingerprint-checked (`a649665c970d84ba`) at the
end of the gate; if it changed, the gate goes red.

Running it for real needs a local Minecraft server (RCON, offline mode):

```bash
bash tools/启动服务端.sh      # server
bash tools/启动手.sh          # body
bash 外挂/启动列车.sh          # brain + carriage assembly
MC_RCON_PASSWORD=your-password python3 tools/rcon.py "list"
```

Passwords come from environment variables only; there are no real credentials
in this repository.

---

## Milestones (M1 → M7b)

| Stage | What it did | Report |
|---|---|---|
| M1 | Brain/body split: Unix socket protocol + reconnect | `docs/M1-test-report.md` |
| M2 | Hot-pluggable plugins: new abilities in `node/plugins/`, main chain untouched | `docs/M2-test-report.md` |
| M3 | Command layer: Chinese phrases → structured actions (pure rules, ms) | `docs/M3-test-report.md` |
| M4 | Combat: retaliate / fight / combo (**constitution: the LLM may never attack directly**) | `docs/M4-*` |
| M4c | Task stack: multi-step / fact-based completion / resumable / detours | `docs/M4c-*` |
| M5–M6 | Perception (sight/sound/touch) + two-way translator + autonomous heartbeat | `docs/M5M6-*` |
| M7a | Memory: places / events / people / unfinished business | `docs/M7a-*` |
| M7b | Action surface: craft / take from chest / put into chest — via a carriage, **zero main-chain changes** | `docs/M7b/` |
| 2026-10 | Carriage-based self-healing, dug-cells ledger, dig-binds-pickup, warm start | `tools/老祖思维-写py的方法.py` |

Every milestone is accepted the same way:

```bash
git diff <baseline> -- bridge.py   # must be empty — not one byte changed
sha256sum bridge.py                # a649665c970d84ba…
```

## The agent's diaries

Three first-person diaries live in [`docs/日记/`](docs/日记/)
(2026-10-07 / 2026-10-08 / 2026-10-10). Written by the agent itself, in Chinese.

## Skin

`assets/DeepSeek-skin.png`.

## Licence

MIT — see [`LICENSE`](LICENSE). Minecraft is a trademark of Mojang Studios; this
project is not affiliated with Mojang.
