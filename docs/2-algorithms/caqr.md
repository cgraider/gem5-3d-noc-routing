# CAQR — Code Walkthrough

CAQR (**Congestion-Aware Q-Routing**) is a **tabular reinforcement-learning** router for a
**2D mesh**. Unlike DeepNR3D/Proposed it needs no external Python agent — the Q-table lives
in C++ and learns online during the simulation. Routing algorithm **ID 5**, topology
`Mesh_XY`.

Based on: Srivastava et al., *"Performance analysis of congestion-aware Q-routing algorithm
for network on chip"*, IJ-AI Vol. 13 No. 1, March 2024, pp. 798–806.

Read [../1-fundamentals/gem5-ruby-garnet-primer.md](../1-fundamentals/gem5-ruby-garnet-primer.md)
first. CAQR is a good bridge between the deterministic XYZ and the deep-RL methods: it is
*learning*, but the learning is simple enough to read end-to-end in one screen.

---

## Files involved

| File | Role |
|---|---|
| `src/mem/ruby/network/garnet/CommonTypes.hh` | `CAQR_ = 5` enum value |
| `src/mem/ruby/network/garnet/RoutingUnit.hh` | Declares `outportComputeCAQR()` |
| `src/mem/ruby/network/garnet/RoutingUnit.cc` | `namespace CAQR` + implementation + dispatch |

No agent, no ZMQ, no `.pth` model — the Q-table is in-memory and discarded at the end of each
run.

---

## The idea: learn a per-destination cost for each next hop

A classic **Q-routing** table answers: *"from router `x`, heading to destination `d`, how
costly is it to send via direction `dir`?"* Lower Q means a faster/less-congested path. The
router picks the feasible direction with the **lowest** Q. After each hop it updates the
*previous* router's Q-value using the queuing delay it actually observed — so the table
gradually reflects real congestion, and traffic steers around hotspots that a fixed XY route
would plow straight through.

---

## 1. The Q-table and hyperparameters (lines 375–402)

```cpp
namespace CAQR {
// qtable[router_id][dest_router][outport_dirn] = Q-value
static std::map<int, std::map<int, std::map<std::string, double>>> qtable;

static int packet_count = 0;           // total routing decisions so far

static const int    TRAIN_STEPS = 50;  // exploration phase length (paper)
static const double ALPHA       = 0.5; // learning rate  α
static const double GAMMA       = 0.7; // discount rate  γ
static const double EPSILON     = 0.5; // exploration probability ε

double getQ(int router, int dest, const std::string &dirn);  // 0.0 if unseen
void   setQ(int router, int dest, const std::string &dirn, double val);
}
```

- The table is a **global static** — shared across all routers in the simulation, indexed by
  `[router][dest][direction]`. Unvisited entries default to `0.0`.
- `packet_count` drives the exploration→exploitation switch: the first `TRAIN_STEPS` (50)
  decisions explore; after that it is pure greedy exploitation.
- `getQ`/`setQ` are thin nested-map accessors so the rest of the code stays readable.

---

## 2. `outportComputeCAQR()` (lines 404–485)

### 2.1 Coordinates (2D) (lines 407–417)

```cpp
int my_x = my_id % num_cols;   int my_y = my_id / num_cols;
int dest_x = dest_id % num_cols; int dest_y = dest_id / num_cols;
```

CAQR runs on `Mesh_XY`, so the router-ID formula collapses to the 2D form (`layers = 1`).

### 2.2 Feasible directions (lines 421–427)

```cpp
std::vector<std::string> feasible;
if (dest_x > my_x) feasible.push_back("East");
if (dest_x < my_x) feasible.push_back("West");
if (dest_y > my_y) feasible.push_back("North");
if (dest_y < my_y) feasible.push_back("South");
assert(!feasible.empty());
```

Only directions that **reduce Manhattan distance** to the destination are considered — at
most 2 in a 2D mesh. This keeps routing minimal (no backtracking) and bounds the choice to
the X-progressing and Y-progressing options. The Q-learning decides *which* of those two to
take when both exist.

### 2.3 Action selection: ε-greedy → greedy (lines 430–446)

```cpp
bool exploring = (CAQR::packet_count < CAQR::TRAIN_STEPS) &&
                 ((double)rand() / RAND_MAX < CAQR::EPSILON);

if (exploring || feasible.size() == 1) {
    chosen_dirn = feasible[rand() % feasible.size()];   // random
} else {
    // greedy: pick the feasible direction with the lowest Q-value
    chosen_dirn  = feasible[0];
    double min_q = CAQR::getQ(my_id, dest_id, feasible[0]);
    for (size_t i = 1; i < feasible.size(); ++i) {
        double q = CAQR::getQ(my_id, dest_id, feasible[i]);
        if (q < min_q) { min_q = q; chosen_dirn = feasible[i]; }
    }
}
int chosen_outport = m_outports_dirn2idx[chosen_dirn];
```

During the first 50 decisions there's a 50% chance to pick a random feasible direction
(exploration); otherwise — and always after warm-up — pick the **minimum-Q** direction
(exploitation). If only one direction is feasible (already aligned in one axis) there is no
choice to make.

### 2.4 The Q-update (Eq. 3 from the paper) (lines 450–481)

This is the heart of CAQR. When a packet **arrives at router `y` from a previous router `x`**
(`inport_dirn != "Local"`), CAQR updates `x`'s Q-value for the hop `x → y → d`:

```cpp
if (inport_dirn != "Local") {
    // 1. reconstruct previous router x from the direction the flit came in on
    int prev_x = my_x, prev_y = my_y;
    if      (inport_dirn == "North") prev_y = my_y + 1;
    else if (inport_dirn == "South") prev_y = my_y - 1;
    else if (inport_dirn == "East")  prev_x = my_x + 1;
    else if (inport_dirn == "West")  prev_x = my_x - 1;
    int prev_id = prev_y * num_cols + prev_x;

    // 2. the outport AT x that led to y is the opposite of the inport at y
    std::string out_x_to_y = opposite(inport_dirn);

    // 3. q_y = current queuing delay at y on the chosen output port
    double q_y = m_router->getOutputUnit(chosen_outport)->getOutQueue()->getSize();
    const double delta_xy = 1.0;   // δ_xy: link transmission delay (1 cycle)

    // 4. apply the update rule
    double Q_y_z_d     = CAQR::getQ(my_id,  dest_id, chosen_dirn);   // best onward cost from y
    double Q_x_y_d     = CAQR::getQ(prev_id, dest_id, out_x_to_y);   // old estimate at x
    double Q_x_y_d_new = Q_x_y_d +
        CAQR::ALPHA * (CAQR::GAMMA * Q_y_z_d + q_y + delta_xy - Q_x_y_d);
    CAQR::setQ(prev_id, dest_id, out_x_to_y, Q_x_y_d_new);
}
CAQR::packet_count++;
```

Mapping to the paper's equation:

```
Q_x(y,d)_new = Q_x(y,d)_old + α · ( γ · Q_y(z,d) + q_y + δ_xy − Q_x(y,d)_old )
```

| Term | Code | Meaning |
|---|---|---|
| `Q_x(y,d)` | `Q_x_y_d` | cost estimate at the previous node x for going toward d via y |
| `Q_y(z,d)` | `Q_y_z_d` | best onward cost from the current node y toward d (the chosen dir) |
| `q_y` | `q_y` | **congestion signal** — output-queue depth at y (the "congestion-aware" part) |
| `δ_xy` | `delta_xy` | fixed 1-cycle link delay |
| `α`, `γ` | `ALPHA`, `GAMMA` | learning rate 0.5, discount 0.7 |

The clever bit: CAQR can't know a hop's true cost until the packet **reaches the next
router** and we can read that router's queue depth. So the update is **deferred one hop** —
each router updates the *previous* router's table using locally observable congestion
(`q_y`). The opposite-direction reconstruction (steps 1–2) recovers which `(x, direction)`
entry to credit. Packets that originate locally (`inport_dirn == "Local"`) have no previous
hop, so they skip the update.

### 2.5 Dispatch (line 254)

```cpp
case CAQR_:  outport = outportComputeCAQR(route, inport, inport_dirn);  break;
```

---

## CAQR vs. the other algorithms

| | XYZ | **CAQR** | DeepNR3D / Proposed |
|---|---|---|---|
| Topology | 3D | **2D (Mesh_XY)** | 3D |
| Learns? | no | **yes, tabular online** | yes, deep Q-network |
| Congestion-aware? | no | **yes (queue depth `q_y`)** | yes (buffer/EMA features) |
| External agent? | no | **no — pure C++** | yes (Python over ZMQ) |
| State | none | `(router, dest, dir)` key | float vector (`2N+8` / `2N+28`) |

CAQR is the lightweight learning baseline: it captures the core Q-routing idea (steer by a
learned, congestion-weighted cost) without any neural network or inter-process communication.

---

## Run it

```bash
./build/ALL/gem5.opt configs/example/garnet_synth_traffic.py \
    --network=garnet --num-cpus=16 --num-dirs=16 \
    --topology=Mesh_XY --mesh-rows=4 --vcs-per-vnet=2 \
    --routing-algorithm=5 --link-latency=1 --router-latency=1 \
    --sim-cycles=10000 --synthetic=uniform_random --injectionrate=0.1
```

No agent terminal needed. See [../3-howto/run.md](../3-howto/run.md).
