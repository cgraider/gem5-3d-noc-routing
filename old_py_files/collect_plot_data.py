"""
collect_plot_data.py
====================
Runs gem5 for every (routing algorithm, injection rate, traffic pattern)
combination, then reads garnet_results.json (written by GarnetStatsExporter
inside gem5) and transforms the records into plot_data.json so that the
existing plot_results.py produces plots from real simulation data.

Usage
-----
    # XYZ + CAQR only (no DQN agents required):
    python collect_plot_data.py

    # All four algorithms (requires deepnr_agent.py / proposed_agent.py
    # already running in separate terminals on ports 5555 / 5556):
    python collect_plot_data.py --no-skip-dqn

    # Tune simulation length or gem5 binary:
    python collect_plot_data.py --sim-cycles 100000 --gem5-bin build/ALL/gem5.opt

    # Write to a different output file (default: plot_data.json):
    python collect_plot_data.py --out my_results.json
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults — mirror the injection rates used in plot_data.json
# ---------------------------------------------------------------------------
GEM5_ROOT = Path(__file__).parent.resolve()
DEFAULT_BIN = GEM5_ROOT / "build" / "Garnet_standalone" / "gem5.opt"
CONFIG      = "configs/example/garnet_synth_traffic.py"

INJECTION_RATES_TRANSPOSE = [0.02, 0.04, 0.06, 0.08, 0.10, 0.16, 0.18, 0.20]
INJECTION_RATES_UNIFORM   = [0.02, 0.04, 0.06, 0.08, 0.10, 0.16, 0.18]

# routing-algorithm flag → label used in plot_data.json
ALGORITHMS = {
    4: "XYZ",
    5: "CAQR",
    2: "3D-DeepNR",   # DQN — requires external agent on port 5555
    3: "proposed",    # DQN — requires external agent on port 5556
}
DQN_ALGOS = {2, 3}

RESULTS_JSON = GEM5_ROOT / "garnet_results.json"
PLOT_DATA_FALLBACK = GEM5_ROOT / "plot_data.json"


# ---------------------------------------------------------------------------
# gem5 runner
# ---------------------------------------------------------------------------

def run_gem5(gem5_bin: Path, algo_id: int, rate: float, traffic: str,
             sim_cycles: int, timeout: int) -> bool:
    """Run one gem5 simulation. Returns True on success."""
    cmd = [
        str(gem5_bin), CONFIG,
        "--network=garnet",
        "--num-cpus=16", "--num-dirs=16",
        "--topology=Mesh_XY", "--mesh-rows=4",
        "--vcs-per-vnet=4",
        f"--routing-algorithm={algo_id}",
        "--link-latency=1", "--router-latency=1",
        f"--sim-cycles={sim_cycles}",
        f"--synthetic={traffic}",
        f"--injectionrate={rate}",
    ]
    label = f"algo={ALGORITHMS[algo_id]}  rate={rate}  traffic={traffic}"
    print(f"  Running: {label}")
    try:
        result = subprocess.run(
            cmd, cwd=str(GEM5_ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        if result.returncode != 0:
            print(f"    [warn] gem5 exited with code {result.returncode}")
            return False
        return True
    except subprocess.TimeoutExpired:
        print(f"    [warn] timed out after {timeout}s — skipping")
        return False
    except FileNotFoundError:
        print(f"  [error] gem5 binary not found: {gem5_bin}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# garnet_results.json → plot_data.json transformation
# ---------------------------------------------------------------------------

def load_sim_results() -> list[dict]:
    """Read all records written by GarnetStatsExporter."""
    if not RESULTS_JSON.exists():
        return []
    try:
        return json.loads(RESULTS_JSON.read_text())
    except Exception as e:
        print(f"[warn] Could not parse {RESULTS_JSON}: {e}")
        return []


def load_fallback() -> dict:
    """Load existing plot_data.json as a fallback for sections we didn't run."""
    if PLOT_DATA_FALLBACK.exists():
        try:
            return json.loads(PLOT_DATA_FALLBACK.read_text())
        except Exception:
            pass
    return {}


def build_plot_data(records: list[dict], algo_ids: list[int],
                    fallback: dict) -> dict:
    """
    Transform the flat list of per-run records into the nested dict that
    plot_results.py expects (same schema as plot_data.json).
    """
    # Index records: (routing_name, traffic_pattern, injection_rate) -> record
    index: dict[tuple, dict] = {}
    for r in records:
        key = (r["routing_name"], r["traffic_pattern"], round(r["injection_rate"], 4))
        index[key] = r

    def latency_series(algo_name: str, traffic: str, rates: list[float]) -> list[float]:
        out = []
        for rate in rates:
            key = (algo_name, traffic, round(rate, 4))
            if key in index:
                out.append(round(index[key]["average_packet_latency"], 1))
            else:
                out.append(0.0)
        return out

    def throughput_series(algo_name: str, traffic: str, rates: list[float]) -> list[float]:
        out = []
        for rate in rates:
            key = (algo_name, traffic, round(rate, 4))
            if key in index:
                out.append(round(index[key]["throughput_pct"], 2))
            else:
                out.append(0.0)
        return out

    algo_names = [ALGORITHMS[a] for a in algo_ids]

    # latency_transpose
    lt: dict = {"injection_rates": INJECTION_RATES_TRANSPOSE}
    for name in algo_names:
        lt[name] = latency_series(name, "transpose", INJECTION_RATES_TRANSPOSE)
    # Fill in algorithms we didn't run from fallback
    for name in ALGORITHMS.values():
        if name not in lt and "latency_transpose" in fallback:
            lt[name] = fallback["latency_transpose"].get(name, [])

    # latency_uniform
    lu: dict = {"injection_rates": INJECTION_RATES_UNIFORM}
    for name in algo_names:
        lu[name] = latency_series(name, "uniform_random", INJECTION_RATES_UNIFORM)
    for name in ALGORITHMS.values():
        if name not in lu and "latency_uniform" in fallback:
            lu[name] = fallback["latency_uniform"].get(name, [])

    # throughput_uniform
    tu: dict = {"injection_rates": INJECTION_RATES_UNIFORM}
    for name in algo_names:
        tu[name] = throughput_series(name, "uniform_random", INJECTION_RATES_UNIFORM)
    for name in ALGORITHMS.values():
        if name not in tu and "throughput_uniform" in fallback:
            tu[name] = fallback["throughput_uniform"].get(name, [])

    # training_loss and throughput_training come from deepnr_metrics.json or
    # the existing fallback — the C++ exporter does not produce these.
    training_loss      = fallback.get("training_loss", {})
    throughput_training = fallback.get("throughput_training", {})

    return {
        "_comment": "Generated by collect_plot_data.py from real gem5 simulation output.",
        "latency_transpose":    lt,
        "latency_uniform":      lu,
        "throughput_uniform":   tu,
        "training_loss":        training_loss,
        "throughput_training":  throughput_training,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gem5-bin", type=Path, default=DEFAULT_BIN,
                        help="Path to the gem5 binary")
    parser.add_argument("--sim-cycles", type=int, default=10_000,
                        help="Simulation cycles per run (default: 10000)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Per-run timeout in seconds (default: 300)")
    parser.add_argument("--skip-dqn", action="store_true", default=True,
                        help="Skip DQN algorithms (2=3D-DeepNR, 3=proposed); default ON")
    parser.add_argument("--no-skip-dqn", dest="skip_dqn", action="store_false",
                        help="Include DQN algorithms (agents must be running)")
    parser.add_argument("--out", type=Path, default=PLOT_DATA_FALLBACK,
                        help="Output JSON file (default: plot_data.json)")
    parser.add_argument("--plot", action="store_true", default=True,
                        help="Run plot_results.py after collecting data")
    parser.add_argument("--no-plot", dest="plot", action="store_false")
    parser.add_argument("--fresh", action="store_true", default=False,
                        help="Delete garnet_results.json before starting sweep")
    args = parser.parse_args()

    if not args.gem5_bin.exists():
        print(f"[error] gem5 binary not found: {args.gem5_bin}")
        print("  Build gem5 first:  scons build/Garnet_standalone/gem5.opt -j$(nproc)")
        sys.exit(1)

    algo_ids = [aid for aid in ALGORITHMS if not (args.skip_dqn and aid in DQN_ALGOS)]
    print(f"Algorithms: {[ALGORITHMS[a] for a in algo_ids]}")
    print(f"Sim cycles: {args.sim_cycles}   Timeout: {args.timeout}s")

    if args.fresh and RESULTS_JSON.exists():
        RESULTS_JSON.unlink()
        print(f"Deleted existing {RESULTS_JSON.name}")

    total = len(algo_ids) * (len(INJECTION_RATES_TRANSPOSE) + len(INJECTION_RATES_UNIFORM))
    done  = 0

    print(f"\n--- Transpose traffic ({len(INJECTION_RATES_TRANSPOSE)} rates) ---")
    for algo_id in algo_ids:
        for rate in INJECTION_RATES_TRANSPOSE:
            done += 1
            print(f"[{done}/{total}]", end=" ")
            run_gem5(args.gem5_bin, algo_id, rate, "transpose",
                     args.sim_cycles, args.timeout)

    print(f"\n--- Uniform traffic ({len(INJECTION_RATES_UNIFORM)} rates) ---")
    for algo_id in algo_ids:
        for rate in INJECTION_RATES_UNIFORM:
            done += 1
            print(f"[{done}/{total}]", end=" ")
            run_gem5(args.gem5_bin, algo_id, rate, "uniform_random",
                     args.sim_cycles, args.timeout)

    print(f"\nAll runs complete. Reading {RESULTS_JSON.name} ...")
    records  = load_sim_results()
    fallback = load_fallback()
    print(f"  {len(records)} records collected.")

    plot_data = build_plot_data(records, algo_ids, fallback)

    args.out.write_text(json.dumps(plot_data, indent=2))
    print(f"Wrote {args.out}")

    if args.plot:
        print("Generating plots ...")
        import plot_results
        plot_results.main()


if __name__ == "__main__":
    main()
