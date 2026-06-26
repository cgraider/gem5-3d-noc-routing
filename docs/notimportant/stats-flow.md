# Simulation Stats — Where They Live and How They Flow

## Where gem5 Writes Stats

After each episode, gem5 writes one stats file:

```
experiment_results/deepnr3d/ep001_stats.txt   ← baseline (3D-DeepNR)
experiment_results/deepnr3d/ep002_stats.txt
...
experiment_results/proposed/ep001_stats.txt   ← proposed method (3D-DeepNR With Improved State)
experiment_results/proposed/ep002_stats.txt
...
```

---

## How gem5 Collects and Calculates These Stats (Source Code)

All network stats come from two C++ files in the Garnet network model:

### 1. Injection — `src/mem/ruby/network/garnet/NetworkInterface.cc` line 437–441

When a packet is created and flitized at the source NI, gem5 increments:

```cpp
m_net_ptr->increment_injected_packets(vnet);   // packets_injected counter
m_net_ptr->increment_injected_flits(vnet);     // flits_injected counter (per flit)
```

It also stamps each flit with `curTick()` as its birth time, and records the
time it spent waiting in the source message buffer (`set_src_delay`).

### 2. Latency measurement — `NetworkInterface.cc` line 154–177 (`incrementStats`)

When a flit **arrives at the destination NI**, gem5 calls `incrementStats(flit*)`:

```
network_delay     = flit.dequeue_time - flit.enqueue_time - 1 cycle
                    (time the flit spent inside the network)

src_queueing_delay = time the packet waited at source before injection
dest_queueing_delay = curTick() - flit.dequeue_time
                    (time waiting at destination output buffer)

queueing_delay = src_queueing_delay + dest_queueing_delay
```

For every flit:
```cpp
m_net_ptr->increment_flit_network_latency(network_delay, vnet);
m_net_ptr->increment_flit_queueing_latency(queueing_delay, vnet);
```

Only on the **tail flit** (marks end of packet):
```cpp
m_net_ptr->increment_received_packets(vnet);
m_net_ptr->increment_packet_network_latency(network_delay, vnet);
m_net_ptr->increment_packet_queueing_latency(queueing_delay, vnet);
```

### 3. Average calculation — `GarnetNetwork.cc` line 437–450

These are declared as `statistics::Formula` — gem5 computes them automatically
at dump time as a ratio:

```cpp
average_packet_network_latency   = sum(packet_network_latency) / sum(packets_received)
average_packet_queueing_latency  = sum(packet_queueing_latency) / sum(packets_received)
average_packet_latency           = network_latency + queueing_latency
```

No explicit loop needed — gem5's stats framework divides the accumulated totals
when writing the file.

### 4. Link utilization — `GarnetNetwork.cc` line 556–579 (`collateStats`)

Called once at the end of simulation. Loops over every network link and reads
`getLinkUtilization()` (how many cycles the link was active), then accumulates:

```cpp
m_total_ext_in_link_utilization  += activity;   // external in-links (NI→router)
m_total_ext_out_link_utilization += activity;   // external out-links (router→NI)
m_total_int_link_utilization     += activity;   // internal links (router↔router)
```

### 5. Stats written to file — gem5 stats framework

gem5's Python layer (`src/python/m5/stats/__init__.py`) calls `m5.stats.dump()`
at the end of each simulation run. This triggers the C++ stats backend to format
every registered `statistics::Scalar`, `Vector`, and `Formula` into the text
output, producing the `ep*_stats.txt` file.

### Full call chain summary

```
Packet injected at source NI
  └─ NetworkInterface.cc:437  increment_injected_packets / increment_injected_flits

Flit traverses routers  (Router.cc → RoutingUnit → OutputUnit → crossbar)

Flit arrives at destination NI
  └─ NetworkInterface.cc:154  incrementStats()
       ├─ measures network_delay and queueing_delay from flit timestamps
       ├─ calls increment_flit_network_latency / increment_flit_queueing_latency
       └─ on tail flit: increment_packet_network_latency / increment_packet_queueing_latency

End of simulation
  └─ GarnetNetwork.cc:556  collateStats()
       └─ loops all links → accumulates ext_in_link_utilization, int_link_utilization

  └─ m5.stats.dump()
       └─ Formula stats computed (averages = totals / counts)
       └─ all values written to ep*_stats.txt
```

---

## Key Network Stats (end of each ep*_stats.txt)

These lines appear near the **last ~20 lines** of every stats file:

| Stat key | Meaning | Unit |
|---|---|---|
| `system.ruby.network.packet_network_latency` | Average packet latency | ticks (÷1000 = cycles) |
| `system.ruby.network.packet_queueing_latency` | Queueing component of latency | ticks |
| `system.ruby.network.flit_network_latency` | Average flit latency | ticks |
| `system.ruby.network.flit_queueing_latency` | Flit queueing latency | ticks |
| `system.ruby.network.packets_injected` | Total packets injected | count |
| `system.ruby.network.flits_injected` | Total flits injected | count |
| `system.ruby.network.ext_in_link_utilization` | External link utilization (throughput proxy) | % |
| `system.ruby.network.int_link_utilization` | Internal link utilization | % |

---

## File Roles

| File | What it contains | Who writes it |
|---|---|---|
| `experiment_results/deepnr3d/ep*_stats.txt` | Real gem5 stats per episode (baseline) | gem5 engine |
| `experiment_results/proposed/ep*_stats.txt` | Real gem5 stats per episode (proposed method) | gem5 engine |
| `deepnr_metrics.json` | Runtime metrics (currently uses random/fake values) | `collect_deepnr_metrics.py` |
| `plot_data.json` | Chart values used by `plot_results.py` (currently mock) | Manually / future parser |
| `deepnr_metrics_plot.png` | Auto-generated plots from runtime metrics | `deepnr_metrics.py` |

---

## Critical Gap

`collect_deepnr_metrics.py` does **not** read the `ep*_stats.txt` files.
It currently fills `deepnr_metrics.json` with `numpy` random numbers.

Nothing automatically reads the real gem5 output and feeds it into `plot_data.json`.

---

## What Needs to Be Built

A parser script that:
1. Loops over all `ep*_stats.txt` files in both `deepnr3d/` and `proposed/`
2. Extracts `packet_network_latency` and `ext_in_link_utilization` from each file
3. Averages or aggregates across episodes per injection rate
4. Writes the real values into `plot_data.json`
5. `plot_results.py` then reads `plot_data.json` and regenerates all 5 figures

---

## How plot_results.py Uses the Data

```
plot_data.json  →  plot_results.py  →  experiment_results/*.png
```

- `latency_transpose`  → `latency_transpose.png`
- `latency_uniform`    → `latency_uniform.png`
- `throughput_uniform` → `throughput_uniform.png`
- `training_loss`      → `training_loss.png`
- `throughput_training`→ `throughput_training.png`

To replace mock data with real values: update the arrays in `plot_data.json`, then run:

```bash
python plot_results.py
```
