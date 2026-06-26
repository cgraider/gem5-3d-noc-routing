#!/usr/bin/env python3
"""
DeepNR Performance Metrics Collection and Analysis
"""

import json
import time
import numpy as np
import matplotlib.pyplot as plt
from collections import defaultdict, deque
import os

class DeepNRMetrics:
    def __init__(self):
        self.metrics = {
            'latency': deque(maxlen=1000),
            'throughput': deque(maxlen=1000),
            'packet_loss': deque(maxlen=1000),
            'reward_history': deque(maxlen=1000),
            'action_distribution': defaultdict(int),
            'training_loss': deque(maxlen=1000),
            'epsilon_history': deque(maxlen=1000),
            'episode_rewards': deque(maxlen=1000)
        }
        
        self.start_time = time.time()
        self.packet_count = 0
        self.total_latency = 0
        self.lost_packets = 0
        
    def record_packet(self, latency, success=True):
        """Record packet metrics"""
        self.packet_count += 1
        self.total_latency += latency
        self.metrics['latency'].append(latency)
        
        if not success:
            self.lost_packets += 1
            self.metrics['packet_loss'].append(1)
        else:
            self.metrics['packet_loss'].append(0)
    
    def record_action(self, action):
        """Record action taken"""
        self.metrics['action_distribution'][action] += 1
    
    def record_reward(self, reward):
        """Record reward received"""
        self.metrics['reward_history'].append(reward)
    
    def record_training_loss(self, loss):
        """Record training loss"""
        self.metrics['training_loss'].append(loss)
    
    def record_epsilon(self, epsilon):
        """Record epsilon value"""
        self.metrics['epsilon_history'].append(epsilon)
    
    def record_episode_reward(self, total_reward):
        """Record total episode reward"""
        self.metrics['episode_rewards'].append(total_reward)
    
    def get_current_metrics(self):
        """Get current performance metrics"""
        if not self.metrics['latency']:
            return {}
        
        current_time = time.time()
        elapsed_time = current_time - self.start_time
        
        return {
            'avg_latency': np.mean(self.metrics['latency']),
            'max_latency': np.max(self.metrics['latency']),
            'min_latency': np.min(self.metrics['latency']),
            'throughput': self.packet_count / elapsed_time if elapsed_time > 0 else 0,
            'packet_loss_rate': self.lost_packets / self.packet_count if self.packet_count > 0 else 0,
            'avg_reward': np.mean(self.metrics['reward_history']) if self.metrics['reward_history'] else 0,
            'total_packets': self.packet_count,
            'elapsed_time': elapsed_time
        }
    
    def save_metrics(self, filename='deepnr_metrics.json'):
        """Save metrics to file"""
        metrics_data = {
            'timestamp': time.time(),
            'current_metrics': self.get_current_metrics(),
            'latency_history': list(self.metrics['latency']),
            'reward_history': list(self.metrics['reward_history']),
            'action_distribution': dict(self.metrics['action_distribution']),
            'training_loss': list(self.metrics['training_loss']),
            'epsilon_history': list(self.metrics['epsilon_history']),
            'episode_rewards': list(self.metrics['episode_rewards'])
        }
        
        with open(filename, 'w') as f:
            json.dump(metrics_data, f, indent=2)
    
    def plot_metrics(self, save_path='deepnr_metrics_plot.png'):
        """Plot performance metrics"""
        fig, axes = plt.subplots(2, 3, figsize=(15, 10))
        fig.suptitle('DeepNR Performance Metrics', fontsize=16)
        
        # Latency over time
        if self.metrics['latency']:
            axes[0, 0].plot(self.metrics['latency'])
            axes[0, 0].set_title('Packet Latency')
            axes[0, 0].set_xlabel('Packet #')
            axes[0, 0].set_ylabel('Latency (cycles)')
        
        # Reward history
        if self.metrics['reward_history']:
            axes[0, 1].plot(self.metrics['reward_history'])
            axes[0, 1].set_title('Reward History')
            axes[0, 1].set_xlabel('Step')
            axes[0, 1].set_ylabel('Reward')
        
        # Action distribution
        if self.metrics['action_distribution']:
            actions = list(self.metrics['action_distribution'].keys())
            counts = list(self.metrics['action_distribution'].values())
            axes[0, 2].bar(actions, counts)
            axes[0, 2].set_title('Action Distribution')
            axes[0, 2].set_xlabel('Action')
            axes[0, 2].set_ylabel('Count')
        
        # Training loss
        if self.metrics['training_loss']:
            axes[1, 0].plot(self.metrics['training_loss'])
            axes[1, 0].set_title('Training Loss')
            axes[1, 0].set_xlabel('Training Step')
            axes[1, 0].set_ylabel('Loss')
        
        # Epsilon decay
        if self.metrics['epsilon_history']:
            axes[1, 1].plot(self.metrics['epsilon_history'])
            axes[1, 1].set_title('Epsilon Decay')
            axes[1, 1].set_xlabel('Step')
            axes[1, 1].set_ylabel('Epsilon')
        
        # Episode rewards
        if self.metrics['episode_rewards']:
            axes[1, 2].plot(self.metrics['episode_rewards'])
            axes[1, 2].set_title('Episode Rewards')
            axes[1, 2].set_xlabel('Episode')
            axes[1, 2].set_ylabel('Total Reward')
        
        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight')
        plt.close()
    
    def print_summary(self):
        """Print metrics summary"""
        metrics = self.get_current_metrics()
        print("\n" + "="*50)
        print("DeepNR Performance Summary")
        print("="*50)
        print(f"Total Packets: {metrics.get('total_packets', 0)}")
        print(f"Average Latency: {metrics.get('avg_latency', 0):.2f} cycles")
        print(f"Max Latency: {metrics.get('max_latency', 0):.2f} cycles")
        print(f"Min Latency: {metrics.get('min_latency', 0):.2f} cycles")
        print(f"Throughput: {metrics.get('throughput', 0):.2f} packets/sec")
        print(f"Packet Loss Rate: {metrics.get('packet_loss_rate', 0)*100:.2f}%")
        print(f"Average Reward: {metrics.get('avg_reward', 0):.3f}")
        print(f"Elapsed Time: {metrics.get('elapsed_time', 0):.2f} seconds")
        print("="*50)
    
    def save_and_plot_metrics(self):
        """Save and plot all metrics"""
        self.save_metrics()
        self.plot_metrics()
        self.print_summary()

# Global metrics instance
_metrics_instance = None

def get_metrics():
    """Get global metrics instance"""
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = DeepNRMetrics()
    return _metrics_instance

def record_packet_metrics(latency, success=True):
    """Record packet metrics"""
    get_metrics().record_packet(latency, success)

def record_action_metrics(action):
    """Record action metrics"""
    get_metrics().record_action(action)

def record_reward_metrics(reward):
    """Record reward metrics"""
    get_metrics().record_reward(reward)

def record_training_metrics(loss):
    """Record training metrics"""
    get_metrics().record_training_loss(loss)

def record_epsilon_metrics(epsilon):
    """Record epsilon metrics"""
    get_metrics().record_epsilon(epsilon)

def save_and_plot_metrics():
    """Save and plot all metrics"""
    metrics = get_metrics()
    metrics.save_metrics()
    metrics.plot_metrics()
    metrics.print_summary()

if __name__ == "__main__":
    # Test the metrics system
    metrics = DeepNRMetrics()
    
    # Simulate some data
    for i in range(100):
        latency = np.random.exponential(10) + 5
        success = np.random.random() > 0.05  # 5% packet loss
        metrics.record_packet(latency, success)
        metrics.record_action(np.random.randint(0, 4))
        metrics.record_reward(np.random.normal(0.5, 0.2))
    
    metrics.save_and_plot_metrics()
    print("Metrics test completed!")
