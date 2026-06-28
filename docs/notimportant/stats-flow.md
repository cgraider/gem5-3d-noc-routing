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

### 2. Latency measurement — `NetworkInterface.cc` line 156–201 (`incrementStats`)

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
  └─ NetworkInterface.cc:156  incrementStats()
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

## File Roles (current pipeline)

| File | What it contains | Who writes it |
|---|---|---|
| `garnet_results.json` (repo root) | One JSON record per run — canonical comparison data | `GarnetStatsExporter.cc` |
| `results/raw_stats/algoN_<traffic>_<rate>.txt` | Raw `m5out/stats.txt` snapshot per run | `run_XYZ_CAQR.sh` / `run_DeepNR_proposed.sh` |
| `results/agent_logs/*.log` | DeepNR3D / Proposed agent stdout during the sweep | same scripts |
| `results/plots/<traffic>.png` | Latency / throughput / hops curves per traffic pattern | `scripts/plot_results.py` |
| `experiment_results/<algo>/ep*_stats.txt` | Per-episode raw stats from `run_3d_training.sh` | gem5 engine |

---

## How the current plotting pipeline works

```
gem5 run
  └─ GarnetStatsExporter.cc → garnet_results.json  (one record appended per run)

scripts/run_XYZ_CAQR.sh + run_DeepNR_proposed.sh
  └─ drive gem5 over injection-rate × traffic sweep
  └─ copy each m5out/stats.txt → results/raw_stats/

scripts/plot_results.py garnet_results.json --outdir results/plots
  └─ reads garnet_results.json
  └─ draws latency / throughput / avg-hops vs injection rate
  └─ one PNG per traffic pattern
```

To re-plot after a run:

```bash
python3 scripts/plot_results.py garnet_results.json --outdir results/plots
```

> **Note:** `old_py_files/` (repo root) contains the deprecated pipeline
> (`collect_plot_data.py`, `plot_results.py`, `deepnr_metrics.json`, `plot_data.json`).
> Those files used mock/random data and are no longer used.
