# Simulation Sequence Guide

A step-by-step walkthrough of exactly what happens when you run the DeepNR
simulation — every file and function, in order.

---

## Overview

```
Shell script
  └─ gem5 binary  (C++ simulation engine)
       └─ Config script (Python)
            └─ Ruby / Garnet network (C++)
                 └─ RoutingUnit (C++) ──ZMQ──► deepnr_agent.py (Python DQN)
                                                    └─ trains, replies with action
  └─ Stats dumped to ep*_stats.txt
```

---

## Stage 1 — Launch

**File:** `run_3d_training.sh`

The shell script starts the Python agent first, then loops to restart gem5 for
each training episode:

```
for episode in 1..N:
    start  deepnr_agent.py  (if not already running)
    run    ./build/ALL/gem5.opt  configs/example/garnet_deepnr_traffic.py  ...
    wait   for gem5 to exit (end of episode)
    save   ep{N}_stats.txt
```

---

## Stage 2 — Python Agent Starts

**File:** `deepnr_agent.py`

**Function:** `DeepNRServer.__init__` → `DeepNRServer.run()`

Before gem5 launches, the agent binds a ZMQ REP socket on port 5555 and waits:

```python
# deepnr_agent.py  ~line 370
zmq_sock.bind("tcp://*:5555")
# blocks here until gem5 connects
```

The agent holds:
- `DQN` — the Q-network (class defined at line 65)
- `ReplayBuffer` — experience memory, capacity 200 (line 126)
- `epsilon` — exploration rate, starts at 0.9

---

## Stage 3 — gem5 Config Script Runs

**File:** `configs/example/garnet_deepnr_traffic.py`

gem5's Python layer runs this script before simulation starts. It:

1. Parses CLI flags (`--num-cpus`, `--topology`, `--routing-algorithm`, etc.)
2. Calls `Ruby.create_system()` to instantiate the Ruby memory model
3. Creates a `GarnetNetwork` object with the chosen topology (`Mesh_3D`)
4. Calls `m5.instantiate()` — finalizes all C++ SimObjects, allocates memory,
   registers all statistics with the framework
5. Calls `m5.simulate(sim_cycles)` — hands control to the C++ engine

---

## Stage 4 — Topology and Network Built

**Files:**
- `configs/topologies/Mesh_3D.py` — creates routers and links
- `src/mem/ruby/network/garnet/GarnetNetwork.cc` — `GarnetNetwork::init()`
- `src/mem/ruby/network/garnet/Router.cc` — `Router::init()`

During `m5.instantiate()`, gem5 builds the 3D mesh:

```
GarnetNetwork::init()
  └─ for each router:   Router::init()
       ├─ SwitchAllocator::init()
       └─ CrossbarSwitch::init()
  └─ for each link:     NetworkLink / CreditLink initialized
  └─ for each NI:       NetworkInterface initialized
  └─ regStats()         registers all stat counters with the framework
                        (GarnetNetwork.cc line 390–552)
```

All stat variables (`m_packet_network_latency`, `m_packets_injected`, etc.) are
registered here — they start at zero and accumulate during the simulation.

---

## Stage 5 — Simulation Tick Loop Begins

**File:** `src/sim/simulate.cc` (gem5 core)

`m5.simulate()` enters the event-driven tick loop. Every simulated cycle, any
SimObject that has a pending event calls its `wakeup()`.

---

## Stage 6 — Packet Injection (Source NI)

**File:** `src/mem/ruby/network/garnet/NetworkInterface.cc`

**Function:** `NetworkInterface::wakeup()` (line ~191)

Each cycle, the NI checks if there is a message ready in the protocol buffer.
If yes:

```
NetworkInterface::wakeup()
  └─ picks message from output MessageBuffer
  └─ computes destination NI ID and route
  └─ m_net_ptr->increment_injected_packets(vnet)     ← packets_injected counter +1
  └─ for each flit in packet:
       ├─ m_net_ptr->increment_injected_flits(vnet)  ← flits_injected counter +1
       ├─ new flit(...)  — timestamps flit with curTick() as birth time
       └─ fl->set_src_delay(curTick() - msg_ptr->getTime())
                           ← records how long the message waited before injection
  └─ places flits in output VC buffer
  └─ schedules output link
```

---

## Stage 7 — Flit Enters Router (Each Hop)

**File:** `src/mem/ruby/network/garnet/Router.cc`

**Function:** `Router::wakeup()` (line 72)

Every cycle, each router with pending events runs:

```
Router::wakeup()
  ├─ InputUnit::wakeup()        — reads incoming flit from link into VC buffer
  ├─ OutputUnit::wakeup()       — processes incoming credit signals
  ├─ SwitchAllocator::wakeup()  — arbitrates which flit gets the crossbar
  └─ CrossbarSwitch::wakeup()   — moves winning flit to the output port
```

---

## Stage 8 — Routing Decision (The DeepNR Core)

**File:** `src/mem/ruby/network/garnet/RoutingUnit.cc`

**Function:** `RoutingUnit::outportCompute()` (line ~214) →
`RoutingUnit::outportComputeDeepNR3D()` (line 368)

Called by `SwitchAllocator` when a flit needs a route. For `--routing-algorithm=2`:

### 8a — First call: ZMQ initialized

```
outportComputeDeepNR3D()
  └─ zmq_ctx_new()          — create ZMQ context (once only)
  └─ zmq_socket(ZMQ_REQ)    — create request socket (once only)
  └─ zmq_connect("tcp://localhost:5555")  — connect to deepnr_agent.py
  └─ open deepnr_routing_log.txt
```

### 8b — Every routing decision (every hop of every packet)

```
outportComputeDeepNR3D()
  │
  ├─ 1. Get reward from PREVIOUS hop
  │      DeepNR::get_reward(packet_id)     — looks up reward stored by OutputUnit
  │      DeepNR::get_done(packet_id)       — was previous hop the last hop?
  │
  ├─ 2. Build state vector  (size = 2*num_routers + 8)
  │      [0..N-1]     one-hot current router ID
  │      [N..2N-1]    one-hot destination router ID
  │      [2N]         normalized hops traversed
  │      [2N+1]       normalized Manhattan distance remaining
  │      [2N+2..2N+7] output buffer credit counts for 6 directions (N,E,S,W,Up,Down)
  │
  ├─ 3. Build available_actions[6]
  │      false if direction leads off-mesh edge or buffer is full
  │
  ├─ 4. Send JSON over ZMQ  →  deepnr_agent.py
  │      {"state":[...], "packet_id":N, "reward":R, "done":bool,
  │       "available_actions":[...]}
  │      zmq_send(zmq_sock, json_msg)
  │
  ├─ 5. Block and wait for action  ←  deepnr_agent.py
  │      zmq_recv(zmq_sock, buffer)
  │      parse: action = 0..5  (N,E,S,W,Up,Down)
  │
  ├─ 6. Validate action
  │      if invalid or dead-end: terminateDeepNR() → exitSimLoopNow()
  │                              (signals agent that episode is over)
  │
  └─ 7. Map action integer → output port index
         return outport  (used by SwitchAllocator to pick the output link)
```

---

## Stage 9 — Agent Processes the Message (Python side)

**File:** `deepnr_agent.py`

**Function:** `DeepNRServer.run()` (line ~508), `DeepNRAgent.select_action()` (line 227)

```
DeepNRServer.run()  — infinite loop
  │
  ├─ zmq_sock.recv()           — receive JSON from gem5 (blocks until message arrives)
  │
  ├─ parse: state, reward, done, available_actions, packet_id
  │
  ├─ if done and packet_count > 0:
  │      agent.remember(prev_state, prev_action, reward, state, done)
  │                                   ← store (s, a, r, s', done) in ReplayBuffer
  │
  ├─ select_action(state, available_actions)
  │      ├─ with prob epsilon:  random action from available_actions  (explore)
  │      └─ with prob 1-epsilon: argmax Q(state) masked to available_actions (exploit)
  │                              Q-values computed by DQN.forward()
  │
  ├─ zmq_sock.send({"action": action})   →  back to gem5
  │
  ├─ if packet_count % train_frequency == 0:
  │      agent.train()
  │           ├─ sample batch from ReplayBuffer
  │           ├─ compute target Q = r + gamma * max Q_target(s')
  │           ├─ MSE loss on Q_network
  │           ├─ optimizer.step()
  │           ├─ decay epsilon  (epsilon *= epsilon_decay)
  │           └─ every target_update_frequency steps:
  │                  update_target_network()  — copy Q → Q_target
  │
  └─ packet_count++
```

---

## Stage 10 — Reward Stored After Each Hop

**File:** `src/mem/ruby/network/garnet/OutputUnit.cc`

**Function:** `OutputUnit::insert_flit()` (or similar)

After the crossbar moves the flit into the output buffer and before it leaves
on the link, gem5 calculates the reward for that hop:

```
reward = 1.0 / (queuing_delay_cycles + 1)
         (high reward = low delay = good routing decision)

DeepNR::store_reward(packet_id, reward, queuing_delay_cycles)
DeepNR::store_terminal(packet_id, is_last_hop)
```

This reward is retrieved at the **next** routing call for that packet
(Stage 8b, step 1), so the (state, action, reward, next_state) tuple is always
complete before being sent to the agent.

---

## Stage 11 — Flit Arrives at Destination NI

**File:** `src/mem/ruby/network/garnet/NetworkInterface.cc`

**Function:** `NetworkInterface::incrementStats()` (line 154)

When the tail flit is dequeued at the destination NI:

```
incrementStats(flit*)
  ├─ network_delay = flit.dequeue_time - flit.enqueue_time - 1 cycle
  │                  (pure in-network transit time)
  ├─ queueing_delay = src_delay + dest_delay
  │
  ├─ increment_flit_network_latency(network_delay, vnet)
  ├─ increment_flit_queueing_latency(queueing_delay, vnet)
  │
  └─ if tail flit:
       ├─ increment_received_packets(vnet)
       ├─ increment_packet_network_latency(network_delay, vnet)   ← accumulates total
       └─ increment_packet_queueing_latency(queueing_delay, vnet)
```

These are running totals — the averages are computed later as formulas.

---

## Stage 12 — Episode Ends

**Trigger:** either `--sim-cycles` is exhausted, or `RoutingUnit` calls
`exitSimLoopNow("DeepNR episode ended: ...")` on an invalid/dead-end action.

gem5 exits the tick loop and returns to the Python config script.

---

## Stage 13 — Stats Collected and Written

**File:** `src/mem/ruby/network/garnet/GarnetNetwork.cc`

**Function:** `GarnetNetwork::collateStats()` (line 556)

Called once when simulation ends:

```
collateStats()
  └─ for each NetworkLink:
       activity = link.getLinkUtilization()   (cycles the link was busy)
       if EXT_IN:   m_total_ext_in_link_utilization  += activity
       if EXT_OUT:  m_total_ext_out_link_utilization += activity
       if INT:      m_total_int_link_utilization     += activity
  └─ for each Router:
       router.collateStats()   (router-level buffer/arbiter stats)
```

Then gem5's stats framework computes all `Formula` stats:

```
average_packet_network_latency  = sum(packet_network_latency) / sum(packets_received)
average_packet_queueing_latency = sum(packet_queueing_latency) / sum(packets_received)
average_packet_latency          = network_latency + queueing_latency
average_hops                    = total_hops / sum(flits_received)
```

**File:** `src/python/m5/stats/__init__.py`

`m5.stats.dump()` is called — formats every registered stat into text and
writes it to the output file (configured by `--stats-file`, default `stats.txt`).

The shell script then copies this to:
```
experiment_results/deepnr3d/ep{NNN}_stats.txt
```

---

## Stage 14 — Next Episode

The shell script restarts gem5. The Python agent is still running with its
accumulated experience and partially-trained model. Over many episodes:

- `epsilon` decays (less random exploration, more exploitation of learned Q-values)
- `ReplayBuffer` fills with more diverse (s, a, r, s') tuples
- `DQN` weights improve via periodic `train()` calls
- Every `target_update_frequency` training steps: target network syncs with Q-network

Model is periodically saved to `deepnr_model.pth` (every 1000 packets).

---

## Complete File Reference

| File | Role |
|---|---|
| `run_3d_training.sh` | Outer loop: restarts gem5 per episode, saves stats |
| `configs/example/garnet_deepnr_traffic.py` | gem5 config: builds system, starts simulation |
| `configs/topologies/Mesh_3D.py` | Defines 3D mesh router/link topology |
| `src/mem/ruby/network/garnet/GarnetNetwork.cc` | Network init, stat registration, collateStats, stats dump |
| `src/mem/ruby/network/garnet/GarnetNetwork.hh` | Stat variable declarations |
| `src/mem/ruby/network/garnet/Router.cc` | Per-cycle router wakeup: coordinates all sub-units |
| `src/mem/ruby/network/garnet/InputUnit.cc` | Receives incoming flit from link into VC buffer |
| `src/mem/ruby/network/garnet/RoutingUnit.cc` | Computes output port — hosts full DeepNR ZMQ logic |
| `src/mem/ruby/network/garnet/SwitchAllocator.cc` | Arbitrates which flit gets the crossbar this cycle |
| `src/mem/ruby/network/garnet/CrossbarSwitch.cc` | Moves flit from input VC to output port |
| `src/mem/ruby/network/garnet/OutputUnit.cc` | Sends flit on outgoing link; calculates and stores hop reward |
| `src/mem/ruby/network/garnet/NetworkInterface.cc` | Injects packets; measures and accumulates latency on arrival |
| `src/mem/ruby/network/garnet/flit.cc / flit.hh` | Flit data structure: carries timestamps, route, packet ID |
| `deepnr_agent.py` | Python DQN agent: ZMQ server, epsilon-greedy policy, replay, training |
| `deepnr_routing_log.txt` | Per-packet log: state, action, reward written by RoutingUnit |
| `experiment_results/deepnr3d/ep*_stats.txt` | gem5 stats output per episode |
| `plot_data.json` | Chart values (currently mock; replace with parsed stats) |
| `plot_results.py` | Reads plot_data.json and generates all 5 figures |

---

## Per-Packet Timeline (single packet, single hop)

```
Tick T+0   NI::wakeup()
             flit created, timestamped, injected into output VC
             packets_injected++, flits_injected++

Tick T+1   Router::wakeup() at next router
             InputUnit::wakeup()  — flit arrives in input VC

Tick T+2   SwitchAllocator::wakeup()
             calls RoutingUnit::outportComputeDeepNR3D()
               → builds state vector
               → zmq_send to deepnr_agent.py  (ZMQ blocks here)
               ← zmq_recv action from agent
             SA grants outport to this flit

Tick T+2   (concurrent, Python side)
             agent.select_action(state)  — epsilon-greedy
             agent.remember(...)         — store experience
             agent.train()               — if due (every 5 packets)
             zmq_sock.send({"action": X})

Tick T+3   CrossbarSwitch::wakeup()
             flit moved to OutputUnit buffer

Tick T+4   OutputUnit sends flit on outgoing link
             store_reward(packet_id, reward, queueing_delay)

     ... repeated for each hop ...

Tick T+N   Last hop: flit arrives at destination NI
             NI::incrementStats(flit)
               packet_network_latency  += network_delay
               packet_queueing_latency += queueing_delay
               packets_received++

End of episode:
             GarnetNetwork::collateStats()  — link utilization
             m5.stats.dump()               — write ep*_stats.txt
```
