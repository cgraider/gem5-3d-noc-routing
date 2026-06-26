#!/bin/bash
# run_DeepNR_proposed.sh — exercise the AugTable augmentation for the
# agent-driven routing algorithms (DeepNR3D=2, proposed=3).
#
# Each algorithm needs a Python RL agent listening on a ZMQ port. This script
# launches the agent in the background, waits for it to become ready, runs the
# gem5 sweep, then shuts the agent down.
#
# Run from the gem5 repo root on the Linux build host:
#     bash scripts/run_DeepNR_proposed.sh
#
# Appends to the SAME results as run_XYZ_CAQR.sh, so a typical full pass is:
#     bash scripts/run_XYZ_CAQR.sh        # algos 4 & 5  (resets garnet_results.json)
#     bash scripts/run_DeepNR_proposed.sh # algos 2 & 3  (appends)

set -u

GEM5=${GEM5:-./build/ALL/gem5.opt}
CONFIG=configs/example/garnet_deepnr_traffic.py
CYCLES=${CYCLES:-20000}

# Mesh sizing (4x4x2 = 32 routers). state-size for DeepNR = 2*routers + 8.
ROWS=${ROWS:-4}; COLS=${COLS:-4}; LAYERS=${LAYERS:-2}
ROUTERS=$((ROWS * COLS * LAYERS))
NODES=$ROUTERS
STATE_SIZE=$((2 * ROUTERS + 8))

RESULTS_DIR=results
RAW_DIR=$RESULTS_DIR/raw_stats
LOG_DIR=$RESULTS_DIR/agent_logs
OUT=garnet_results.json
mkdir -p "$RAW_DIR" "$LOG_DIR"

if [ ! -x "$GEM5" ]; then
    echo "ERROR: gem5 binary not found at $GEM5"
    echo "Build it first, e.g.:  scons build/ALL/gem5.opt -j\$(nproc)"
    exit 1
fi

RATES="0.02 0.06 0.10 0.18"
TRAFFIC="uniform_random transpose"

AGENT_PID=""

# Wait until $1 (a regex) appears in $2 (a log file), up to $3 seconds.
wait_for_ready() {
    local pat=$1 log=$2 timeout=${3:-60} waited=0
    while ! grep -q "$pat" "$log" 2>/dev/null; do
        sleep 1; waited=$((waited + 1))
        if ! kill -0 "$AGENT_PID" 2>/dev/null; then
            echo "    agent process died — see $log"; return 1
        fi
        if [ "$waited" -ge "$timeout" ]; then
            echo "    timed out waiting for agent ready"; return 1
        fi
    done
    return 0
}

stop_agent() {
    if [ -n "$AGENT_PID" ] && kill -0 "$AGENT_PID" 2>/dev/null; then
        kill "$AGENT_PID" 2>/dev/null
        wait "$AGENT_PID" 2>/dev/null
    fi
    AGENT_PID=""
}
trap stop_agent EXIT

sweep() {
    # $1=algo
    local algo=$1
    for tr in $TRAFFIC; do
        for r in $RATES; do
            echo ">>> algo=$algo traffic=$tr rate=$r"
            "$GEM5" "$CONFIG" \
                --network=garnet \
                --num-cpus=$NODES --num-dirs=$NODES \
                --topology=Mesh_3D \
                --mesh-rows=$ROWS --mesh-layers=$LAYERS \
                --vcs-per-vnet=2 \
                --routing-algorithm="$algo" \
                --link-latency=1 --router-latency=1 \
                --sim-cycles="$CYCLES" \
                --synthetic="$tr" \
                --injectionrate="$r" \
                >/dev/null 2>&1 \
                || echo "    (gem5 exited non-zero — expected for RL agents; stats still dumped)"
            [ -f m5out/stats.txt ] && \
                cp m5out/stats.txt "$RAW_DIR/algo${algo}_${tr}_${r}.txt"
        done
    done
}

# ── DeepNR3D (algo 2), agent on ZMQ port 5555 ───────────────────────────────
echo "=== DeepNR3D (algo 2): launching agent on port 5555 ==="
python3 deepnr_agent.py --port 5555 --state-size "$STATE_SIZE" \
    --action-size 6 --fresh > "$LOG_DIR/deepnr_agent.log" 2>&1 &
AGENT_PID=$!
if wait_for_ready "ready and waiting" "$LOG_DIR/deepnr_agent.log" 60; then
    sweep 2
else
    echo "    skipping algo 2 (agent not ready)"
fi
stop_agent

# ── proposed (algo 3), agent on ZMQ port 5556 ───────────────────────────────
echo "=== proposed (algo 3): launching agent on port 5556 ==="
python3 proposed_agent.py --port 5556 \
    --num-rows "$ROWS" --num-cols "$COLS" --num-layers "$LAYERS" \
    > "$LOG_DIR/proposed_agent.log" 2>&1 &
AGENT_PID=$!
if wait_for_ready "Ready" "$LOG_DIR/proposed_agent.log" 60; then
    sweep 3
else
    echo "    skipping algo 3 (agent not ready)"
fi
stop_agent

# Keep the augmented records with the rest of the results.
[ -f "$OUT" ] && cp "$OUT" "$RESULTS_DIR/$OUT"

echo
echo "=== augmented records in $RESULTS_DIR/$OUT ==="
python3 scripts/verify_augmentation.py "$OUT"

echo
echo "=== drawing plots ==="
python3 scripts/plot_augmentation.py "$OUT" --outdir "$RESULTS_DIR/plots"
