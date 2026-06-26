#!/usr/bin/env python3
"""
Modify DeepNR Parameters
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'src', 'mem', 'ruby', 'network', 'garnet'))

from deepnr_pytorch import DeepNRNetwork, DeepNRState

def test_parameter_changes():
    print("=== Testing Parameter Changes ===")
    
    # Create network with default parameters
    network_default = DeepNRNetwork()
    print(f"Default Epsilon: {network_default.epsilon}")
    print(f"Default Learning Rate: {network_default.learning_rate}")
    print(f"Default Batch Size: {network_default.batch_size}")
    
    # Create network with modified parameters
    network_modified = DeepNRNetwork(
        input_size=64,
        hidden1=512,  # Increased from 256
        hidden2=256,  # Increased from 128
        hidden3=128,  # Increased from 64
        output_size=4,
        learning_rate=0.0001  # Decreased from 0.001
    )
    
    # Modify epsilon
    network_modified.epsilon = 0.5  # Decreased from 0.9
    network_modified.epsilon_decay = 0.99  # Decreased from 0.995
    network_modified.batch_size = 64  # Increased from 32
    
    print(f"\nModified Epsilon: {network_modified.epsilon}")
    print(f"Modified Learning Rate: {network_modified.learning_rate}")
    print(f"Modified Batch Size: {network_modified.batch_size}")
    
    # Test action selection with different epsilons
    state = DeepNRState(0, 15, 2, 5, [1, 2, 0, 3])
    state_tensor = state.to_tensor()
    
    print(f"\nTesting action selection:")
    for epsilon in [0.9, 0.5, 0.1, 0.0]:
        action = network_modified.get_action(state_tensor, epsilon)
        print(f"Epsilon {epsilon}: Action {action}")

if __name__ == "__main__":
    test_parameter_changes()

