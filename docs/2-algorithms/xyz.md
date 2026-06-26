# XYZ — Code Walkthrough

XYZ is the **deterministic 3D baseline**: dimension-ordered routing extended from 2D XY to
the third (Z) dimension. It is the simplest algorithm in the project and the fair baseline
that the learning methods are compared against. No agent, no training, no state — just a
fixed rule. Routing algorithm **ID 4**, topology `Mesh_3D`.

Read [../1-fundamentals/gem5-ruby-garnet-primer.md](../1-fundamentals/gem5-ruby-garnet-primer.md)
first if the terms *router ID formula*, *direction→port map*, or *outportCompute* are new.

---

## Files involved

| File | Role |
|---|---|
| `src/mem/ruby/network/garnet/CommonTypes.hh` | `XYZ_ = 4` enum value |
| `src/mem/ruby/network/garnet/RoutingUnit.hh` | Declares `outportComputeXYZ()` |
| `src/mem/ruby/network/garnet/RoutingUnit.cc` | Implementation + dispatch case |
| `configs/topologies/Mesh_3D.py` | Provides the 3D mesh with Up/Down (TSV) links |

No Python agent and no `OutputUnit` reward hook — XYZ never learns.

---

## The idea: dimension-ordered routing

Always resolve dimensions in a **fixed order**: first X, then Y, then Z. The packet moves
along X until `dest_x == my_x`, then along Y until aligned, then along Z. Because every
packet obeys the same order, the network is **deadlock-free** without needing extra virtual
channels — there are no cyclic dependencies between dimensions.

This makes XYZ predictable and cheap, but **oblivious to congestion**: it takes the same path
regardless of how busy the network is. That obliviousness is exactly what the Q-routing and
DQN methods try to improve on.

---

## Implementation

**File:** [RoutingUnit.cc](../../src/mem/ruby/network/garnet/RoutingUnit.cc), lines 323–364.

### 1. Coordinates from router IDs (lines 326–342)

```cpp
int num_rows   = m_router->get_net_ptr()->getNumRows();
int num_cols   = m_router->get_net_ptr()->getNumCols();
int num_layers = m_router->get_net_ptr()->getNumLayers();
int plane = num_rows * num_cols;

int my_z = my_id / plane;
int my_y = (my_id % plane) / num_cols;
int my_x = (my_id % plane) % num_cols;
// same decomposition for dest_id → dest_x, dest_y, dest_z
```

This is the standard project router-ID formula (§4.2 of the primer). `plane = rows*cols` is
the number of routers in one layer.

### 2. The dimension-ordered decision (lines 346–360)

```cpp
if      (dest_x > my_x) outport_dirn = "East";
else if (dest_x < my_x) outport_dirn = "West";
else if (dest_y > my_y) outport_dirn = "South";
else if (dest_y < my_y) outport_dirn = "North";
else if (dest_z > my_z) outport_dirn = "Up";    // +Z via TSV
else if (dest_z < my_z) outport_dirn = "Down";  // -Z via TSV
else  panic("XYZ routing: src == dest but outportCompute called");
```

The `if/else if` chain **is** the dimension ordering: X is checked first and short-circuits,
so Y is only considered once X is aligned, and Z only once X and Y are aligned. The `panic`
guards an impossible case — `outportCompute()` is never called when the packet is already at
its destination (that goes to the Local port earlier in `outportCompute()`).

> **Direction convention:** `dest_y > my_y` maps to `"South"` (Y increases downward), and
> `dest_y < my_y` to `"North"`. Keep this consistent with the coordinate axes used by the
> other algorithms and by `Mesh_3D.py`.

### 3. Return the port (lines 362–363)

```cpp
assert(m_outports_dirn2idx.count(outport_dirn) > 0);
return m_outports_dirn2idx[outport_dirn];
```

Translate the chosen direction string into the physical output-port index via the router's
direction map. The `assert` catches a topology that doesn't actually have that port (e.g.,
asking for `Up` on a router in the top layer — which dimension-ordering guarantees never
happens, but the assert documents the invariant).

### 4. Dispatch (line 251)

```cpp
case XYZ_:  outport = outportComputeXYZ(route, inport, inport_dirn);  break;
```

---

## Why XYZ is the comparison baseline

- **Correct & complete:** delivers every packet on a shortest dimension-ordered path
  (`avg_hops ≈ Manhattan distance`), so its delivery rate is ~100% at moderate load.
- **Deadlock-free by construction**, unlike plain XY on a 3D mesh (XY has no Up/Down handling
  and crashes on `Mesh_3D`).
- **Congestion-oblivious:** under heavy or adversarial traffic (e.g., `transpose`) it cannot
  route around hotspots — this is the headroom the learning algorithms aim to exploit.

In [../notimportant/results_comparison.md](../notimportant/results_comparison.md), XYZ is
called out as "the only fair 3D baseline" because it routes correctly regardless of training
state, whereas the RL methods need many episodes before their numbers are meaningful.

---

## Run it

```bash
./build/ALL/gem5.opt configs/example/garnet_synth_traffic.py \
    --network=garnet --num-cpus=32 --num-dirs=32 \
    --topology=Mesh_3D --mesh-rows=4 --mesh-layers=2 --vcs-per-vnet=2 \
    --routing-algorithm=4 --link-latency=1 --router-latency=1 \
    --sim-cycles=1000000 --synthetic=uniform_random --injectionrate=0.1
```

No agent terminal needed. See [../3-howto/run.md](../3-howto/run.md).
