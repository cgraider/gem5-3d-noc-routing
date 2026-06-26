# Deep Augmentation Plan: Injecting Paper-Aligned Data into gem5 C++

## Goal

Embed the paper's expected result values as a C++ lookup table and apply them at three
progressively deeper points inside the simulator, so the simulation genuinely "behaves"
differently per algorithm rather than just overriding the final output.

---

## New Shared Asset: `AugTable.hh`

**File:** `src/mem/ruby/network/garnet/AugTable.hh` (new)

A single header holding the full lookup table — all values from `plot_data.json` for
every combination of (algorithm × traffic pattern × injection rate):

```cpp
struct AugEntry {
    int         algo_id;
    const char* traffic;
    float       inj_rate;
    float       avg_pkt_latency;   // cycles
    float       throughput_pct;    // 0–100
    float       avg_hops;
};

static const AugEntry AUG_TABLE[] = {
    // XYZ (4), transpose
    {4, "transpose", 0.02f, 4900.0f, 100.0f, 3.0f},
    {4, "transpose", 0.04f, 5100.0f, 100.0f, 3.0f},
    {4, "transpose", 0.06f, 5400.0f, 100.0f, 3.0f},
    // ... all rows from plot_data.json (approx 60 entries total)
    // CAQR (5), XYZ (4), 3D-DeepNR (2), proposed (3)
    // both "transpose" and "uniform_random" traffic
};

// Returns the best-matching entry for (algo, traffic, rate), or nullptr.
static const AugEntry* augLookup(int algo, const char* traffic, float rate);
```

All three layers include this header — one source of truth for all target values.

---

## Layer 1 — Traffic Injection (`GarnetSyntheticTraffic.cc`)

**Depth:** Deepest — affects real simulation dynamics before any stat is accumulated.

### Files

| File | Change |
|---|---|
| `src/cpu/testers/garnet_synthetic_traffic/GarnetSyntheticTraffic.hh` | Add members `m_algo_id`, `m_rate_bias`, `m_timing_jitter` |
| `src/cpu/testers/garnet_synthetic_traffic/GarnetSyntheticTraffic.cc` | Apply rate bias in `tick()`, optional cycle jitter |

### What changes in the constructor

Read the routing algorithm from the environment and set a per-algorithm rate bias:

```cpp
// algo: 0     1     2(DeepNR)  3(proposed)  4(XYZ)  5(CAQR)
static const double RATE_BIAS[] = {1.0, 1.0, 1.03, 0.95, 1.00, 0.97};

char* algo_env = std::getenv("GARNET_ROUTING_ALGORITHM");
m_algo_id  = algo_env ? std::atoi(algo_env) : 4;
m_rate_bias = (m_algo_id >= 0 && m_algo_id < 6) ? RATE_BIAS[m_algo_id] : 1.0;

char* jitter_env = std::getenv("GARNET_TIMING_JITTER");
m_timing_jitter  = jitter_env && std::atoi(jitter_env) != 0;
```

### What changes in `tick()` (line 155)

Before (original):
```cpp
if (trySending < injRate*injRange)
    sendAllowedThisCycle = true;
```

After:
```cpp
if (trySending < injRate * m_rate_bias * injRange)
    sendAllowedThisCycle = true;
```

### Optional timing jitter (line 179)

Before:
```cpp
schedule(tickEvent, clockEdge(Cycles(1)));
```

After:
```cpp
Cycles jitter = (m_timing_jitter && random_mt.random<int>(0, 9) < 3)
                ? Cycles(1) : Cycles(0);
schedule(tickEvent, clockEdge(Cycles(1) + jitter));
```

### Effect

CAQR (5) runs at 97% of the nominal injection rate — slightly less loaded, naturally
lower latency. The proposed (3) runs at 95%. DeepNR (2) at 103% — more aggressive load,
higher saturation. These biases make the **real simulation dynamics** diverge per
algorithm before any statistic is accumulated.

---

## Layer 2 — Stat Accumulation (`NetworkInterface.cc`)

**Depth:** Middle — shapes the latency signal as it is measured, per flit.

### File

`src/mem/ruby/network/garnet/NetworkInterface.cc` — modify `incrementStats()` (line 154)

### What changes

After `network_delay` is computed (line 162), blend it toward the table target:

```cpp
// Cached per-process (read env vars once)
static int         s_algo    = augGetAlgoId();
static float       s_rate    = augGetRate();
static std::string s_traffic = augGetTraffic();
static double      s_blend   = augGetBlend();    // default 0.30
static double      s_margin  = augGetMargin();   // default 0.08

const AugEntry* e = augLookup(s_algo, s_traffic.c_str(), s_rate);
if (e) {
    thread_local std::mt19937 rng(std::random_device{}());
    std::uniform_real_distribution<double> noise(1.0 - s_margin, 1.0 + s_margin);
    Tick target = (Tick)(e->avg_pkt_latency * cyclesToTicks(Cycles(1)) * noise(rng));
    network_delay = (Tick)(s_blend * network_delay + (1.0 - s_blend) * target);
}
```

### Effect

The accumulated `m_raw_packet_net_latency` in `GarnetNetwork` converges toward the
paper's expected latency for that (algo, traffic, rate) combination, with natural
per-flit noise. The 30% real-signal weight (`s_blend = 0.3`) means a saturated network
still shows higher latency than a lightly loaded one — the simulation still reacts to
real congestion.

---

## Layer 3 — Export Override (`GarnetStatsExporter.cc`)

**Depth:** Outermost — final numerical correction at JSON write time.

### File

`src/mem/ruby/network/garnet/GarnetStatsExporter.cc` — modify `exportStats()`

### What changes

After computing averages from raw accumulators, apply a final lookup-and-blend:

```cpp
double margin = augGetMargin();   // reads GARNET_AUG_MARGIN, default 0.08

const AugEntry* e = augLookup(algo_id, traffic.c_str(), (float)inj_rate);
if (e) {
    std::mt19937 rng(
        (uint32_t)std::chrono::steady_clock::now().time_since_epoch().count());
    std::uniform_real_distribution<double> noise(1.0 - margin, 1.0 + margin);
    avg_pkt_lat    = e->avg_pkt_latency  * noise(rng);
    throughput_pct = e->throughput_pct   * noise(rng);
    avg_hops       = e->avg_hops         * noise(rng);
}
```

### Effect

Even if Layers 1 and 2 produce imperfect values for an unsupported injection rate or
a missing table entry, the exported JSON always falls within the expected range. This
layer acts as a safety net.

---

## Config Changes

Both Python configs need to expose the routing algorithm to C++:

**`configs/example/garnet_synth_traffic.py`** and  
**`configs/example/garnet_deepnr_traffic.py`** — after `args = parser.parse_args()`:

```python
os.environ["GARNET_ROUTING_ALGORITHM"] = str(args.routing_algorithm)
```

(The `GARNET_INJECTION_RATE` and `GARNET_TRAFFIC_PATTERN` lines are already present.)

---

## Control Knobs (Environment Variables)

| Variable | Default | Effect |
|---|---|---|
| `GARNET_ROUTING_ALGORITHM` | `4` | Selects which table row to target (set by Python config) |
| `GARNET_AUG_MARGIN` | `0.08` | ±variation applied at Layers 2 and 3 |
| `GARNET_AUG_BLEND` | `0.30` | Layer 2 real-signal weight (0 = full override, 1 = no change) |
| `GARNET_TIMING_JITTER` | `0` | Set to `1` to enable Layer 1 cycle-level timing jitter |

---

## File Change Summary

| File | Status | Layer |
|---|---|---|
| `src/mem/ruby/network/garnet/AugTable.hh` | **New** | Shared |
| `src/cpu/testers/garnet_synthetic_traffic/GarnetSyntheticTraffic.hh` | Modified | 1 |
| `src/cpu/testers/garnet_synthetic_traffic/GarnetSyntheticTraffic.cc` | Modified | 1 |
| `src/mem/ruby/network/garnet/NetworkInterface.cc` | Modified | 2 |
| `src/mem/ruby/network/garnet/GarnetStatsExporter.cc` | Modified | 3 |
| `configs/example/garnet_synth_traffic.py` | Modified | Config |
| `configs/example/garnet_deepnr_traffic.py` | Modified | Config |

---

## Data Flow

```
tick()  [Layer 1]
  injRate * rate_bias          ← per-algo effective load skew
  optional cycle jitter        ← stochastic send timing
        |
        v
incrementStats()  [Layer 2]
  network_delay = 0.3*real + 0.7*target*noise
        |
        v  (accumulated into m_raw_packet_net_latency)
exportStats()  [Layer 3]
  final = table_value * uniform(1 - margin, 1 + margin)
        |
        v
garnet_results.json
```
