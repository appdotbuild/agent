import asyncio
import json
import uuid
import pytest
import anyio
from httpx import AsyncClient, ASGITransport
import os
from typing import List, Dict, Any, Tuple, Optional

os.environ["CODEGEN_AGENT"] = "empty_diff"

from api.agent_server.async_server import app
from api.agent_server.models import AgentStatus
from api.agent_server.agent_api_client import AgentApiClient

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.mark.skipif(os.getenv("TEST_ASYNC_AGENT_SERVER") != "true", reason="Set TEST_ASYNC_AGENT_SERVER=true to run async agent server tests")
async def test_async_agent_message_endpoint():
    async with AgentApiClient() as client:
        (event_objects, event_dicts), request = await client.send_message("Implement a calculator app")

        # Check that we received some events
        assert len(event_objects) > 0, "No SSE events received"
        assert len(event_dicts) > 0, "No raw SSE events received"

        # Verify model objects
        for event in event_objects:
            assert event.trace_id == request.trace_id, "Trace IDs do not match in model objects"
            assert event.message is not None, "Event message is missing in model objects"

        # Verify raw dictionaries
        for event in event_dicts:
            assert "traceId" in event, "Missing traceId in SSE payload"
            assert event["traceId"] == request.trace_id, "Trace IDs do not match"


@pytest.mark.skipif(os.getenv("TEST_ASYNC_AGENT_SERVER") != "true", reason="Set TEST_ASYNC_AGENT_SERVER=true to run async agent server tests")
async def test_async_agent_state_continuation():
    """Test that agent state can be restored and conversation can continue."""
    async with AgentApiClient() as client:
        # Initial request
        (initial_events, initial_raw_events), initial_request = await client.send_message("Create a todo app")
        assert len(initial_events) > 0, "No initial events received"

        # Continue conversation with new message
        (continuation_events, continuation_raw_events), continuation_request = await client.continue_conversation(
            previous_events=initial_events,
            previous_request=initial_request,
            message="Add authentication to the app"
        )

        assert len(continuation_events) > 0, "No continuation events received"

        # Verify trace IDs match between initial and continuation
        for event in continuation_events:
            assert event.trace_id == initial_request.trace_id, "Trace IDs don't match in continuation (model)"

        for event in continuation_raw_events:
            assert "traceId" in event, "Missing traceId in continuation events"
            assert event["traceId"] == initial_request.trace_id, "Trace IDs don't match in continuation (raw)"


@pytest.mark.skipif(os.getenv("TEST_ASYNC_AGENT_SERVER") != "true", reason="Set TEST_ASYNC_AGENT_SERVER=true to run async agent server tests")
async def test_sequential_sse_responses():
    """Test that sequential SSE responses work properly within a session."""
    async with AgentApiClient() as client:
        # Initial request
        (initial_events, _), initial_request = await client.send_message("Create a hello world app")
        assert len(initial_events) > 0, "No initial events received"

        # First continuation
        (first_continuation_events, _), first_continuation_request = await client.continue_conversation(
            previous_events=initial_events,
            previous_request=initial_request,
            message="Add a welcome message"
        )
        assert len(first_continuation_events) > 0, "No first continuation events received"

        # Second continuation
        (second_continuation_events, _), second_continuation_request = await client.continue_conversation(
            previous_events=first_continuation_events,
            previous_request=first_continuation_request,
            message="Add a goodbye message"
        )
        assert len(second_continuation_events) > 0, "No second continuation events received"

        # Verify trace IDs remain consistent across all requests
        assert initial_request.trace_id == first_continuation_request.trace_id == second_continuation_request.trace_id, \
            "Trace IDs don't match across sequential requests"

        # Verify the sequence is maintained (check trace IDs in all events)
        all_trace_ids = [event.trace_id for event in initial_events + first_continuation_events + second_continuation_events]
        assert all(tid == initial_request.trace_id for tid in all_trace_ids), "Trace IDs inconsistent across sequential SSE responses"


@pytest.mark.skipif(os.getenv("TEST_ASYNC_AGENT_SERVER") != "true", reason="Set TEST_ASYNC_AGENT_SERVER=true to run async agent server tests")
async def test_session_with_no_state():
    """Test session behavior when no state is provided in continuation requests."""
    async with AgentApiClient() as client:
        # Generate a fixed trace/chatbot ID to use for all requests
        fixed_trace_id = uuid.uuid4().hex
        fixed_chatbot_id = f"test-bot-{uuid.uuid4().hex[:8]}"

        # First request
        (first_events, _), _ = await client.send_message(
            "Create a counter app",
            chatbot_id=fixed_chatbot_id,
            trace_id=fixed_trace_id
        )
        assert len(first_events) > 0, "No events received from first request"

        # Second request - same session, explicitly pass None for agent_state
        (second_events, _), _ = await client.send_message(
            "Add a reset button",
            chatbot_id=fixed_chatbot_id,
            trace_id=fixed_trace_id,
            agent_state=None
        )
        assert len(second_events) > 0, "No events received from second request"

        # Verify each event has the expected trace ID
        for event in first_events + second_events:
            assert event.trace_id == fixed_trace_id, f"Trace ID mismatch: {event.trace_id} != {fixed_trace_id}"


@pytest.mark.skipif(os.getenv("TEST_ASYNC_AGENT_SERVER") != "true", reason="Set TEST_ASYNC_AGENT_SERVER=true to run async agent server tests")
async def test_agent_reaches_idle_state():
    """Test that the agent eventually transitions to IDLE state after processing a simple prompt."""
    async with AgentApiClient() as client:
        # Send a simple "Hello" prompt
        (events, _), _ = await client.send_message("Hello")

        # Check that we received some events
        assert len(events) > 0, "No events received"

        # Verify the final event has IDLE status
        final_event = events[-1]
        assert final_event.status == AgentStatus.IDLE, "Agent did not reach IDLE state"

        # Additional checks that may be useful
        assert final_event.message is not None, "Final event has no message"
        assert final_event.message.role == "agent", "Final message role is not 'agent'"


@pytest.mark.skipif(os.getenv("TEST_ASYNC_AGENT_SERVER") != "true", reason="Set TEST_ASYNC_AGENT_SERVER=true to run async agent server tests")
async def test_agent_completes_app_generation():
    """Test that the agent transitions to IDLE state after processing an app generation request.
    
    This test verifies:
    1. The agent processes the request and returns events
    2. The agent reaches the IDLE state when done
    3. The response contains some message content
    4. For non-test agents, the content should include app-related terminology
    5. If the agent generates diffs, they should be non-empty
    """
    async with AgentApiClient() as client:
        # Send a prompt to generate a simple app
        (events, event_dicts), request = await client.send_message("Generate a simple counter app with increment and decrement buttons")

        # Check that we received some events
        assert len(events) > 0, "No events received"
        
        # Verify the final event has IDLE status indicating completion
        final_event = events[-1]
        assert final_event.status == AgentStatus.IDLE, "Agent did not complete app generation (not in IDLE state)"
        
        # Verify the response includes a message with agent role
        assert final_event.message is not None, "Final event has no message"
        assert final_event.message.role == "agent", "Final message role is not 'agent'"
        
        # Verify there is some content in the message
        content = final_event.message.content
        assert content, "No content in the final message"
        
        # For the "empty_diff" agent implementation used in tests, we can't expect 
        # real app content, so we skip the content verification
        if os.environ.get("CODEGEN_AGENT") != "empty_diff":
            # For real agent implementations, verify the content includes app-related terms
            app_indicators = [
                "counter", "increment", "decrement", "button",
                "function", "component", "app", "application",
                "code", "html", "javascript", "react"
            ]
            
            has_app_content = any(indicator.lower() in content.lower() for indicator in app_indicators)
            assert has_app_content, "Generated content does not appear to include app-related content"
        
        # If the agent implementation includes unified diffs (code changes), verify they're non-empty
        if hasattr(final_event.message, 'unified_diff') and final_event.message.unified_diff:
            assert len(final_event.message.unified_diff) > 0, "Unified diff is empty"


@pytest.mark.skipif(os.getenv("TEST_ASYNC_AGENT_SERVER") != "true", reason="Set TEST_ASYNC_AGENT_SERVER=true to run async agent server tests")
async def test_template_diff_agent():
    """Test that the TemplateDiffAgentImplementation properly generates a counter app with a unified diff."""
    
    # Import the config module to directly modify the agent type
    from api import config
    
    # Temporarily set the agent type to use the template diff agent
    original_agent_type = config.AGENT_TYPE
    config.AGENT_TYPE = "template_diff"
    
    try:
        async with AgentApiClient() as client:
            # Send a prompt to generate a counter app
            (events, event_dicts), request = await client.send_message(
                "Create a counter app with increment and decrement buttons"
            )

            # Check that we received events
            assert len(events) > 0, "No events received"
            
            # Verify the final event has IDLE status
            final_event = events[-1]
            assert final_event.status == AgentStatus.IDLE, "Agent did not reach IDLE state"
            
            # Verify the app content is included in the response
            assert final_event.message is not None, "Final event has no message"
            
            # Check for counter app specific content
            content = final_event.message.content
            assert "counter app" in content.lower(), "Response doesn't mention counter app"
            assert "increment" in content.lower(), "Response doesn't mention increment"
            assert "decrement" in content.lower(), "Response doesn't mention decrement"
            
            # Verify unified diff was created
            assert hasattr(final_event.message, 'unified_diff'), "Message doesn't have unified_diff attribute"
            assert final_event.message.unified_diff is not None, "Unified diff is None"
            assert len(final_event.message.unified_diff) > 0, "Unified diff is empty"
            
            # Check that the diff includes the expected changes
            diff = final_event.message.unified_diff
            assert "useState" in diff, "Diff doesn't include React useState"
            assert "Counter App" in diff, "Diff doesn't include Counter App title"
            assert "increment" in diff.lower(), "Diff doesn't include increment function"
            assert "decrement" in diff.lower(), "Diff doesn't include decrement function"
            
            # Check the agent state for app generation info
            assert final_event.message.agent_state is not None, "Agent state is None"
            assert final_event.message.agent_state.get("app_generated") is True, "app_generated flag not set in state"
            assert final_event.message.agent_state.get("app_type") == "counter", "app_type not set to counter in state"
            
            # Verify expected modified files are tracked in state
            assert "template_files" in final_event.message.agent_state, "template_files not in state"
            assert "modified_files" in final_event.message.agent_state, "modified_files not in state"
            assert "App.tsx" in final_event.message.agent_state["modified_files"], "App.tsx not in modified files"
    finally:
        # Restore the original agent implementation
        config.AGENT_TYPE = original_agent_type


if __name__ == "__main__":
    anyio.run(test_async_agent_message_endpoint, backend="asyncio")
