# gem5 / Ruby / Garnet Primer

The prerequisite knowledge needed **before** reading or writing the routing algorithms in
this project (XYZ, CAQR, DeepNR3D, Proposed). Read this first, then
[simulation-sequence.md](simulation-sequence.md) for the end-to-end runtime flow, then the
per-algorithm docs in [../2-algorithms/](../2-algorithms/).

---

## 1. The layers, top to bottom

```
gem5 (C++ event-driven simulator)
  └─ Ruby            — detailed memory/cache + interconnect model
       └─ Garnet     — the cycle-accurate Network-on-Chip (NoC) inside Ruby
            └─ Router → InputUnit / RoutingUnit / SwitchAllocator / CrossbarSwitch / OutputUnit
```

- **gem5** is an event-driven simulator: every component schedules `wakeup()` events on a
  tick timeline. Nothing runs "in a loop" — it reacts to scheduled events.
- **Ruby** is gem5's detailed memory-system model. We don't touch the cache-coherence side;
  we only use it to stand up the network.
- **Garnet** is the NoC model inside Ruby. **All of our routing code lives here**, under
  `src/mem/ruby/network/garnet/`.

We run Garnet in *synthetic-traffic* mode: instead of real CPU memory traffic, a
`GarnetSyntheticTraffic` tester injects packets following a chosen pattern
(`uniform_random`, `transpose`, …). This isolates the network so we can measure routing.

---

## 2. Packets, flits, and virtual channels (VCs)

- A **packet** is the logical unit sent from a source node to a destination node.
- A packet is split into **flits** (flow-control units): a **HEAD** flit (carries the route
  + timestamps), zero or more **BODY** flits, and a **TAIL** flit (marks the end). A 1-flit
  packet is a single **HEAD_TAIL** flit. Enum: `flit_type` in
  [CommonTypes.hh](../../src/mem/ruby/network/garnet/CommonTypes.hh).
- A physical link is divided into **virtual channels (VCs)** — independent buffer queues
  that share the wire. VCs prevent head-of-line blocking and are the unit of
  **credit-based flow control**.
- **Credits** track free buffer slots downstream. A router may only send a flit on a VC if
  it holds a credit for it. **Buffer occupancy / free credits are the congestion signal**
  every one of our algorithms reads.

Key idea for routing: **routing happens per-packet, decided at the HEAD flit**, once per
hop. The chosen output port is then reused by the packet's BODY/TAIL flits.

---

## 3. The router pipeline (one hop)

Each `Router::wakeup()` ([Router.cc](../../src/mem/ruby/network/garnet/Router.cc)) runs its
sub-units every cycle:

| Sub-unit | Role |
|----------|------|
| **InputUnit** | Receives an incoming flit from a link into a VC buffer. |
| **RoutingUnit** | **Computes the output port** for a HEAD flit. ← *our code lives here* |
| **SwitchAllocator** | Arbitrates which buffered flit wins the crossbar this cycle. |
| **CrossbarSwitch** | Moves the winning flit from its input VC to the chosen output port. |
| **OutputUnit** | Holds the output queue, sends flits on the outgoing link, tracks credits. |

The **RoutingUnit** is the only stage we modify. `SwitchAllocator` calls
`RoutingUnit::outportCompute()` when a HEAD flit needs a route; everything else is stock.

---

## 4. RoutingUnit — where every algorithm plugs in

File: [RoutingUnit.cc](../../src/mem/ruby/network/garnet/RoutingUnit.cc).

`outportCompute()` is the dispatch point. It reads `--routing-algorithm=N` from the network
config and switches to the matching implementation:

```cpp
switch (routing_algorithm) {
case TABLE_:    outport = lookupRoutingTable(...);       break; // 0
case XY_:       outport = outportComputeXY(...);          break; // 1
case DEEPNR3D_: outport = outportComputeDeepNR3D(...);     break; // 2
case PROPOSED_: outport = outportComputeProposed(...);     break; // 3
case XYZ_:      outport = outportComputeXYZ(...);          break; // 4
case CAQR_:     outport = outportComputeCAQR(...);         break; // 5
}
```

A routing function's job is simple: **return an output port index** (an `int`). To do that
it works with two project-wide conventions:

### 4.1 Direction strings ↔ port indices

Every router owns maps that translate a human direction into a physical port index:

```cpp
m_outports_dirn2idx["North"]  // → output port index for the North neighbour
m_inports_dirn2idx["South"]   // → input  port index a flit arrived on
```

The six 3D directions are `North, East, South, West, Up, Down`. `Up`/`Down` are the
**TSV** (Through-Silicon-Via) vertical links between layers, only present on `Mesh_3D`.
A routing function decides a *direction*, then returns `m_outports_dirn2idx[dirn]`.

### 4.2 Router ID ↔ (x, y, z) coordinates

Router IDs are linearised **row-major, per layer**:

```
id = z * (rows * cols) + y * cols + x

z = id / (rows*cols)
y = (id % (rows*cols)) / cols
x = (id % (rows*cols)) % cols
```

This single formula appears in **every** algorithm (XYZ, CAQR, DeepNR3D, Proposed). It is
the bridge between gem5's flat router IDs and the geometric reasoning (Manhattan distance,
boundary checks, which direction reduces distance) that routing needs. **Get this wrong and
every algorithm misroutes.**

For a 2D mesh (`Mesh_XY`) `layers = 1`, so it collapses to `id = y*cols + x`.

---

## 5. Reading congestion: OutputUnit credits & queues

Routing decisions depend on how busy each outgoing direction is. Two sources:

- **Free credits** (free downstream buffer space) — higher = less congested:
  ```cpp
  m_router->getOutputUnit(port)->get_credit_count(vc);
  ```
  DeepNR3D and Proposed normalise this into the state vector (feature `f5`).
- **Output queue depth** (flits waiting to leave) — higher = more congested:
  ```cpp
  m_router->getOutputUnit(port)->getOutQueue()->getSize();
  ```
  CAQR uses this directly as the queuing-delay term `q_y` in its Q-update.

---

## 6. Topology: how the mesh is built

The Python topology script wires routers and links before simulation:

- [configs/topologies/Mesh_XY.py](../../configs/topologies/Mesh_XY.py) — standard 2D mesh.
- [configs/topologies/Mesh_3D.py](../../configs/topologies/Mesh_3D.py) — custom 3D mesh with
  vertical TSV links (`Up`/`Down`), higher latency than horizontal links.

**Sizing rule:** `num-cpus == num-dirs == rows × cols × layers`. The topology assigns one
router per node and connects neighbours; it also sets `getNumRows/getNumCols/getNumLayers`,
which the routing functions read back to compute coordinates.

---

## 7. How results are measured

You measure routing quality from latency/throughput/hops, accumulated as the simulation runs:

- **NetworkInterface** injects packets (timestamps each flit) and, on arrival, measures
  `network_delay` and `queueing_delay` and accumulates them.
- **GarnetNetwork** holds the running totals; gem5's stats framework divides them into
  averages at dump time (`average_packet_latency = network + queueing`).
- Output lands in `m5out/stats.txt` (full dump, overwritten each run) and — in this project —
  a `GarnetStatsExporter` also appends a compact JSON record to `garnet_results.json`.

The exact stat-by-stat flow is documented in
[../notimportant/stats-flow.md](../notimportant/stats-flow.md) if you need it.

---

## 8. The RL feedback loop (DeepNR3D & Proposed only)

The two learning algorithms add a Python agent over **ZMQ** (a request/reply socket library):

```
gem5 RoutingUnit (C++, ZMQ client)  ──state──►  agent.py (Python, ZMQ server)
                                    ◄─action──
```

- gem5 builds a **state vector**, sends it as JSON, and **blocks** until the agent replies
  with an action `0–5` (a direction).
- The **reward** for a hop is computed in `OutputUnit.cc` as `1 / (queuing_delay + 1)` and
  stored in a shared `DeepNR::` namespace, then consumed at the packet's *next* routing call
  so the `(state, action, reward, next_state)` tuple is complete.
- gem5 deliberately calls `fatal()` / `exitSimLoopNow()` on an invalid action — that is the
  signal that an episode ended, which the outer training loop uses to restart gem5.

You do **not** need ML background to read the gem5 side — it just serialises state and
applies the returned port. The learning lives entirely in the Python agents.

---

## 9. Build/run in one line (details in [../3-howto/](../3-howto/))

```bash
scons build/ALL/gem5.opt -j$(nproc)        # ZMQ required for algos 2 & 3
./build/ALL/gem5.opt configs/example/garnet_synth_traffic.py --routing-algorithm=4 ...
```

gem5 only builds/runs on the **Linux host**, not the Windows mount.

---

## Where to go next

1. [simulation-sequence.md](simulation-sequence.md) — every file/function in execution order.
2. [../2-algorithms/xyz.md](../2-algorithms/xyz.md) — the simplest algorithm; start here.
3. [../2-algorithms/caqr.md](../2-algorithms/caqr.md) — first learning algorithm (tabular Q).
4. [../2-algorithms/deepnr3d.md](../2-algorithms/deepnr3d.md) & [proposed.md](../2-algorithms/proposed.md) — the DQN agents.
