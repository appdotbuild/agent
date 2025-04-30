import os
import pytest
import json
from pathlib import Path
import logging

from api.agent_server.agent_api_client import latest_unified_diff
from api.agent_server.models import AgentSseEvent, AgentMessage, AgentStatus, MessageKind

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return 'asyncio'

async def test_mock_diff_extraction():
    """Test that the mock diff is properly extracted from the mock message."""
    mock_cache_path = Path(__file__).parent.parent / "llm" / "caches" / "mock_cache.json"
    assert mock_cache_path.exists(), f"Mock cache file not found at {mock_cache_path}"
    
    with open(mock_cache_path, "r") as f:
        mock_data = json.load(f)
        mock_response = mock_data.get("mock_key", {})
        
        # Print the mock_response to debug
        logger.info(f"Mock response: {mock_response}")
        
        mock_message = AgentMessage.model_validate({
            "content": "Mock response for testing",
            "unifiedDiff": mock_response.get("unified_diff", ""),  # Use the alias "unifiedDiff" instead of "unified_diff"
            "kind": MessageKind.STAGE_RESULT
        })
        
        # Print the mock_message to debug
        logger.info(f"Mock message unified_diff: {mock_message.unified_diff}")
        
        mock_event = AgentSseEvent(
            status=AgentStatus.IDLE,
            trace_id="mock-trace-id",
            message=mock_message
        )
        
        events = [mock_event]
        diff = latest_unified_diff(events)
        
        # Print the extracted diff to debug
        logger.info(f"Extracted diff: {diff}")
        
        assert diff, "No diff was generated in the mock response"
