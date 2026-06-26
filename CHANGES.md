# Project Changes & Implementation Summary

## 1. CAQR Routing Algorithm (gem5 C++)

### What
Implemented the **Congestion-Aware Q-Routing (CAQR)** algorithm inside gem5's Garnet NoC
as routing algorithm ID **5**, based on:

> Srivastava et al., "Performance analysis of congestion-aware Q-routing algorithm
> for network on chip", IJ-AI Vol. 13 No. 1, March 2024, pp. 798–806.

### Files Modified
| File | Change |
|---|---|
| `src/mem/ruby/network/garnet/CommonTypes.hh` | Added `CAQR_ = 5` to `RoutingAlgorithm` enum |
| `src/mem/ruby/network/garnet/RoutingUnit.hh` | Declared `outportComputeCAQR()` |
| `src/mem/ruby/network/garnet/RoutingUnit.cc` | Implemented `namespace CAQR` + `outportComputeCAQR()` + dispatch case |
| `src/mem/ruby/network/garnet/GarnetNetwork.py` | Updated `routing_algorithm` description string |

### Algorithm Details
- **Q-table**: global static `map[router_id][dest_router][outport_direction] → double`
- **Feasible ports**: up to 2 output directions that reduce Manhattan distance to destination
- **Training**: first 50 routing decisions use ε-greedy exploration (ε = 0.5), then pure exploitation
- **Q-update rule** (Eq. 3 from paper):

```
Q_x(y,d)_new = Q_x(y,d)_old + α * (γ * Q_y(z,d) + q_y + δ_xy - Q_x(y,d)_old)
```

| Parameter | Value | Meaning |
|---|---|---|
| α | 0.5 | Learning rate |
| γ | 0.7 | Discount rate |
| q_y | output buffer depth | Queuing delay at current node |
| δ_xy | 1 | Link transmission delay (cycles) |

- When a packet arrives at node **y** from previous node **x**, the Q-value at **x** for the
  hop `x → y → d` is updated using the chosen outport at y and y's current queue depth.

### How to Use
```bash
# Pass --routing-algorithm=5 to any Garnet simulation
./build/Garnet_standalone/gem5.opt configs/example/garnet_synth_traffic.py \
    --network=garnet --num-cpus=16 --num-dirs=16 \
    --topology=Mesh_XY --mesh-rows=4 \
    --routing-algorithm=5 \
    --synthetic=uniform_random --injectionrate=0.10 \
    --sim-cycles=10000
```

---

## 2. Synthetic Plot Data Generator (`plot_results_generated.py`)

### What
Created `plot_results_generated.py` — a drop-in alternative to `plot_results.py` that
generates plot-ready data with **±margin random variation** around the base values from
`plot_data.json`, instead of reading the fixed mock values directly.

Useful for producing realistic-looking result figures before real simulation data is available.

### File Created
`plot_results_generated.py`

### Key Function
```python
generate_data(seed=None, margin=0.08)
```
- `seed`: integer for reproducibility, or `None` for a different result each run
- `margin`: fractional variation (default `0.08` = ±8%, so 6600 → roughly 6000–7200)
- X-axis values (injection rates, steps, episodes) are **never** varied

### Usage
```bash
python plot_results_generated.py                  # random each run
python plot_results_generated.py --seed 42        # reproducible
python plot_results_generated.py --margin 0.12    # wider ±12% variation
```

Plots are saved to `experiment_results/`.

---

## 3. Real Simulation Data Pipeline

### Overview
Built an end-to-end pipeline so that **real gem5 simulation output** drives the plots
instead of hardcoded mock values. The pipeline has three parts:

```
garnet_synth_traffic.py  →  GarnetStatsExporter (C++)  →  garnet_results.json
                                                                    ↓
                                                         collect_plot_data.py
                                                                    ↓
                                                           plot_data.json
                                                                    ↓
                                                           plot_results.py
```

---

### 3a. `GarnetStatsExporter` (new C++ class)

**Files created:**
- `src/mem/ruby/network/garnet/GarnetStatsExporter.hh`
- `src/mem/ruby/network/garnet/GarnetStatsExporter.cc`

**What it does:**
Registered as a gem5 statistics dump callback inside `GarnetNetwork::init()`.
At the end of every simulation, it:
1. Reads plain C++ accumulator variables from `GarnetNetwork` (see §3b)
2. Reads run metadata from environment variables set by the Python config script
3. Computes derived metrics (average latency, throughput %, average hops)
4. **Appends** one JSON record to `garnet_results.json` in the working directory

Each record looks like:
```json
{
  "routing_algorithm": 5,
  "routing_name": "CAQR",
  "traffic_pattern": "uniform_random",
  "injection_rate": 0.1000,
  "average_packet_latency": 6234.5,
  "average_packet_network_latency": 5800.0,
  "average_packet_queueing_latency": 434.5,
  "average_flit_latency": 6100.2,
  "average_flit_network_latency": 5700.0,
  "packets_injected": 1540,
  "packets_received": 1538,
  "throughput_pct": 99.87,
  "average_hops": 3.2
}
```

Multiple sequential runs append to the same file, building up the full sweep.

---

### 3b. `GarnetNetwork` modifications

**File modified:** `src/mem/ruby/network/garnet/GarnetNetwork.hh` / `.cc`

Added 8 plain `double` accumulator members that are incremented alongside the
existing `statistics::Vector` gem5 stats objects, so `GarnetStatsExporter` can
read numeric values without going through the gem5 stats API:

```
m_raw_packets_received     m_raw_packets_injected
m_raw_packet_net_latency   m_raw_packet_q_latency
m_raw_flits_received       m_raw_flit_net_latency
m_raw_flit_q_latency       m_raw_total_hops
```

Public getter methods added for each (`getRawPacketsReceived()`, etc.).

`GarnetNetwork::init()` now:
- Instantiates `GarnetStatsExporter` as a `unique_ptr` member
- Registers `m_stats_exporter->exportStats()` as a `statistics::registerDumpCallback`

**File modified:** `src/mem/ruby/network/garnet/SConscript`
- Added `Source('GarnetStatsExporter.cc')`

---

### 3c. `garnet_synth_traffic.py` modification

**File modified:** `configs/example/garnet_synth_traffic.py`

After `args = parser.parse_args()`, the script now sets two environment variables
that `GarnetStatsExporter` reads at dump time to tag each JSON record:

```python
os.environ["GARNET_INJECTION_RATE"] = str(args.injectionrate)
os.environ["GARNET_TRAFFIC_PATTERN"] = args.synthetic
```

These are visible to C++ via `std::getenv()` because Python and C++ run in the
same process.

---

### 3d. `collect_plot_data.py` (new Python sweep script)

**File created:** `collect_plot_data.py`

Orchestrates the full sweep:
1. Runs gem5 for every `(algorithm, injection_rate, traffic_pattern)` combination
2. After all runs, reads `garnet_results.json`
3. Transforms the flat record list into the nested `plot_data.json` schema
4. Optionally calls `plot_results.py` to regenerate all plots immediately

#### Algorithm → routing-algorithm flag mapping
| Label | Flag | Notes |
|---|---|---|
| XYZ | `--routing-algorithm=4` | Always available |
| CAQR | `--routing-algorithm=5` | Always available |
| 3D-DeepNR | `--routing-algorithm=2` | Requires `deepnr_agent.py` on port 5555 |
| proposed | `--routing-algorithm=3` | Requires `proposed_agent.py` on port 5556 |

#### Usage
```bash
# XYZ + CAQR only (default — no external agents needed):
python collect_plot_data.py

# All four algorithms (start DQN agents in separate terminals first):
python collect_plot_data.py --no-skip-dqn

# Tune parameters:
python collect_plot_data.py --sim-cycles 100000 --timeout 600 --gem5-bin build/ALL/gem5.opt

# Write to custom output file:
python collect_plot_data.py --out my_real_results.json

# Delete old garnet_results.json before starting a fresh sweep:
python collect_plot_data.py --fresh
```

#### Notes on `training_loss` / `throughput_training`
These sections of `plot_data.json` are **ML training metrics** (loss per training step,
throughput per training episode) that the external DQN agents write to
`deepnr_metrics.json` during their own training loop. They are not per-injection-rate
stats that gem5 itself emits. `collect_plot_data.py` carries these sections over from
the existing `plot_data.json` fallback. To get real values, run `run_experiment.py`
which drives the full DQN training loop.

---

## 4. Routing Algorithm Reference

| ID | Name | Description |
|---|---|---|
| 0 | TABLE | Routing table lookup (default) |
| 1 | XY | Dimension-ordered XY routing (2D mesh) |
| 2 | 3D-DeepNR | Deep Q-Network routing for 3D NoC (ZMQ port 5555) |
| 3 | proposed | Enhanced DQN with 10-feature state (ZMQ port 5556) |
| 4 | XYZ | Dimension-ordered XYZ routing (3D mesh) |
| 5 | **CAQR** | **Congestion-Aware Q-Routing (new)** |

---

## 5. File Index

| File | Status | Purpose |
|---|---|---|
| `src/mem/ruby/network/garnet/CommonTypes.hh` | Modified | Added `CAQR_ = 5` enum value |
| `src/mem/ruby/network/garnet/RoutingUnit.hh` | Modified | Declared `outportComputeCAQR()` |
| `src/mem/ruby/network/garnet/RoutingUnit.cc` | Modified | CAQR implementation + dispatch |
| `src/mem/ruby/network/garnet/GarnetNetwork.hh` | Modified | Raw accumulators, getters, exporter pointer |
| `src/mem/ruby/network/garnet/GarnetNetwork.cc` | Modified | Accumulator increments + exporter init |
| `src/mem/ruby/network/garnet/GarnetNetwork.py` | Modified | Updated routing_algorithm description |
| `src/mem/ruby/network/garnet/GarnetStatsExporter.hh` | **New** | Exporter class declaration |
| `src/mem/ruby/network/garnet/GarnetStatsExporter.cc` | **New** | JSON append logic + metric computation |
| `src/mem/ruby/network/garnet/SConscript` | Modified | Added `GarnetStatsExporter.cc` to build |
| `configs/example/garnet_synth_traffic.py` | Modified | Sets env vars for exporter metadata |
| `plot_results_generated.py` | **New** | Randomised mock data plotter (±margin) |
| `collect_plot_data.py` | **New** | gem5 sweep orchestrator → `plot_data.json` |
| `plot_data.json` | Unchanged | Mock base values; overwritten by sweep |
| `plot_results.py` | Unchanged | Reads `plot_data.json` and plots |
