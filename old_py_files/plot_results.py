"""
Generate all simulation result plots from plot_data.json.
To use real simulation values, update plot_data.json and re-run this script.
"""

import json
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from pathlib import Path

DATA_FILE = Path(__file__).parent / "plot_data.json"
OUT_DIR = Path(__file__).parent / "experiment_results"

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


def load_data() -> dict:
    with open(DATA_FILE) as f:
        return json.load(f)


def save(fig: plt.Figure, name: str) -> None:
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
    save(fig, fname)
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
    save(fig, "throughput_uniform")
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
    save(fig, "training_loss")
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
    save(fig, "throughput_training")
    plt.close(fig)


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    data = load_data()

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
