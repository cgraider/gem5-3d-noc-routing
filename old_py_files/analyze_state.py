#!/usr/bin/env python3
"""
Analyze DeepNR State Representation
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src', 'mem', 'ruby', 'network', 'garnet'))

from deepnr_pytorch import DeepNRState
import numpy as np

def analyze_state():
    print("=== Analyzing State Representation ===")
    
    # Create different states
    states = [
        DeepNRState(0, 15, 2, 5, [1, 2, 0, 3]),    # State 1
        DeepNRState(10, 20, 0, 8, [4, 4, 4, 4]),    # State 2
        DeepNRState(30, 45, 10, 2, [0, 1, 2, 3]),   # State 3
    ]
    
    for i, state in enumerate(states, 1):
        print(f"\n--- State {i} ---")
        print(f"Current Router ID: {state.current_router_id}")
        print(f"Destination Router ID: {state.dest_router_id}")
        print(f"Distance Traversed: {state.distance_traversed}")
        print(f"Distance Remaining: {state.distance_remaining}")
        print(f"Free Buffers: {state.free_buffers}")
        
        # Convert to tensor
        tensor = state.to_tensor()
        print(f"Tensor shape: {tensor.shape}")
        print(f"First 8 values: {tensor[0][:8].tolist()}")
        
        # Analyze features
        features = tensor[0][:8].numpy()
        print(f"Normalized features:")
        print(f"  Current router: {features[0]:.3f}")
        print(f"  Dest router: {features[1]:.3f}")
        print(f"  Distance traversed: {features[2]:.3f}")
        print(f"  Distance remaining: {features[3]:.3f}")
        print(f"  Free buffers: {features[4:8].tolist()}")

if __name__ == "__main__":
    analyze_state()

