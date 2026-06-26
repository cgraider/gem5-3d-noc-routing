#!/usr/bin/env python3
"""
PyTorch-based DeepNR implementation for Gem5 integration.
This module provides the neural network model and training logic for DeepNR routing.
"""

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import numpy as np
import random
from collections import deque
import pickle
import os

class DeepNRState:
    """State representation for DeepNR routing."""
    def __init__(self, current_router_id=0, dest_router_id=0, 
                 distance_traversed=0, distance_remaining=0, 
                 free_buffers=None):
        self.current_router_id = current_router_id
        self.dest_router_id = dest_router_id
        self.distance_traversed = distance_traversed
        self.distance_remaining = distance_remaining
        self.free_buffers = free_buffers if free_buffers is not None else [0, 0, 0, 0]
    
    def to_tensor(self, input_size=64):
        """Convert state to PyTorch tensor."""
        # Convert state to input vector (5 features -> input_size dimensions)
        input_vec = np.zeros(input_size, dtype=np.float32)
        
        # Feature 1: Current router ID (normalized)
        input_vec[0] = float(self.current_router_id) / 64.0
        
        # Feature 2: Destination router ID (normalized)
        input_vec[1] = float(self.dest_router_id) / 64.0
        
        # Feature 3: Distance traversed (normalized)
        input_vec[2] = float(self.distance_traversed) / 16.0
        
        # Feature 4: Distance remaining (normalized)
        input_vec[3] = float(self.distance_remaining) / 16.0
        
        # Feature 5: Free buffers in 4 directions (normalized)
        for i in range(min(4, len(self.free_buffers))):
            input_vec[4 + i] = float(self.free_buffers[i]) / 4.0
        
        return torch.FloatTensor(input_vec).unsqueeze(0)  # Add batch dimension

class Experience:
    """Experience tuple for replay memory."""
    def __init__(self, state, action, reward, next_state, done):
        self.state = state
        self.action = action
        self.reward = reward
        self.next_state = next_state
        self.done = done

class DeepNRNetwork(nn.Module):
    """PyTorch implementation of DeepNR neural network."""
    
    def __init__(self, input_size=64, hidden1=256, hidden2=128, 
                 hidden3=64, output_size=4, learning_rate=0.001):
        super(DeepNRNetwork, self).__init__()
        
        self.input_size = input_size
        self.hidden1_size = hidden1
        self.hidden2_size = hidden2
        self.hidden3_size = hidden3
        self.output_size = output_size
        
        # Network layers
        self.fc1 = nn.Linear(input_size, hidden1)
        self.fc2 = nn.Linear(hidden1, hidden2)
        self.fc3 = nn.Linear(hidden2, hidden3)
        self.fc4 = nn.Linear(hidden3, output_size)
        
        # Dropout for regularization
        self.dropout = nn.Dropout(0.1)
        
        # Initialize weights
        self._initialize_weights()
        
        # Training parameters
        self.learning_rate = learning_rate
        self.optimizer = optim.Adam(self.parameters(), lr=learning_rate)
        self.criterion = nn.MSELoss()
        
        # Epsilon-greedy parameters
        self.epsilon = 0.9
        self.epsilon_decay = 0.995
        self.min_epsilon = 0.01
        self.gamma = 0.9
        
        # Experience replay
        self.replay_memory = deque(maxlen=10000)
        self.batch_size = 32
        
        # Target network (will be created when needed)
        self.target_network = None
    
    def _initialize_weights(self):
        """Initialize network weights using Xavier initialization."""
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.constant_(m.bias, 0)
    
    def forward(self, x):
        """Forward pass through the network."""
        x = F.relu(self.fc1(x))
        x = self.dropout(x)
        x = F.relu(self.fc2(x))
        x = self.dropout(x)
        x = F.relu(self.fc3(x))
        x = self.dropout(x)
        x = self.fc4(x)
        return x
    
    def get_action(self, state, epsilon=None):
        """Get action using epsilon-greedy policy."""
        if epsilon is None:
            epsilon = self.epsilon
            
        if random.random() < epsilon:
            # Random action
            return random.randint(0, self.output_size - 1)
        else:
            # Greedy action
            with torch.no_grad():
                q_values = self.forward(state)
                return q_values.argmax().item()
    
    def add_experience(self, experience):
        """Add experience to replay memory."""
        self.replay_memory.append(experience)
    
    def sample_batch(self, batch_size=None):
        """Sample a batch from replay memory."""
        if batch_size is None:
            batch_size = self.batch_size
            
        if len(self.replay_memory) < batch_size:
            return []
        
        return random.sample(self.replay_memory, batch_size)
    
    def train_step(self, batch):
        """Train the network on a batch of experiences."""
        if not batch:
            return 0.0
        
        # Convert batch to tensors
        states = torch.cat([exp.state.to_tensor(self.input_size) for exp in batch])
        actions = torch.LongTensor([exp.action for exp in batch])
        rewards = torch.FloatTensor([exp.reward for exp in batch])
        next_states = torch.cat([exp.next_state.to_tensor(self.input_size) for exp in batch])
        dones = torch.BoolTensor([exp.done for exp in batch])
        
        # Current Q values
        current_q_values = self.forward(states).gather(1, actions.unsqueeze(1))
        
        # Target Q values
        with torch.no_grad():
            next_q_values = self.target_network.forward(next_states).max(1)[0]
            target_q_values = rewards + (self.gamma * next_q_values * ~dones)
        
        # Compute loss
        loss = self.criterion(current_q_values.squeeze(), target_q_values)
        
        # Backward pass
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()
        
        return loss.item()
    
    def update_target_network(self):
        """Update target network with current network weights."""
        if self.target_network is None:
            # Create target network as a copy
            self.target_network = type(self)(self.input_size, self.hidden1_size, 
                                           self.hidden2_size, self.hidden3_size, 
                                           self.output_size, self.learning_rate)
        self.target_network.load_state_dict(self.state_dict())
    
    def decay_epsilon(self):
        """Decay epsilon for exploration."""
        self.epsilon = max(self.min_epsilon, self.epsilon * self.epsilon_decay)
    
    def save_model(self, filepath):
        """Save model to file."""
        save_dict = {
            'model_state_dict': self.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'epsilon': self.epsilon,
            'replay_memory': list(self.replay_memory)
        }
        
        # Only save target network if it exists
        if self.target_network is not None:
            save_dict['target_state_dict'] = self.target_network.state_dict()
        
        torch.save(save_dict, filepath)
    
    def load_model(self, filepath):
        """Load model from file."""
        if os.path.exists(filepath):
            try:
                # Try loading with weights_only=False for compatibility
                checkpoint = torch.load(filepath, weights_only=False)
                self.load_state_dict(checkpoint['model_state_dict'])
                
                # Load target network if it exists in checkpoint
                if 'target_state_dict' in checkpoint and self.target_network is not None:
                    self.target_network.load_state_dict(checkpoint['target_state_dict'])
                
                self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
                self.epsilon = checkpoint['epsilon']
                self.replay_memory = deque(checkpoint['replay_memory'], maxlen=10000)
            except Exception as e:
                print(f"Warning: Could not load model from {filepath}: {e}")
                print("Starting with fresh model...")

class DeepNRManager:
    """Manager class for DeepNR PyTorch integration with Gem5."""
    
    def __init__(self, model_path=None):
        self.network = DeepNRNetwork()
        self.model_path = model_path or "deepnr_model.pth"
        
        # Load existing model if available
        if os.path.exists(self.model_path):
            self.network.load_model(self.model_path)
    
    def get_action(self, current_router_id, dest_router_id, 
                   distance_traversed, distance_remaining, free_buffers):
        """Get routing action for given state."""
        state = DeepNRState(current_router_id, dest_router_id, 
                           distance_traversed, distance_remaining, free_buffers)
        state_tensor = state.to_tensor()
        print("get_action function started")
        return self.network.get_action(state_tensor)
    
    def add_experience(self, current_router_id, dest_router_id, 
                      distance_traversed, distance_remaining, free_buffers,
                      action, reward, next_router_id, next_dest_router_id,
                      next_distance_traversed, next_distance_remaining, 
                      next_free_buffers, done):
        """Add experience for training."""
        print("add_experience function started")
        state = DeepNRState(current_router_id, dest_router_id, 
                           distance_traversed, distance_remaining, free_buffers)
        next_state = DeepNRState(next_router_id, next_dest_router_id,
                                next_distance_traversed, next_distance_remaining, 
                                next_free_buffers)
        
        experience = Experience(state, action, reward, next_state, done)
        self.network.add_experience(experience)
    
    def train(self):
        """Train the network on a batch of experiences."""
        print("train function started")
        batch = self.network.sample_batch()
        if batch:
            loss = self.network.train_step(batch)
            # Decay epsilon after each training step
            self.network.decay_epsilon()
            return loss
        return 0.0
    
    def update_target_network(self):
        """Update target network."""
        self.network.update_target_network()
    
    def decay_epsilon(self):
        """Decay exploration rate."""
        self.network.decay_epsilon()
    
    def save_model(self):
        """Save the current model."""
        self.network.save_model(self.model_path)
    
    def get_epsilon(self):
        """Get current epsilon value."""
        return self.network.epsilon

# Global manager instance for Gem5 integration
_manager = None

def get_manager():
    """Get the global DeepNR manager instance."""
    global _manager
    if _manager is None:
        _manager = DeepNRManager()
    return _manager

def initialize_deepnr(model_path=None):
    """Initialize DeepNR with optional model path."""
    global _manager
    _manager = DeepNRManager(model_path)
    return _manager

def cleanup_deepnr():
    """Cleanup and save DeepNR model."""
    global _manager
    if _manager:
        _manager.save_model()
        _manager = None

if __name__ == "__main__":
    # Test the implementation
    print("Testing DeepNR PyTorch implementation...")
    
    # Create manager
    manager = DeepNRManager()
    
    # Test action selection
    action = manager.get_action(0, 15, 2, 5, [1, 2, 0, 3])
    print(f"Selected action: {action}")
    
    # Test experience addition
    manager.add_experience(0, 15, 2, 5, [1, 2, 0, 3], action, 0.1, 
                          1, 15, 3, 4, [2, 1, 1, 2], False)
    
    # Test training
    loss = manager.train()
    print(f"Training loss: {loss}")
    
    print("DeepNR PyTorch implementation test completed!")
