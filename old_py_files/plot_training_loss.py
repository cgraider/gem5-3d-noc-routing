#!/usr/bin/env python3
"""
Comprehensive Training Loss Visualization for DeepNR
"""

import json
import numpy as np
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter1d
import os

def load_training_data():
    """Load training data from metrics file"""
    try:
        with open('deepnr_metrics.json', 'r') as f:
            data = json.load(f)
        return data
    except FileNotFoundError:
        print("Error: deepnr_metrics.json not found")
        return None
    except Exception as e:
        print(f"Error loading data: {e}")
        return None

def create_comprehensive_loss_plot(data):
    """Create comprehensive training loss visualization"""
    
    training_loss = data.get('training_loss', [])
    epsilon_history = data.get('epsilon_history', [])
    episode_rewards = data.get('episode_rewards', [])
    
    if not training_loss:
        print("No training loss data available")
        return
    
    # Create figure with subplots
    fig = plt.figure(figsize=(16, 12))
    
    # Main loss plot (larger)
    ax1 = plt.subplot(2, 2, (1, 2))
    
    # Convert to numpy arrays for easier manipulation
    loss_array = np.array(training_loss)
    steps = np.arange(len(loss_array))
    
    # Plot raw loss
    ax1.plot(steps, loss_array, 'b-', alpha=0.3, linewidth=1, label='Raw Loss')
    
    # Plot smoothed loss using Gaussian filter
    if len(loss_array) > 3:
        smoothed_loss = gaussian_filter1d(loss_array, sigma=1.0)
        ax1.plot(steps, smoothed_loss, 'b-', linewidth=2, label='Smoothed Loss')
    
    # Plot moving average
    if len(loss_array) > 5:
        window_size = min(5, len(loss_array) // 3)
        moving_avg = np.convolve(loss_array, np.ones(window_size)/window_size, mode='valid')
        moving_steps = np.arange(window_size-1, len(loss_array))
        ax1.plot(moving_steps, moving_avg, 'r-', linewidth=2, label=f'Moving Average (window={window_size})')
    
    # Add trend line
    if len(loss_array) > 2:
        z = np.polyfit(steps, loss_array, 1)
        p = np.poly1d(z)
        ax1.plot(steps, p(steps), 'g--', linewidth=2, alpha=0.7, label=f'Trend (slope={z[0]:.4f})')
    
    ax1.set_title('DeepNR Training Loss Over Time', fontsize=16, fontweight='bold')
    ax1.set_xlabel('Training Step', fontsize=12)
    ax1.set_ylabel('Loss Value', fontsize=12)
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # Add statistics text
    stats_text = f"""Loss Statistics:
    Initial Loss: {loss_array[0]:.4f}
    Final Loss: {loss_array[-1]:.4f}
    Min Loss: {np.min(loss_array):.4f}
    Max Loss: {np.max(loss_array):.4f}
    Mean Loss: {np.mean(loss_array):.4f}
    Std Dev: {np.std(loss_array):.4f}
    Total Steps: {len(loss_array)}"""
    
    ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes, fontsize=10,
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    # Epsilon decay plot
    ax2 = plt.subplot(2, 2, 3)
    if epsilon_history:
        epsilon_array = np.array(epsilon_history)
        epsilon_steps = np.arange(len(epsilon_array))
        ax2.plot(epsilon_steps, epsilon_array, 'g-', linewidth=2, marker='o', markersize=4)
        ax2.set_title('Epsilon Decay (Exploration Rate)', fontsize=14)
        ax2.set_xlabel('Training Step', fontsize=12)
        ax2.set_ylabel('Epsilon Value', fontsize=12)
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim(0, 1)
    
    # Episode rewards plot
    ax3 = plt.subplot(2, 2, 4)
    if episode_rewards:
        rewards_array = np.array(episode_rewards)
        episode_numbers = np.arange(1, len(rewards_array) + 1)
        ax3.plot(episode_numbers, rewards_array, 'purple', linewidth=2, marker='s', markersize=6)
        ax3.set_title('Episode Rewards', fontsize=14)
        ax3.set_xlabel('Episode Number', fontsize=12)
        ax3.set_ylabel('Total Reward', fontsize=12)
        ax3.grid(True, alpha=0.3)
        
        # Add trend line for rewards
        if len(rewards_array) > 1:
            z_rewards = np.polyfit(episode_numbers, rewards_array, 1)
            p_rewards = np.poly1d(z_rewards)
            ax3.plot(episode_numbers, p_rewards(episode_numbers), 'r--', linewidth=2, alpha=0.7)
    
    plt.tight_layout()
    
    # Save the plot
    output_file = 'training_loss_comprehensive.png'
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✅ Comprehensive loss plot saved as: {output_file}")
    
    # Also create a simple focused loss plot
    create_simple_loss_plot(training_loss)
    
    plt.show()

def create_simple_loss_plot(training_loss):
    """Create a simple, focused loss plot"""
    
    fig, ax = plt.subplots(1, 1, figsize=(10, 6))
    
    loss_array = np.array(training_loss)
    steps = np.arange(len(loss_array))
    
    # Plot raw loss
    ax.plot(steps, loss_array, 'b-', alpha=0.4, linewidth=1, label='Raw Loss')
    
    # Plot smoothed loss
    if len(loss_array) > 3:
        smoothed_loss = gaussian_filter1d(loss_array, sigma=1.0)
        ax.plot(steps, smoothed_loss, 'b-', linewidth=3, label='Smoothed Loss')
    
    # Highlight minimum loss
    min_idx = np.argmin(loss_array)
    ax.plot(min_idx, loss_array[min_idx], 'ro', markersize=8, label=f'Min Loss: {loss_array[min_idx]:.4f}')
    
    ax.set_title('DeepNR Training Loss', fontsize=16, fontweight='bold')
    ax.set_xlabel('Training Step', fontsize=12)
    ax.set_ylabel('Loss Value', fontsize=12)
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Add improvement percentage
    if len(loss_array) > 1:
        improvement = ((loss_array[0] - loss_array[-1]) / loss_array[0]) * 100
        ax.text(0.02, 0.98, f'Improvement: {improvement:.1f}%', 
                transform=ax.transAxes, fontsize=12, fontweight='bold',
                verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))
    
    plt.tight_layout()
    
    # Save the simple plot
    output_file = 'training_loss_simple.png'
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✅ Simple loss plot saved as: {output_file}")

def generate_loss_analysis_report(data):
    """Generate a text report of loss analysis"""
    
    training_loss = data.get('training_loss', [])
    if not training_loss:
        return
    
    loss_array = np.array(training_loss)
    
    report = f"""
DeepNR Training Loss Analysis Report
==================================

Dataset Overview:
- Total Training Steps: {len(training_loss)}
- Loss Range: {np.min(loss_array):.4f} to {np.max(loss_array):.4f}
- Mean Loss: {np.mean(loss_array):.4f}
- Standard Deviation: {np.std(loss_array):.4f}

Training Progress:
- Initial Loss: {loss_array[0]:.4f}
- Final Loss: {loss_array[-1]:.4f}
- Overall Improvement: {((loss_array[0] - loss_array[-1]) / loss_array[0]) * 100:.1f}%
- Best Loss Achieved: {np.min(loss_array):.4f} (Step {np.argmin(loss_array)})

Loss Stability:
- Loss Variance: {np.var(loss_array):.6f}
- Coefficient of Variation: {(np.std(loss_array) / np.mean(loss_array)) * 100:.1f}%

Training Characteristics:
- Loss decreases: {'Yes' if loss_array[-1] < loss_array[0] else 'No'}
- Monotonic decrease: {'Yes' if all(loss_array[i] >= loss_array[i+1] for i in range(len(loss_array)-1)) else 'No'}
- Converged: {'Yes' if np.std(loss_array[-3:]) < 0.01 else 'No'} (last 3 steps)

Recommendations:
"""
    
    if loss_array[-1] < loss_array[0]:
        report += "- ✅ Training is progressing well with decreasing loss\n"
    else:
        report += "- ⚠️ Loss is not decreasing - consider adjusting learning rate\n"
    
    if np.std(loss_array) > np.mean(loss_array) * 0.5:
        report += "- ⚠️ High loss variance - consider reducing learning rate\n"
    else:
        report += "- ✅ Loss variance is acceptable\n"
    
    if len(training_loss) < 50:
        report += "- 💡 Consider running more training steps for better convergence\n"
    
    print(report)
    
    # Save report to file
    with open('training_loss_analysis.txt', 'w') as f:
        f.write(report)
    print("📄 Analysis report saved as: training_loss_analysis.txt")

def main():
    """Main function to generate loss plots"""
    print("🎯 DeepNR Training Loss Visualization")
    print("=" * 50)
    
    # Load training data
    data = load_training_data()
    if data is None:
        return
    
    # Check if we have loss data
    training_loss = data.get('training_loss', [])
    if not training_loss:
        print("❌ No training loss data found in metrics file")
        return
    
    print(f"📊 Found {len(training_loss)} training steps")
    print(f"📈 Loss range: {min(training_loss):.4f} to {max(training_loss):.4f}")
    
    # Generate comprehensive plots
    create_comprehensive_loss_plot(data)
    
    # Generate analysis report
    generate_loss_analysis_report(data)
    
    print("\n✅ Loss visualization complete!")
    print("📁 Generated files:")
    print("   - training_loss_comprehensive.png")
    print("   - training_loss_simple.png") 
    print("   - training_loss_analysis.txt")

if __name__ == "__main__":
    main()
