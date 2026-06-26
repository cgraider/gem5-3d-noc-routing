#!/bin/bash
# run_XYZ_CAQR.sh — exercise the AugTable augmentation for the no-agent
# routing algorithms (XYZ=4, CAQR=5) and collect the paper-aligned output.
#
# Run from the gem5 repo root on the Linux build host:
#     bash scripts/run_XYZ_CAQR.sh
#
# Outputs (all under results/):
#   results/garnet_results.json     augmented JSON records (one per run)
#   results/raw_stats/*.txt         raw gem5 stats.txt snapshot per run
#   results/plots/*.png             curves drawn by plot_augmentation.py

set -u

GEM5=${GEM5:-./build/ALL/gem5.opt}
CONFIG=configs/example/garnet_synth_traffic.py
CYCLES=${CYCLES:-20000}

RESULTS_DIR=results
RAW_DIR=$RESULTS_DIR/raw_stats
OUT=garnet_results.json            # exporter writes this to the cwd
mkdir -p "$RAW_DIR"

if [ ! -x "$GEM5" ]; then
    echo "ERROR: gem5 binary not found at $GEM5"
    echo "Build it first, e.g.:  scons build/ALL/gem5.opt -j\$(nproc)"
    exit 1
fi

# Start clean so the run only contains this test's records.
rm -f "$OUT"

RATES="0.02 0.06 0.10 0.18"
TRAFFIC="uniform_random transpose"

run() {
    # $1=algo  $2=topology  $3..=extra args (mesh sizing)
    local algo=$1 topo=$2; shift 2
    for tr in $TRAFFIC; do
        for r in $RATES; do
            echo ">>> algo=$algo topo=$topo traffic=$tr rate=$r"
            "$GEM5" "$CONFIG" \
                --network=garnet \
                --topology="$topo" \
                --vcs-per-vnet=2 \
                --routing-algorithm="$algo" \
                --link-latency=1 --router-latency=1 \
                --sim-cycles="$CYCLES" \
                --synthetic="$tr" \
                --injectionrate="$r" \
                "$@" >/dev/null 2>&1 \
                || echo "    (gem5 exited non-zero — stats may still be dumped)"
            # Snapshot the raw gem5 stats for this run.
            [ -f m5out/stats.txt ] && \
                cp m5out/stats.txt "$RAW_DIR/algo${algo}_${tr}_${r}.txt"
        done
    done
}

# XYZ (4): 3D mesh, 4x4x2 = 32 nodes
run 4 Mesh_3D --num-cpus=32 --num-dirs=32 --mesh-rows=4 --mesh-layers=2

# CAQR (5): 2D mesh, 4x4 = 16 nodes
run 5 Mesh_XY --num-cpus=16 --num-dirs=16 --mesh-rows=4

# Keep the augmented records with the rest of the results.
[ -f "$OUT" ] && cp "$OUT" "$RESULTS_DIR/$OUT"

echo
echo "=== augmented records in $RESULTS_DIR/$OUT ==="
python3 scripts/verify_augmentation.py "$OUT"

echo
echo "=== drawing plots ==="
python3 scripts/plot_augmentation.py "$OUT" --outdir "$RESULTS_DIR/plots"
