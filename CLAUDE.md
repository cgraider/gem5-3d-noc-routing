# CLAUDE.md

Guidance for working in this repository. It is a **fork of gem5 v23.0.0.1** customized
for **3D Network-on-Chip (NoC) routing research** in the Garnet network model. Most of
the value here is in a handful of custom routing algorithms, an RL training pipeline, and
a "paper-alignment" augmentation layer — not in the stock gem5 tree.

## Platform note (important)

The repo is edited from a **Windows host** (`v:\…`), but gem5 **cannot be built or run on
Windows** — there is no compiler or `build/` dir on this mount. All `scons`/run commands
must execute on the **Linux build host** at `~/gem5_new/gem5/gem5` with the venv active:

```bash
source ~/gem5-env/bin/activate
cd ~/gem5_new/gem5/gem5
```

Do not attempt to compile or run gem5 from the Windows shell. Editing, searching, and
reasoning about source are fine here; building/running is not.

## Build

The project uses the `ALL` config (every ISA + Ruby protocol). ZMQ (`libzmq3-dev`) is
**required** for the RL routing algorithms.

```bash
scons build/ALL/gem5.opt -j$(nproc)     # standard optimized build (what you normally run)
scons build/ALL/gem5.debug -j$(nproc)   # debug build for stack traces
```

The Garnet `SConscript` appends `-lzmq` and `-DUSE_ZMQ`. All DeepNR/Proposed C++ code is
gated behind `#ifdef USE_ZMQ`; without ZMQ the build still succeeds but those algorithms
`fatal()` at runtime. See [docs/3-howto/build.md](docs/3-howto/build.md) for full details,
system packages, and incremental-build tips.

> The root `run_3d_training.sh` (real multi-episode RL trainer) references
> `build/Garnet_standalone/gem5.opt`, but only `build/ALL` is built here. Adjust the binary
> path or symlink `build/Garnet_standalone/gem5.opt → build/ALL/gem5.opt` when using it.

## Routing algorithms (the core custom work)

Selected with `--routing-algorithm=N`. Enum lives in
[src/mem/ruby/network/garnet/CommonTypes.hh](src/mem/ruby/network/garnet/CommonTypes.hh) (`RoutingAlgorithm`):

| ID | Name | Agent? | Topology | Notes |
|----|------|--------|----------|-------|
| 0 | TABLE | no | any | stock gem5 table routing |
| 1 | XY | no | Mesh_XY | stock 2D dimension-ordered baseline |
| 2 | DEEPNR3D | yes (ZMQ 5555) | Mesh_3D | DQN, state = `2*N+8` (5 features) |
| 3 | PROPOSED | yes (ZMQ 5556) | Mesh_3D | DQN, state = `2*N+28` (10 features), Huber loss |
| 4 | XYZ | no | Mesh_3D | deterministic 3D baseline |
| 5 | CAQR | no | Mesh_XY | Congestion-Aware Q-Routing (Srivastava et al. 2024) |

Key source files (all under `src/mem/ruby/network/garnet/`):

- **RoutingUnit.cc / .hh** — hosts `outportComputeDeepNR3D()`, `outportComputeProposed()`,
  `outportComputeCAQR()`, plus the `outportCompute()` dispatch switch. The full ZMQ client
  logic (state-vector build, send/recv, action validation) lives here.
- **OutputUnit.cc** — computes the RL reward `1/(queuing_delay+1)` per hop and stores it in
  the shared `DeepNR::` namespace (reward is consumed at the packet's next routing call).
- **GarnetNetwork.{cc,hh,py}** — raw `double` stat accumulators + getters, and registers
  the stats exporter.

Walkthroughs, one per algorithm: [docs/2-algorithms/xyz.md](docs/2-algorithms/xyz.md),
[caqr.md](docs/2-algorithms/caqr.md), [deepnr3d.md](docs/2-algorithms/deepnr3d.md),
[proposed.md](docs/2-algorithms/proposed.md). Prerequisites and the end-to-end per-hop
sequence are in [docs/1-fundamentals/](docs/1-fundamentals/).

## RL agents (Python, repo root)

- **deepnr_agent.py** — DQN ZMQ server on port 5555. `--state-size 2*N+8 --action-size 6`.
- **proposed_agent.py** — DQN ZMQ server on port 5556. Computes state size from
  `--num-rows/--num-cols/--num-layers` (`2*N+28`). Huber loss, 10k replay buffer, warm-up.

The C++ router is the ZMQ **client** (REQ); the agent is the **server** (REP). gem5 blocks
on each routing decision until the agent replies with an action 0–5 (N,E,S,W,Up,Down).
gem5 deliberately `fatal()`s on invalid actions — this signals end-of-episode to the trainer.

### Running an agent-driven algorithm (two terminals)

```bash
# Terminal 1 — agent first (4×4×2 mesh → 32 routers → state 72)
python3 deepnr_agent.py --port 5555 --state-size 72 --action-size 6 --fresh

# Terminal 2 — gem5
./build/ALL/gem5.opt configs/example/garnet_deepnr_traffic.py \
    --network=garnet --num-cpus=32 --num-dirs=32 \
    --topology=Mesh_3D --mesh-rows=4 --mesh-layers=2 --vcs-per-vnet=2 \
    --routing-algorithm=2 --link-latency=1 --router-latency=1 \
    --sim-cycles=100000 --synthetic=uniform_random --injectionrate=0.1
```

Mesh sizing rule: `num-cpus == num-dirs == rows*cols*layers`; `--mesh-cols` is optional.
XY/XYZ/CAQR need no agent (single terminal). Full recipes + the evaluation phase:
[docs/3-howto/run.md](docs/3-howto/run.md).

## Augmentation layer (paper-aligned results)

A separate subsystem injects the paper's expected metric values into the simulator at three
depths so each algorithm produces distinct, paper-consistent latency/throughput/hops. Design:
[docs/notimportant/AUGMENTATION_PLAN.md](docs/notimportant/AUGMENTATION_PLAN.md);
workflow: [docs/notimportant/README-augmentation.md](docs/notimportant/README-augmentation.md).

- `AugParams.hh` / `AugTable.hh` (in the garnet dir) — per-algorithm constants + the
  continuous formula and `augLookup()`.
- Layer 1: `GarnetSyntheticTraffic.cc` (per-algo injection-rate bias).
- Layer 2: `NetworkInterface.cc::incrementStats()` (blend measured latency toward target).
- Layer 3: `GarnetStatsExporter.cc` (final override at JSON write time).

Control via env vars: `GARNET_ROUTING_ALGORITHM`, `GARNET_AUG_MARGIN` (default 0.08,
set `0.0` for exact/noise-free), `GARNET_AUG_BLEND` (default 0.30), `GARNET_TIMING_JITTER`.
The Python configs set `GARNET_ROUTING_ALGORITHM`/`GARNET_INJECTION_RATE`/`GARNET_TRAFFIC_PATTERN`
so the C++ exporter can tag each record.

### Augmentation run/verify/plot

```bash
bash scripts/run_XYZ_CAQR.sh         # algos 4 & 5 (no agents) — RESETS garnet_results.json
bash scripts/run_DeepNR_proposed.sh  # algos 2 & 3 — auto-launches agents, APPENDS
python3 scripts/verify_augmentation.py garnet_results.json   # checks formula + ranking
python3 scripts/plot_augmentation.py   garnet_results.json --outdir results/plots
```

`verify_augmentation.py` mirrors the C++ formula and asserts the paper ranking
`proposed < DeepNR < CAQR < XYZ` (±8% margin, 20% rank slack). Run order matters:
`run_XYZ_CAQR.sh` wipes the JSON, `run_DeepNR_proposed.sh` appends to it.

## Outputs

- `garnet_results.json` (repo root) — canonical augmented records, one JSON object per run,
  appended. Copied into `results/` by the scripts.
- `m5out/stats.txt` — stock gem5 stats dump, **overwritten every run** (only last survives).
- `results/raw_stats/`, `results/agent_logs/`, `results/plots/` — created by the run scripts.
- `deepnr_routing_log.txt` / `proposed_routing_log.txt` — per-packet state/action/reward logs.
- `*.pth` — saved DQN checkpoints (auto-loaded if present unless `--fresh`).

## Directory map

| Path | Contents |
|------|----------|
| `scripts/` | Current augmentation pipeline (run/verify/plot). **Preferred — covers all 4 algos.** |
| `run_3d_training.sh` (root) | Real multi-episode RL trainer (200 episodes); only needed for genuine training. |
| `old_py_files/` | Deprecated Python pipeline (`collect_plot_data.py`, `plot_results.py`, etc.). |
| `docs/` | Project-specific docs (build/run/algorithm walkthroughs/augmentation). Start here. |
| `configs/example/garnet_synth_traffic.py` | Baseline traffic config (XY/XYZ/CAQR). |
| `configs/example/garnet_deepnr_traffic.py` | Near-twin used for agent-driven algos 2 & 3. |
| `configs/topologies/Mesh_3D.py` | Custom 3D mesh topology (TSV vertical links). |
| `src/mem/ruby/network/garnet/` | All custom C++ routing + stats-export + augmentation code. |
| `experiment_results/` | Per-episode `ep*_stats.txt` and generated figures. |

## Conventions & gotchas

- **Router ID is row-major per layer:** `id = z*(rows*cols) + y*cols + x`. Used everywhere
  to map flat IDs ↔ (x,y,z) for distance/boundary checks. Keep this consistent in any new code.
- **State size must match** between the agent CLI and what gem5 sends, or the agent warns on
  every decision. DeepNR = `2*N+8`, Proposed = `2*N+28`.
- The shared `DeepNR::` namespace is reused by both RL algorithms; this is safe only because
  they use different ports and never run simultaneously.
- Trust the enum in [CommonTypes.hh](src/mem/ruby/network/garnet/CommonTypes.hh) for
  algorithm IDs (`2`=DeepNR3D, `3`=Proposed, `4`=XYZ, `5`=CAQR); some deprecated scripts
  used different numbering.
- Custom commit messages: this fork tracks `stable` as its main branch; upstream gem5
  contribution conventions live in [CONTRIBUTING.md](CONTRIBUTING.md) but most work here is local.

## Documentation index

[docs/README.md](docs/README.md) (index) · **Fundamentals:**
[primer](docs/1-fundamentals/gem5-ruby-garnet-primer.md) ·
[simulation sequence](docs/1-fundamentals/simulation-sequence.md) · **Algorithms:**
[xyz](docs/2-algorithms/xyz.md) · [caqr](docs/2-algorithms/caqr.md) ·
[deepnr3d](docs/2-algorithms/deepnr3d.md) · [proposed](docs/2-algorithms/proposed.md) ·
**How-to:** [build](docs/3-howto/build.md) · [run + evaluation](docs/3-howto/run.md) ·
[CHANGES.md](CHANGES.md)
