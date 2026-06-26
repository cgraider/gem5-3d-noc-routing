#!/usr/bin/env python3
"""
run_experiment.py
Runs DeepNR3D and Proposed method for N episodes, collects latency/throughput/loss,
then plots all three metrics side-by-side.
"""

import json
import os
import re
import subprocess
import sys
import time
import signal
from pathlib import Path

# ─── Configuration ────────────────────────────────────────────────────────────
GEM5_ROOT   = Path(__file__).parent.resolve()
GEM5_BIN    = GEM5_ROOT / "build/ALL/gem5.opt"
CONFIG      = "configs/example/garnet_deepnr_traffic.py"

MESH_ROWS   = 4
MESH_COLS   = 4
MESH_LAYERS = 2
NUM_NODES   = MESH_ROWS * MESH_COLS * MESH_LAYERS  # 32 (mesh routers)
NUM_EPISODES = 20
SIM_CYCLES   = 100_000
INJECTION    = 0.10
TRAFFIC      = "uniform_random"
TSV_LATENCY  = 2

# gem5 getNumRouters() returns num_cpus + num_dirs = 32 + 32 = 64 in this config
ACTUAL_NUM_ROUTERS  = NUM_NODES * 2  # 64
STATE_SIZE_DEEPNR   = 2 * ACTUAL_NUM_ROUTERS + 8   # 136
STATE_SIZE_PROPOSED = 2 * ACTUAL_NUM_ROUTERS + 28  # 156

RESULTS_DIR = GEM5_ROOT / "experiment_results"
RESULTS_DIR.mkdir(exist_ok=True)

GEM5_TIMEOUT = 360  # seconds per episode before giving up

# ─── Stat parsing ─────────────────────────────────────────────────────────────

def parse_stats(stats_file):
    """Return (avg_latency_cycles, throughput_pct) from a stats.txt."""
    lat = inj = rcv = None
    try:
        for line in Path(stats_file).read_text().splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            if "average_packet_latency" in parts[0] and lat is None:
                try:
                    lat = float(parts[1])
                except ValueError:
                    pass
            if "packets_injected::total" in parts[0] and inj is None:
                try:
                    inj = float(parts[1])
                except ValueError:
                    pass
            if "packets_received::total" in parts[0] and rcv is None:
                try:
                    rcv = float(parts[1])
                except ValueError:
                    pass
    except Exception as e:
        print(f"    [warn] stats parse error: {e}")

    tput = None
    if inj and inj > 0 and rcv is not None:
        tput = rcv / inj * 100.0
    return lat, tput


def latest_loss_deepnr(log_path):
    """Parse 'Training: loss=X' lines from deepnr_agent log."""
    try:
        text = Path(log_path).read_text(errors="replace")
        vals = re.findall(r"loss=([\d.]+)", text)
        vals = [float(v) for v in vals if float(v) > 0]
        return vals[-1] if vals else None
    except Exception:
        return None


def latest_loss_proposed(log_path):
    """Parse 'loss=X' from proposed_agent log (every-1000-step prints)."""
    try:
        text = Path(log_path).read_text(errors="replace")
        vals = re.findall(r"\|\s*loss=([\d.]+)", text)
        vals = [float(v) for v in vals if float(v) > 0]
        return vals[-1] if vals else None
    except Exception:
        return None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def kill_port(port):
    """Kill any process listening on a TCP port."""
    try:
        out = subprocess.check_output(
            ["lsof", "-ti", f":{port}"], text=True, stderr=subprocess.DEVNULL
        )
        for pid in out.strip().splitlines():
            os.kill(int(pid), signal.SIGKILL)
        time.sleep(0.5)
    except Exception:
        pass


def wait_for(log_path, keyword, timeout=40):
    """Block until keyword appears in log_path, or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if keyword in Path(log_path).read_text(errors="replace"):
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def run_gem5_episode(algorithm, ep_log):
    """Run one gem5 episode. Returns returncode."""
    cmd = [
        str(GEM5_BIN),
        CONFIG,
        "--network=garnet",
        f"--num-cpus={NUM_NODES}",
        f"--num-dirs={NUM_NODES}",
        f"--num-l2caches={NUM_NODES}",
        "--topology=Mesh_3D",
        f"--mesh-rows={MESH_ROWS}",
        f"--mesh-layers={MESH_LAYERS}",
        f"--tsv-latency={TSV_LATENCY}",
        "--vcs-per-vnet=2",
        f"--routing-algorithm={algorithm}",
        "--link-latency=1",
        "--router-latency=1",
        f"--sim-cycles={SIM_CYCLES}",
        f"--synthetic={TRAFFIC}",
        f"--injectionrate={INJECTION}",
    ]
    with open(ep_log, "w") as f:
        proc = subprocess.run(
            cmd, cwd=str(GEM5_ROOT),
            stdout=f, stderr=subprocess.STDOUT,
            timeout=GEM5_TIMEOUT,
        )
    return proc.returncode


# ─── Main experiment loop ─────────────────────────────────────────────────────

def run_algorithm(label, algorithm, port, agent_cmd, ready_kw, loss_fn):
    """
    Start agent, run NUM_EPISODES gem5 episodes, collect metrics.
    Returns (latencies, throughputs, losses) lists of length NUM_EPISODES.
    """
    print(f"\n{'='*62}")
    print(f"  {label}  —  {NUM_EPISODES} episodes  "
          f"({MESH_ROWS}×{MESH_COLS}×{MESH_LAYERS} mesh, "
          f"{SIM_CYCLES:,} cycles/ep)")
    print(f"{'='*62}")

    run_dir  = RESULTS_DIR / label.lower().replace(" ", "_")
    run_dir.mkdir(exist_ok=True)
    agent_log = run_dir / "agent.log"

    # Clear stale log and kill any process on the port
    agent_log.write_text("")
    kill_port(port)

    # Start agent (keep file open so agent can write to it; -u for unbuffered)
    print(f"  Starting {label} agent on port {port} …")
    agent_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    agent_log_f = open(agent_log, "w")
    agent = subprocess.Popen(
        agent_cmd, cwd=str(GEM5_ROOT),
        stdout=agent_log_f, stderr=subprocess.STDOUT,
        env=agent_env,
    )

    if not wait_for(agent_log, ready_kw, timeout=40):
        print(f"  ERROR: {label} agent did not become ready in 40 s")
        agent.terminate()
        return [None]*NUM_EPISODES, [None]*NUM_EPISODES, [None]*NUM_EPISODES

    print(f"  Agent ready.\n")

    latencies, throughputs, losses = [], [], []

    for ep in range(1, NUM_EPISODES + 1):
        ep_log   = run_dir / f"ep{ep:03d}_gem5.log"
        stats_dst = run_dir / f"ep{ep:03d}_stats.txt"

        print(f"  Ep {ep:2d}/{NUM_EPISODES} ", end="", flush=True)
        t0 = time.time()

        # Run gem5
        try:
            rc = run_gem5_episode(algorithm, ep_log)
            status = "OK" if rc == 0 else f"exit={rc}"
        except subprocess.TimeoutExpired:
            status = "TIMEOUT"
            rc = -1

        elapsed = time.time() - t0
        print(f"[{status} {elapsed:.0f}s] ", end="", flush=True)

        # Save stats copy
        stats_src = GEM5_ROOT / "m5out" / "stats.txt"
        if stats_src.exists():
            stats_dst.write_bytes(stats_src.read_bytes())

        # Extract metrics
        lat, tput = parse_stats(stats_dst) if stats_dst.exists() else (None, None)
        loss = loss_fn(agent_log)

        latencies.append(lat)
        throughputs.append(tput)
        losses.append(loss)

        lat_s  = f"{lat:.1f}"   if lat  is not None else "N/A"
        tput_s = f"{tput:.1f}%" if tput is not None else "N/A"
        loss_s = f"{loss:.5f}"  if loss is not None else "N/A"
        print(f"lat={lat_s}  tput={tput_s}  loss={loss_s}")

        # Check agent still alive
        if agent.poll() is not None:
            print(f"  WARNING: agent died at episode {ep} — restarting …")
            agent_log.write_text("")      # clear so ready_kw triggers again
            agent_log_f = open(agent_log, "a")
            agent = subprocess.Popen(
                agent_cmd, cwd=str(GEM5_ROOT),
                stdout=agent_log_f, stderr=subprocess.STDOUT,
                env=agent_env,
            )
            if not wait_for(agent_log, ready_kw, timeout=40):
                print("  ERROR: agent failed to restart. Stopping experiment.")
                break

        time.sleep(0.5)

    # Graceful stop
    print(f"\n  Stopping {label} agent …")
    agent.terminate()
    try:
        agent.wait(timeout=8)
    except subprocess.TimeoutExpired:
        agent.kill()
    agent_log_f.close()

    return latencies, throughputs, losses


# ─── Plotting ─────────────────────────────────────────────────────────────────

def moving_avg(data, w=5):
    import numpy as np
    arr = np.array([v if v is not None else np.nan for v in data], dtype=float)
    out = []
    for i in range(len(arr)):
        window = arr[max(0, i - w + 1): i + 1]
        valid  = window[~np.isnan(window)]
        out.append(float(np.mean(valid)) if len(valid) else np.nan)
    return out


def plot(ep_range, d_lat, d_tput, d_loss, p_lat, p_tput, p_loss):
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    import numpy as np

    fig = plt.figure(figsize=(17, 11))
    fig.patch.set_facecolor("#FAFAFA")
    fig.suptitle(
        f"DeepNR3D vs Proposed Method\n"
        f"{MESH_ROWS}×{MESH_COLS}×{MESH_LAYERS} 3D Mesh  ·  "
        f"uniform_random  ·  inj={INJECTION}  ·  {SIM_CYCLES:,} cycles/episode",
        fontsize=14, fontweight="bold", y=0.99,
    )

    gs = gridspec.GridSpec(2, 3, hspace=0.42, wspace=0.38,
                           left=0.07, right=0.97, top=0.91, bottom=0.08)

    C = {"deepnr": "#1565C0", "prop": "#B71C1C"}
    ep = list(ep_range)

    def get_vals(data):
        return [v if v is not None else float("nan") for v in data]

    def add_panel(ax, x_vals, d_raw, p_raw, ylabel, title, ylim=None):
        d = get_vals(d_raw)
        p = get_vals(p_raw)
        d_ma = moving_avg(d_raw)
        p_ma = moving_avg(p_raw)

        ax.plot(x_vals, d, "o", color=C["deepnr"], alpha=0.30, ms=4)
        ax.plot(x_vals, p, "s", color=C["prop"],   alpha=0.30, ms=4)
        ax.plot(x_vals, d_ma, "-",  color=C["deepnr"], lw=2.2, label="DeepNR3D")
        ax.plot(x_vals, p_ma, "--", color=C["prop"],   lw=2.2, label="Proposed")

        ax.set_xlabel("Episode", fontsize=10)
        ax.set_ylabel(ylabel, fontsize=10)
        ax.set_title(title, fontsize=11, fontweight="bold")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.25)
        ax.set_facecolor("#FFFFFF")
        if ylim:
            ax.set_ylim(ylim)

    # Row 0: full-scale plots
    ax_lat1  = fig.add_subplot(gs[0, 0])
    ax_tput1 = fig.add_subplot(gs[0, 1])
    ax_loss1 = fig.add_subplot(gs[0, 2])

    add_panel(ax_lat1,  ep, d_lat,  p_lat,
              "Avg Packet Latency (cycles)", "Latency vs Episode")
    add_panel(ax_tput1, ep, d_tput, p_tput,
              "Throughput  (rcv / inj  ×100 %)", "Throughput vs Episode")
    add_panel(ax_loss1, ep, d_loss, p_loss,
              "Training Loss", "Loss vs Episode")

    # Row 1: zoomed last 2/3 of episodes (after warm-up)
    cut = len(ep) // 3
    ep2 = ep[cut:]

    ax_lat2  = fig.add_subplot(gs[1, 0])
    ax_tput2 = fig.add_subplot(gs[1, 1])
    ax_loss2 = fig.add_subplot(gs[1, 2])

    add_panel(ax_lat2,  ep2, d_lat[cut:],  p_lat[cut:],
              "Avg Packet Latency (cycles)",
              f"Latency — episodes {ep2[0]}–{ep2[-1]} (zoomed)")
    add_panel(ax_tput2, ep2, d_tput[cut:], p_tput[cut:],
              "Throughput  (rcv / inj  ×100 %)",
              f"Throughput — episodes {ep2[0]}–{ep2[-1]} (zoomed)")
    add_panel(ax_loss2, ep2, d_loss[cut:], p_loss[cut:],
              "Training Loss",
              f"Loss — episodes {ep2[0]}–{ep2[-1]} (zoomed)")

    # Axes labels use correct x range
    for ax in (ax_lat2, ax_tput2, ax_loss2):
        ax.set_xlim(ep2[0] - 0.5, ep2[-1] + 0.5)

    out = RESULTS_DIR / "results_plot.png"
    plt.savefig(str(out), dpi=150, bbox_inches="tight")
    print(f"\nPlot saved → {out}")

    # Also save PDF for crisp printing
    out_pdf = RESULTS_DIR / "results_plot.pdf"
    plt.savefig(str(out_pdf), bbox_inches="tight")
    print(f"Plot saved → {out_pdf}")


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    print(f"gem5 binary : {GEM5_BIN}")
    print(f"Mesh        : {MESH_ROWS}×{MESH_COLS}×{MESH_LAYERS}  ({NUM_NODES} routers)")
    print(f"Episodes    : {NUM_EPISODES}")
    print(f"Sim cycles  : {SIM_CYCLES:,}")
    print(f"Injection   : {INJECTION}")
    print(f"Results dir : {RESULTS_DIR}")

    # ── DeepNR3D ──────────────────────────────────────────────────
    deepnr_cmd = [
        sys.executable, "deepnr_agent.py",
        "--port",        "5555",
        "--state-size",  str(STATE_SIZE_DEEPNR),
        "--action-size", "6",
        "--fresh",
        "--save-model",  str(RESULTS_DIR / "deepnr_model.pth"),
        "--train-frequency",       "5",
        "--target-update-frequency", "50",
        "--learning-rate",  "0.01",
        "--epsilon",        "0.9",
        "--epsilon-min",    "0.01",
        "--epsilon-decay",  "0.995",
        "--gamma",          "0.9",
    ]

    d_lat, d_tput, d_loss = run_algorithm(
        label     = "DeepNR3D",
        algorithm = 2,
        port      = 5555,
        agent_cmd = deepnr_cmd,
        ready_kw  = "Server is ready",
        loss_fn   = latest_loss_deepnr,
    )

    # ── Proposed ──────────────────────────────────────────────────
    proposed_cmd = [
        sys.executable, "proposed_agent.py",
        "--port",        "5556",
        "--num-routers", str(ACTUAL_NUM_ROUTERS),
        "--save-model",  str(RESULTS_DIR / "proposed_model.pth"),
    ]

    p_lat, p_tput, p_loss = run_algorithm(
        label     = "Proposed",
        algorithm = 3,
        port      = 5556,
        agent_cmd = proposed_cmd,
        ready_kw  = "Ready — waiting for gem5",
        loss_fn   = latest_loss_proposed,
    )

    # ── Save raw JSON ──────────────────────────────────────────────
    raw = {
        "config": {
            "mesh":            f"{MESH_ROWS}x{MESH_COLS}x{MESH_LAYERS}",
            "num_nodes":       NUM_NODES,
            "episodes":        NUM_EPISODES,
            "sim_cycles":      SIM_CYCLES,
            "injection_rate":  INJECTION,
            "traffic":         TRAFFIC,
        },
        "deepnr3d":  {"latency": d_lat,  "throughput": d_tput,  "loss": d_loss},
        "proposed":  {"latency": p_lat,  "throughput": p_tput,  "loss": p_loss},
    }
    (RESULTS_DIR / "results.json").write_text(json.dumps(raw, indent=2))
    print(f"\nRaw data saved → {RESULTS_DIR / 'results.json'}")

    # ── Plot ───────────────────────────────────────────────────────
    ep_range = range(1, NUM_EPISODES + 1)
    plot(ep_range, d_lat, d_tput, d_loss, p_lat, p_tput, p_loss)

    # ── Print summary ──────────────────────────────────────────────
    import numpy as np

    def stat(lst):
        vals = [v for v in lst if v is not None and not (isinstance(v, float) and v != v)]
        if not vals:
            return "N/A", "N/A"
        return f"{np.mean(vals):.2f}", f"{np.mean(vals[-5:]):.2f}"

    print("\n" + "="*52)
    print(f"{'Metric':<30} {'DeepNR3D':>10} {'Proposed':>10}")
    print("="*52)
    for name, d, p in [
        ("Avg Latency (all eps)",     d_lat,  p_lat),
        ("Avg Latency (last 5 eps)",  d_lat,  p_lat),
        ("Avg Throughput % (all)",    d_tput, p_tput),
        ("Avg Throughput % (last 5)", d_tput, p_tput),
        ("Avg Loss (all)",            d_loss, p_loss),
        ("Avg Loss (last 5 eps)",     d_loss, p_loss),
    ]:
        da, dl = stat(d)
        pa, pl = stat(p)
        val = dl if "last" in name else da
        pval = pl if "last" in name else pa
        print(f"  {name:<28} {val:>10} {pval:>10}")
    print("="*52)


if __name__ == "__main__":
    main()
