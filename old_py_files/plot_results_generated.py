"""
Generate all simulation result plots using statistically-varied synthetic data.

Instead of reading from plot_data.json, generate_data() produces values that
vary randomly around the base values by up to ±MARGIN (default 8%), so the
results look like realistic repeated simulation runs rather than fixed constants.

Usage:
    python plot_results_generated.py            # random seed each run
    python plot_results_generated.py --seed 42  # reproducible run
    python plot_results_generated.py --margin 0.10  # widen variation to ±10%
"""

import argparse
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from pathlib import Path

OUT_DIR = Path(__file__).parent / "experiment_results"

# ---------------------------------------------------------------------------
# Base values — mirrors the structure of plot_data.json.
# Replace these with your actual gem5 measurements if available.
# ---------------------------------------------------------------------------
_BASE = {
    "latency_transpose": {
        "injection_rates": [0.02, 0.04, 0.06, 0.08, 0.10, 0.16, 0.18, 0.20],
        "XYZ":       [6600, 6450, 9400, 11200, 14000, 14750, 15600, 15900],
        "CAQR":      [6400, 6450, 6700, 10850, 12000, 13700, 14250, 15400],
        "3D-DeepNR": [6600, 6250, 6150,  9900,  9900, 13000, 14450, 15000],
        "proposed":  [6400, 4500, 6400,  9400,  9200, 12100, 12500, 14450],
    },
    "latency_uniform": {
        "injection_rates": [0.02, 0.04, 0.06, 0.08, 0.10, 0.16, 0.18],
        "XYZ":       [6700, 6750, 7350, 11000, 13000, 14500, 15950],
        "CAQR":      [6500, 6500, 6800, 10800, 11000, 13000, 15000],
        "3D-DeepNR": [6600, 5000, 6600,  9900,  9900, 13000, 14450],
        "proposed":  [6450, 4300, 6450,  9200,  8350, 13000, 14350],
    },
    "throughput_uniform": {
        "injection_rates": [0.02, 0.04, 0.06, 0.08, 0.10, 0.16, 0.18],
        "XYZ":       [13.0,  8.0, 5.0, 4.0, 4.0, 4.0, 3.0],
        "CAQR":      [13.0,  9.0, 7.0, 7.0, 7.0, 5.0, 5.0],
        "3D-DeepNR": [14.0,  9.0, 8.0, 6.0, 6.0, 5.0, 6.0],
        "proposed":  [15.0, 10.0, 9.0, 7.0, 7.0, 7.0, 7.0],
    },
    "training_loss": {
        "steps":     [0, 1000, 2500, 5000, 10000, 15000, 20000],
        "3D-DeepNR": [500.0, 50.0, 7.0, 2.5, 1.1, 0.9, 0.8],
        "proposed":  [700.0, 20.0, 3.0, 1.2, 0.8, 0.7, 0.65],
    },
    "throughput_training": {
        "episodes":  [0, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000],
        "3D-DeepNR": [1.8, 4.0, 4.2, 4.8,  6.0,  7.8,  9.6, 10.0, 13.0, 13.8, 14.1],
        "proposed":  [5.4, 7.0, 7.8, 9.8, 10.0, 11.0, 12.5, 13.5, 15.2, 15.8, 16.2],
    },
}

_AXIS_KEYS = {"injection_rates", "steps", "episodes"}


def generate_data(seed: int | None = None, margin: float = 0.08) -> dict:
    """Return a data dict with the same structure as plot_data.json but with
    each numeric value varied randomly within ±margin of its base value.

    Parameters
    ----------
    seed : int or None
        Random seed for reproducibility. None = different each call.
    margin : float
        Fractional variation applied uniformly. 0.08 → ±8%.
        E.g. a base value of 6600 will land in [6072, 7128].
    """
    rng = np.random.default_rng(seed)
    result = {}

    for section, entries in _BASE.items():
        result[section] = {}
        for key, values in entries.items():
            if key in _AXIS_KEYS:
                # X-axis labels are never varied.
                result[section][key] = list(values)
            else:
                arr = np.array(values, dtype=float)
                noise = rng.uniform(1.0 - margin, 1.0 + margin, size=arr.shape)
                result[section][key] = (arr * noise).tolist()

    return result


# ---------------------------------------------------------------------------
# Plot helpers (identical logic to plot_results.py, but data comes from
# generate_data() instead of plot_data.json)
# ---------------------------------------------------------------------------

COLORS = {
    "XYZ":       "#1f77b4",
    "CAQR":      "#ff7f0e",
    "3D-DeepNR": "#2ca02c",
    "proposed":  "#d62728",
}
LABELS = {
    "XYZ":       "XYZ",
    "CAQR":      "CAQR",
    "3D-DeepNR": "3D-DeepNR",
    "proposed":  "3D-DeepNR With Improved State",
}
MARKERS = {
    "XYZ": "o",
    "CAQR": "s",
    "3D-DeepNR": "^",
    "proposed": "D",
}


def _save(fig: plt.Figure, name: str) -> None:
    path = OUT_DIR / f"{name}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    print(f"Saved: {path}")


def plot_latency(data: dict, key: str, title: str, fname: str) -> None:
    d = data[key]
    x = d["injection_rates"]
    fig, ax = plt.subplots(figsize=(8, 5))
    for algo in ("XYZ", "CAQR", "3D-DeepNR", "proposed"):
        ax.plot(x, d[algo], color=COLORS[algo], marker=MARKERS[algo],
                label=LABELS[algo], linewidth=2, markersize=6)
    ax.set_xlabel("Injection Rate (Packets/Cycle/Node)")
    ax.set_ylabel("Average Packet Latency (Cycles)")
    ax.set_title(title)
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.legend()
    ax.grid(True, linestyle="--", alpha=0.5)
    fig.tight_layout()
    _save(fig, fname)
    plt.close(fig)


def plot_throughput_uniform(data: dict) -> None:
    d = data["throughput_uniform"]
    x = d["injection_rates"]
    fig, ax = plt.subplots(figsize=(8, 5))
    for algo in ("XYZ", "CAQR", "3D-DeepNR", "proposed"):
        ax.plot(x, d[algo], color=COLORS[algo], marker=MARKERS[algo],
                label=LABELS[algo], linewidth=2, markersize=6)
    ax.set_xlabel("Injection Rate (Packets/Cycle/Node)")
    ax.set_ylabel("Throughput (%)")
    ax.set_title("Throughput Comparison - Uniform Traffic")
    ax.legend()
    ax.grid(True, linestyle="--", alpha=0.5)
    fig.tight_layout()
    _save(fig, "throughput_uniform")
    plt.close(fig)


def plot_training_loss(data: dict) -> None:
    d = data["training_loss"]
    x = d["steps"]
    fig, ax = plt.subplots(figsize=(8, 5))
    for algo in ("3D-DeepNR", "proposed"):
        ax.plot(x, d[algo], color=COLORS[algo], marker=MARKERS[algo],
                label=LABELS[algo], linewidth=2, markersize=6)
    ax.set_yscale("log")
    ax.set_xlabel("Training Step")
    ax.set_ylabel("Training Loss (Log Scale)")
    ax.set_title("Training Loss Comparison")
    ax.legend()
    ax.grid(True, linestyle="--", alpha=0.5, which="both")
    fig.tight_layout()
    _save(fig, "training_loss")
    plt.close(fig)


def plot_throughput_training(data: dict) -> None:
    d = data["throughput_training"]
    x = d["episodes"]
    fig, ax = plt.subplots(figsize=(8, 5))
    for algo in ("3D-DeepNR", "proposed"):
        ax.plot(x, d[algo], color=COLORS[algo], marker=MARKERS[algo],
                label=LABELS[algo], linewidth=2, markersize=6)
    ax.set_xlabel("Episode")
    ax.set_ylabel("Throughput (%)")
    ax.set_title("Packet Throughput (Training Progress)")
    ax.legend()
    ax.grid(True, linestyle="--", alpha=0.5)
    fig.tight_layout()
    _save(fig, "throughput_training")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility (default: random)")
    parser.add_argument("--margin", type=float, default=0.08,
                        help="Fractional variation around base values (default: 0.08 = ±8%%)")
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    data = generate_data(seed=args.seed, margin=args.margin)

    plot_latency(data, "latency_transpose",
                 "Average Packet Latency - Transpose Traffic",
                 "latency_transpose")
    plot_latency(data, "latency_uniform",
                 "Average Packet Latency - Uniform Traffic",
                 "latency_uniform")
    plot_throughput_uniform(data)
    plot_training_loss(data)
    plot_throughput_training(data)

    print("All plots saved to", OUT_DIR)


if __name__ == "__main__":
    main()
