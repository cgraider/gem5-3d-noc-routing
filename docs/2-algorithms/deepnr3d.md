# DeepNR3D — Code Walkthrough

DeepNR3D is a Deep Q-Network (DQN) based routing algorithm for 3D Network-on-Chip. At each routing hop, the gem5 router sends the current network state to a Python agent over ZMQ, receives a routing direction, and forwards the packet that way. The agent trains on the experience while the simulation runs.

---

## Files involved

| File | Role |
|---|---|
| `src/mem/ruby/network/garnet/CommonTypes.hh` | Adds `DEEPNR3D_` enum value |
| `src/mem/ruby/network/garnet/SConscript` | Links ZMQ and defines `USE_ZMQ` |
| `src/mem/ruby/network/garnet/RoutingUnit.hh` | Declares `outportComputeDeepNR3D()` |
| `src/mem/ruby/network/garnet/RoutingUnit.cc` | Full routing implementation (C++) |
| `src/mem/ruby/network/garnet/OutputUnit.cc` | Calculates reward when flit exits |
| `src/mem/ruby/network/garnet/GarnetNetwork.py` | Exposes routing algorithm to config |
| `deepnr_agent.py` | Python DQN agent (ZMQ server) |

---

## 1. CommonTypes.hh — routing algorithm enum

**File:** `src/mem/ruby/network/garnet/CommonTypes.hh`, line 53

```cpp
enum RoutingAlgorithm { TABLE_ = 0, XY_ = 1, DEEPNR3D_ = 2,
                        PROPOSED_ = 3, NUM_ROUTING_ALGORITHM_};
```

This enum is how the `--routing-algorithm=2` CLI flag maps to C++ code. The value 2 selects DeepNR3D in the switch statement inside `outportCompute()`.

---

## 2. SConscript — ZMQ linkage

**File:** `src/mem/ruby/network/garnet/SConscript`, appended at the bottom

```python
try:
    env.Append(LIBS=['zmq'])
    env.Append(CPPFLAGS=['-DUSE_ZMQ'])
except:
    pass
```

Adds `-lzmq` to the linker and `-DUSE_ZMQ` to the compiler. All DeepNR C++ code is inside `#ifdef USE_ZMQ` guards. If ZMQ is not installed, the build still succeeds but DeepNR will call `fatal()` at runtime.

---

## 3. RoutingUnit.hh — declarations

**File:** `src/mem/ruby/network/garnet/RoutingUnit.hh`, lines 76–83

```cpp
// DeepNR 3D: DQN-based adaptive routing for 3D NoC (ZMQ port 5555)
int outportComputeDeepNR3D(RouteInfo route,
                           int inport,
                           PortDirection inport_dirn);
```

Declares the method alongside `outportComputeXY()`. The `RoutingUnit` class owns port-direction maps (`m_outports_dirn2idx`, `m_inports_dirn2idx`) used to translate direction strings like `"North"` to output port indices.

---

## 4. RoutingUnit.cc — dispatch

**File:** `src/mem/ruby/network/garnet/RoutingUnit.cc`, lines 218–256

`outportCompute()` is called by the InputUnit on every flit that needs a routing decision. It reads the algorithm from the network config and dispatches:

```cpp
switch (routing_algorithm) {
case TABLE_:   outport = lookupRoutingTable(...); break;
case XY_:      outport = outportComputeXY(...);   break;
case DEEPNR3D_: outport = outportComputeDeepNR3D(...); break;
case PROPOSED_: outport = outportComputeProposed(...); break;
}
```

If the destination is the current router, the packet goes to a local port immediately (line 222–228) without consulting the algorithm.

---

## 5. RoutingUnit.cc — DeepNR namespace (reward storage)

**Lines 67–113**

Before the routing function itself, a small namespace `DeepNR` provides shared storage for rewards and terminal flags:

```cpp
namespace DeepNR {
static std::map<int, float> packet_rewards;  // packet_id → reward
static std::map<int, bool>  packet_terminal; // packet_id → is_terminal
```

**`store_reward(packet_id, reward, queuing_delay_cycles)`** (line 74) — called from `OutputUnit.cc` when a flit leaves a router's output buffer. Stores the reward keyed by packet ID.

**`store_terminal(packet_id, is_terminal)`** (line 86) — stores whether the next hop is the destination (done flag for RL).

**`get_reward(packet_id)`** (line 90) — retrieves and erases the stored reward. One-time use: the reward is consumed when the next routing decision reads it.

**`get_done(packet_id)`** (line 99) — same pattern for the done flag.

**`set_log_file(file, every_n, counter)`** (line 108) — lets the routing function pass a log file handle into this namespace so `store_reward` can log reward calculations.

---

## 6. RoutingUnit.cc — `outportComputeDeepNR3D()`

**Lines 319–834**

This is the main DeepNR3D function. It is called once per routing hop per packet.

### 6.1 Static state (lines 323–358)

```cpp
static void *zmq_ctx  = nullptr;
static void *zmq_sock = nullptr;
static bool  zmq_initialized = false;
static int   packet_counter  = 0;
static int   connection_failure_count = 0;
static int   invalid_action_count = 0;
static int   total_actions = 0;
```

`static` here means these variables persist across calls to the function (they are shared across all routers in the simulation). The ZMQ context and socket are created once on the first call and reused.

### 6.2 Termination thresholds (lines 333–337)

```cpp
static const int    MAX_CONNECTION_FAILURES  = 10;
static const double MAX_INVALID_ACTION_RATE  = 0.3;
static const int    MIN_ACTIONS_FOR_RATE_CHECK = 100;
```

If the agent is not responding (10 ZMQ failures) or is choosing invalid directions more than 30% of the time (after 100 actions), `fatal()` is called to end the simulation. This is intentional — it signals to the training loop that the episode is over.

### 6.3 ZMQ initialisation (lines 369–443)

```cpp
if (!zmq_initialized) {
    zmq_ctx  = zmq_ctx_new();
    zmq_sock = zmq_socket(zmq_ctx, ZMQ_REQ);
    zmq_setsockopt(zmq_sock, ZMQ_RCVTIMEO, &timeout, sizeof(timeout)); // 1 second
    zmq_connect(zmq_sock, "tcp://localhost:5555");
    zmq_initialized = true;
}
```

Creates a ZMQ REQ socket (request-reply pattern). gem5 is the client; the Python agent is the server. The 1-second timeout ensures gem5 does not hang forever if the agent crashes.

A log file `deepnr_routing_log.txt` is opened here on first use (line 418).

### 6.4 Retrieving reward from the previous hop (lines 480–488)

```cpp
float reward_from_previous = DeepNR::get_reward(packet_id_for_reward);
bool  done_from_previous   = DeepNR::get_done(packet_id_for_reward);
```

The reward for the previous routing decision was stored by `OutputUnit` when the flit exited that router's output buffer. It is retrieved here and will be sent to the agent as part of this state message, closing the RL feedback loop.

### 6.5 Network dimensions and 3D coordinates (lines 491–532)

```cpp
int total_routers_in_network = m_router->get_net_ptr()->getNumRouters();
int num_layers = total_routers_in_network / (num_rows * num_cols);
int num_routers = num_rows * num_cols * num_layers;

// Router ID = z * (rows * cols) + y * cols + x
int my_z = my_id / (num_rows * num_cols);
int my_y = (my_id % (num_rows * num_cols)) / num_cols;
int my_x = my_id % num_cols;
```

Router IDs are linearised in row-major order per layer. This decomposition converts a flat ID back to (x, y, z) coordinates for distance calculations and boundary checks.

### 6.6 Building the state vector (lines 540–596)

State size = `2 * num_routers + 8`.

```cpp
std::vector<float> state_vector;
state_vector.reserve(2 * num_routers + 8);
```

**f1 — current router one-hot** (lines 544–546): `num_routers` floats, all 0 except position `my_id` which is 1.

**f2 — destination router one-hot** (lines 549–551): same encoding for `dest_id`.

**f3 — normalised hops traversed** (lines 553–559): `hops_traversed / max_hops` clamped to [0, 1]. `max_hops = (rows-1) + (cols-1) + (layers-1)`.

**f4 — normalised 3D Manhattan distance** (lines 562–564): `(|dx| + |dy| + |dz|) / max_hops`.

**f5 — buffer free ratios for 6 directions** (lines 566–589): For each direction (N, E, S, W, Up, Down), reads `get_credit_count(vc)` from the corresponding `OutputUnit` and normalises by `num_vcs * 4`. Higher value = more free buffer space.

### 6.7 Available-actions mask (lines 599–621)

```cpp
std::vector<bool> available_actions(6, true);
if (my_y == 0)              available_actions[0] = false; // no North
if (my_x == num_cols - 1)   available_actions[1] = false; // no East
if (my_y == num_rows - 1)   available_actions[2] = false; // no South
if (my_x == 0)              available_actions[3] = false; // no West
if (my_z == num_layers - 1) available_actions[4] = false; // no Up
if (my_z == 0)              available_actions[5] = false; // no Down
```

Boundary routers cannot move in directions that would go off-mesh. Directions with zero free buffer are also blocked (lines 614–621). This mask is sent to the agent so it can avoid selecting illegal actions.

### 6.8 Sending the state to the agent (lines 623–659)

```cpp
json_stream << "{\"state\":[...]"
            << ",\"packet_id\":" << packet_counter
            << ",\"reward\":"    << reward_from_previous
            << ",\"done\":"      << (done_from_previous ? "true" : "false")
            << ",\"available_actions\":[...]}";
zmq_send(zmq_sock, json_msg.c_str(), json_msg.length(), 0);
```

A JSON string is built manually (no external JSON library) and sent over ZMQ. If `zmq_send` fails, the failure counter increments; at 10 failures the simulation terminates.

### 6.9 Receiving and validating the action (lines 661–738)

```cpp
zmq_recv(zmq_sock, buffer, sizeof(buffer) - 1, 0);
// parse "action": N from the JSON response
```

The agent replies with `{"action": 0}` through `{"action": 5}`. The code:

1. Checks the action is in range 0–5.
2. Checks `available_actions[action]` is true.
3. If either check fails: stores reward −10 for this packet, increments `invalid_action_count`, and calls `terminateDeepNR()`.
4. Checks if the cumulative invalid rate exceeds 30% (after 100 actions) and terminates if so.

### 6.10 Storing the terminal flag (lines 764–777)

```cpp
int next_router_id = next_z * (num_rows * num_cols) + next_y * num_cols + next_x;
DeepNR::store_terminal(packet_id_for_reward, next_router_id == dest_id);
```

After computing which router this action would reach, stores `done=true` if it is the destination. This flag will be read at the next routing decision (or by `OutputUnit`) and sent back to the agent.

### 6.11 Returning the output port (lines 780–826)

```cpp
PortDirection outport_dirn = directions[action]; // e.g. "North"
outport_idx = m_outports_dirn2idx[outport_dirn];
return outport_idx;
```

Translates the integer action to a port direction string, then looks up the physical output port index from the router's direction map.

---

## 7. OutputUnit.cc — reward calculation

**File:** `src/mem/ruby/network/garnet/OutputUnit.cc`, lines appended near `insert_flit()`

```cpp
#ifdef USE_ZMQ
namespace DeepNR {
    extern void store_reward(int packet_id, float reward,
                             double queuing_delay_cycles);
}

int ra = m_router->get_net_ptr()->getRoutingAlgorithm();
if (ra == DEEPNR3D_ || ra == PROPOSED_) {
    flit_type ft = t_flit->get_type();
    if (ft == HEAD_ || ft == HEAD_TAIL_) {
        Tick enqueue_time  = t_flit->get_enqueue_time();
        Tick queuing_ticks = (curTick() > enqueue_time)
                             ? (curTick() - enqueue_time) : 0;
        double queuing_cycles = (double)queuing_ticks /
                                (double)m_router->clockPeriod();
        float reward = 1.0f / (float(queuing_cycles) + 1.0f);
        DeepNR::store_reward(t_flit->getPacketID(), reward, queuing_cycles);
    }
}
#endif
```

When a flit is inserted into an output buffer (`insert_flit`), if the routing algorithm is DEEPNR3D_ or PROPOSED_, and the flit is a HEAD flit (carries the enqueue timestamp), the reward is computed as `1 / (queuing_delay + 1)`. This maps low delay to reward near 1.0 and high delay toward 0. The reward is stored in the `DeepNR::packet_rewards` map and consumed at the next routing decision.

---

## 8. deepnr_agent.py — Python DQN agent

### 8.1 DQN class (lines 65–110)

Five-layer network:

```
state_size → 64 (compress)  → ReLU
64 → 256 (fc1)              → ReLU
256 → 128 (fc2)             → ReLU
128 → 64 (fc3)              → ReLU
64 → action_size (fc4)      → linear (raw Q-values)
```

The compression layer (`fc_compress`) handles variable mesh sizes — a 4×4×2 mesh has state size 72, an 8×8×4 mesh has 272, but the rest of the network is always 64→256→128→64→6.

### 8.2 ReplayBuffer class (lines 118–155)

```python
self.buffer = deque(maxlen=capacity)  # default 200
```

Fixed-size circular buffer. `push()` adds `(state, action, reward, next_state, done)`. `sample(batch_size)` draws random experiences and returns them as PyTorch tensors. The small default size (200) follows the paper; the training script overrides this to 20 000.

### 8.3 DeepNR_Agent class (lines 163–363)

**`__init__`**: Creates `q_network` (online) and `target_network` (frozen copy). Adam optimizer. Initialises replay buffer.

**`select_action(state, training, available_actions)`** (lines 227–285): Epsilon-greedy with action masking. During exploration (`random() < epsilon`), picks randomly from valid actions only. During exploitation, runs a forward pass, masks invalid actions to `-inf`, adds tiny noise to break ties, returns `argmax`.

**`remember(state, action, reward, next_state, done)`** (line 287): Pushes one experience to the replay buffer.

**`train()`** (lines 292–339):
1. Samples a batch from the replay buffer.
2. Computes current Q-values: `q_network(states).gather(1, actions)`.
3. Computes target Q-values: `reward + gamma * target_network(next_states).max() * ~done`.
4. Loss: MSE between current and target.
5. Gradient clipping at norm 1.0.
6. Decays epsilon after each training step.
7. Copies weights to `target_network` every `target_update_frequency` steps.

**`save_model / load_model`** (lines 341–363): Saves/loads all network weights, optimizer state, epsilon, and training step count to a `.pth` file.

### 8.4 DeepNR_Server class (lines 371–972)

ZMQ REP socket bound on port 5555. Main loop in `run()` (lines 506–972):

1. **Poll** for incoming messages with 50ms timeout (allows Ctrl+C to interrupt).
2. **Receive** JSON from gem5: `{state, packet_id, reward, done, available_actions}`.
3. **Store experience** from the previous step (now that we have the reward for it): calls `agent.remember(last_state, last_action, reward, next_state, done)`.
4. **Select action**: calls `agent.select_action()` with action mask.
5. **Send** `{"action": N}` back to gem5.
6. **Train** every `train_frequency` packets once the buffer has enough entries.
7. **Auto-save** model every 500 packets.
8. Prints status every 100 packets (epsilon, memory size, invalid action rate).

### 8.5 main() (lines 980–1223)

Parses CLI args, creates the agent with the specified hyperparameters, optionally loads a saved model, creates the server, and calls `server.run()`. On exit (Ctrl+C or gem5 disconnect), always saves the model.
