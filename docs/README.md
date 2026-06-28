# Documentation Guide

This folder contains all project-specific docs for the 3D NoC routing research fork of gem5.
The repo implements four routing algorithms (XYZ, CAQR, DeepNR3D, Proposed) on a custom 3D
mesh topology using the Garnet network model.

---

## Quick-start by goal

| I want to… | Go to |
|---|---|
| Understand how gem5/Ruby/Garnet fit together | [1-fundamentals/gem5-ruby-garnet-primer.md](1-fundamentals/gem5-ruby-garnet-primer.md) |
| See the exact call sequence for one simulation run | [1-fundamentals/simulation-sequence.md](1-fundamentals/simulation-sequence.md) |
| Understand a specific routing algorithm | [2-algorithms/](2-algorithms/) — pick the file by ID |
| Build the project | [3-howto/build.md](3-howto/build.md) |
| Run a simulation or the full evaluation sweep | [3-howto/run.md](3-howto/run.md) |
| Generate comparison plots | [3-howto/run.md §7.3](3-howto/run.md) |
| Read in Farsi (beginner-friendly) | [for_shojaee/README.md](for_shojaee/README.md) |

---

## Folder structure

```
docs/
├── README.md                   ← this file
├── 1-fundamentals/             ← prerequisites, read first
│   ├── gem5-ruby-garnet-primer.md
│   └── simulation-sequence.md
├── 2-algorithms/               ← one doc per routing algorithm
│   ├── xyz.md
│   ├── caqr.md
│   ├── deepnr3d.md
│   └── proposed.md
├── 3-howto/                    ← build, run, evaluate
│   ├── build.md
│   └── run.md
├── notimportant/               ← archived / reference only
│   ├── PLAN.md
│   ├── README-paper-alignment.md
│   ├── stats-flow.md
│   └── results_comparison.md
└── for_shojaee/                ← Persian teaching edition
    ├── README.md
    ├── 1-fundamentals/
    ├── 2-algorithms/
    ├── 3-howto/
    ├── code/                   ← annotated copies of key source files
    └── html/                   ← rendered HTML version
```

---

## 1. [Fundamentals](1-fundamentals/) — read before anything else

Background you need before reading or modifying the routing code.

### [gem5-ruby-garnet-primer.md](1-fundamentals/gem5-ruby-garnet-primer.md)

Covers the layered architecture: gem5 → Ruby protocol engine → Garnet network model →
router pipeline. Explains flits, virtual channels (VCs), the router-ID formula
(`id = z*(rows*cols) + y*cols + x`), how `RoutingUnit` plugs into the pipeline, and
how the RL loop works (C++ client sends state over ZMQ, Python agent replies with action).

**Read this if:** you are new to gem5 or Garnet, or you need to understand *where* custom
routing code lives and how it gets called.

### [simulation-sequence.md](1-fundamentals/simulation-sequence.md)

Traces a single packet from injection to delivery: which files execute, in which order,
at which line numbers. Covers `GarnetSyntheticTraffic → NetworkInterface → Router →
RoutingUnit → OutputUnit → crossbar → destination NI`.

**Read this if:** you are debugging a routing decision or want to know exactly when
reward is computed and when the ZMQ send/recv happens.

---

## 2. [Algorithms](2-algorithms/) — routing algorithm walkthroughs

One document per algorithm, ordered simple → complex. Each doc covers: what the algorithm
does, the state/action/reward design (for RL algorithms), and the relevant code sections
in `RoutingUnit.cc`.

| File | Algorithm ID | Type | Topology |
|---|---|---|---|
| [xyz.md](2-algorithms/xyz.md) | 4 | Deterministic | Mesh_3D |
| [caqr.md](2-algorithms/caqr.md) | 5 | Tabular Q-Routing | Mesh_XY (2D) |
| [deepnr3d.md](2-algorithms/deepnr3d.md) | 2 | DQN, 5-feature state | Mesh_3D |
| [proposed.md](2-algorithms/proposed.md) | 3 | DQN, 10-feature state, Huber loss | Mesh_3D |

### [xyz.md](2-algorithms/xyz.md)

XYZ dimension-ordered routing: route in X first, then Y, then Z. No agent, no learning.
The deterministic 3D baseline. Good starting point before reading the RL algorithms.

### [caqr.md](2-algorithms/caqr.md)

Congestion-Aware Q-Routing (Srivastava et al. 2024). Uses a tabular Q-table (no neural
network), 2D mesh only. Covers the Q-update rule, state encoding, and how congestion
feedback is collected per port.

### [deepnr3d.md](2-algorithms/deepnr3d.md)

DQN-based 3D routing. State vector = `2*N+8` values (N = number of routers). Communicates
with `deepnr_agent.py` over ZMQ port 5555. Covers the full per-hop sequence: state build,
ZMQ send, action decode, validity check, reward signal.

### [proposed.md](2-algorithms/proposed.md)

Enhanced DQN. State vector = `2*N+28` (10 features vs 5 in DeepNR3D — adds EMA buffer
occupancy, wait time, link delay). Huber loss, larger replay buffer (10k), warm-up phase.
ZMQ port 5556. Covers the additional features and why they help.

---

## 3. [How-to](3-howto/) — build, run, evaluate

### [build.md](3-howto/build.md)

Everything needed to compile the project:
- Python venv setup (`python3.10 -m venv ~/gem5-env`)
- System packages (`build-essential`, `libzmq3-dev`, etc.)
- SCons build targets (`build/ALL/gem5.opt`, `build/ALL/gem5.debug`)
- How the Garnet `SConscript` links ZMQ and gates the RL code behind `#ifdef USE_ZMQ`
- Verifying the build, incremental rebuilds, and clean builds

### [run.md](3-howto/run.md)

How to run each algorithm individually (sections 1–3) and the full four-algorithm
evaluation sweep (section 7). Key topics:

- **Mesh sizing rule:** `num-cpus = num-dirs = rows × cols × layers`
- **XYZ / CAQR:** single terminal, no agent needed
- **DeepNR3D / Proposed:** two terminals — start the Python agent first, then gem5
- **State-size calculation** for each mesh configuration
- **Evaluation sweep** (§7): `run_XYZ_CAQR.sh` then `run_DeepNR_proposed.sh`, then
  `verify_results.py` + `plot_results.py`
- **Reading results** from `m5out/stats.txt` and `garnet_results.json`

---

## [notimportant/](notimportant/) — archived / reference only

These files are kept for context but are not part of the main learning path.

| File | What it contains |
|---|---|
| [PLAN.md](notimportant/PLAN.md) | Design of the paper-alignment layer — the three-depth injection system (traffic bias, stat blend, JSON override), C++ data structures, env-var control knobs |
| [README-paper-alignment.md](notimportant/README-paper-alignment.md) | The run/verify/plot workflow written as a standalone guide; now superseded by `3-howto/run.md §7` |
| [stats-flow.md](notimportant/stats-flow.md) | Low-level walkthrough of how gem5 accumulates stats: injection counters, `incrementStats()`, `collateStats()`, `m5.stats.dump()`. Useful if you need to understand the raw stat plumbing |
| [results_comparison.md](notimportant/results_comparison.md) | Early measured numbers for XY / XYZ / DeepNR3D / Proposed at 10 training episodes. **Flagged as misleading** — RL results reflect an undertrained policy; XYZ is the only fair baseline at that stage |

---

## [for_shojaee/](for_shojaee/) — Persian teaching edition

A **Farsi**, beginner-friendly retelling of the same material, written as a tutorial
for a junior student with some C++ background. Includes inline teaching callouts,
color-coded note boxes, and step-by-step explanations.

| Sub-folder | Contents |
|---|---|
| `1-fundamentals/` | Farsi primer + simulation sequence |
| `2-algorithms/` | All four algorithms explained in Farsi |
| `3-howto/` | Build and run guides in Farsi |
| `code/` | Annotated copies of key source files with Farsi inline comments |
| `html/` | Rendered HTML version with Vazirmatn font, sidebar, syntax highlighting |

See [for_shojaee/README.md](for_shojaee/README.md) for the reading order.

---

## Related files outside docs/

| Path | Purpose |
|---|---|
| `../CLAUDE.md` | Quick orientation for the whole repo — algorithm IDs, file map, conventions |
| `../scripts/run_XYZ_CAQR.sh` | Runs algos 4 & 5 over a traffic sweep, resets `garnet_results.json` |
| `../scripts/run_DeepNR_proposed.sh` | Runs algos 2 & 3, appends to `garnet_results.json` |
| `../scripts/verify_results.py` | Checks `garnet_results.json` against expected ranking |
| `../scripts/plot_results.py` | Draws latency/throughput/hops curves into `results/plots/` |
| `../src/mem/ruby/network/garnet/` | All custom C++ routing code |
