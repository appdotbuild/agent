import uuid
import pytest
from log import get_logger
from api.agent_server.models import AgentSseEvent, AgentStatus, MessageKind
from api.agent_server.agent_api_client import AgentApiClient


logger = get_logger(__name__)

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def trpc_agent(monkeypatch):
    monkeypatch.setenv("CODEGEN_AGENT", "trpc_agent")
    yield


@pytest.fixture
def empty_diff(monkeypatch):
    monkeypatch.setenv("CODEGEN_AGENT", "empty_diff")
    yield


@pytest.mark.parametrize("agent_type", ["trpc_agent", "empty_diff"])
async def test_async_agent_message_endpoint(agent_type, request):
    """Test the message endpoint with different agent types."""
    # Use the appropriate fixture based on agent_type
    if agent_type == "trpc_agent":
        request.getfixturevalue("trpc_agent")
    elif agent_type == "empty_diff":
        request.getfixturevalue("empty_diff")

    async with AgentApiClient() as client:
        events, request = await client.send_message("Implement a simple app with a counter of clicks on a single button")

        assert len(events) > 0, f"No SSE events received with agent_type={agent_type}"

        # Verify model objects
        for event in events:
            match event:
                case None:
                    raise ValueError(f"Received None event for {agent_type}")
                case AgentSseEvent():
                    assert event.trace_id == request.trace_id, f"Trace IDs do not match in model objects with agent_type={agent_type}"
                    assert event.status == AgentStatus.IDLE
                    assert event.message.kind == MessageKind.STAGE_RESULT


async def test_async_agent_state_continuation(empty_diff):
    """Test that agent state can be restored and conversation can continue."""
    async with AgentApiClient() as client:
        # Initial request
        initial_events, initial_request = await client.send_message("Implement a simple app with a counter of clicks on a single button")
        assert len(initial_events) > 0, "No initial events received"

        # Continue conversation with new message
        continuation_events, continuation_request = await client.continue_conversation(
            previous_events=initial_events,
            previous_request=initial_request,
            message="Add authentication to the app"
        )

        assert len(continuation_events) > 0, "No continuation events received"

        # Verify trace IDs match between initial and continuation
        for event in continuation_events:
            assert event.trace_id == initial_request.trace_id, "Trace IDs don't match in continuation (model)"


async def test_sequential_sse_responses(empty_diff):
    """Test that sequential SSE responses work properly within a session."""
    async with AgentApiClient() as client:
        # Initial request
        initial_events, initial_request = await client.send_message("Create a hello world app")
        assert len(initial_events) > 0, "No initial events received"

        # First continuation
        first_continuation_events, first_continuation_request = await client.continue_conversation(
            previous_events=initial_events,
            previous_request=initial_request,
            message="Add a welcome message"
        )
        assert len(first_continuation_events) > 0, "No first continuation events received"

        # Second continuation
        second_continuation_events, second_continuation_request = await client.continue_conversation(
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


async def test_session_with_no_state(empty_diff):
    """Test session behavior when no state is provided in continuation requests."""
    async with AgentApiClient() as client:
        # Generate a fixed trace/chatbot ID to use for all requests
        fixed_trace_id = uuid.uuid4().hex
        fixed_application_id = f"test-bot-{uuid.uuid4().hex[:8]}"

        # First request
        first_events, _ = await client.send_message(
            "Create a counter app",
            application_id=fixed_application_id,
            trace_id=fixed_trace_id
        )
        assert len(first_events) > 0, "No events received from first request"

        # Second request - same session, explicitly pass None for agent_state
        second_events, _ = await client.send_message(
            "Add a reset button",
            application_id=fixed_application_id,
            trace_id=fixed_trace_id,
            agent_state=None
        )
        assert len(second_events) > 0, "No events received from second request"

        # Verify each event has the expected trace ID
        for event in first_events + second_events:
            assert event.trace_id == fixed_trace_id, f"Trace ID mismatch: {event.trace_id} != {fixed_trace_id}"


async def test_agent_reaches_idle_state(empty_diff):
    """Test that the agent eventually transitions to IDLE state after processing a simple prompt."""
    async with AgentApiClient() as client:
        # Send a simple "Hello" prompt
        events, _ = await client.send_message("Hello")

        # Check that we received some events
        assert len(events) > 0, "No events received"

        # Verify the final event has IDLE status
        final_event = events[-1]
        assert final_event.status == AgentStatus.IDLE, "Agent did not reach IDLE state"

        # Additional checks that may be useful
        assert final_event.message is not None, "Final event has no message"
        assert final_event.message.role == "agent", "Final message role is not 'agent'"
