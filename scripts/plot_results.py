#!/usr/bin/env python3
"""plot_results.py — draw latency / throughput / packet-loss curves from
the garnet_results.json produced by the run_*.sh scripts.

For each traffic pattern it draws one figure with three panels
(avg packet latency, throughput %, packet loss %) versus injection rate, one
line per routing algorithm — the same view as the paper's comparison plots.

Usage (from repo root):
    python3 scripts/plot_results.py [garnet_results.json] [--outdir results/plots]
"""
import argparse
import json
import os
import sys
from collections import defaultdict

try:
    import matplotlib
    matplotlib.use("Agg")            # headless: write PNGs, no display needed
    import matplotlib.pyplot as plt
except ImportError:
    print("ERROR: matplotlib is required (pip install matplotlib).")
    sys.exit(1)

# Stable colour/marker per algorithm id.
STYLE = {
    2: ("3D-DeepNR",                   "tab:green",  "o"),
    3: ("3D-DeepNR w/ Improved State", "tab:red",    "s"),
    4: ("XYZ",                         "tab:blue",   "^"),
    5: ("CAQR",                        "tab:orange", "D"),
}
METRICS = [
    ("average_packet_latency", "Avg Packet Latency (cycles)"),
    ("throughput_pct",         "Throughput (%)"),
    ("packet_loss_pct",        "Packet Loss (%)"),
]


def load(path):
    with open(path) as f:
        return json.load(f)


def plot(records, outdir):
    os.makedirs(outdir, exist_ok=True)

    # group: traffic -> algo -> list of (rate, record)
    grouped = defaultdict(lambda: defaultdict(list))
    for r in records:
        grouped[r["traffic_pattern"]][r["routing_algorithm"]].append(
            (r["injection_rate"], r))

    written = []
    for traffic, algos in sorted(grouped.items()):
        fig, axes = plt.subplots(1, len(METRICS), figsize=(16, 4.5))
        fig.suptitle(f"Routing comparison — {traffic} traffic", fontsize=14)

        for ax, (key, label) in zip(axes, METRICS):
            for algo in sorted(algos):
                pts = sorted(algos[algo])
                xs = [p[0] for p in pts]
                ys = [p[1][key] for p in pts]
                name, color, marker = STYLE.get(
                    algo, (f"algo {algo}", "gray", "x"))
                ax.plot(xs, ys, marker=marker, color=color, label=name)
            ax.set_xlabel("Injection rate (pkts/cycle/node)")
            ax.set_ylabel(label)
            ax.set_title(label)
            ax.grid(True, alpha=0.3)
            ax.legend(fontsize=8)

        fig.tight_layout(rect=[0, 0, 1, 0.95])
        out = os.path.join(outdir, f"{traffic}.png")
        fig.savefig(out, dpi=120)
        plt.close(fig)
        written.append(out)

    # Dedicated standalone packet-loss figure (one panel per traffic pattern).
    traffics = sorted(grouped)
    fig, axes = plt.subplots(1, len(traffics),
                             figsize=(6 * len(traffics), 4.5), squeeze=False)
    fig.suptitle("Packet Loss (%) vs injection rate", fontsize=14)
    for ax, traffic in zip(axes[0], traffics):
        algos = grouped[traffic]
        for algo in sorted(algos):
            pts = sorted(algos[algo])
            xs = [p[0] for p in pts]
            ys = [p[1].get("packet_loss_pct", 0.0) for p in pts]
            name, color, marker = STYLE.get(
                algo, (f"algo {algo}", "gray", "x"))
            ax.plot(xs, ys, marker=marker, color=color, label=name)
        ax.set_xlabel("Injection rate (pkts/cycle/node)")
        ax.set_ylabel("Packet Loss (%)")
        ax.set_title(f"{traffic} traffic")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=8)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out = os.path.join(outdir, "packet_loss.png")
    fig.savefig(out, dpi=120)
    plt.close(fig)
    written.append(out)

    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results", nargs="?", default="garnet_results.json",
                    help="path to garnet_results.json")
    ap.add_argument("--outdir", default="results/plots",
                    help="directory to write PNGs into")
    args = ap.parse_args()

    try:
        records = load(args.results)
    except FileNotFoundError:
        print(f"ERROR: {args.results} not found — run the simulations first.")
        return 1

    if not records:
        print("No records to plot.")
        return 1

    written = plot(records, args.outdir)
    print(f"Plotted {len(records)} records into:")
    for w in written:
        print(f"  {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
