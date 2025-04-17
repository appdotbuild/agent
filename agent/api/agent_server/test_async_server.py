import json
import uuid
import pytest
import anyio
from httpx import AsyncClient, ASGITransport
import os
import traceback
from typing import List, Dict, Any, Tuple, Optional
from log import get_logger
from api.agent_server.async_server import app, CONFIG
from api.agent_server.models import AgentSseEvent, AgentRequest, UserMessage, AgentStatus, MessageKind
from api.agent_server.agent_client import AgentApiClient


logger = get_logger(__name__)

# Set dummy token for tests
os.environ["BUILDER_TOKEN"] = "dummy_token_for_tests"

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.fixture(params=["empty_diff", "trpc_agent"])
def agent_type(request, monkeypatch):
    agent_value = request.param
    monkeypatch.setenv("CODEGEN_AGENT", agent_value)
    yield agent_value


@pytest.fixture
def empty_token(monkeypatch):
    monkeypatch.delenv("BUILDER_TOKEN", raising=False)
    yield


async def test_health():
    async with AgentApiClient() as client:
        resp = await client.client.get("http://test/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "healthy"}


async def test_invalid_token():
    async with AgentApiClient() as client:
        with pytest.raises(ValueError, match="Request failed with status code 403"):
            await client.send_message("Hello", auth_token="invalid_token")

async def test_auth_disabled(empty_token):
    async with AgentApiClient() as client:
        events, _ = await client.send_message("Hello", auth_token=None)
        assert len(events) > 0, "No events received with empty token"

async def test_empty_token(monkeypatch):
    """Test that authentication fails when no token is provided but auth is required."""
    # Save the original token
    original_token = os.environ.get("BUILDER_TOKEN")
    
    try:
        # Make sure a valid token exists in the environment, but don't pass it to the client
        monkeypatch.setenv("BUILDER_TOKEN", "valid_token_that_will_not_be_used")
        
        async with AgentApiClient() as client:
            # Explicitly set auth_token to None to bypass the default behavior in the client
            with pytest.raises(ValueError, match="Request failed with status code 401"):
                await client.send_message("Hello", auth_token=None)
    finally:
        # Restore the original token
        if original_token is not None:
            monkeypatch.setenv("BUILDER_TOKEN", original_token)
        else:
            monkeypatch.delenv("BUILDER_TOKEN", raising=False)


async def test_async_agent_message_endpoint(agent_type):
    """Test the message endpoint with different agent types."""
    async with AgentApiClient() as client:
        # Explicitly use the environment token
        auth_token = os.environ.get("BUILDER_TOKEN")
        events, request = await client.send_message(
            "Implement a calculator app", 
            auth_token=auth_token
        )

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



async def test_async_agent_state_continuation():
    """Test that agent state can be restored and conversation can continue."""
    async with AgentApiClient() as client:
        # Explicitly use the environment token
        auth_token = os.environ.get("BUILDER_TOKEN")
        
        # Initial request
        initial_events, initial_request = await client.send_message(
            "Create a todo app",
            auth_token=auth_token
        )
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



async def test_sequential_sse_responses():
    """Test that sequential SSE responses work properly within a session."""
    async with AgentApiClient() as client:
        # Explicitly use the environment token
        auth_token = os.environ.get("BUILDER_TOKEN")
        
        # Initial request
        initial_events, initial_request = await client.send_message(
            "Create a hello world app",
            auth_token=auth_token
        )
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


async def test_session_with_no_state():
    """Test session behavior when no state is provided in continuation requests."""
    async with AgentApiClient() as client:
        # Explicitly use the environment token
        auth_token = os.environ.get("BUILDER_TOKEN")
        
        # Generate a fixed trace/chatbot ID to use for all requests
        fixed_trace_id = uuid.uuid4().hex
        fixed_application_id = f"test-bot-{uuid.uuid4().hex[:8]}"

        # First request
        first_events, _ = await client.send_message(
            "Create a counter app",
            application_id=fixed_application_id,
            trace_id=fixed_trace_id,
            auth_token=auth_token
        )
        assert len(first_events) > 0, "No events received from first request"

        # Second request - same session, explicitly pass None for agent_state
        second_events, _ = await client.send_message(
            "Add a reset button",
            application_id=fixed_application_id,
            trace_id=fixed_trace_id,
            agent_state=None,
            auth_token=auth_token
        )
        assert len(second_events) > 0, "No events received from second request"

        # Verify each event has the expected trace ID
        for event in first_events + second_events:
            assert event.trace_id == fixed_trace_id, f"Trace ID mismatch: {event.trace_id} != {fixed_trace_id}"


async def test_agent_reaches_idle_state():
    """Test that the agent eventually transitions to IDLE state after processing a simple prompt."""
    async with AgentApiClient() as client:
        # Explicitly use the environment token
        auth_token = os.environ.get("BUILDER_TOKEN")
        
        # Send a simple "Hello" prompt
        events, _ = await client.send_message("Hello", auth_token=auth_token)

        # Check that we received some events
        assert len(events) > 0, "No events received"

        # Verify the final event has IDLE status
        final_event = events[-1]
        assert final_event.status == AgentStatus.IDLE, "Agent did not reach IDLE state"

        # Additional checks that may be useful
        assert final_event.message is not None, "Final event has no message"
        assert final_event.message.role == "agent", "Final message role is not 'agent'"


@pytest.mark.skipif(os.getenv("TEST_EXTERNAL_SERVER") != "true", reason="Set TEST_EXTERNAL_SERVER=true to run tests against an external server")
async def test_external_server_health():
    """Test the health endpoint of an external server."""
    external_server_url = os.getenv("EXTERNAL_SERVER_URL", "http://localhost")

    async with AsyncClient(base_url=external_server_url) as client:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

@pytest.mark.skipif(os.getenv("TEST_EXTERNAL_SERVER") != "true", reason="Set TEST_EXTERNAL_SERVER=true to run tests against an external server")
async def test_external_server_message():
    """Test the message endpoint of an external server."""
    external_server_url = os.getenv("EXTERNAL_SERVER_URL", "http://localhost")

    async with AgentApiClient(base_url=external_server_url) as client:
        try:
            # Use a simple prompt that should be processed quickly
            events, request = await client.send_message("Hello, world")

            # Check that we received some events
            assert len(events) > 0, "No SSE events received"

            # Verify the final event has IDLE status
            final_event = events[-1]
            assert final_event.status == AgentStatus.IDLE, "Agent did not reach IDLE state"

            print(f"Successfully tested external server at {external_server_url}")
        except Exception as e:
            pytest.fail(f"Error testing external server: {e}")


async def run_chatbot_client(host: str, port: int, state_file: str, settings: str) -> None:
    """
    Async interactive Agent CLI chat.
    """
    import json
    from datetime import datetime

    # Prepare state and settings
    state_file = os.path.expanduser(state_file)
    settings_dict = json.loads(settings)
    previous_events: List[AgentSseEvent] = []
    previous_messages: List[str] = []
    request = None

    # Load saved state if available
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                saved = json.load(f)
                previous_events = [
                    AgentSseEvent.model_validate(e) for e in saved.get("events", [])
                ]
                previous_messages = saved.get("messages", [])
                print(f"Loaded conversation with {len(previous_messages)} messages")
        except Exception as e:
            print(f"Warning: could not load state: {e}")

    # Banner
    divider = "=" * 60
    print(divider)
    print("Interactive Agent CLI Chat")
    print("Type '/help' for commands.")
    print(divider)

    if host:
        base_url = f"http://{host}:{port}"
        print(f"Connected to {base_url}")
    else:
        base_url = None # Use ASGI transport for local testing
    async with AgentApiClient(base_url=base_url) as client:
        while True:
            try:
                ui = input("\033[94mYou> \033[0m")
            except (EOFError, KeyboardInterrupt):
                print("\nExiting…")
                return

            cmd = ui.strip()
            if not cmd:
                continue
            action, *rest = cmd.split(None, 1)
            match action.lower():
                case "/exit" | "/quit":
                    print("Goodbye!")
                    return
                case "/help":
                    print(
                        "Commands:\n"
                        "/help       Show this help\n"
                        "/exit, /quit Exit chat\n"
                        "/clear      Clear conversation\n"
                        "/save       Save state to file"
                    )
                    continue
                case "/clear":
                    previous_events.clear()
                    previous_messages.clear()
                    request = None
                    print("Conversation cleared.")
                    continue
                case "/save":
                    with open(state_file, "w") as f:
                        json.dump({
                            "events": [e.model_dump() for e in previous_events],
                            "messages": previous_messages,
                            "agent_state": request.agent_state if request else None,
                            "timestamp": datetime.now().isoformat()
                        }, f, indent=2)
                    print(f"State saved to {state_file}")
                    continue
                case _:
                    content = cmd

            # Send or continue conversation
            try:
                print("\033[92mBot> \033[0m", end="", flush=True)
                auth_token = os.environ.get("BUILDER_TOKEN")
                if request is None:
                    events, request = await client.send_message(content, settings=settings_dict, auth_token=auth_token)
                else:
                    events, request = await client.continue_conversation(
                        previous_events, request, content, settings=settings_dict
                    )

                for evt in events:
                    if evt.message and evt.message.content:
                        print(evt.message.content, end="", flush=True)
                print()

                previous_messages.append(content)
                previous_events.extend(events)

                # Auto-save
                with open(state_file, "w") as f:
                    json.dump({
                        "events": [e.model_dump() for e in previous_events],
                        "messages": previous_messages,
                        "agent_state": request.agent_state,
                        "timestamp": datetime.now().isoformat()
                    }, f, indent=2)
            except Exception as e:
                print(f"Error: {e}")
                traceback.print_exc()

def cli(host: str = "",
        port: int = 8001,
        state_file: str = "/tmp/agent_chat_state.json",
        settings: str = "{}"):
    anyio.run(run_chatbot_client, host, port, state_file, settings, backend="asyncio")

if __name__ == "__main__":
    from fire import Fire
    Fire(cli)
