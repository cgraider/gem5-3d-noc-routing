# Routing Algorithm Comparison Results

## Simulation Setup
- Mesh: 4×8 2D (XY) / 4×4×2 3D (DeepNR3D)
- Nodes: 32 CPUs + 32 dirs
- Traffic: uniform_random, injection rate = 0.1 flits/node/cycle
- Link latency: 1 cycle, Router latency: 1 cycle
- VCs per Vnet: 2

---

## XY Routing (Baseline)

**Command:**
```bash
./build/ALL/gem5.opt configs/example/garnet_synth_traffic.py \
    --network=garnet --num-cpus=32 --num-dirs=32 \
    --topology=Mesh_XY --mesh-rows=4 --vcs-per-vnet=2 \
    --routing-algorithm=1 --link-latency=1 --router-latency=1 \
    --sim-cycles=1000000 --synthetic=uniform_random --injectionrate=0.1
```

**Results:**

| Metric | Value |
|---|---|
| Sim cycles | 1,000,000 ticks (1,000 cycles @ 1 GHz) |
| Packets injected | 2,140 |
| Packets received | 2,124 (99.3% delivery) |
| Avg packet latency | **76.1 cycles** (76,146 ticks) |
| Avg flit latency | **110.7 cycles** (110,706 ticks) |
| Avg hops | **3.95** |
| Effective throughput | **0.066 pkts/node/cycle** |
| Configured injection rate | 0.1 pkts/node/cycle |

---

## XYZ Routing (3D Mesh Baseline)

**Command:**
```bash
./build/ALL/gem5.opt configs/example/garnet_synth_traffic.py \
    --network=garnet --num-cpus=32 --num-dirs=32 \
    --topology=Mesh_3D --mesh-rows=4 --mesh-layers=2 --vcs-per-vnet=2 \
    --routing-algorithm=4 --link-latency=1 --router-latency=1 \
    --sim-cycles=1000000 --synthetic=uniform_random --injectionrate=0.1
```

**Results:**

| Metric | Value |
|---|---|
| Sim cycles | 1,000,000 ticks (1,000 cycles @ 1 GHz) |
| Packets injected | 2,205 |
| Packets received | 2,129 (96.6% delivery) |
| Avg packet latency | **81.9 cycles** (81,864 ticks) |
| Avg flit latency | **89.4 cycles** (89,419 ticks) |
| Avg hops | **3.99** |
| Effective throughput | **0.066 pkts/node/cycle** |

**Note:** Routing algorithm=4 (XYZ) was implemented in this session. XY (algorithm=1) crashes on Mesh_3D because it has no handling for Up/Down port directions.

---

## DeepNR3D

**Command:**
```bash
# Terminal 1 - Agent (eval mode, trained model):
python3 deepnr_agent.py --port 5555 --state-size 136 --action-size 6 \
    --load-model deepnr_model.pth --eval-mode

# Terminal 2 - gem5:
./build/ALL/gem5.opt configs/example/garnet_deepnr_traffic.py \
    --network=garnet --num-cpus=32 --num-dirs=32 \
    --topology=Mesh_3D --mesh-rows=4 --mesh-layers=2 --vcs-per-vnet=2 \
    --routing-algorithm=2 --link-latency=1 --router-latency=1 \
    --sim-cycles=1000000 --synthetic=uniform_random --injectionrate=0.1
```

**Training:** 10 episodes × 500k cycles = ~45,000 routing decisions, 9,074 training steps, epsilon decayed to 0.01.

**Results:**

| Metric | Value |
|---|---|
| Sim cycles | 1,000,000 ticks (1,000 cycles @ 1 GHz) |
| Packets injected | 203 |
| Packets received | 14 (6.9% delivery) |
| Avg packet latency | **24.9 cycles** (24,892 ticks) |
| Avg flit latency | **24.9 cycles** |
| Avg hops | **17.9** (looping — model still learning) |
| Effective throughput | **0.0004 pkts/node/cycle** |

**Notes:**
- A loop-breaker fallback (XYZ override when hops > max_shortest_path) was added to prevent deadlock while the model is still training.
- High hop count (17.9 vs optimal ~4) shows the model is not yet routing optimally — packets loop before the fallback kicks in.
- More training episodes are needed for the model to converge to near-optimal paths.

---

## Proposed Method

**Command:**
```bash
# Terminal 1 - Agent (eval mode, trained model):
python3 proposed_agent.py --port 5556 \
    --num-rows 4 --num-cols 8 --num-layers 2 \
    --load-model proposed_model.pth --eval

# Terminal 2 - gem5:
./build/ALL/gem5.opt configs/example/garnet_deepnr_traffic.py \
    --network=garnet --num-cpus=32 --num-dirs=32 \
    --topology=Mesh_3D --mesh-rows=4 --mesh-layers=2 --vcs-per-vnet=2 \
    --routing-algorithm=3 --link-latency=1 --router-latency=1 \
    --sim-cycles=1000000 --synthetic=uniform_random --injectionrate=0.1
```

**Training:** 10 episodes × 500k cycles, 18,000+ training steps, epsilon decayed to 0.107. Larger replay buffer (10,000 vs 200 in DeepNR3D). State vector = 92 features for a 4×4×2 mesh (2*32+28 = 92: 10 feature groups including EMA buffer occupancy, wait time, link delay).

**Results:**

| Metric | Value |
|---|---|
| Sim cycles | 1,000,000 ticks (1,000 cycles @ 1 GHz) |
| Packets injected | 154 |
| Packets received | 3 (1.9% delivery) |
| Avg packet latency | **4.0 cycles** (4,000 ticks) |
| Avg flit latency | **4.0 cycles** |
| Avg hops | **1.0** |
| Effective throughput | **0.00009 pkts/node/cycle** |

**Notes:**
- Only trivial 1-hop packets completed delivery; the network is still heavily congested.
- With `ε=0.1` in eval mode and an undertrained policy, most routing decisions are suboptimal → congestion → injection backpressure.
- The loop-breaker (XYZ fallback) is active but congestion builds before packets can be drained.

---

## Summary Comparison

| Metric | XY (2D Mesh) | XYZ (3D Mesh) | DeepNR3D (early) | Proposed (early) |
|---|---|---|---|---|
| Topology | 4×8 2D | 4×4×2 3D | 4×4×2 3D | 4×4×2 3D |
| Training steps | — | — | ~9,000 | ~18,000 |
| Avg packet latency | **76.1 cycles** | **81.9 cycles** | 24.9 cycles† | 4.0 cycles† |
| Avg hops | 3.95 | 3.99 | 17.9 | 1.0 |
| Throughput | 0.066 pkt/node/cycle | 0.066 pkt/node/cycle | 0.0004 | 0.00009 |
| Packets received | 2,124/2,140 | 2,129/2,205 | 14/203 | 3/154 |
| Delivery rate | 99.3% | 96.6% | 6.9% | 1.9% |

† Misleading: RL results reflect only the tiny fraction of packets that found short paths through a congested network. XYZ is the only fair 3D baseline at this training level.

**Key takeaway:** XYZ routing is the solid deterministic 3D baseline. Both RL methods need significantly more training (100+ episodes) before their delivery rate and latency can be fairly compared against XYZ.

---
