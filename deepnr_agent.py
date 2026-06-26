#!/usr/bin/env python3
"""
DeepNR: Deep Reinforcement Learning based NoC Routing Algorithm
This script implements a DQN agent that learns optimal routing decisions
for Network-on-Chip (NoC) systems.

Based on the paper: "DeepNR: An adaptive deep reinforcement learning
based NoC routing algorithm"
"""

import argparse
import glob
import os
import random
import signal
import time
from collections import deque

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import zmq

# Import dashboard (optional)
DASHBOARD_AVAILABLE = False
SIMPLE_DASHBOARD_AVAILABLE = False
WEB_DASHBOARD_AVAILABLE = False

try:
    from deepnr_dashboard import init_dashboard

    DASHBOARD_AVAILABLE = True
except ImportError:
    DASHBOARD_AVAILABLE = False

try:
    from deepnr_dashboard_simple import init_simple_dashboard

    SIMPLE_DASHBOARD_AVAILABLE = True
except ImportError:
    SIMPLE_DASHBOARD_AVAILABLE = False

try:
    from deepnr_web_dashboard import init_web_dashboard
    from deepnr_web_dashboard import update_metrics as update_web_metrics

    WEB_DASHBOARD_AVAILABLE = True
except ImportError:
    WEB_DASHBOARD_AVAILABLE = False

try:
    from deepnr_report import init_report

    REPORT_AVAILABLE = True
except ImportError:
    REPORT_AVAILABLE = False

# ============================================================================
# DQN Neural Network Architecture
# ============================================================================


class DQN(nn.Module):
    """
    Deep Q-Network (DQN) for 3D NoC routing (DeepNR-3D).

    Architecture (DeepNR paper + 3D extension):
    Input compression: state_size → 64
    Hidden layer 1:    64  → 256
    Hidden layer 2:    256 → 128
    Hidden layer 3:    128 → 64
    Output layer:      64  → 6  (N, E, S, W, Up, Down)

    State size = 2*num_routers + 8
      = one-hot(current) + one-hot(dest) + f3 + f4 + f5(6 dirs)
    Example: 4x4x2 mesh → 2*32+8 = 72; 4x4x4 → 2*64+8 = 136
    """

    def __init__(self, state_size, action_size):
        super(DQN, self).__init__()

        # Input compression layer: variable state_size → 64
        # This handles different mesh sizes (8x8=134, 4x4=38, etc.)
        self.fc_compress = nn.Linear(state_size, 64)
        self.relu_compress = nn.ReLU()

        # Hidden layer 1: 64 → 256 (paper specification)
        self.fc1 = nn.Linear(64, 256)
        self.relu1 = nn.ReLU()

        # Hidden layer 2: 256 → 128 (paper specification)
        self.fc2 = nn.Linear(256, 128)
        self.relu2 = nn.ReLU()

        # Hidden layer 3: 128 → 64 (paper specification)
        self.fc3 = nn.Linear(128, 64)
        self.relu3 = nn.ReLU()

        # Output layer: 64 → 6 (N, E, S, W, U, D) for 3D NoC
        self.fc4 = nn.Linear(64, action_size)

    def forward(self, x):
        """Forward pass through the network."""
        x = self.relu_compress(self.fc_compress(x))
        x = self.relu1(self.fc1(x))
        x = self.relu2(self.fc2(x))
        x = self.relu3(self.fc3(x))
        return self.fc4(x)  # Linear activation for Q-values


# ============================================================================
# Experience Replay Buffer
# ============================================================================


class ReplayBuffer:
    """
    Stores and samples experiences for training the DQN.
    This breaks the correlation between consecutive experiences.

    Paper specification: "limited entries" (200 entries)
    """

    def __init__(self, capacity=200):
        self.capacity = capacity
        self.buffer = deque(maxlen=capacity)

    def push(self, state, action, reward, next_state, done):
        """Add an experience to the buffer."""
        self.buffer.append((state, action, reward, next_state, done))

    def sample(self, batch_size):
        """Sample a batch of experiences randomly."""
        batch = random.sample(self.buffer, min(batch_size, len(self.buffer)))
        state, action, reward, next_state, done = zip(*batch)

        # Convert to numpy arrays first to avoid slow tensor creation warning
        state_array = np.array(state, dtype=np.float32)
        next_state_array = np.array(next_state, dtype=np.float32)
        action_array = np.array(action, dtype=np.int64)
        reward_array = np.array(reward, dtype=np.float32)
        done_array = np.array(done, dtype=bool)

        return (
            torch.FloatTensor(state_array),
            torch.LongTensor(action_array),
            torch.FloatTensor(reward_array),
            torch.FloatTensor(next_state_array),
            torch.BoolTensor(done_array),
        )

    def __len__(self):
        return len(self.buffer)


# ============================================================================
# DeepNR Agent
# ============================================================================


class DeepNR_Agent:
    """
    Deep Reinforcement Learning agent for NoC routing.

    This agent learns to make routing decisions by:
    1. Observing the network state (buffer occupancies)
    2. Selecting routing actions (which direction to route)
    3. Receiving rewards (negative queuing delay)
    4. Learning from experience to improve routing decisions
    """

    def __init__(
        self,
        state_size=136,  # 3D default: 2*num_routers+8 (e.g. 4x4x4=64 → 2*64+8=136)
        action_size=6,   # 6 directions: N, E, S, W, Up, Down
        lr=0.01,  # Learning rate (paper: 0.01)
        gamma=0.9,  # Discount factor (paper: 0.9)
        epsilon=0.9,  # Initial exploration rate (paper: 0.9)
        epsilon_min=0.01,  # Minimum exploration rate (paper: 0.01)
        epsilon_decay=0.995,  # Exploration decay rate
        memory_size=200,  # Experience replay buffer size (paper: "limited entries")
        batch_size=32,  # Training batch size (smaller for 200-entry buffer)
        train_frequency=5,  # T_train: Train every N packets (Algorithm 1)
        target_update_frequency=100,  # T_target: Update target network every N training steps (Algorithm 1)
        device=None,  # GPU or CPU device
    ):
        self.state_size = state_size
        self.action_size = action_size
        self.lr = lr
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.batch_size = batch_size
        self.train_frequency = train_frequency
        self.target_update_frequency = target_update_frequency

        # Set device (GPU if available, else CPU)
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = device

        print(f"Using device: {self.device}")

        # Create the DQN model
        self.q_network = DQN(state_size, action_size).to(self.device)
        self.target_network = DQN(state_size, action_size).to(self.device)
        self.optimizer = optim.Adam(self.q_network.parameters(), lr=lr)

        # Initialize target network with same weights as main network
        self.update_target_network()

        # Experience replay buffer
        self.memory = ReplayBuffer(memory_size)

        # Training statistics
        self.training_step = 0
        self.total_reward = 0.0

    def update_target_network(self):
        """Copy weights from main network to target network."""
        self.target_network.load_state_dict(self.q_network.state_dict())

    def select_action(self, state, training=True, available_actions=None):
        """
        Select an action using epsilon-greedy policy with action masking.

        IMPROVED: Always prefer valid actions to reduce invalid action rate.

        Args:
            state: Current state vector (numpy array or list)
            training: If True, use epsilon-greedy. If False, always exploit.
            available_actions: List of booleans indicating which actions are valid.
                              If provided, only select from valid actions.

        Returns:
            action: Selected action (integer 0-3 for N, E, S, W)
                   Will be valid if available_actions is provided
        """
        # Get valid actions if provided
        valid_actions = None
        if available_actions is not None:
            valid_actions = [i for i in range(self.action_size) if available_actions[i]]
            if not valid_actions:
                # No valid actions - this shouldn't happen, but fallback to all actions
                valid_actions = list(range(self.action_size))

        if training and random.random() < self.epsilon:
            # Explore: choose random action from valid actions only
            if valid_actions:
                return random.choice(valid_actions)
            else:
                return random.randint(0, self.action_size - 1)

        # Exploit: choose best action according to Q-network, but only from valid actions
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            q_values = self.q_network(state_tensor)

            if valid_actions:
                # Mask invalid actions by setting their Q-values to very negative
                # This ensures we ALWAYS select a valid action
                masked_q_values = q_values.clone()
                for i in range(self.action_size):
                    if i not in valid_actions:
                        masked_q_values[0][i] = float("-inf")

                # Add small random noise to Q-values to break ties and encourage exploration
                # This helps avoid getting stuck in local optima
                noise = torch.randn_like(masked_q_values) * 0.01
                masked_q_values = masked_q_values + noise

                action = masked_q_values.argmax().item()

                # Safety check: if somehow we still got an invalid action, fallback to first valid
                if action not in valid_actions:
                    action = valid_actions[0]
            else:
                # No masking info - use original Q-values (shouldn't happen if available_actions provided)
                action = q_values.argmax().item()

        return action

    def remember(self, state, action, reward, next_state, done):
        """Store experience in replay buffer."""
        self.memory.push(state, action, reward, next_state, done)
        self.total_reward += reward

    def train(self):
        """
        Train the DQN on a batch of experiences from the replay buffer.
        Uses the standard DQN algorithm with target network.
        """
        if len(self.memory) < self.batch_size:
            return 0.0  # Not enough experiences to train

        # Sample a batch of experiences
        states, actions, rewards, next_states, dones = self.memory.sample(
            self.batch_size
        )

        # Move tensors to the correct device
        states = states.to(self.device)
        actions = actions.to(self.device)
        rewards = rewards.to(self.device)
        next_states = next_states.to(self.device)
        dones = dones.to(self.device)

        # Compute current Q-values
        current_q_values = self.q_network(states).gather(1, actions.unsqueeze(1))

        # Compute next Q-values using target network
        with torch.no_grad():
            next_q_values = self.target_network(next_states).max(1)[0]
            target_q_values = rewards + (self.gamma * next_q_values * ~dones)

        # Compute loss (Mean Squared Error)
        loss = F.mse_loss(current_q_values.squeeze(), target_q_values)

        # Optimize with gradient clipping for stability
        self.optimizer.zero_grad()
        loss.backward()
        # Clip gradients to prevent exploding gradients
        torch.nn.utils.clip_grad_norm_(self.q_network.parameters(), max_norm=1.0)
        self.optimizer.step()

        # Decay epsilon
        if self.epsilon > self.epsilon_min:
            self.epsilon *= self.epsilon_decay

        # Update target network periodically (Algorithm 1: every T_target steps)
        self.training_step += 1
        if self.training_step % self.target_update_frequency == 0:
            self.update_target_network()

        return loss.item()

    def save_model(self, filepath):
        """Save the trained model to disk."""
        torch.save(
            {
                "q_network_state_dict": self.q_network.state_dict(),
                "target_network_state_dict": self.target_network.state_dict(),
                "optimizer_state_dict": self.optimizer.state_dict(),
                "epsilon": self.epsilon,
                "training_step": self.training_step,
            },
            filepath,
        )
        print(f"Model saved to {filepath}")

    def load_model(self, filepath):
        """Load a trained model from disk."""
        checkpoint = torch.load(filepath, map_location=self.device)
        self.q_network.load_state_dict(checkpoint["q_network_state_dict"])
        self.target_network.load_state_dict(checkpoint["target_network_state_dict"])
        self.optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
        self.epsilon = checkpoint["epsilon"]
        self.training_step = checkpoint["training_step"]
        print(f"Model loaded from {filepath}")


# ============================================================================
# ZMQ Server for Communication with gem5
# ============================================================================


class DeepNR_Server:
    """
    ZMQ server that communicates with gem5 routers.

    Protocol:
    1. Router sends state (JSON): {"state": [buffer_occupancies...], "packet_id": ...}
    2. Server responds with action (JSON): {"action": 0-3, "packet_id": ...}
    """

    def __init__(
        self,
        agent,
        port=5555,
        enable_dashboard=False,
        dashboard_port=5000,
        simple_dashboard=True,
        eval_mode=False,
        max_invalid_action_rate=0.5,  # Increased to 50% to match gem5 threshold
        max_latency_threshold=1000.0,
        enable_state_monitor=False,
        state_log_file="deepnr_states.log",
        save_model_path=None,
        save_frequency=1000,  # Save model every N packets
    ):
        self.agent = agent
        self.port = port
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)  # REP = Reply socket
        # Set timeout to make recv interruptible (50ms timeout - shorter for better responsiveness)
        self.socket.setsockopt(zmq.RCVTIMEO, 50)  # 50ms timeout
        self.socket.setsockopt(zmq.SNDTIMEO, 50)  # 50ms timeout
        self.socket.bind(f"tcp://*:{port}")
        self.running = True  # Flag to control the loop
        self.enable_dashboard = enable_dashboard
        self.dashboard_port = dashboard_port
        self.eval_mode = eval_mode  # If True, disable training for stable evaluation
        self.enable_state_monitor = enable_state_monitor
        self.state_log_file = state_log_file
        self.save_model_path = save_model_path
        self.save_frequency = save_frequency
        self.last_save_packet = 0
        self.packet_count = 0  # Track packet count for saving

        # Termination thresholds (paper approach: restart if too many invalid actions)
        self.max_invalid_action_rate = (
            max_invalid_action_rate  # 30% invalid actions = restart
        )
        self.max_latency_threshold = (
            max_latency_threshold  # Max latency in cycles before restart
        )

        # Initialize state monitor if enabled
        self.state_monitor = None
        if self.enable_state_monitor:
            try:
                from deepnr_state_monitor import StateMonitor

                self.state_monitor = StateMonitor(
                    log_file=self.state_log_file, verbose=False
                )
                print(f"📊 State monitor enabled (logging to {self.state_log_file})")
            except ImportError:
                print(
                    "⚠️  Warning: State monitor module not found. Disabling state monitoring."
                )
                self.enable_state_monitor = False

        # Tracking for termination
        self.invalid_action_count = 0
        self.total_actions = 0
        self.should_terminate = False
        self.termination_reason = None

        # Initialize report
        if REPORT_AVAILABLE:
            self.report = init_report()
        else:
            self.report = None

        # Initialize dashboard if requested
        self.dashboard = None
        self.simple_dashboard = None
        self.web_dashboard = False

        if self.enable_dashboard:
            # Prefer web dashboard
            if WEB_DASHBOARD_AVAILABLE:
                init_web_dashboard(port=dashboard_port, open_browser=True)
                self.web_dashboard = True
                print("🌐 Web dashboard enabled!")
            elif DASHBOARD_AVAILABLE:
                dashboard_obj = init_dashboard()
                # Check if we got a graphical dashboard or simple dashboard
                if dashboard_obj and hasattr(dashboard_obj, "fig"):
                    # It's a graphical dashboard
                    self.dashboard = dashboard_obj
                    print("📊 Real-time graphical dashboard enabled!")
                elif dashboard_obj:
                    # It's a simple dashboard (fallback)
                    self.simple_dashboard = dashboard_obj
                    print(
                        "📊 Simple text dashboard enabled (graphical dashboard unavailable)!"
                    )
            elif SIMPLE_DASHBOARD_AVAILABLE:
                self.simple_dashboard = init_simple_dashboard()
                print("📊 Simple text dashboard enabled!")
        elif simple_dashboard and SIMPLE_DASHBOARD_AVAILABLE:
            self.simple_dashboard = init_simple_dashboard()
            print("📊 Simple text dashboard enabled!")

        # Set up signal handler for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        print(f"DeepNR Server listening on port {self.port}")
        print("Waiting for gem5 router connections...")
        print("Press Ctrl+C to stop the server gracefully.")

    def _signal_handler(self, signum, frame):
        """Handle interrupt signals (Ctrl+C, SIGTERM)."""
        print("\n\n⚠️  Interrupt signal received. Shutting down server gracefully...")
        self.running = False

    def save_model_now(self):
        """Force save the model immediately."""
        if self.save_model_path:
            try:
                self.agent.save_model(self.save_model_path)
                self.last_save_packet = getattr(self, "packet_count", 0)
                return True
            except Exception as e:
                print(f"⚠️  Warning: Failed to save model: {e}")
                return False
        return False

    def run(self):
        """Main server loop: receive state, return action, receive reward."""
        self.packet_count = 0  # Make it an instance variable for saving
        packet_count = 0  # Keep local for compatibility
        last_state = None
        last_action = None
        # Track if last action was invalid for penalty application
        self._last_action_invalid = False
        self._pending_invalid_penalty = 0.0

        # Create a poller for non-blocking receive with timeout
        poller = zmq.Poller()
        poller.register(self.socket, zmq.POLLIN)

        print("✅ Server is ready and waiting for connections...")

        while self.running:
            try:
                # Poll for messages with short timeout (50ms) for better interrupt responsiveness
                # Use zmq.POLLIN to check for incoming messages
                socks = dict(
                    poller.poll(50)
                )  # 50ms timeout - shorter for better Ctrl+C response

                # Check if we should exit (signal handler may have set self.running = False)
                if not self.running:
                    break

                if self.socket not in socks:
                    # No message received, continue loop (allows KeyboardInterrupt to be caught)
                    continue

                # Receive message from gem5 router (non-blocking since we know data is available)
                try:
                    message = self.socket.recv_json(zmq.NOBLOCK)
                    # Debug: Log first message to verify communication
                    if not hasattr(self, "_first_msg_logged"):
                        print(
                            f"📨 ✅ CONNECTION VERIFIED: Received first message from gem5! Packet ID: {message.get('packet_id', 'unknown')}"
                        )
                        import sys

                        sys.stdout.flush()
                        self._first_msg_logged = True
                except zmq.Again:
                    # No message available (shouldn't happen after poll, but handle it)
                    continue
                except Exception as e:
                    print(f"⚠️  Error receiving message: {e}")
                    import sys

                    sys.stdout.flush()
                    continue

                # State message includes both state and reward from previous action
                state = message.get("state", [])
                packet_id = message.get("packet_id", 0)
                reward = message.get("reward", 0.0)  # Reward from previous action
                done = message.get("done", False)  # CRITICAL FIX: Extract done flag
                available_actions = message.get(
                    "available_actions", None
                )  # Action mask

                # Log state to monitor if enabled
                if self.enable_state_monitor and self.state_monitor:
                    self.state_monitor.log_state(
                        state, packet_id, reward, done, available_actions, action=None
                    )

                # DEBUG: Print detailed state information (first few packets)
                if packet_count < 5:
                    print(f"\n{'=' * 80}")
                    print(f"📨 Python Agent - Received Message #{packet_count}")
                    print(f"{'=' * 80}")
                    print(f"  Packet ID: {packet_id}")
                    print(
                        f"  State size: {len(state)} (expected: {self.agent.state_size})"
                    )
                    print(f"  Reward: {reward:.6f}")
                    print(f"  Done: {done}")
                    print(f"  Available actions: {available_actions}")

                    if len(state) > 0:
                        # Calculate feature indices (assuming 8x8 mesh = 64 routers)
                        num_routers = (
                            len(state) - 8
                        ) // 2  # state_size = 2*num_routers + 8 (f3+f4+6 buffer dirs)
                        f1_end = num_routers
                        f2_end = 2 * num_routers
                        f3_idx = 2 * num_routers
                        f4_idx = 2 * num_routers + 1
                        f5_start = 2 * num_routers + 2

                        print("\n  State Vector Details:")
                        print(
                            f"    f1 (current router one-hot): indices 0-{f1_end - 1}"
                        )
                        # Find which router is active in f1
                        f1_active = [
                            i
                            for i in range(f1_end)
                            if i < len(state) and abs(state[i] - 1.0) < 0.001
                        ]
                        if f1_active:
                            print(f"      → Active router: {f1_active[0]}")
                        else:
                            print(f"      → First 5 values: {state[: min(5, f1_end)]}")

                        print(
                            f"    f2 (dest router one-hot): indices {num_routers}-{f2_end - 1}"
                        )
                        # Find which router is active in f2
                        if f2_end <= len(state):
                            f2_active = [
                                i
                                for i in range(num_routers, f2_end)
                                if abs(state[i] - 1.0) < 0.001
                            ]
                            if f2_active:
                                print(
                                    f"      → Active router: {f2_active[0] - num_routers}"
                                )
                            else:
                                print(
                                    f"      → Sample values: {state[num_routers : min(num_routers + 5, f2_end)]}"
                                )

                        if f3_idx < len(state):
                            print(
                                f"    f3 (hops traversed, normalized): index {f3_idx} = {state[f3_idx]:.6f}"
                            )
                        if f4_idx < len(state):
                            print(
                                f"    f4 (remaining distance, normalized): index {f4_idx} = {state[f4_idx]:.6f}"
                            )

                        print(
                            f"    f5 (buffer states N,E,S,W,U,D): indices {f5_start}-{f5_start + 5}"
                        )
                        if f5_start + 5 < len(state):
                            print(
                                f"      → N: {state[f5_start]:.6f}, E: {state[f5_start + 1]:.6f}, "
                                f"S: {state[f5_start + 2]:.6f}, W: {state[f5_start + 3]:.6f}, "
                                f"U: {state[f5_start + 4]:.6f}, D: {state[f5_start + 5]:.6f}"
                            )

                        # Print first and last few elements
                        print_elements = 5
                        print(
                            f"\n  First {print_elements} elements: {state[:print_elements]}"
                        )
                        if len(state) > print_elements * 2:
                            print(
                                f"  Last {print_elements} elements: {state[-print_elements:]}"
                            )
                        else:
                            print(f"  All elements: {state}")

                    print(f"{'=' * 80}\n")

                # Convert state to numpy array if needed
                if isinstance(state, list):
                    state = np.array(state, dtype=np.float32)

                # Store experience from previous state-action pair
                # Skip first packet (no previous action to reward)
                if (
                    last_state is not None
                    and last_action is not None
                    and packet_count > 0
                ):
                    # Apply invalid action penalty if the last action was invalid
                    # This ensures negative reward is properly associated with invalid actions
                    adjusted_reward = reward
                    if hasattr(self, '_last_action_invalid') and self._last_action_invalid:
                        invalid_penalty = getattr(self, '_pending_invalid_penalty', -5.0)
                        adjusted_reward = reward + invalid_penalty
                        if invalid_penalty != 0.0:
                            # Log the penalty application for debugging
                            if packet_count <= 10 or packet_count % 1000 == 0:
                                print(f"  ⚠️  Applied invalid action penalty: {invalid_penalty:.2f} (total reward: {adjusted_reward:.2f})")
                    
                    # Store experience: (state, action, reward, next_state, done)
                    # reward is from the last_action taken in last_state
                    # CRITICAL FIX: Use actual done flag from message
                    self.agent.remember(last_state, last_action, adjusted_reward, state, done)
                    self.agent.total_reward += adjusted_reward

                # Select action using the agent WITH action masking to reduce invalid actions
                # In eval mode, disable training (no exploration, no training updates)
                if self.eval_mode:
                    # In eval mode, always exploit (use learned policy)
                    action = self.agent.select_action(
                        state, training=False, available_actions=available_actions
                    )
                    is_exploration = False
                else:
                    # Normal mode: use epsilon-greedy with action masking
                    is_exploration = (packet_count == 0) or (
                        random.random() < self.agent.epsilon
                    )
                    action = self.agent.select_action(
                        state, training=True, available_actions=available_actions
                    )

                # Check if action is invalid (for tracking and termination)
                is_invalid = False
                if available_actions is not None:
                    is_invalid = (
                        not available_actions[action]
                        if action < len(available_actions)
                        else True
                    )

                # Track invalid actions for termination logic
                self.total_actions += 1
                # Store whether this action is invalid for next reward calculation
                self._last_action_invalid = is_invalid
                if is_invalid:
                    self.invalid_action_count += 1
                    # Apply additional negative reward penalty for invalid action
                    # This ensures the agent learns to avoid invalid actions
                    # The C++ code also gives -10.0, but we add an extra penalty here
                    # to make the learning signal stronger and ensure it's properly
                    # associated with the invalid action in the experience replay buffer
                    invalid_action_penalty = -5.0  # Additional penalty on top of C++ -10.0
                    # Store this penalty to be applied when we receive the next reward
                    if not hasattr(self, '_pending_invalid_penalty'):
                        self._pending_invalid_penalty = 0.0
                    self._pending_invalid_penalty = invalid_action_penalty
                else:
                    # Clear any pending penalty if action is valid
                    if hasattr(self, '_pending_invalid_penalty'):
                        self._pending_invalid_penalty = 0.0

                # Check termination conditions (paper approach: restart if too many invalid actions)
                if (
                    not self.eval_mode and self.total_actions > 100
                ):  # Check after some actions
                    invalid_rate = self.invalid_action_count / self.total_actions
                    if invalid_rate > self.max_invalid_action_rate:
                        self.should_terminate = True
                        self.termination_reason = f"Invalid action rate too high: {invalid_rate:.2%} > {self.max_invalid_action_rate:.2%}"
                        print(f"\n⚠️  TERMINATION TRIGGERED: {self.termination_reason}")
                        print(
                            f"   Invalid actions: {self.invalid_action_count}/{self.total_actions}"
                        )
                        break

                # Record in report
                if self.report:
                    self.report.record_action(
                        action, is_invalid, is_exploration, reward
                    )
                    if len(self.report.state_samples) < 100:
                        self.report.record_state_sample(
                            state.tolist() if hasattr(state, "tolist") else list(state)
                        )

                # Update dashboard
                if self.web_dashboard and WEB_DASHBOARD_AVAILABLE:
                    update_web_metrics(
                        reward=reward,
                        epsilon=self.agent.epsilon,
                        action=action,
                        is_invalid=is_invalid,
                    )
                elif self.dashboard:
                    self.dashboard.update_metrics(
                        reward=reward,
                        epsilon=self.agent.epsilon,
                        action=action,
                        is_invalid=is_invalid,
                        packet_id=packet_id,
                    )
                elif self.simple_dashboard:
                    self.simple_dashboard.update_metrics(
                        reward=reward,
                        epsilon=self.agent.epsilon,
                        action=action,
                        is_invalid=is_invalid,
                        packet_id=packet_id,
                    )

                # DEBUG: Print action selection details (first few packets)
                if packet_count < 5:
                    action_names = ["North", "East", "South", "West", "Up", "Down"]
                    print(f"\n{'=' * 80}")
                    print(f"📤 Python Agent - Sending Action #{packet_count}")
                    print(f"{'=' * 80}")
                    print(f"  Packet ID: {packet_id}")
                    print(
                        f"  Selected action: {action} ({action_names[action] if action < 6 else 'INVALID'})"
                    )
                    print(f"  Action valid: {not is_invalid}")
                    print(f"  Exploration: {is_exploration}")
                    print(f"  Epsilon: {self.agent.epsilon:.6f}")

                    # Show Q-values if we're exploiting
                    if not is_exploration:
                        with torch.no_grad():
                            state_tensor = (
                                torch.FloatTensor(state)
                                .unsqueeze(0)
                                .to(self.agent.device)
                            )
                            q_values = self.agent.q_network(state_tensor)
                            q_vals = q_values[0].cpu().numpy()
                            print(
                                f"  Q-values: N={q_vals[0]:.4f}, E={q_vals[1]:.4f}, "
                                f"S={q_vals[2]:.4f}, W={q_vals[3]:.4f}"
                            )
                            print(
                                f"  Max Q-value: {q_vals.max():.4f} (action {q_vals.argmax()})"
                            )

                    print(f"{'=' * 80}\n")

                # Update state monitor with selected action
                if self.enable_state_monitor and self.state_monitor:
                    # Re-log state with action (if we have the state)
                    if len(state) > 0:
                        self.state_monitor.log_state(
                            state, packet_id, reward, done, available_actions, action
                        )

                # Send action back to gem5 router
                response = {"action": int(action), "packet_id": packet_id}
                self.socket.send_json(response)

                # Store current state and action for next iteration
                last_state = state.copy()
                last_action = action

                packet_count += 1
                self.packet_count = packet_count  # Update instance variable

                # Trigger training periodically (Algorithm 1: every T_train)
                # Skip in eval mode for stability
                if (
                    not self.eval_mode
                    and len(self.agent.memory) >= self.agent.batch_size
                ):
                    if packet_count % self.agent.train_frequency == 0:
                        loss = self.agent.train()

                        # Update dashboard with loss
                        if self.web_dashboard and WEB_DASHBOARD_AVAILABLE and loss > 0:
                            update_web_metrics(loss=loss)
                        elif self.dashboard and loss > 0:
                            self.dashboard.update_metrics(loss=loss)
                        elif self.simple_dashboard and loss > 0:
                            self.simple_dashboard.update_metrics(loss=loss)

                        # Record training in report
                        if self.report and loss > 0:
                            self.report.record_training(loss, self.agent.epsilon)

                        if packet_count % 100 == 0 and loss > 0:
                            print(
                                f"🧠 Training: loss={loss:.4f}, total_reward={self.agent.total_reward:.2f}"
                            )

                # Periodic status updates
                if packet_count % 100 == 0:
                    invalid_rate = (
                        (self.invalid_action_count / self.total_actions * 100)
                        if self.total_actions > 0
                        else 0
                    )
                    print(
                        f"✅ Processed {packet_count} routing decisions. "
                        f"Epsilon: {self.agent.epsilon:.4f}, "
                        f"Memory: {len(self.agent.memory)}/{self.agent.memory.capacity}, "
                        f"Invalid actions: {invalid_rate:.1f}%, "
                        f"Training steps: {self.agent.training_step}"
                    )
                    import sys

                    sys.stdout.flush()

                    # Periodic model save (every save_frequency packets)
                    if (
                        self.save_model_path
                        and packet_count - self.last_save_packet >= self.save_frequency
                    ):
                        try:
                            self.agent.save_model(self.save_model_path)
                            self.last_save_packet = packet_count
                            print(
                                f"💾 Model auto-saved (packet {packet_count}, epsilon: {self.agent.epsilon:.4f})"
                            )
                        except Exception as e:
                            print(f"⚠️  Warning: Failed to save model: {e}")
                elif packet_count == 1:
                    print(
                        f"✅ First routing decision processed! Communication is working. "
                        f"State size: {len(state)}, Memory: {len(self.agent.memory)}/{self.agent.memory.capacity}"
                    )
                    # Force print to ensure it's visible
                    import sys

                    sys.stdout.flush()
                elif packet_count == 10:
                    print(
                        f"✅ Processed {packet_count} packets. Memory: {len(self.agent.memory)}/{self.agent.memory.capacity}, "
                        f"Epsilon: {self.agent.epsilon:.4f}"
                    )
                    import sys

                    sys.stdout.flush()

            except KeyboardInterrupt:
                print(
                    "\n\n⚠️  KeyboardInterrupt received. Shutting down server gracefully..."
                )
                self.running = False
                break
            except zmq.Again:
                # Timeout or no message - continue polling
                continue
            except zmq.ZMQError as e:
                # ZMQ-specific errors (like context termination)
                if self.running:
                    print(f"ZMQ Error: {e}")
                break
            except Exception as e:
                # Only print errors if we're still running (avoid errors during shutdown)
                if self.running:
                    print(f"Error in server loop: {e}")
                    import traceback

                    traceback.print_exc()
                continue

        # Close state monitor
        if self.enable_state_monitor and self.state_monitor:
            self.state_monitor.close()

        # Generate and print report
        if self.report:
            self.report.finalize()
            print("\n" + "=" * 80)
            print("GENERATING DETAILED REPORT...")
            print("=" * 80)
            report_text = self.report.generate_report(
                f"deepnr_report_{int(time.time())}.txt"
            )
            print("\n" + report_text)
            print("\n" + "=" * 80)
            print("Report also saved to file (deepnr_report_*.txt)")
            print("=" * 80 + "\n")

        # Cleanup
        if self.should_terminate:
            print(f"\n⚠️  Server terminated due to: {self.termination_reason}")
            print(
                "   Recommendation: Restart simulation with fresh training or check agent learning."
            )

        print("Closing socket and cleaning up...")
        try:
            self.socket.close()
            self.context.term()
        except Exception:
            pass
        print("✅ Server shutdown complete.")


# ============================================================================
# Main Entry Point
# ============================================================================


def main():
    parser = argparse.ArgumentParser(description="DeepNR DRL Agent for NoC Routing")
    parser.add_argument("--port", type=int, default=5555, help="ZMQ server port")
    parser.add_argument(
        "--state-size",
        type=int,
        default=136,
        help="State vector size = 2*num_routers+8 (e.g. 4x4x4=64 routers → 136)",
    )
    parser.add_argument(
        "--action-size", type=int, default=6,
        help="Number of routing directions (6 for 3D: N,E,S,W,Up,Down)",
    )
    parser.add_argument(
        "--load-model",
        type=str,
        default=None,
        help="Path to load trained model (e.g., deepnr_model.pth)",
    )
    parser.add_argument(
        "--use-saved-model",
        action="store_true",
        help="Automatically find and load the most recent saved model",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Start fresh: don't load any saved model (overrides --use-saved-model)",
    )
    parser.add_argument(
        "--save-model",
        type=str,
        default="deepnr_model.pth",
        help="Path to save model (default: deepnr_model.pth in current directory)",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Enable web dashboard (opens in browser)",
    )
    parser.add_argument(
        "--dashboard-port", type=int, default=5000, help="Port for web dashboard"
    )
    parser.add_argument(
        "--eval-mode",
        action="store_true",
        help="Evaluation mode: disable training for stable results",
    )
    parser.add_argument(
        "--state-monitor",
        action="store_true",
        help="Enable state monitoring (logs all states to file)",
    )
    parser.add_argument(
        "--state-log-file",
        type=str,
        default="deepnr_states.log",
        help="File to log states to",
    )
    parser.add_argument(
        "--max-invalid-action-rate",
        type=float,
        default=0.3,
        help="Maximum invalid action rate before termination (default: 0.3 = 30%%)",
    )
    parser.add_argument(
        "--max-latency-threshold",
        type=float,
        default=1000.0,
        help="Maximum latency threshold in cycles before termination (default: 1000)",
    )
    parser.add_argument(
        "--train-frequency",
        type=int,
        default=5,
        help="T_train: Train every N packets (Algorithm 1, default: 5)",
    )
    parser.add_argument(
        "--target-update-frequency",
        type=int,
        default=100,
        help="T_target: Update target network every N training steps (Algorithm 1, default: 100)",
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=0.01,
        help="Learning rate α (alpha) for Adam optimizer (default: 0.01)",
    )
    parser.add_argument(
        "--gamma",
        type=float,
        default=0.9,
        help="Discount factor γ (gamma) for future rewards (default: 0.9)",
    )
    parser.add_argument(
        "--epsilon",
        type=float,
        default=0.9,
        help="Initial epsilon for epsilon-greedy exploration (default: 0.9)",
    )
    parser.add_argument(
        "--epsilon-min",
        type=float,
        default=0.01,
        help="Minimum epsilon value (default: 0.01)",
    )
    parser.add_argument(
        "--epsilon-decay",
        type=float,
        default=0.995,
        help="Epsilon decay rate per episode (default: 0.995)",
    )

    args = parser.parse_args()

    # Determine model file location
    model_dir = (
        os.path.dirname(args.save_model) if os.path.dirname(args.save_model) else "."
    )
    model_filename = os.path.basename(args.save_model)
    default_model_path = os.path.join(model_dir, model_filename)

    print("=" * 70)
    print("DeepNR Agent Configuration")
    print("=" * 70)
    print(f"Model save location: {os.path.abspath(default_model_path)}")

    # Find existing models
    existing_models = glob.glob("deepnr_model*.pth") + glob.glob(
        "**/deepnr_model*.pth", recursive=True
    )
    if existing_models:
        print(f"\nFound {len(existing_models)} existing model file(s):")
        for model in sorted(existing_models, key=os.path.getmtime, reverse=True):
            mtime = os.path.getmtime(model)
            size = os.path.getsize(model) / 1024  # KB
            print(
                f"  - {os.path.abspath(model)} ({size:.1f} KB, modified: {time.ctime(mtime)})"
            )
    else:
        print("\nNo existing model files found (will start fresh)")
    print("=" * 70)

    # Create the agent with optimized hyperparameters
    agent = DeepNR_Agent(
        state_size=args.state_size,
        action_size=args.action_size,
        lr=args.learning_rate,
        gamma=args.gamma,
        epsilon=args.epsilon,
        epsilon_min=args.epsilon_min,
        epsilon_decay=args.epsilon_decay,
        train_frequency=args.train_frequency,
        target_update_frequency=args.target_update_frequency,
    )

    # Load model logic
    model_loaded = False
    if args.fresh:
        print("\n🆕 Starting fresh: No model will be loaded")
    elif args.load_model:
        # Explicit model path provided
        if os.path.exists(args.load_model):
            print(f"\n📂 Loading model from: {os.path.abspath(args.load_model)}")
            agent.load_model(args.load_model)
            model_loaded = True
        else:
            print(f"\n⚠️  Warning: Model file not found: {args.load_model}")
            print("   Starting with fresh (untrained) model")
    elif args.use_saved_model:
        # Auto-find most recent model
        if existing_models:
            # Get most recently modified model
            latest_model = max(existing_models, key=os.path.getmtime)
            print(
                f"\n📂 Auto-loading most recent model: {os.path.abspath(latest_model)}"
            )
            agent.load_model(latest_model)
            model_loaded = True
        else:
            print("\n⚠️  Warning: --use-saved-model specified but no saved model found")
            print("   Starting with fresh (untrained) model")
    elif os.path.exists(default_model_path):
        # Default model exists - auto-load to continue training
        print(f"\n📂 Found default model: {os.path.abspath(default_model_path)}")
        print("   Auto-loading to continue training...")
        agent.load_model(default_model_path)
        model_loaded = True
    elif existing_models:
        # No default model, but found models in subdirectories - load most recent
        latest_model = max(existing_models, key=os.path.getmtime)
        print(f"\n📂 Found model in subdirectory: {os.path.abspath(latest_model)}")
        print("   Auto-loading to continue training...")
        agent.load_model(latest_model)
        model_loaded = True

    if model_loaded:
        print(f"✅ Model loaded successfully (Epsilon: {agent.epsilon:.4f})")

    # Create and run the server
    server = DeepNR_Server(
        agent,
        port=args.port,
        enable_dashboard=args.dashboard,
        dashboard_port=args.dashboard_port,
        eval_mode=args.eval_mode,
        max_invalid_action_rate=args.max_invalid_action_rate,
        max_latency_threshold=args.max_latency_threshold,
        enable_state_monitor=args.state_monitor,
        state_log_file=args.state_log_file,
        save_model_path=default_model_path,  # Enable periodic model saving
        save_frequency=500,  # Save every 500 packets
    )

    if args.eval_mode:
        print("⚠️  EVALUATION MODE: Training disabled for stable results")
        print("   Make sure to use a pre-trained model (--load-model)")

    try:
        server.run()
    except (KeyboardInterrupt, SystemExit):
        print("\n⚠️  Interrupt received in main...")
        server.running = False
    except Exception as e:
        print(f"\n⚠️  Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        server.running = False
    finally:
        # Always save model and cleanup on exit
        if server.running is False or True:  # Always try to save
            print("\n💾 Saving model before exit...")
            try:
                agent.save_model(args.save_model)
                print(f"✅ Model saved to {args.save_model}")
            except Exception as e:
                print(f"⚠️  Error saving model: {e}")
        print("👋 Exiting.")


if __name__ == "__main__":
    main()
