# Proposed Method — Code Walkthrough

The Proposed method is an enhanced DQN-based 3D NoC routing algorithm. It shares the same gem5-side infrastructure as DeepNR3D (ZMQ, OutputUnit reward, CommonTypes enum) but uses a richer 10-feature state vector, different hyperparameters, and Huber loss instead of MSE. The Python agent (`proposed_agent.py`) is a leaner, tighter implementation than `deepnr_agent.py`.

---

## Files involved

| File | Role |
|---|---|
| `src/mem/ruby/network/garnet/CommonTypes.hh` | Adds `PROPOSED_` enum value |
| `src/mem/ruby/network/garnet/SConscript` | Links ZMQ (shared with DeepNR3D) |
| `src/mem/ruby/network/garnet/RoutingUnit.hh` | Declares `outportComputeProposed()` |
| `src/mem/ruby/network/garnet/RoutingUnit.cc` | Full routing implementation (C++) |
| `src/mem/ruby/network/garnet/OutputUnit.cc` | Reward calculation (shared with DeepNR3D) |
| `proposed_agent.py` | Python DQN agent (ZMQ server on port 5556) |

---

## How it differs from DeepNR3D

| Aspect | DeepNR3D | Proposed |
|---|---|---|
| ZMQ port | 5555 | 5556 |
| State size | `2*N + 8` (5 features) | `2*N + 28` (10 features) |
| Loss | MSE | Huber (smooth L1) |
| Learning rate | 0.01 | 0.0003 |
| Replay buffer | 200 | 10 000 |
| Warm-up | none | 1 000 steps before training |
| Train frequency | every 5 packets | every 40 packets |
| Target update | every 100 train steps | every 500 train steps |
| epsilon_min | 0.01 | 0.1 |

---

## 1. CommonTypes.hh — enum

**File:** `src/mem/ruby/network/garnet/CommonTypes.hh`, line 53

```cpp
enum RoutingAlgorithm { TABLE_ = 0, XY_ = 1, DEEPNR3D_ = 2,
                        PROPOSED_ = 3, XYZ_ = 4, CAQR_ = 5,
                        NUM_ROUTING_ALGORITHM_};
```

Value 3 selects the Proposed method via `--routing-algorithm=3`.

---

## 2. RoutingUnit.hh — declaration

**File:** `src/mem/ruby/network/garnet/RoutingUnit.hh`, lines 81–84

```cpp
// Proposed: DQN-based 3D NoC routing with 10-feature state (via ZMQ port 5556)
int outportComputeProposed(RouteInfo route,
                           int inport,
                           PortDirection inport_dirn);
```

Declared alongside `outportComputeDeepNR3D()` in the same class.

---

## 3. RoutingUnit.cc — dispatch

**File:** `src/mem/ruby/network/garnet/RoutingUnit.cc`, lines 247–249

```cpp
case PROPOSED_:
    outport = outportComputeProposed(route, inport, inport_dirn);
    break;
```

Selected by the same `switch` in `outportCompute()` that dispatches DeepNR3D.

---

## 4. RoutingUnit.cc — `outportComputeProposed()`

**Lines 1019–1338**

### 4.1 Static state (lines 1028–1048)

```cpp
static void *zmq_ctx  = nullptr;
static void *zmq_sock = nullptr;
static bool  zmq_initialized = false;
static int   packet_counter  = 0;
static int   connection_failure_count = 0;
static int   invalid_action_count = 0;
static int   total_actions = 0;

static std::map<int, std::array<float, 6>> ema_occ; // per-router EMA
static const float EMA_ALPHA = 0.1f;
```

The `ema_occ` map is the most important addition over DeepNR3D. It maintains a per-router exponential moving average of buffer occupancy for each of the 6 directions, updated on every routing call for that router. `EMA_ALPHA = 0.1` gives slow-changing, smoothed estimates.

### 4.2 ZMQ initialisation (lines 1059–1087)

Identical pattern to DeepNR3D but connects to port **5556**:

```cpp
zmq_connect(zmq_sock, "tcp://localhost:5556");
```

Log file is `proposed_routing_log.txt`.

### 4.3 Network dimensions (lines 1116–1125)

```cpp
int num_layers = (num_rows * num_cols > 0)
                 ? total_rt / (num_rows * num_cols) : 1;
int num_routers = total_rt;
int layer_size  = num_rows * num_cols;
int clock_period_ticks = (int)m_router->get_net_ptr()->clockPeriod();
```

`clock_period_ticks` is needed for f6 (packet wait time in cycles).

### 4.4 Per-direction buffer info (lines 1143–1171)

```cpp
std::array<float, 6> buf_free{}; // free buffer ratio  (used in f5)
std::array<float, 6> buf_occ{};  // occupied ratio     (used in f7/f8/f9)

for (int d = 0; d < 6; d++) {
    // read credit count from OutputUnit
    buf_free[d] = float(credits) / float(max_credits);
    buf_occ[d]  = 1.0f - buf_free[d];
}

// Update EMA for this router
for (int d = 0; d < 6; d++)
    ema_occ[my_id][d] = EMA_ALPHA * buf_occ[d]
                        + (1.0f - EMA_ALPHA) * ema_occ[my_id][d];
```

The EMA update happens every time this router makes a routing decision, so it accumulates history across all packets passing through.

### 4.5 State vector — 10 features (lines 1173–1233)

State size = `2 * num_routers + 28`. The 28 scalar features come from 10 feature groups:

**f1 — current router one-hot** (lines 992–994): `num_routers` floats. Same as DeepNR3D.

**f2 — destination router one-hot** (lines 996–998): `num_routers` floats. Same as DeepNR3D.

**f3 — normalised hops traversed** (lines 1000–1003): `min(hops / max_hops, 1.0)`. Same as DeepNR3D.

**f4 — normalised 3D Manhattan distance** (lines 1005–1007): `min(manhattan / max_hops, 1.0)`. Same as DeepNR3D.

**f5 — free buffer ratio per direction** (line 1010): 6 floats. Same as DeepNR3D but named `buf_free`.

**f6 — normalised packet wait time** (lines 1012–1020):

```cpp
float wait_cycles = float(current_time - enqueue_time) / float(clock_period_ticks);
float max_wait    = float(max_hops + 1) * 10.0f;
sv.push_back(min(1.0f, wait_cycles / max_wait));
```

How long this packet has been waiting in the current router's input buffer, normalised. A packet waiting longer than expected incurs a higher f6 value, giving the agent a signal to route it urgently.

**f7 — EMA buffer occupancy per direction** (line 1023): 6 floats from `ema_occ[my_id]`. Smoothed history of how busy each output direction has been.

**f8 — predicted link delay** (lines 1027–1032):

```cpp
static const float PIPELINE_DEPTH = 5.0f;
sv.push_back(min(1.0f, ema_occ[my_id][d] * PIPELINE_DEPTH / PIPELINE_DEPTH));
```

Intended to model delay as `EMA_occ × pipeline_depth`, but the normalisation divides by `PIPELINE_DEPTH` again, making f8 = f7. This is a simplification in the current implementation — if you want true delay prediction, change the normalisation denominator to `max_pipeline_cycles`.

**f9 — instantaneous utilisation** (line 1036): 6 floats. `buf_occ[d] = 1 - buf_free[d]`. Instantaneous counterpart of f7.

**f10 — congestion-weighted remaining distance** (lines 1038–1046):

```cpp
float avg_ema = average of ema_occ[my_id] over 6 directions;
float f10 = float(manhattan) * (1.0f + avg_ema)
            / float(max(1, max_hops) * 2);
sv.push_back(min(1.0f, f10));
```

Scales Manhattan distance by `(1 + average congestion)`. When the network is congested, this grows, encouraging the agent to prefer shorter or less congested paths.

### 4.6 Available-actions mask (lines 1239–1249)

```cpp
std::vector<bool> avail(6, true);
if (my_y == 0)              avail[0] = false; // North
if (my_x == num_cols - 1)   avail[1] = false; // East
if (my_y == num_rows - 1)   avail[2] = false; // South
if (my_x == 0)              avail[3] = false; // West
if (my_z == num_layers - 1) avail[4] = false; // Up
if (my_z == 0)              avail[5] = false; // Down
for (int d = 0; d < 6; d++)
    if (buf_free[d] <= 0.0f) avail[d] = false; // no free buffer
```

Same boundary and buffer checks as DeepNR3D.

### 4.7 Sending state and receiving action (lines 1251–1285)

Same JSON protocol as DeepNR3D:

```cpp
js << "{\"state\":[...],\"packet_id\":...,\"reward\":...,\"done\":...,\"available_actions\":[...]}";
zmq_send(zmq_sock, msg.c_str(), msg.size(), 0);
// ...
zmq_recv(zmq_sock, buf, sizeof(buf) - 1, 0);
```

The only difference is the port (5556) and the larger state vector.

### 4.8 Validation and termination (lines 1289–1302)

```cpp
bool bad_action = (action < 0 || action >= 6 || !avail[action]);
if (bad_action) {
    invalid_action_count++;
    DeepNR::store_reward(packet_id, -10.0f, -1.0);
    // check invalid rate then terminate
    terminate("Invalid action ...");
}
```

Same −10 penalty and termination logic as DeepNR3D.

### 4.9 Terminal flag and port mapping (lines 1304–1329)

```cpp
static const int delta[6][3] = {{0,-1,0},{1,0,0},{0,1,0},{-1,0,0},{0,0,1},{0,0,-1}};
int nx = my_x + delta[action][0];
int ny = my_y + delta[action][1];
int nz = my_z + delta[action][2];
int next_id = nz * layer_size + ny * num_cols + nx;
DeepNR::store_terminal(packet_id, next_id == dest_id);
```

Uses a cleaner delta-table instead of the if-else chain in DeepNR3D. The terminal flag is stored in the shared `DeepNR` namespace (same one used by DeepNR3D — this is safe because both algorithms use different ports and cannot run simultaneously).

---

## 5. OutputUnit.cc — reward (shared with DeepNR3D)

**File:** `src/mem/ruby/network/garnet/OutputUnit.cc`

```cpp
if (ra == DEEPNR3D_ || ra == PROPOSED_) {
    // ...
    float reward = 1.0f / (float(queuing_cycles) + 1.0f);
    DeepNR::store_reward(t_flit->getPacketID(), reward, queuing_cycles);
}
```

The reward function is identical for both algorithms. `PROPOSED_` is explicitly included in the condition.

---

## 6. proposed_agent.py — Python agent

### 6.1 Hyperparameters (lines 35–44)

```python
WARM_UP_PHASE      = 1000   # no training for first 1000 steps
TRAIN_FREQUENCY    = 40     # train every 40 routing decisions
TARGET_UPDATE_FREQ = 500    # sync target network every 500 train steps
LEARNING_RATE      = 0.0003
DISCOUNT_FACTOR    = 0.9
EPSILON_START      = 0.9
EPSILON_MIN        = 0.1    # higher floor than DeepNR3D's 0.01
REPLAY_BUFFER_SIZE = 10_000 # 50x larger than DeepNR3D
BATCH_SIZE         = 64
```

All defined as module-level constants. The 1000-step warm-up fills the replay buffer with diverse early experiences before training starts, stabilising initial learning.

### 6.2 DQN class (lines 50–74)

Same five-layer architecture as `deepnr_agent.py`. The only difference is the larger input (state size = `2*N+28`), which is handled by the `compress` layer:

```python
self.compress = nn.Linear(state_size, 64)  # any size → 64
self.fc1 = nn.Linear(64, 256)
self.fc2 = nn.Linear(256, 128)
self.fc3 = nn.Linear(128, 64)
self.out  = nn.Linear(64, action_size)     # → 6
```

### 6.3 ReplayBuffer class (lines 80–99)

```python
self.buf = deque(maxlen=capacity)  # default 10 000
```

Same implementation as DeepNR3D's buffer but with a 50× larger capacity. Larger buffer means more diverse experience samples, reducing correlation between training batches.

### 6.4 ProposedAgent class (lines 105–214)

**`select_action(state, available, training)`** (lines 127–145): Same epsilon-greedy with masking as DeepNR3D, but without the small noise added to Q-values — the higher `epsilon_min = 0.1` provides enough inherent exploration.

**`remember(state, action, reward, next_state, done)`** (lines 148–149): Pushes to replay buffer and increments `step_count`.

**`train()`** (lines 152–192): Key difference from DeepNR3D:

```python
# Huber loss (smooth L1) instead of MSE
loss = nn.functional.smooth_l1_loss(
    current_q.squeeze(), target_q)
```

Huber loss is less sensitive to outlier rewards (very large or very small). For NoC routing where rewards can vary widely depending on network load, this makes training more stable. Everything else (target network, gradient clipping, epsilon decay) is the same as DeepNR3D.

**`save / load`** (lines 195–214): Saves `q_net`, `target_net`, `optimizer`, `epsilon`, `step_count`, and `train_count` to a `.pth` file.

### 6.5 ProposedServer class (lines 220–337)

ZMQ REP socket on port 5556. `run()` loop (lines 251–337):

1. **Poll** with 100ms timeout.
2. **Receive** JSON from gem5.
3. **Store experience** from previous step (once reward arrives).
4. **Select action** and send back.
5. **Train** only if `step_count >= WARM_UP_PHASE` and `step_count % TRAIN_FREQUENCY == 0` and buffer has enough entries.
6. **Log** every 1000 steps: epsilon, buffer size, loss, invalid rate.
7. **Auto-save** every `save_freq` steps (default 2000).

The server loop is simpler than `DeepNR_Server` — no dashboard, no state monitor, no separate invalid-action penalty on the Python side. The gem5 C++ side already stores −10 rewards for invalid actions.

### 6.6 main() (lines 343–390)

```python
num_routers = args.num_rows * args.num_cols * args.num_layers
state_size  = 2 * num_routers + 28
```

State size is computed from the mesh dimensions passed on the CLI. This must match what gem5 sends — if the mesh dimensions differ, the agent will print a warning every routing decision.
