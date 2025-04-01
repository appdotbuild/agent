import pytest
import uuid
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from api.agent_server.server import app
from api.agent_server.models import AgentStatus, MessageKind, AgentMessage, AgentSseEvent
from statemachine import StateMachine
from application import FsmState, FsmEvent

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
def mock_application():
    with patch('api.agent_server.server.Application') as mock:
        app_instance = MagicMock()
        # Mock make_fsm_states to return a list of states
        app_instance.make_fsm_states.return_value = [
            MagicMock(name="state1"),
            MagicMock(name="state2")
        ]
        mock.return_value = app_instance
        yield mock

@pytest.fixture
def mock_statemachine():
    with patch('api.agent_server.server.StateMachine') as mock:
        fsm_instance = MagicMock()
        # Mock stack_path to return a list with the current state
        fsm_instance.stack_path = [FsmState.TYPESPEC_REVIEW]
        # Mock context to return a dictionary
        fsm_instance.context = {
            "typespec_schema": MagicMock(
                typespec="test typespec",
                reasoning="test reasoning"
            )
        }
        mock.return_value = fsm_instance
        yield mock

def test_healthcheck():
    """Test the health check endpoint"""
    response = client.get("/healthcheck")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

@pytest.mark.asyncio
async def test_message_endpoint(
    mock_langfuse, mock_client, mock_compiler, mock_application, mock_statemachine
):
    """Test the message endpoint"""
    # Test data
    request_data = {
        "allMessages": ["Build me an app to plan my meals"],
        "chatbotId": "test-bot-id",
        "traceId": "test-trace-id",
        "settings": {"max-iterations": 3}
    }
    
    # Mock the sse_event_generator function
    with patch('api.agent_server.server.sse_event_generator') as mock_gen:
        # Define a list of SSE events to yield
        sse_events = [
            f'data: {{"status": "running", "traceId": "test-trace-id", "message": {{"kind": "StageResult", "content": "Processing...", "agentState": null, "unifiedDiff": null}}}}\n\n',
            f'data: {{"status": "idle", "traceId": "test-trace-id", "message": {{"kind": "FeedbackResponse", "content": "Ready for review", "agentState": {{}}, "unifiedDiff": null}}}}\n\n'
        ]
        
        # Configure the mock to yield these events
        mock_gen.return_value.__aiter__.return_value = sse_events
        
        # Make the request
        with client.stream("POST", "/message", json=request_data) as response:
            # Check the response
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream"
            
            # Collect the response chunks
            chunks = []
            for chunk in response.iter_content():
                chunks.append(chunk.decode("utf-8"))
            
            # Verify the expected events
            assert len(chunks) == 2
            assert chunks[0].startswith('data: {"status": "running"')
            assert chunks[1].startswith('data: {"status": "idle"')

def test_message_endpoint_error_handling(
    mock_langfuse, mock_client, mock_compiler, mock_application
):
    """Test error handling in the message endpoint"""
    # Force an error by making the StateMachine constructor raise an exception
    with patch('api.agent_server.server.StateMachine', side_effect=ValueError("Test error")):
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
        assert "error" in response.json()
        assert "detail" in response.json()
        assert "Test error" in response.json()["detail"]