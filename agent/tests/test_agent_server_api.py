import pytest
import uuid
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import asyncio

from api.agent_server.server import app
from api.agent_server.models import AgentStatus, MessageKind, AgentMessage, AgentSseEvent

# Create test client
client = TestClient(app)

@pytest.fixture
def mock_langfuse():
    with patch('api.agent_server.server.Langfuse') as mock:
        trace_mock = MagicMock()
        trace_mock.id = "test-trace-id"
        mock.return_value.trace.return_value = trace_mock
        yield mock

@pytest.fixture
def mock_client():
    with patch('api.agent_server.server.get_sync_client') as mock:
        yield mock

@pytest.fixture
def mock_compiler():
    with patch('api.agent_server.server.Compiler') as mock:
        yield mock

@pytest.fixture
def mock_fsm_manager():
    with patch('api.agent_server.server.FSMManager') as mock:
        fsm_instance = MagicMock()
        # Mock methods to work with external state
        fsm_instance.set_full_external_state = MagicMock()
        fsm_instance.get_full_external_state = MagicMock(return_value={})
        mock.return_value = fsm_instance
        yield mock

@pytest.fixture
def mock_fsm_processor():
    with patch('api.agent_server.server.FSMToolProcessor') as mock:
        processor_instance = MagicMock()
        # Mock tool_start_fsm to return a success result
        processor_instance.tool_start_fsm = MagicMock(return_value={
            "success": True,
            "message": "FSM started successfully"
        })
        mock.return_value = processor_instance
        yield mock

@pytest.fixture
def mock_run_with_claude():
    with patch('api.agent_server.server.run_with_claude') as mock:
        # Mock to return a message, completion status, and trace ID
        mock.return_value = (
            {"role": "assistant", "content": "Hello, this is a test response"},
            True,  # is_complete
            "test-trace-id"
        )
        yield mock

def test_healthcheck():
    """Test the health check endpoint"""
    response = client.get("/healthcheck")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

def test_message_endpoint(
    mock_langfuse, mock_client, mock_compiler, mock_fsm_manager, mock_fsm_processor, mock_run_with_claude
):
    """Test the message endpoint"""
    # Test data
    request_data = {
        "allMessages": ["Build me an app to plan my meals"],
        "chatbotId": "test-bot-id",
        "traceId": "test-trace-id",
        "settings": {"max-iterations": 3}
    }
    
    # Mock the AgentSession.process_step method to return a predefined event
    with patch('api.agent_server.server.AgentSession.process_step') as mock_process:
        # Return a predefined event for the first call, None for subsequent calls to end iteration
        mock_process.side_effect = [
            AgentSseEvent(
                status=AgentStatus.RUNNING,
                trace_id="test-trace-id",
                message=AgentMessage(
                    kind=MessageKind.STAGE_RESULT,
                    content="Processing...",
                    agent_state={},
                    unified_diff=None
                )
            ),
            None  # Return None to end iteration
        ]
        
        # Mock the AgentSession.advance_fsm method to return False after one iteration
        with patch('api.agent_server.server.AgentSession.advance_fsm') as mock_advance:
            mock_advance.return_value = False
            
            # Make the request with timeout to prevent hanging
            with client.stream("POST", "/message", json=request_data, timeout=2.0) as response:
                # Check the response
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                
                # Verify we got at least one chunk
                content = b''
                for chunk in response.iter_raw():
                    content += chunk
                    # Break after receiving one chunk to prevent test from hanging
                    break
                
                # Verify we received data
                assert content.startswith(b'data:')

def test_message_endpoint_error_handling(
    mock_langfuse, mock_client, mock_compiler, mock_fsm_manager
):
    """Test error handling in the message endpoint"""
    # Force an error by making the sse_event_generator function raise an exception
    with patch('api.agent_server.server.sse_event_generator', side_effect=ValueError("Test error")):
        # Test data
        request_data = {
            "allMessages": ["Build me an app to plan my meals"],
            "chatbotId": "test-bot-id",
            "traceId": "test-trace-id",
            "settings": {"max-iterations": 3}
        }
        
        # Make the request
        response = client.post("/message", json=request_data)
        
        # Check the response
        assert response.status_code == 500
        assert "detail" in response.json()
        assert "Test error" in response.json()["detail"]