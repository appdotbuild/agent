import pytest
import uuid
import json
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import asyncio
import sys
import os

# Add project root to path to make imports work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

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
        "allMessages": [{"role": "user", "content": "Build me an app to plan my meals"}],
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
                traceId="test-trace-id",
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.STAGE_RESULT,
                    content="Processing...",
                    agentState={},
                    unifiedDiff=None
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
            "allMessages": [{"role": "user", "content": "Build me an app to plan my meals"}],
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


def test_multiple_sse_updates(
    mock_langfuse, mock_client, mock_compiler, mock_fsm_manager, mock_fsm_processor, mock_run_with_claude
):
    """Test receiving multiple SSE updates from the agent"""
    # Test data
    request_data = {
        "allMessages": [{"role": "user", "content": "Build me an app with multiple steps"}],
        "chatbotId": "test-bot-id",
        "traceId": "test-trace-id",
        "settings": {"max-iterations": 3}
    }
    
    # Mock the AgentSession.process_step method to return multiple events
    with patch('api.agent_server.server.AgentSession.process_step') as mock_process:
        # Return three events for progress updates, then None to end iteration
        mock_process.side_effect = [
            AgentSseEvent(
                status=AgentStatus.RUNNING,
                traceId="test-trace-id",
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.STAGE_RESULT,
                    content="Analyzing requirements...",
                    agentState={"step": 1},
                    unifiedDiff=None
                )
            ),
            AgentSseEvent(
                status=AgentStatus.RUNNING,
                traceId="test-trace-id",
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.STAGE_RESULT,
                    content="Designing architecture...",
                    agentState={"step": 2},
                    unifiedDiff=None
                )
            ),
            AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId="test-trace-id",
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.STAGE_RESULT,
                    content="Implementation complete",
                    agentState={"step": 3, "completed": True},
                    unifiedDiff="--- a/file.txt\n+++ b/file.txt\n@@ -1,1 +1,1 @@\n-Old\n+New"
                )
            ),
            None  # Return None to end iteration
        ]
        
        # Mock the AgentSession.advance_fsm method to return True twice, then False
        with patch('api.agent_server.server.AgentSession.advance_fsm') as mock_advance:
            mock_advance.side_effect = [True, True, False]
            
            # Make the request with timeout to prevent hanging
            with client.stream("POST", "/message", json=request_data, timeout=3.0) as response:
                # Check the response
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                
                # Collect all event data
                events = []
                for i, chunk in enumerate(response.iter_raw()):
                    if chunk.startswith(b'data:'):
                        events.append(json.loads(chunk.decode().replace('data: ', '')))
                    if i >= 3:  # Limit to prevent test from hanging
                        break
                
                # Verify we got multiple events
                assert len(events) > 1
                # Verify event sequence
                steps = [event["message"]["agentState"].get("step") for event in events if "message" in event and "agentState" in event["message"]]
                assert steps, "No steps found in events"
                assert steps == sorted(steps), "Steps not in ascending order"


def test_different_message_kinds(
    mock_langfuse, mock_client, mock_compiler, mock_fsm_manager, mock_fsm_processor, mock_run_with_claude
):
    """Test handling different message kinds in SSE updates"""
    # Test data
    request_data = {
        "allMessages": [{"role": "user", "content": "Build me an app with feedback"}],
        "chatbotId": "test-bot-id",
        "traceId": "test-trace-id",
        "settings": {"max-iterations": 3}
    }
    
    # Mock the AgentSession.process_step method to return different message kinds
    with patch('api.agent_server.server.AgentSession.process_step') as mock_process:
        # Return events with different message kinds
        mock_process.side_effect = [
            AgentSseEvent(
                status=AgentStatus.RUNNING,
                traceId="test-trace-id",
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.STAGE_RESULT,
                    content="Working on implementation...",
                    agentState={"stage": "implementation"},
                    unifiedDiff=None
                )
            ),
            AgentSseEvent(
                status=AgentStatus.RUNNING,
                traceId="test-trace-id",
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.FEEDBACK_RESPONSE,
                    content="Responding to feedback...",
                    agentState={"stage": "feedback"},
                    unifiedDiff=None
                )
            ),
            AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId="test-trace-id",
                message=AgentMessage(
                    role="agent",
                    kind=MessageKind.RUNTIME_ERROR,
                    content="Non-fatal error occurred during processing",
                    agentState={"stage": "error_handling"},
                    unifiedDiff=None
                )
            ),
            None  # Return None to end iteration
        ]
        
        # Mock the AgentSession.advance_fsm method to return True twice, then False
        with patch('api.agent_server.server.AgentSession.advance_fsm') as mock_advance:
            mock_advance.side_effect = [True, True, False]
            
            # Make the request with timeout to prevent hanging
            with client.stream("POST", "/message", json=request_data, timeout=3.0) as response:
                # Check the response
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                
                # Collect all event data
                events = []
                for i, chunk in enumerate(response.iter_raw()):
                    if chunk.startswith(b'data:'):
                        events.append(json.loads(chunk.decode().replace('data: ', '')))
                    if i >= 3:  # Limit to prevent test from hanging
                        break
                
                # Verify we got events with different message kinds
                message_kinds = [event["message"]["kind"] for event in events if "message" in event]
                assert MessageKind.STAGE_RESULT.value in message_kinds
                assert MessageKind.FEEDBACK_RESPONSE.value in message_kinds
                assert MessageKind.RUNTIME_ERROR.value in message_kinds