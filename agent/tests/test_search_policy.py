import unittest
from unittest.mock import Mock, patch
from anthropic import AnthropicBedrock
from agent.compiler.core import Compiler
from agent.search import SearchPolicy, Node

class TestSearchPolicy(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.mock_client = Mock(spec=AnthropicBedrock)
        self.mock_client.messages = Mock()
        self.mock_client.messages.create = Mock()
        self.mock_compiler = Mock(spec=Compiler)
        self.policy = SearchPolicy(self.mock_client, self.mock_compiler)

    def tearDown(self):
        """Clean up after each test method."""
        self.mock_client = None
        self.mock_compiler = None
        self.policy = None

    @patch('agent.search.SearchPolicy.run_typespec')
    def test_bfs_typespec_should_return_successful_node(self, mock_run_typespec):
        """Test that bfs_typespec returns a successful node after failed attempt."""
        # Arrange
        failed_attempt = {
            "message": {"role": "assistant", "content": "attempt 1"},
            "output": {"typespec_definitions": "invalid code"},
            "feedback": {"exit_code": 1, "stdout": "Error in code"}
        }
        successful_attempt = {
            "message": {"role": "assistant", "content": "attempt 2"},
            "output": {"typespec_definitions": "valid code"},
            "feedback": {"exit_code": 0, "stdout": None}
        }
        mock_run_typespec.side_effect = [failed_attempt, successful_attempt]

        root = Node(
            {
                "message": {"role": "user", "content": "initial"},
                "output": None,
                "feedback": {"exit_code": 1, "stdout": "Initial error"}
            },
            score=0
        )

        # Act
        result = self.policy.bfs_typespec(
            {"role": "user", "content": "test"},
            root,
            max_depth=2,
            branch_factor=1,
            max_workers=1
        )

        # Assert
        self.assertEqual(result.score, 1, "Result score should be 1 for successful node")
        self.assertEqual(result.data["feedback"]["exit_code"], 0, "Exit code should be 0 for successful attempt")
        mock_run_typespec.assert_called()
        self.assertEqual(mock_run_typespec.call_count, 2, "run_typespec should be called twice")

    @patch('agent.search.SearchPolicy.run_drizzle')
    def test_bfs_drizzle_should_return_successful_node(self, mock_run_drizzle):
        """Test that bfs_drizzle returns a successful node after failed attempt."""
        # Arrange
        failed_attempt = {
            "message": {"role": "assistant", "content": "attempt 1"},
            "output": {"drizzle_schema": "invalid schema"},
            "feedback": {"exit_code": 1, "stderr": "Schema error"}
        }
        successful_attempt = {
            "message": {"role": "assistant", "content": "attempt 2"},
            "output": {"drizzle_schema": "valid schema"},
            "feedback": {"exit_code": 0, "stderr": None}
        }
        mock_run_drizzle.side_effect = [failed_attempt, successful_attempt]

        root = Node(
            {
                "message": {"role": "user", "content": "initial"},
                "output": None,
                "feedback": {"exit_code": 1, "stderr": "Initial error"}
            },
            score=0
        )

        # Act
        result = self.policy.bfs_drizzle(
            {"role": "user", "content": "test"},
            root,
            max_depth=2,
            branch_factor=1,
            max_workers=1
        )

        # Assert
        self.assertEqual(result.score, 1, "Result score should be 1 for successful node")
        self.assertIsNone(result.data["feedback"]["stderr"], "stderr should be None for successful attempt")
        mock_run_drizzle.assert_called()
        self.assertEqual(mock_run_drizzle.call_count, 2, "run_drizzle should be called twice")

if __name__ == '__main__':
    unittest.main()