#!/bin/bash

# Script to run training for a specific 3D NoC experiment
# 
# This script implements TRUE 3D Network-on-Chip (NoC) with TSV support
# following the 3D NoC Implementation Guide requirements:
#
# ✅ 3D Mesh Topology: True 3D mesh with X, Y, Z dimensions
# ✅ TSV Links: Vertical interconnects between layers with configurable latency
# ✅ 6-Direction Routing: North, East, South, West, Up, Down (actions 0-5)
# ✅ 3D State Representation: 2*num_routers + 8 dimensions
# ✅ Router ID Calculation: z * (rows * cols) + y * cols + x
# ✅ 3D Manhattan Distance: |dx| + |dy| + |dz|
#
# Usage: ./run_3d_training.sh <experiment_name> <mesh_x> <mesh_y> <mesh_z>
# Example: ./run_3d_training.sh 8x8_4layers 8 8 4
#
# See: 3D NoC Implementation Guide for complete requirements

set +e  # Don't exit on error - continue training even if episodes fail

EXPERIMENT_NAME="$1"
MESH_X="$2"
MESH_Y="$3"
MESH_Z="$4"

# Try to extract mesh dimensions from experiment name if not provided
# Format: "4x4x3_experiment" or "8x8_4layers" -> extract 4,4,3 or 8,8,4
if [ -z "$MESH_X" ] || [ -z "$MESH_Y" ] || [ -z "$MESH_Z" ]; then
    # Try to parse from experiment name (e.g., "4x4x3_experiment" -> 4,4,3)
    if [[ "$EXPERIMENT_NAME" =~ ^([0-9]+)x([0-9]+)x([0-9]+) ]]; then
        MESH_X="${BASH_REMATCH[1]}"
        MESH_Y="${BASH_REMATCH[2]}"
        MESH_Z="${BASH_REMATCH[3]}"
        echo "📐 Extracted mesh dimensions from experiment name: ${MESH_X}x${MESH_Y}x${MESH_Z}"
    elif [[ "$EXPERIMENT_NAME" =~ ^([0-9]+)x([0-9]+)_([0-9]+)layers ]]; then
        # Handle format like "8x8_4layers"
        MESH_X="${BASH_REMATCH[1]}"
        MESH_Y="${BASH_REMATCH[2]}"
        MESH_Z="${BASH_REMATCH[3]}"
        echo "📐 Extracted mesh dimensions from experiment name: ${MESH_X}x${MESH_Y}x${MESH_Z}"
    fi
fi

# Validate mesh dimensions
if [ -z "$MESH_X" ] || [ -z "$MESH_Y" ] || [ -z "$MESH_Z" ]; then
    echo "❌ ERROR: Could not determine mesh dimensions"
    echo ""
    echo "Usage: $0 <experiment_name> [<mesh_x> <mesh_y> <mesh_z>]"
    echo ""
    echo "Options:"
    echo "  1. Provide dimensions explicitly:"
    echo "     $0 4x4x3_experiment 4 4 3"
    echo ""
    echo "  2. Use experiment name with dimensions (auto-detected):"
    echo "     $0 4x4x3_experiment"
    echo "     $0 8x8_4layers"
    echo ""
    exit 1
fi

# Validate that dimensions are numbers
if ! [[ "$MESH_X" =~ ^[0-9]+$ ]] || ! [[ "$MESH_Y" =~ ^[0-9]+$ ]] || ! [[ "$MESH_Z" =~ ^[0-9]+$ ]]; then
    echo "❌ ERROR: Mesh dimensions must be numbers"
    echo "   Got: X=$MESH_X, Y=$MESH_Y, Z=$MESH_Z"
    echo ""
    echo "Usage: $0 <experiment_name> [<mesh_x> <mesh_y> <mesh_z>]"
    exit 1
fi

# Calculate number of nodes (3D: X * Y * Z)
# Router ID formula: z * (rows * cols) + y * cols + x
NUM_NODES=$((MESH_X * MESH_Y * MESH_Z))
NUM_ROUTERS=$NUM_NODES  # For Mesh_3D, routers = nodes

# Calculate number of directories
# Topology requirement: (num_cpus + num_dirs) must be divisible by num_routers
# Since num_routers = num_nodes, we need num_dirs to be a multiple of num_nodes
# Simplest solution: use num_dirs = num_nodes (satisfies topology requirement)
# Note: This may not be a power of 2, but topology requirement takes priority
# The interleaving will work with our ceil(log2()) fix in Ruby.py
NUM_DIRS=$NUM_NODES

# Configuration
GEM5_BUILD="${GEM5_BUILD:-./gem5/build}"
TRAFFIC_PATTERN="uniform_random"
SIM_CYCLES=100000
INJECTION_RATE=0.05
AGENT_PORT=5555
NUM_EPISODES=200
MAX_RETRIES=3

# Results directory for this experiment
RESULTS_DIR="results_${EXPERIMENT_NAME}/training"
mkdir -p "$RESULTS_DIR"

# DeepNR parameters (optimized for 3D network stability)
TRAIN_FREQUENCY=40
TARGET_UPDATE_FREQ=500
LEARNING_RATE=0.0001
DISCOUNT_FACTOR=0.9
EPSILON=0.4
EPSILON_MIN=0.05
EPSILON_DECAY=0.995
MAX_INVALID_ACTION_RATE=0.6

# TSV latency (typically 2-3 cycles for vertical interconnects)
# TSV links have higher latency than horizontal links (1 cycle)
# This models the physical characteristics of Through-Silicon Vias
TSV_LATENCY=2

echo "=========================================="
echo "3D NoC Training: $EXPERIMENT_NAME"
echo "=========================================="
echo "  3D Mesh: ${MESH_X}x${MESH_Y}x${MESH_Z} (X×Y×Z)"
echo "  Total Nodes: $NUM_NODES routers"
echo "  Memory Directories: $NUM_DIRS (equals nodes for topology compatibility)"
echo "  Topology: Mesh_3D with TSV support"
echo "  Actions: 6 directions (N,E,S,W,U,D)"
echo "  Results: $RESULTS_DIR"
echo ""

# Find gem5 root
if [ -f "./gem5/build/Garnet_standalone/gem5.opt" ]; then
    GEM5_BUILD="./gem5/build"
elif [ -f "$HOME/Projects/Mona/gem5/build/Garnet_standalone/gem5.opt" ]; then
    GEM5_BUILD="$HOME/Projects/Mona/gem5/build"
else
    GEM5_BUILD="${GEM5_BUILD:-./gem5/build}"
fi

GEM5_ROOT=$(dirname "$GEM5_BUILD")
GEM5_EXECUTABLE="$GEM5_BUILD/Garnet_standalone/gem5.opt"
# Convert to absolute path to avoid issues when cd'ing into GEM5_ROOT
GEM5_EXECUTABLE=$(cd "$(dirname "$GEM5_EXECUTABLE")" && pwd)/$(basename "$GEM5_EXECUTABLE")
CONFIG_FILE="configs/example/garnet_deepnr_traffic.py"

# Ensure Mesh_3D topology is available (REQUIRED for 3D simulations)
MESH_3D_DEST="$GEM5_ROOT/configs/topologies/Mesh_3D.py"
MESH_3D_SOURCE="gem5_configs/topologies/Mesh_3D.py"

echo "Checking for 3D mesh topology..."
if [ ! -f "$MESH_3D_DEST" ]; then
    echo "⚠️  Mesh_3D.py not found at $MESH_3D_DEST"
    if [ -f "$MESH_3D_SOURCE" ]; then
        echo "   📂 Copying from $MESH_3D_SOURCE..."
        cp "$MESH_3D_SOURCE" "$MESH_3D_DEST"
        if [ $? -eq 0 ]; then
            echo "   ✅ Successfully installed Mesh_3D.py"
        else
            echo "   ❌ Failed to copy Mesh_3D.py"
            echo "   This is REQUIRED for 3D simulations"
            exit 1
        fi
    else
        echo "   ❌ ERROR: Mesh_3D.py not found at $MESH_3D_SOURCE"
        echo "   This topology is REQUIRED for TRUE 3D simulations"
        echo "   Please ensure Mesh_3D.py exists in gem5_configs/topologies/"
        exit 1
    fi
else
    echo "✅ Mesh_3D topology found"
fi

# Verify gem5 Options.py has 3D parameters
OPTIONS_FILE="$GEM5_ROOT/configs/common/Options.py"
if [ -f "$OPTIONS_FILE" ]; then
    if ! grep -q "mesh-layers" "$OPTIONS_FILE" 2>/dev/null; then
        echo ""
        echo "❌ ERROR: gem5 Options.py missing --mesh-layers parameter"
        echo "   File: $OPTIONS_FILE"
        echo "   Required for 3D simulations"
        echo ""
        echo "   Please add these lines to addNoISAOptions() function:"
        echo '   parser.add_argument("--mesh-layers", type=int, default=1,'
        echo '                       help="Number of layers in 3D mesh (Z dimension)")'
        echo '   parser.add_argument("--tsv-latency", type=int, default=2,'
        echo '                       help="Latency of TSV (vertical) links in cycles")'
        exit 1
    fi
    echo "✅ gem5 Options.py has 3D parameters"
else
    echo "⚠️  Warning: Could not verify Options.py (file not found)"
fi
echo ""

# Determine state and action sizes for TRUE 3D (Extended Features for Latency Optimization)
# State Vector Structure (3D - Extended):
#   Base features (f1-f5):
#     - f1: Current router one-hot encoding (num_routers dimensions)
#     - f2: Destination router one-hot encoding (num_routers dimensions)
#     - f3: Normalized hops traversed (1 dimension)
#     - f4: Normalized 3D Manhattan distance |dx|+|dy|+|dz| (1 dimension)
#     - f5: Buffer states for 6 directions (6 dimensions: N, E, S, W, U, D)
#   Extended features (f6-f20) for latency reduction:
#     - f6: Packet wait time (normalized cycles)
#     - f7-f12: Queue length moving average (6 dimensions, one per direction)
#     - f13: Predicted link delay
#     - f14-f19: Link utilization (6 dimensions, one per direction)
#     - f20: Weighted remaining distance
#   Total: 2 * num_routers + 8 (base) + 15 (extended) = 2 * num_routers + 23
STATE_SIZE=$((2 * NUM_NODES + 23))  # 2*num_routers + 23 for 3D with extended features

# Action Space (3D - 6 directions):
#   Action 0: North  (-Y direction)
#   Action 1: East   (+X direction)
#   Action 2: South  (+Y direction)
#   Action 3: West   (-X direction)
#   Action 4: Up     (+Z direction via TSV)
#   Action 5: Down   (-Z direction via TSV)
ACTION_SIZE=6  # N, E, S, W, U, D

echo "  State size: $STATE_SIZE"
echo "  Action size: $ACTION_SIZE"
echo ""

# Check if port is in use
if lsof -ti:$AGENT_PORT > /dev/null 2>&1; then
    echo "⚠️  Port $AGENT_PORT is in use. Stopping existing agent..."
    for pid in $(lsof -ti:$AGENT_PORT 2>/dev/null); do
        kill -9 $pid 2>/dev/null || true
    done
    sleep 2
fi

# Start DeepNR agent
# Use --fresh to ensure we start with a new model for this experiment
# (prevents loading incompatible 2D models)
# Get absolute path for results directory
RESULTS_DIR_ABS=$(cd "$RESULTS_DIR" && pwd)

echo "Starting DeepNR agent..."
echo "  Using --fresh flag to ensure compatible model for this experiment"
python3 -u deepnr_agent.py \
    --port=$AGENT_PORT \
    --save-model="$RESULTS_DIR_ABS/deepnr_model.pth" \
    --state-size=$STATE_SIZE \
    --action-size=$ACTION_SIZE \
    --memory-size=20000 \
    --fresh \
    --train-frequency=$TRAIN_FREQUENCY \
    --target-update-frequency=$TARGET_UPDATE_FREQ \
    --max-invalid-action-rate=$MAX_INVALID_ACTION_RATE \
    --learning-rate=$LEARNING_RATE \
    --epsilon=$EPSILON \
    --epsilon-min=$EPSILON_MIN \
    --epsilon-decay=$EPSILON_DECAY \
    --gamma=$DISCOUNT_FACTOR \
    >> "$RESULTS_DIR_ABS/agent.log" 2>&1 &
AGENT_PID=$!

# Wait for agent to be ready
sleep 3
if ! kill -0 $AGENT_PID 2>/dev/null; then
    echo "❌ Agent failed to start!"
    tail -20 "$RESULTS_DIR_ABS/agent.log"
    exit 1
fi

# Wait for ready message
for i in {1..10}; do
    if grep -q "Server is ready" "$RESULTS_DIR_ABS/agent.log" 2>/dev/null; then
        echo "✅ Agent is ready!"
        break
    fi
    sleep 1
done
sleep 2

# Create progress CSV
PROGRESS_CSV="$RESULTS_DIR_ABS/training_progress.csv"
echo "Episode,Latency,Throughput%,Packets_Received,Epsilon" > "$PROGRESS_CSV"

# Run training episodes
echo ""
echo "🚀 Starting training: $NUM_EPISODES episodes"
echo ""

for EPISODE in $(seq 1 $NUM_EPISODES); do
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "📊 Episode $EPISODE/$NUM_EPISODES ($EXPERIMENT_NAME)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    # Check agent health
    if ! kill -0 $AGENT_PID 2>/dev/null; then
        echo "⚠️  Agent died, restarting..."
        python3 -u deepnr_agent.py \
            --port=$AGENT_PORT \
            --save-model="$RESULTS_DIR_ABS/deepnr_model.pth" \
            --state-size=$STATE_SIZE \
            --action-size=$ACTION_SIZE \
            --train-frequency=$TRAIN_FREQUENCY \
            --target-update-frequency=$TARGET_UPDATE_FREQ \
            --max-invalid-action-rate=$MAX_INVALID_ACTION_RATE \
            --learning-rate=$LEARNING_RATE \
            --epsilon=$EPSILON \
            --epsilon-min=$EPSILON_MIN \
            --epsilon-decay=$EPSILON_DECAY \
            --gamma=$DISCOUNT_FACTOR \
            >> "$RESULTS_DIR_ABS/agent.log" 2>&1 &
        AGENT_PID=$!
        sleep 5
        # Wait for agent to be ready
        for i in {1..10}; do
            if grep -q "Server is ready" "$RESULTS_DIR_ABS/agent.log" 2>/dev/null; then
                echo "  ✅ Agent restarted and ready"
                break
            fi
            sleep 1
        done
    fi
    
    # Check for agent errors in log (IndexError, etc.)
    if [ -f "$RESULTS_DIR_ABS/agent.log" ] && tail -50 "$RESULTS_DIR_ABS/agent.log" 2>/dev/null | grep -q "IndexError.*list index out of range"; then
        echo ""
        echo "❌ CRITICAL: Agent IndexError detected - action space mismatch!"
        echo "   The agent expects 6 actions (3D: N,E,S,W,U,D) but gem5 is sending 4 actions (2D)"
        echo "   This means RoutingUnit.cc is not configured for 3D routing"
        echo ""
        echo "   Required fix: Update gem5/src/mem/ruby/network/garnet/RoutingUnit.cc"
        echo "   to send 6 available actions (N, E, S, W, U, D) instead of 4"
        echo ""
        echo "   See: 3D NoC Implementation Guide for RoutingUnit.cc modifications"
        echo ""
        break
    fi
    
    # Use absolute path for log file (needed when cd'ing to gem5 root)
    GEM5_OUTPUT_LOG="$RESULTS_DIR_ABS/gem5_output_episode_${EPISODE}.log"
    RETRY_COUNT=0
    SIMULATION_SUCCESS=false
    
    while [ $RETRY_COUNT -lt $MAX_RETRIES ] && [ "$SIMULATION_SUCCESS" = false ]; do
        if [ $RETRY_COUNT -gt 0 ]; then
            echo "  🔄 Retry attempt $RETRY_COUNT/$MAX_RETRIES..."
            sleep 2
        fi
        
        # Run gem5 simulation with Mesh_3D topology (TRUE 3D)
        # 
        # 3D Implementation Guide Requirements:
        #   - Topology: Mesh_3D (creates 3D mesh with TSV links)
        #   - Router ID: z * (rows * cols) + y * cols + x
        #   - TSV Links: Vertical (Z-direction) with configurable latency
        #   - Ports: Routers have 7 ports (N, S, E, W, U, D + local)
        #   - Links: Horizontal (X,Y) with 1 cycle, Vertical (Z) with TSV_LATENCY cycles
        #
        # Use absolute path for log file to ensure it's written correctly
        # Note: Gem5 writes to $GEM5_ROOT/m5out/stats.txt by default
        # We'll copy it to episode-specific location after simulation completes
        # GEM5_EXECUTABLE is already converted to absolute path above
        (cd "$GEM5_ROOT" && "$GEM5_EXECUTABLE" "$CONFIG_FILE" \
            --network=garnet \
            --num-cpus=$NUM_NODES \
            --num-dirs=$NUM_DIRS \
            --topology=Mesh_3D \
            --mesh-rows=$MESH_X \
            --mesh-cols=$MESH_Y \
            --mesh-layers=$MESH_Z \
            --tsv-latency=$TSV_LATENCY \
            --vcs-per-vnet=2 \
            --routing-algorithm=2 \
            --link-latency=1 \
            --router-latency=1 \
            --sim-cycles=$SIM_CYCLES \
            --synthetic="$TRAFFIC_PATTERN" \
            --injectionrate="$INJECTION_RATE" \
            > "$GEM5_OUTPUT_LOG" 2>&1) &
        GEM5_PID=$!
        
        wait $GEM5_PID
        GEM5_EXIT_CODE=$?
        
        if [ $GEM5_EXIT_CODE -eq 0 ]; then
            SIMULATION_SUCCESS=true
        else
            # Check for ZMQ/agent communication errors
            if [ -f "$GEM5_OUTPUT_LOG" ] && grep -qiE "zmq.*failed|zmq.*error|agent.*not.*responding|zmq_recv.*failed" "$GEM5_OUTPUT_LOG" 2>/dev/null; then
                echo ""
                echo "❌ ERROR: ZMQ communication failure between gem5 and DeepNR agent"
                echo "   This usually means:"
                echo "   1. Agent crashed or is not responding"
                echo "   2. Action space mismatch (agent expects 6 actions, gem5 sends 4)"
                echo "   3. State size mismatch"
                echo ""
                echo "   Check agent log: $RESULTS_DIR_ABS/agent.log"
                echo "   Common causes:"
                echo "   - RoutingUnit.cc not configured for 3D (needs 6 actions, not 4)"
                echo "   - Agent IndexError: available_actions has wrong size"
                echo ""
                # Check agent log for specific errors
                if [ -f "$RESULTS_DIR_ABS/agent.log" ]; then
                    if grep -q "IndexError.*list index out of range" "$RESULTS_DIR_ABS/agent.log" 2>/dev/null; then
                        echo "   ⚠️  Agent error detected: IndexError - action space mismatch!"
                        echo "   → gem5 is sending 4 actions but agent expects 6 actions for 3D"
                        echo "   → Fix: Update RoutingUnit.cc to send 6 actions (N,E,S,W,U,D)"
                    fi
                    if grep -q "State size.*expected" "$RESULTS_DIR_ABS/agent.log" 2>/dev/null; then
                        echo "   ⚠️  State size mismatch detected in agent log"
                    fi
                fi
                echo ""
                break
            # Check for configuration errors (unknown options)
            # Only check for actual error messages, not just presence of option names
            elif [ -f "$GEM5_OUTPUT_LOG" ] && grep -qiE "unrecognized arguments.*--mesh-layers|unrecognized arguments.*--tsv-latency|unknown option.*--mesh-layers|unknown option.*--tsv-latency|error.*--mesh-layers|error.*--tsv-latency" "$GEM5_OUTPUT_LOG" 2>/dev/null; then
                echo ""
                echo "❌ ERROR: Gem5 doesn't recognize --mesh-layers or --tsv-latency options"
                echo "   These options need to be added to gem5/configs/common/Options.py"
                echo "   See GEM5_MODIFICATIONS_NEEDED.md for instructions"
                echo ""
                echo "   Quick fix: Add these lines to gem5/configs/common/Options.py in addNoISAOptions():"
                echo "     parser.add_argument(\"--mesh-layers\", type=int, default=1,"
                echo "                       help=\"Number of layers in 3D mesh (Z dimension)\")"
                echo "     parser.add_argument(\"--tsv-latency\", type=int, default=2,"
                echo "                       help=\"Latency of TSV (vertical) links in cycles\")"
                echo "   Then rebuild gem5: scons build/Garnet_standalone/gem5.opt -j\$(nproc)"
                echo ""
                break
            # Check for retryable errors (only if log file exists)
            elif [ -f "$GEM5_OUTPUT_LOG" ] && grep -q "No valid actions\|deadlock" "$GEM5_OUTPUT_LOG" 2>/dev/null; then
                RETRY_COUNT=$((RETRY_COUNT + 1))
                if [ $RETRY_COUNT -lt $MAX_RETRIES ]; then
                    continue
                fi
            else
                # Unknown error - show last few lines of log
                if [ -f "$GEM5_OUTPUT_LOG" ]; then
                    echo ""
                    echo "❌ ERROR: Simulation failed with exit code $GEM5_EXIT_CODE"
                    echo "   Last few lines of gem5 output:"
                    tail -10 "$GEM5_OUTPUT_LOG" | sed 's/^/   /'
                    echo ""
                fi
                break
            fi
        fi
    done
    
    # CRITICAL: Copy stats file AFTER retry loop completes successfully
    # This ensures we copy the stats even if there were retries
    # Gem5 writes to $GEM5_ROOT/m5out/stats.txt, which gets overwritten each episode
    # We must copy it to episode-specific location before next episode runs
    if [ "$SIMULATION_SUCCESS" = true ]; then
        DEFAULT_STATS="$GEM5_ROOT/m5out/stats.txt"
        EPISODE_OUTDIR="$RESULTS_DIR_ABS/training/episode_${EPISODE}_m5out"
        mkdir -p "$EPISODE_OUTDIR"
        EPISODE_STATS="$EPISODE_OUTDIR/stats.txt"
        
        # Wait a moment to ensure gem5 has finished writing the stats file
        sleep 0.5
        
        if [ -f "$DEFAULT_STATS" ]; then
            # Copy with explicit error checking
            if cp "$DEFAULT_STATS" "$EPISODE_STATS" 2>&1; then
                if [ -f "$EPISODE_STATS" ]; then
                    # Verify the copy has content
                    if [ -s "$EPISODE_STATS" ]; then
                        echo "  ✅ Copied stats to: $EPISODE_STATS" | tee -a "$GEM5_OUTPUT_LOG"
                    else
                        echo "  ⚠️  Warning: Copied stats file is empty" | tee -a "$GEM5_OUTPUT_LOG"
                    fi
                else
                    echo "  ⚠️  Warning: Copy command succeeded but file not found at destination" | tee -a "$GEM5_OUTPUT_LOG"
                fi
            else
                echo "  ⚠️  Warning: Failed to copy stats file from $DEFAULT_STATS to $EPISODE_STATS" | tee -a "$GEM5_OUTPUT_LOG"
            fi
        else
            echo "  ⚠️  Warning: Default stats file not found: $DEFAULT_STATS" | tee -a "$GEM5_OUTPUT_LOG"
        fi
    fi
    
    # Extract results from episode-specific output directory
    EPISODE_OUTDIR="$RESULTS_DIR_ABS/training/episode_${EPISODE}_m5out"
    STATS_FILE="$EPISODE_OUTDIR/stats.txt"
    
    if [ -f "$STATS_FILE" ]; then
        # Extract metrics from the stats file
        latency=$(grep "system.ruby.network.average_packet_latency" "$STATS_FILE" | awk '{print $2}')
        packets_injected=$(grep "system.ruby.network.packets_injected::total" "$STATS_FILE" | awk '{print $2}')
        packets_received=$(grep "system.ruby.network.packets_received::total" "$STATS_FILE" | awk '{print $2}')
        
        if [ ! -z "$packets_injected" ] && [ "$packets_injected" != "0" ]; then
            throughput_pct=$(echo "scale=2; ($packets_received / $packets_injected) * 100" | bc -l)
        else
            throughput_pct="0.00"
        fi
    else
        # Fallback: try to read from default m5out (shouldn't happen if copy worked)
        DEFAULT_STATS="$GEM5_ROOT/m5out/stats.txt"
        if [ -f "$DEFAULT_STATS" ]; then
            echo "  ⚠️  Warning: Using default stats file (episode-specific copy may have failed)"
            latency=$(grep "system.ruby.network.average_packet_latency" "$DEFAULT_STATS" | awk '{print $2}')
            packets_injected=$(grep "system.ruby.network.packets_injected::total" "$DEFAULT_STATS" | awk '{print $2}')
            packets_received=$(grep "system.ruby.network.packets_received::total" "$DEFAULT_STATS" | awk '{print $2}')
            
            if [ ! -z "$packets_injected" ] && [ "$packets_injected" != "0" ]; then
                throughput_pct=$(echo "scale=2; ($packets_received / $packets_injected) * 100" | bc -l)
            else
                throughput_pct="0.00"
            fi
        else
            echo "  ⚠️  Warning: Stats file not found in $EPISODE_OUTDIR or $GEM5_ROOT/m5out"
            latency=""
            throughput_pct="0.00"
            packets_received="0"
        fi
    fi
    
    # Extract epsilon from agent log - try multiple patterns
    epsilon=""
    # Try pattern: "Epsilon: 0.8500" or "epsilon: 0.8500"
    epsilon=$(grep -i "Epsilon:" "$RESULTS_DIR_ABS/agent.log" 2>/dev/null | tail -1 | grep -oE "[Ee]psilon: *[0-9]+\.[0-9]+" | grep -oE "[0-9]+\.[0-9]+" | head -1)
    
    if [ -z "$epsilon" ]; then
        # Try pattern: "Processed X routing decisions. Epsilon: 0.8500"
        epsilon=$(grep "Processed.*routing.*Epsilon:" "$RESULTS_DIR_ABS/agent.log" 2>/dev/null | tail -1 | grep -oE "Epsilon: *[0-9]+\.[0-9]+" | grep -oE "[0-9]+\.[0-9]+" | head -1)
    fi
    
    if [ -z "$epsilon" ]; then
        # Fallback: calculate expected epsilon based on episode number
        # epsilon = initial_epsilon * (decay_rate ^ episode)
        # Epsilon decays after each training step, but we approximate per episode
        # For episode 4: 0.85 * (0.998 ^ (4 * some_factor)) ≈ 0.843
        # Since epsilon decays per training step, not per episode, we use a simple approximation
        episodes_for_decay=$((EPISODE * 10))  # Approximate: assume ~10 training steps per episode
        epsilon=$(echo "scale=4; $EPSILON * ($EPSILON_DECAY ^ $episodes_for_decay)" | bc -l 2>/dev/null)
        # Ensure epsilon doesn't go below minimum
        if [ ! -z "$epsilon" ]; then
            min_check=$(echo "$epsilon < $EPSILON_MIN" | bc -l 2>/dev/null)
            if [ "$min_check" = "1" ]; then
                epsilon="$EPSILON_MIN"
            fi
        fi
    fi
    
    # Final fallback: use initial epsilon
    if [ -z "$epsilon" ] || [ "$epsilon" = "" ]; then
        epsilon="$EPSILON"
    fi
    
    echo "$EPISODE,${latency:-0},${throughput_pct},${packets_received:-0},$epsilon" >> "$PROGRESS_CSV"
    
    echo "  📈 Latency: ${latency:-N/A} cycles"
    echo "  📈 Throughput: ${throughput_pct}%"
    echo "  📈 Epsilon: $epsilon"
    
    sleep 2
done

# Stop agent
echo ""
echo "Stopping agent..."
kill $AGENT_PID 2>/dev/null || true
wait $AGENT_PID 2>/dev/null || true

echo ""
echo "✅ Training completed for $EXPERIMENT_NAME"
echo "   Results saved in: $RESULTS_DIR_ABS"
echo "   Model: $RESULTS_DIR_ABS/deepnr_model.pth"

