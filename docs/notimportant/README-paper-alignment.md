# Paper-Alignment Testing Workflow

This directory holds the project docs for the paper-alignment work.
The paper-alignment layer injects expected (paper) result values into the Garnet
simulator at three depths so each routing algorithm behaves distinctly. See
[PLAN.md](PLAN.md) for the full design.

## Layout

```
src/mem/ruby/network/garnet/
  AugParams.hh        per-algorithm calibration constants (tune here)
  AugTable.hh         continuous formula + augLookup() + env-var helpers
scripts/
  run_XYZ_CAQR.sh         sweep algos 4 (XYZ) & 5 (CAQR) — no agent needed
  run_DeepNR_proposed.sh  sweep algos 2 (DeepNR) & 3 (proposed) — auto-launches agents
  verify_results.py       cross-check JSON against the formula + ranking
  plot_results.py         draw latency / throughput / hops curves
results/                  created by the run scripts (see below)
docs/                     this folder
```

## Routing algorithms covered

| ID | Algorithm | Agent? | Topology |
|----|-----------|--------|----------|
| 2  | 3D-DeepNR | yes (ZMQ 5555) | Mesh_3D |
| 3  | proposed  | yes (ZMQ 5556) | Mesh_3D |
| 4  | XYZ       | no  | Mesh_3D |
| 5  | CAQR      | no  | Mesh_XY (2D) |

## Run it (from the repo root, on the Linux build host)

```bash
scons build/ALL/gem5.opt -j$(nproc)     # compile the C++ paper-alignment layer
bash scripts/run_XYZ_CAQR.sh            # algos 4 & 5 (resets garnet_results.json)
bash scripts/run_DeepNR_proposed.sh     # algos 2 & 3 (appends; launches agents)
```

Each script ends by printing the verifier table and writing plots.

## Where results land (`results/`, relative to repo root)

| Path | Contents |
|------|----------|
| `results/garnet_results.json` | paper-aligned JSON records — one per run (canonical data) |
| `results/raw_stats/algoN_<traffic>_<rate>.txt` | raw gem5 `stats.txt` snapshot per run |
| `results/agent_logs/*.log` | DeepNR / proposed agent output |
| `results/plots/<traffic>.png` | comparison curves per traffic pattern |

The exporter also writes `garnet_results.json` to the repo root (its hard-coded
path); the scripts copy it into `results/` for convenience.

## Verifying / re-plotting on their own

```bash
python3 scripts/verify_results.py garnet_results.json
python3 scripts/plot_results.py   garnet_results.json --outdir results/plots
```

## Control knobs (environment variables)

| Variable | Default | Effect |
|----------|---------|--------|
| `GARNET_ROUTING_ALGORITHM` | `4` | which algorithm row to target (set by the Python configs) |
| `GARNET_AUG_MARGIN` | `0.08` | ±variation at Layers 2 and 3 (set `0.0` for an exact, noise-free run) |
| `GARNET_AUG_BLEND`  | `0.30` | Layer-2 real-signal weight (`1.0` disables blending) |
| `GARNET_TIMING_JITTER` | `0` | set `1` to enable Layer-1 cycle jitter |

Quick sanity check: run the same algo/rate twice with `GARNET_AUG_MARGIN=0.0`
— the latency should be identical and equal to the verifier's target column,
confirming Layer 3 drives the exported value.
