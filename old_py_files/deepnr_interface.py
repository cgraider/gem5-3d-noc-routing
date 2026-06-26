#!/usr/bin/env python3
"""
DeepNR Interface Script for Gem5 Integration
This script handles communication between Gem5 C++ code and PyTorch DeepNR model
"""

import sys
import os
import argparse
import json
import time
from pathlib import Path

# Add the garnet directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src', 'mem', 'ruby', 'network', 'garnet'))

try:
    from deepnr_pytorch import get_manager, DeepNRState
    from deepnr_metrics import get_metrics, record_action_metrics, record_reward_metrics, record_training_metrics, record_epsilon_metrics
except ImportError as e:
    print(f"Warning: Could not import deepnr_pytorch: {e}")
    print("Falling back to simple heuristic routing")
    DeepNRState = None
    get_manager = None

class DeepNRInterface:
    def __init__(self):
        self.manager = None
        self.fallback_mode = False
        
        # Try to initialize PyTorch manager
        if get_manager is not None:
            try:
                self.manager = get_manager()
                print("DeepNR PyTorch manager initialized successfully")
            except Exception as e:
                print(f"Failed to initialize PyTorch manager: {e}")
                self.fallback_mode = True
        else:
            self.fallback_mode = True
            
        if self.fallback_mode:
            print("Running in fallback mode (simple heuristic routing)")

    def get_action_from_state(self, current_router_id, dest_router_id, 
                            distance_traversed, distance_remaining, free_buffers):
        """Get routing action from current state"""
        
        if self.fallback_mode or self.manager is None:
            return self._fallback_routing(current_router_id, dest_router_id)
        
        try:
            # Get action from PyTorch model with individual parameters
            action = self.manager.get_action(
                current_router_id, dest_router_id, 
                distance_traversed, distance_remaining, free_buffers
            )
            
            # Record action metrics
            try:
                record_action_metrics(action)
            except:
                pass  # Don't fail if metrics recording fails
            
            return action
            
        except Exception as e:
            print(f"Error getting action from PyTorch: {e}")
            return self._fallback_routing(current_router_id, dest_router_id)

    def _fallback_routing(self, current_router_id, dest_router_id):
        """Simple heuristic fallback routing"""
        # Simple XY-like routing heuristic
        # This is a placeholder - in practice you'd implement proper XY routing
        
        # For 8x8 mesh (64 routers)
        mesh_size = 8
        
        current_x = current_router_id % mesh_size
        current_y = current_router_id // mesh_size
        dest_x = dest_router_id % mesh_size
        dest_y = dest_router_id // mesh_size
        
        # XY routing: first X, then Y
        if current_x != dest_x:
            # Move in X direction
            if dest_x > current_x:
                return 0  # East
            else:
                return 1  # West
        elif current_y != dest_y:
            # Move in Y direction
            if dest_y > current_y:
                return 2  # North
            else:
                return 3  # South
        else:
            # Already at destination
            return 0  # Default to East

    def add_experience(self, experience_data):
        """Add experience to replay buffer"""
        
        if self.fallback_mode or self.manager is None:
            return
            
        try:
            # Add to replay buffer with all required parameters
            self.manager.add_experience(
                current_router_id=experience_data['current_router_id'],
                dest_router_id=experience_data['dest_router_id'],
                distance_traversed=experience_data['distance_traversed'],
                distance_remaining=experience_data['distance_remaining'],
                free_buffers=experience_data['free_buffers'],
                action=experience_data['action'],
                reward=experience_data['reward'],
                next_router_id=experience_data['next_router_id'],
                next_dest_router_id=experience_data['next_dest_router_id'],
                next_distance_traversed=experience_data['next_distance_traversed'],
                next_distance_remaining=experience_data['next_distance_remaining'],
                next_free_buffers=experience_data['next_free_buffers'],
                done=experience_data['done']
            )
            
            # Record reward metrics
            try:
                record_reward_metrics(reward)
            except:
                pass  # Don't fail if metrics recording fails
            
        except Exception as e:
            print(f"Error adding experience: {e}")

def main():
    parser = argparse.ArgumentParser(description='DeepNR Interface for Gem5')
    parser.add_argument('--get-action', action='store_true', 
                       help='Get action from current state')
    parser.add_argument('--add-experience', action='store_true',
                       help='Add experience to replay buffer')
    parser.add_argument('--train', action='store_true',
                       help='Train the model')
    
    args = parser.parse_args()
    
    # Initialize interface
    interface = DeepNRInterface()
    
    if args.get_action:
        # Read state from file
        try:
            print("get_action started")
            with open('deepnr_state.json', 'r') as f:
                state_data = json.load(f)
            
            action = interface.get_action_from_state(
                state_data['current_router_id'],
                state_data['dest_router_id'],
                state_data['distance_traversed'],
                state_data['distance_remaining'],
                state_data['free_buffers']
            )
            
            # Write action to file
            with open('deepnr_action.json', 'w') as f:
                json.dump({'action': action}, f)
                
            print(f"Action: {action}")
            
        except FileNotFoundError:
            print("Error: deepnr_state.json not found")
            sys.exit(1)
        except Exception as e:
            print(f"Error processing action request: {e}")
            sys.exit(1)
    
    elif args.add_experience:
        # Read experience from file
        try:
            print("add_experience started")
            with open('deepnr_experience.json', 'r') as f:
                exp_data = json.load(f)
            
            interface.add_experience(exp_data)
            
            print("Experience added successfully")
            
        except FileNotFoundError:
            print("Error: deepnr_experience.json not found")
            sys.exit(1)
        except Exception as e:
            print(f"Error adding experience: {e}")
            sys.exit(1)
    
    elif args.train:
        # Train the model
        try:
            print("train started")
            if interface.manager is not None:
                # Get training loss
                loss = interface.manager.train()
                
                # Record training metrics
                try:
                    record_training_metrics(loss)
                    record_epsilon_metrics(interface.manager.network.epsilon)
                except:
                    pass  # Don't fail if metrics recording fails
                
                print(f"Model training completed with loss: {loss:.4f}")
            else:
                print("No PyTorch manager available for training")
        except Exception as e:
            print(f"Error during training: {e}")
            sys.exit(1)
    
    else:
        print("No action specified. Use --get-action, --add-experience, or --train")

if __name__ == "__main__":
    main()
