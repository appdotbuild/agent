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


if __name__ == "__main__":
    anyio.run(test_async_agent_message_endpoint, backend="asyncio")
