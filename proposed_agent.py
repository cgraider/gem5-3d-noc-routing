#!/usr/bin/env python3
"""
Proposed Method: Enhanced DQN-based 3D NoC Routing Agent (Paper 2).

Differences from DeepNR-3D (deepnr_agent.py):
  - State: 10 features (2*num_routers+28) vs 5 (2*num_routers+8)
  - Loss:  Huber loss  vs MSE
  - lr:    0.0003      vs 0.01
  - eps_min: 0.1       vs 0.01
  - replay:  10 000    vs 200
  - warm-up: 1 000 steps before training starts
  - train_freq: 40, target_update: 500

Run before gem5:
    python3 proposed_agent.py --num-rows 4 --num-cols 4 --num-layers 4
"""

import argparse
import json
import os
import random
import signal
import time
from collections import deque

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import zmq

# ---------------------------------------------------------------------------
# Hyperparameters (from paper)
# ---------------------------------------------------------------------------
WARM_UP_PHASE        = 1000    # steps before training starts
TRAIN_FREQUENCY      = 40      # train every N routing decisions
TARGET_UPDATE_FREQ   = 500     # copy Q → Q_hat every N training steps
LEARNING_RATE        = 0.0003
DISCOUNT_FACTOR      = 0.9     # γ
EPSILON_START        = 0.9
EPSILON_MIN          = 0.1
EPSILON_DECAY        = 0.995
REPLAY_BUFFER_SIZE   = 10_000
BATCH_SIZE           = 64


# ---------------------------------------------------------------------------
# Neural Network
# ---------------------------------------------------------------------------
class DQN(nn.Module):
    """
    Architecture (same as DeepNR paper, adapted for new state/action size):
      Input compression : state_size → 64
      Hidden 1          : 64  → 256
      Hidden 2          : 256 → 128
      Hidden 3          : 128 → 64
      Output            : 64  → 6  (N, E, S, W, Up, Down)
    """

    def __init__(self, state_size: int, action_size: int = 6):
        super().__init__()
        self.compress = nn.Linear(state_size, 64)
        self.fc1 = nn.Linear(64, 256)
        self.fc2 = nn.Linear(256, 128)
        self.fc3 = nn.Linear(128, 64)
        self.out = nn.Linear(64, action_size)
        self.relu = nn.ReLU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.relu(self.compress(x))
        x = self.relu(self.fc1(x))
        x = self.relu(self.fc2(x))
        x = self.relu(self.fc3(x))
        return self.out(x)  # linear output → raw Q-values


# ---------------------------------------------------------------------------
# Experience Replay
# ---------------------------------------------------------------------------
class ReplayBuffer:
    def __init__(self, capacity: int = REPLAY_BUFFER_SIZE):
        self.buf = deque(maxlen=capacity)

    def push(self, state, action, reward, next_state, done):
        self.buf.append((state, action, reward, next_state, done))

    def sample(self, batch_size: int):
        batch = random.sample(self.buf, min(batch_size, len(self.buf)))
        s, a, r, ns, d = zip(*batch)
        return (
            torch.FloatTensor(np.array(s, dtype=np.float32)),
            torch.LongTensor(np.array(a, dtype=np.int64)),
            torch.FloatTensor(np.array(r, dtype=np.float32)),
            torch.FloatTensor(np.array(ns, dtype=np.float32)),
            torch.BoolTensor(np.array(d, dtype=bool)),
        )

    def __len__(self):
        return len(self.buf)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
class ProposedAgent:
    def __init__(self, state_size: int, action_size: int = 6,
                 device: torch.device = None):
        self.state_size  = state_size
        self.action_size = action_size
        self.device = device or torch.device(
            "cuda" if torch.cuda.is_available() else "cpu")
        print(f"[Proposed] Device: {self.device}")

        self.q_net     = DQN(state_size, action_size).to(self.device)
        self.target_net = DQN(state_size, action_size).to(self.device)
        self.target_net.load_state_dict(self.q_net.state_dict())
        self.target_net.eval()

        self.optimizer = optim.Adam(self.q_net.parameters(), lr=LEARNING_RATE)
        self.memory    = ReplayBuffer(REPLAY_BUFFER_SIZE)

        self.epsilon      = EPSILON_START
        self.step_count   = 0   # total routing decisions seen
        self.train_count  = 0   # training steps performed

    # ------------------------------------------------------------------
    def select_action(self, state: np.ndarray,
                      available: list[bool] | None = None,
                      training: bool = True) -> int:
        valid = [i for i in range(self.action_size)
                 if available is None or available[i]]
        if not valid:
            valid = list(range(self.action_size))

        if training and random.random() < self.epsilon:
            return random.choice(valid)

        with torch.no_grad():
            q = self.q_net(
                torch.FloatTensor(state).unsqueeze(0).to(self.device))
            masked = q.clone()
            for i in range(self.action_size):
                if i not in valid:
                    masked[0][i] = float("-inf")
            return masked.argmax().item()

    # ------------------------------------------------------------------
    def remember(self, state, action, reward, next_state, done):
        self.memory.push(state, action, reward, next_state, done)

    # ------------------------------------------------------------------
    def train(self) -> float:
        """One gradient step using Huber loss."""
        if len(self.memory) < BATCH_SIZE:
            return 0.0

        states, actions, rewards, next_states, dones = \
            self.memory.sample(BATCH_SIZE)

        states      = states.to(self.device)
        actions     = actions.to(self.device)
        rewards     = rewards.to(self.device)
        next_states = next_states.to(self.device)
        dones       = dones.to(self.device)

        current_q = self.q_net(states).gather(1, actions.unsqueeze(1))

        with torch.no_grad():
            max_next_q = self.target_net(next_states).max(1)[0]
            target_q   = rewards + DISCOUNT_FACTOR * max_next_q * ~dones

        # Huber loss (smooth L1) — innovation over DeepNR's MSE
        loss = nn.functional.smooth_l1_loss(
            current_q.squeeze(), target_q)

        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.q_net.parameters(), max_norm=1.0)
        self.optimizer.step()

        # Epsilon decay
        if self.epsilon > EPSILON_MIN:
            self.epsilon *= EPSILON_DECAY
            self.epsilon = max(self.epsilon, EPSILON_MIN)

        self.train_count += 1
        if self.train_count % TARGET_UPDATE_FREQ == 0:
            self.target_net.load_state_dict(self.q_net.state_dict())
            print(f"[Proposed] Target network synced at train step "
                  f"{self.train_count}")

        return loss.item()

    # ------------------------------------------------------------------
    def save(self, path: str):
        torch.save({
            "q_net": self.q_net.state_dict(),
            "target_net": self.target_net.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "epsilon": self.epsilon,
            "step_count": self.step_count,
            "train_count": self.train_count,
        }, path)
        print(f"[Proposed] Model saved → {path}")

    def load(self, path: str):
        ckpt = torch.load(path, map_location=self.device)
        self.q_net.load_state_dict(ckpt["q_net"])
        self.target_net.load_state_dict(ckpt["target_net"])
        self.optimizer.load_state_dict(ckpt["optimizer"])
        self.epsilon    = ckpt.get("epsilon", EPSILON_MIN)
        self.step_count = ckpt.get("step_count", 0)
        self.train_count = ckpt.get("train_count", 0)
        print(f"[Proposed] Model loaded ← {path}")


# ---------------------------------------------------------------------------
# ZMQ Server
# ---------------------------------------------------------------------------
class ProposedServer:
    DIR_NAMES = ["North", "East", "South", "West", "Up", "Down"]

    def __init__(self, agent: ProposedAgent, port: int = 5556,
                 save_path: str = "proposed_model.pth",
                 save_freq: int = 2000, eval_mode: bool = False):
        self.agent     = agent
        self.port      = port
        self.save_path = save_path
        self.save_freq = save_freq
        self.eval_mode = eval_mode
        self.running   = True

        self.ctx    = zmq.Context()
        self.socket = self.ctx.socket(zmq.REP)
        self.socket.setsockopt(zmq.RCVTIMEO, 100)
        self.socket.setsockopt(zmq.SNDTIMEO, 100)
        self.socket.bind(f"tcp://*:{port}")
        print(f"[Proposed] Server listening on port {port}")
        print(f"[Proposed] State size = {agent.state_size}, "
              f"action size = {agent.action_size}")
        print(f"[Proposed] Warm-up: {WARM_UP_PHASE} steps, "
              f"then train every {TRAIN_FREQUENCY} steps")

        signal.signal(signal.SIGINT,  self._stop)
        signal.signal(signal.SIGTERM, self._stop)

    def _stop(self, *_):
        print("\n[Proposed] Shutting down …")
        self.running = False

    def run(self):
        last_state  = None
        last_action = None
        step        = 0
        total_loss  = 0.0
        invalid_cnt = 0

        poller = zmq.Poller()
        poller.register(self.socket, zmq.POLLIN)

        print("[Proposed] Ready — waiting for gem5 …")
        while self.running:
            try:
                if not dict(poller.poll(100)):
                    continue
                try:
                    msg = self.socket.recv_json(zmq.NOBLOCK)
                except zmq.Again:
                    continue
            except Exception as e:
                print(f"[Proposed] recv error: {e}")
                continue

            state      = np.array(msg.get("state", []), dtype=np.float32)
            reward     = float(msg.get("reward", 0.0))
            done       = bool(msg.get("done", False))
            avail      = msg.get("available_actions", None)

            # Validate state size
            if len(state) != self.agent.state_size:
                print(f"[Proposed] WARNING: state size {len(state)} "
                      f"!= expected {self.agent.state_size}. "
                      f"Restart with --num-rows/--num-cols/--num-layers "
                      f"matching gem5.")

            # Store previous transition once we have the reward for it
            if last_state is not None and last_action is not None and step > 0:
                self.agent.remember(last_state, last_action,
                                    reward, state, done)
                self.agent.step_count += 1

            # Select action
            action = self.agent.select_action(
                state, available=avail,
                training=not self.eval_mode)

            # Check validity
            if avail is not None and not avail[action]:
                invalid_cnt += 1

            # Train (after warm-up, every TRAIN_FREQUENCY steps)
            loss = 0.0
            if (not self.eval_mode
                    and self.agent.step_count >= WARM_UP_PHASE
                    and self.agent.step_count % TRAIN_FREQUENCY == 0
                    and len(self.agent.memory) >= BATCH_SIZE):
                loss = self.agent.train()
                total_loss += loss

            # Periodic save & log
            step += 1
            if step % 1000 == 0:
                eps  = self.agent.epsilon
                buf  = len(self.agent.memory)
                inv_rate = invalid_cnt / max(step, 1) * 100
                print(f"[Proposed] step={step:6d} | ε={eps:.4f} | "
                      f"buf={buf:5d} | loss={loss:.5f} | "
                      f"invalid={inv_rate:.1f}%")

            if self.save_path and step % self.save_freq == 0:
                self.agent.save(self.save_path)

            last_state  = state
            last_action = action

            try:
                self.socket.send_json({"action": action})
            except Exception as e:
                print(f"[Proposed] send error: {e}")

        # Final save
        if self.save_path:
            self.agent.save(self.save_path)
        self.socket.close()
        self.ctx.term()
        print(f"[Proposed] Done. Total steps={step}, "
              f"training steps={self.agent.train_count}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Proposed Method DQN agent for 3D NoC routing")
    parser.add_argument("--port", type=int, default=5556)
    parser.add_argument("--num-rows",    type=int, default=4,
                        help="Rows in each mesh layer (same as gem5 --mesh-rows)")
    parser.add_argument("--num-cols",    type=int, default=4,
                        help="Columns per layer (same as gem5 --num-cpus / cols)")
    parser.add_argument("--num-layers",  type=int, default=4,
                        help="Number of mesh layers (z-dimension)")
    parser.add_argument("--num-routers", type=int, default=None,
                        help="Override total router count (gem5 getNumRouters()). "
                             "If set, ignores --num-rows/cols/layers for state size.")
    parser.add_argument("--save-model", type=str,
                        default="proposed_model.pth")
    parser.add_argument("--load-model", type=str, default=None)
    parser.add_argument("--save-freq",  type=int, default=2000)
    parser.add_argument("--eval",       action="store_true",
                        help="Evaluation mode: no training, ε fixed at min")
    args = parser.parse_args()

    if args.num_routers is not None:
        num_routers = args.num_routers
    else:
        num_routers = args.num_rows * args.num_cols * args.num_layers
    # State: 2*num_routers + 28
    #   f1(num_r) + f2(num_r) + f3(1) + f4(1) + f5(6) +
    #   f6(1) + f7(6) + f8(6) + f9(6) + f10(1)
    state_size  = 2 * num_routers + 28

    print(f"[Proposed] Routers: {num_routers}")
    print(f"[Proposed] State size: {state_size}")

    agent = ProposedAgent(state_size=state_size, action_size=6)

    if args.load_model and os.path.exists(args.load_model):
        agent.load(args.load_model)
    elif args.eval:
        print("[Proposed] WARNING: eval mode but no model loaded.")

    if args.eval:
        agent.epsilon = EPSILON_MIN
        print(f"[Proposed] Eval mode: ε fixed at {EPSILON_MIN}")

    server = ProposedServer(agent, port=args.port,
                            save_path=args.save_model,
                            save_freq=args.save_freq,
                            eval_mode=args.eval)
    server.run()


if __name__ == "__main__":
    main()
