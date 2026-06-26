# How to Run DeepNR3D, Proposed, and XY Routing

All commands are run from inside `~/gem5_new/gem5/gem5` with the venv active:

```bash
source ~/gem5-env/bin/activate
cd ~/gem5_new/gem5/gem5
```

The routing algorithm is selected with `--routing-algorithm=N`:

| Value | Algorithm |
|---|---|
| 1 | XY (baseline, no agent needed) |
| 2 | DeepNR3D (agent on port 5555) |
| 3 | Proposed method (agent on port 5556) |

---

## Mesh sizing

The number of CPUs must equal `rows × cols × layers`. The number of directories must match too (set `--num-dirs` equal to `--num-cpus`).

```
4×4×2 mesh → --num-cpus=32 --num-dirs=32 --mesh-rows=4 --mesh-layers=2
4×4×4 mesh → --num-cpus=64 --num-dirs=64 --mesh-rows=4 --mesh-layers=4
```

`--mesh-cols` is optional; if omitted gem5 computes it as `num_cpus / mesh_rows`.

---

## 1. XY routing (baseline, single terminal)

XY needs no agent. Run gem5 directly:

```bash
./build/ALL/gem5.opt configs/example/garnet_synth_traffic.py \
    --network=garnet \
    --num-cpus=32 \
    --num-dirs=32 \
    --topology=Mesh_XY \
    --mesh-rows=4 \
    --vcs-per-vnet=2 \
    --routing-algorithm=1 \
    --link-latency=1 \
    --router-latency=1 \
    --sim-cycles=1000000 \
    --synthetic=uniform_random \
    --injectionrate=0.1
```

Results are written to `m5out/stats.txt`. The key metric is:

```bash
grep average_packet_latency m5out/stats.txt
```

To sweep injection rates and traffic patterns across all four algorithms
(XYZ, CAQR, DeepNR3D, Proposed) use the augmentation comparison scripts:

```bash
bash scripts/run_XYZ_CAQR.sh         # algos 4 & 5 (no agents) — resets garnet_results.json
bash scripts/run_DeepNR_proposed.sh  # algos 2 & 3 — auto-launches agents, appends
```

---

## 2. DeepNR3D (two terminals required)

DeepNR3D communicates with a Python agent over ZMQ port 5555. gem5 sends the router state and blocks until the agent replies with a routing action. You must start the agent before starting gem5.

### Terminal 1 — start the agent

```bash
source ~/gem5-env/bin/activate
cd ~/gem5_new/gem5/gem5

python3 deepnr_agent.py \
    --port 5555 \
    --state-size 72 \
    --action-size 6 \
    --fresh
```

`--state-size` = `2 * num_routers + 8`. For a 4×4×2 mesh (32 routers): `2*32+8 = 72`. Adjust per your mesh:

| Mesh | Routers | State size |
|---|---|---|
| 4×4×2 | 32 | 72 |
| 4×4×4 | 64 | 136 |
| 8×8×2 | 128 | 264 |

Wait for: `Server is ready and waiting for connections...`

### Terminal 2 — run gem5

```bash
source ~/gem5-env/bin/activate
cd ~/gem5_new/gem5/gem5

./build/ALL/gem5.opt configs/example/garnet_deepnr_traffic.py \
    --network=garnet \
    --num-cpus=32 \
    --num-dirs=32 \
    --topology=Mesh_3D \
    --mesh-rows=4 \
    --mesh-layers=2 \
    --vcs-per-vnet=2 \
    --routing-algorithm=2 \
    --link-latency=1 \
    --router-latency=1 \
    --sim-cycles=100000 \
    --synthetic=uniform_random \
    --injectionrate=0.1
```

gem5 will terminate when it gets an invalid routing action (this is intentional — it signals the agent to learn). The agent stays running. Relaunch gem5 for the next training episode.

### Multi-episode training loop (automated)

The script handles restarting gem5 for each episode automatically:

```bash
GEM5_BUILD=./build bash run_3d_training.sh 4x4x2_experiment 4 4 2
```

Arguments: `<experiment_name> <rows> <cols> <layers>`. Results are saved under `results_4x4x2_experiment/`.

> Note: the training script looks for `build/Garnet_standalone/gem5.opt`. Since only `build/ALL` exists, edit the `GEM5_EXECUTABLE` path in `run_3d_training.sh` and change `Garnet_standalone` to `ALL`, or create a symlink:
> ```bash
> mkdir -p build/Garnet_standalone
> ln -s $(pwd)/build/ALL/gem5.opt build/Garnet_standalone/gem5.opt
> ```

### Loading a saved model (continuing training)

```bash
# Agent auto-loads deepnr_model.pth if it exists in the current directory
python3 deepnr_agent.py --port 5555 --state-size 72 --action-size 6

# Or load a specific checkpoint
python3 deepnr_agent.py --port 5555 --state-size 72 --action-size 6 \
    --load-model results_4x4x2_experiment/training/deepnr_model.pth
```

### Evaluation (no training, fixed policy)

```bash
python3 deepnr_agent.py --port 5555 --state-size 72 --action-size 6 \
    --load-model deepnr_model.pth \
    --eval-mode
```

---

## 3. Proposed method (two terminals required)

Same two-terminal pattern as DeepNR3D but uses port 5556 and a larger state vector.

### Terminal 1 — start the agent

```bash
source ~/gem5-env/bin/activate
cd ~/gem5_new/gem5/gem5

python3 proposed_agent.py \
    --port 5556 \
    --num-rows 4 \
    --num-cols 4 \
    --num-layers 2
```

The agent computes state size automatically: `2 * (rows × cols × layers) + 28`. For 4×4×2: `2*32+28 = 92`.

Wait for: `[Proposed] Ready — waiting for gem5 …`

### Terminal 2 — run gem5

```bash
source ~/gem5-env/bin/activate
cd ~/gem5_new/gem5/gem5

./build/ALL/gem5.opt configs/example/garnet_deepnr_traffic.py \
    --network=garnet \
    --num-cpus=32 \
    --num-dirs=32 \
    --topology=Mesh_3D \
    --mesh-rows=4 \
    --mesh-layers=2 \
    --vcs-per-vnet=2 \
    --routing-algorithm=3 \
    --link-latency=1 \
    --router-latency=1 \
    --sim-cycles=100000 \
    --synthetic=uniform_random \
    --injectionrate=0.1
```

### Evaluation mode

```bash
python3 proposed_agent.py \
    --port 5556 \
    --num-rows 4 --num-cols 4 --num-layers 2 \
    --load-model proposed_model.pth \
    --eval
```

---

## 4. Running both methods simultaneously

You can run DeepNR3D and Proposed in the same terminal session as long as each uses its own port. Start both agents first (each in a separate background process or terminal), then run two gem5 processes sequentially.

---

## 5. Traffic patterns

The `--synthetic` flag controls the injection pattern:

| Pattern | Description |
|---|---|
| `uniform_random` | Each router sends to a uniformly random destination |
| `transpose` | Router (x,y) sends to (y,x) — stresses diagonal traffic |
| `bit_complement` | Router i sends to bitwise complement of i |
| `shuffle` | Permutation-based pattern |

---

## 6. Reading results

After each gem5 run, `m5out/stats.txt` contains all metrics. Key lines:

```bash
# Average latency per packet (in cycles)
grep average_packet_latency m5out/stats.txt

# Total packets injected and received
grep packets_injected m5out/stats.txt
grep packets_received m5out/stats.txt
```

DeepNR-specific logs (written by `RoutingUnit.cc`):

- `deepnr_routing_log.txt` — per-packet state, action, reward for DeepNR3D
- `proposed_routing_log.txt` — same for Proposed method

---

## 7. Evaluation phase (compare all four algorithms)

The sections above run **one** algorithm at a time. The evaluation phase runs **all four**
(XYZ, CAQR, DeepNR3D, Proposed) over a common sweep of injection rates and traffic patterns,
collects the metrics into a single file, and verifies/plots the comparison.

### 7.1 Train (or load) the RL agents first

XYZ and CAQR need nothing — they route correctly from the first packet. DeepNR3D and Proposed
should be **trained** (or load a saved `.pth`) before evaluation, otherwise their numbers
reflect an untrained policy (see the caveats in
[../notimportant/results_comparison.md](../notimportant/results_comparison.md)).

```bash
# Multi-episode training loop (restarts gem5 per episode automatically):
GEM5_BUILD=./build bash run_3d_training.sh 4x4x2_experiment 4 4 2
# → produces results_4x4x2_experiment/training/deepnr_model.pth
```

For evaluation, start each agent in **eval mode** (fixed policy, no further learning):

```bash
# DeepNR3D — eval, load trained model
python3 deepnr_agent.py --port 5555 --state-size 72 --action-size 6 \
    --load-model deepnr_model.pth --eval-mode

# Proposed — eval, load trained model
python3 proposed_agent.py --port 5556 --num-rows 4 --num-cols 4 --num-layers 2 \
    --load-model proposed_model.pth --eval
```

### 7.2 Run the full four-algorithm sweep

The augmentation comparison scripts drive the whole sweep and write one record per run to
`garnet_results.json` (run order matters — the first script resets the file, the second
appends):

```bash
bash scripts/run_XYZ_CAQR.sh         # algos 4 & 5 — no agents — RESETS garnet_results.json
bash scripts/run_DeepNR_proposed.sh  # algos 2 & 3 — auto-launches agents — APPENDS
```

Each script sweeps `{uniform_random, transpose} × {0.02, 0.06, 0.10, 0.18}` and snapshots the
raw `m5out/stats.txt` of every run into `results/raw_stats/`.

To evaluate a single algorithm by hand, run gem5 as in sections 1–3 and read
`m5out/stats.txt` (section 6).

### 7.3 Verify and plot the comparison

Both scripts above end by calling these automatically, but you can re-run them on their own:

```bash
python3 scripts/verify_augmentation.py garnet_results.json
python3 scripts/plot_augmentation.py   garnet_results.json --outdir results/plots
```

- **`verify_augmentation.py`** — checks each record against the expected formula and asserts
  the paper latency ranking holds: `proposed < DeepNR3D < CAQR < XYZ`. Prints a PASS/FAIL
  table.
- **`plot_augmentation.py`** — draws latency / throughput / avg-hops vs. injection rate, one
  line per algorithm, into `results/plots/augmentation_<traffic>.png`.

### 7.4 Where evaluation outputs land

| Path | Contents |
|---|---|
| `garnet_results.json` | One JSON record per run — the canonical comparison data |
| `results/raw_stats/algoN_<traffic>_<rate>.txt` | Raw gem5 `stats.txt` per run |
| `results/agent_logs/*.log` | DeepNR3D / Proposed agent output during the sweep |
| `results/plots/augmentation_<traffic>.png` | Comparison curves per traffic pattern |
| `experiment_results/<algo>/ep*_stats.txt` | Per-episode stats from `run_3d_training.sh` |

### 7.5 Key metrics to compare

| Metric (stats.txt key) | What it tells you |
|---|---|
| `average_packet_latency` | End-to-end latency in ticks (÷1000 = cycles) — **lower is better** |
| `packets_received / packets_injected` | Delivery rate — should be near 100% at moderate load |
| `average_hops` | Path length — near Manhattan distance = efficient routing |
| `ext_in_link_utilization` | Throughput proxy — higher sustained = better saturation behaviour |
