"""
Script to run the run_sequence function directly without import issues.
This imports run_sequence module correctly by treating the agent directory as a package.
"""
import sys
import os

# Make sure the agent directory is in the path
agent_dir = os.path.dirname(os.path.abspath(__file__))
if agent_dir not in sys.path:
    sys.path.insert(0, agent_dir)

# Import and run directly
from fsm_core import run_sequence

if __name__ == "__main__":
    run_sequence.run_sequence()