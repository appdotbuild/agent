import unittest
import os
import sys

# Add the parent directory to sys.path to avoid import issues
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fsm_core.run_sequence import run_sequence

class TestRunSequence(unittest.TestCase):
    """Test the run_sequence function without mocking"""
    
    def test_run_sequence_no_mocks(self):
        """
        Test running the full sequence without mocking.
        
        This test makes real API calls to AnthropicBedrock and Langfuse and may incur costs.
        It requires valid AWS credentials with access to Claude and proper environment setup.
        """
        # Run the sequence with no mocking
        run_sequence()
        # If we get here without exceptions, the test passes
        self.assertTrue(True)

if __name__ == "__main__":
    unittest.main()