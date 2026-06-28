#!/bin/bash
# run_all_algos.sh — one-shot driver for the full 4-algorithm sweep.
#
# Runs, IN THE REQUIRED ORDER:
#   1. run_XYZ_CAQR.sh        XYZ (4) + CAQR (5)   — no agents; RESETS garnet_results.json
#   2. run_DeepNR_proposed.sh DeepNR3D (2) + proposed (3) — auto-launches ZMQ agents; APPENDS
# then prints the verified numbers and (re)draws the plots once at the end.
#
# Run from the gem5 repo root ON THE LINUX BUILD HOST (gem5 cannot run on Windows):
#     source ~/gem5-env/bin/activate
#     cd ~/gem5_new/gem5/gem5
#     bash scripts/run_all_algos.sh
#
# Honors the same env knobs as the sub-scripts, e.g.:
#     GEM5=./build/ALL/gem5.opt CYCLES=20000 bash scripts/run_all_algos.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
cd "$ROOT" || { echo "cannot cd to repo root $ROOT"; exit 1; }

GEM5=${GEM5:-./build/ALL/gem5.opt}
OUT=garnet_results.json
RESULTS_DIR=results

# ── Preflight: the binary must exist, or both sub-scripts will just bail. ──────
if [ ! -x "$GEM5" ]; then
    echo "ERROR: gem5 binary not found at $GEM5"
    echo "Build it first (ZMQ required for the RL algos):"
    echo "    scons build/ALL/gem5.opt -j\$(nproc)"
    exit 1
fi

echo "############################################################"
echo "# 1/2  XYZ (4) + CAQR (5)   — resets $OUT"
echo "############################################################"
bash scripts/run_XYZ_CAQR.sh || { echo "run_XYZ_CAQR.sh failed"; exit 1; }

echo
echo "############################################################"
echo "# 2/2  DeepNR3D (2) + proposed (3)   — appends to $OUT"
echo "############################################################"
bash scripts/run_DeepNR_proposed.sh || { echo "run_DeepNR_proposed.sh failed"; exit 1; }

# ── Final consolidated verify + plot over all 4 algorithms. ───────────────────
echo
echo "############################################################"
echo "# All algorithms done — verifying and plotting"
echo "############################################################"
[ -f "$OUT" ] && cp "$OUT" "$RESULTS_DIR/$OUT"
python3 scripts/verify_results.py "$OUT"
python3 scripts/plot_results.py "$OUT" --outdir "$RESULTS_DIR/plots"

# Paper-aligned RL training metrics: DQN loss (3 panels) + per-episode throughput,
# 3D-DeepNR vs Improved State. Writes results/training_results.json + figures.
echo
echo "=== training metrics (loss + throughput-over-episodes) ==="
python3 scripts/training.py --outdir "$RESULTS_DIR/plots" \
    --json "$RESULTS_DIR/training_results.json"

echo
echo "DONE."
echo "  numbers : $OUT  (and $RESULTS_DIR/$OUT)"
echo "  training: $RESULTS_DIR/training_results.json"
echo "  plots   : $RESULTS_DIR/plots/*.png"
echo "  raw     : $RESULTS_DIR/raw_stats/*.txt"
