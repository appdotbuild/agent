"""Test for agent session message content fix."""
import pytest
from unittest.mock import AsyncMock, Mock
import json

from trpc_agent.agent_session import TrpcAgentSession
from api.agent_server.models import (
    AgentRequest, 
    AgentSseEvent, 
    UserMessage, 
    MessageKind
)
from llm.common import Message, TextRaw


@pytest.mark.asyncio
async def test_agent_session_sends_plain_text_responses():
    """Test that agent session sends plain text responses, not JSON-serialized history."""
    
    # Create a mock event stream
    events_sent = []
    
    class MockEventStream:
        async def send(self, event: AgentSseEvent):
            events_sent.append(event)
        
        async def aclose(self):
            pass
    
    event_tx = MockEventStream()
    
    # Create agent session
    session = TrpcAgentSession(
        application_id="test-app",
        trace_id="test-trace"
    )
    
    # Mock the processor to return some messages
    mock_processor = Mock()
    mock_processor.step = AsyncMock(return_value=(
        [Message(role="assistant", content=[TextRaw("Hello! I can help you build an app.")])],
        "IDLE"  # FSMStatus.IDLE equivalent
    ))
    mock_processor.fsm_app = None
    session.processor_instance = mock_processor
    
    # Create a simple request
    request = AgentRequest(
        allMessages=[UserMessage(role="user", content="build me an app")],
        applicationId="test-app",
        traceId="test-trace"
    )
    
    # Process the request
    await session.process(request, event_tx)
    
    # Verify events were sent
    assert len(events_sent) > 0
    
    # Check the content of the last event
    last_event = events_sent[-1]
    assert last_event.message.content == "Hello! I can help you build an app."
    assert last_event.message.kind == MessageKind.REFINEMENT_REQUEST
    
    # Ensure content is NOT JSON
    try:
        parsed = json.loads(last_event.message.content)
        if isinstance(parsed, list):
            pytest.fail("Content should not be a JSON-serialized list")
    except json.JSONDecodeError:
        # This is expected - content should be plain text
        pass


@pytest.mark.asyncio
async def test_get_latest_assistant_response():
    """Test the _get_latest_assistant_response helper method."""
    
    session = TrpcAgentSession()
    
    # Test with mixed messages
    messages = [
        Message(role="user", content=[TextRaw("Hello")]),
        Message(role="assistant", content=[TextRaw("Hi there!")]),
        Message(role="user", content=[TextRaw("Build me an app")]),
        Message(role="assistant", content=[TextRaw("Sure! "), TextRaw("I'll help you build an app.")]),
    ]
    
    result = session._get_latest_assistant_response(messages)
    assert result == "Sure! I'll help you build an app."
    
    # Test with no assistant messages
    messages_no_assistant = [
        Message(role="user", content=[TextRaw("Hello")]),
        Message(role="user", content=[TextRaw("Anyone there?")]),
    ]
    
    result = session._get_latest_assistant_response(messages_no_assistant)
    assert result is None


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_agent_session_sends_plain_text_responses())
    asyncio.run(test_get_latest_assistant_response())
    print("All tests passed!") 