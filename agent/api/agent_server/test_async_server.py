import json
import uuid
import pytest
import anyio
from httpx import AsyncClient, ASGITransport
import os
from typing import List, Dict, Any, Tuple, Optional

from api.agent_server.async_server import app
from api.agent_server.models import AgentSseEvent, AgentRequest, UserMessage, AgentStatus, MessageKind

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return 'asyncio'

@pytest.fixture(params=["empty_diff", "trpc_agent"])
def agent_type(request, monkeypatch):
    previous_value = os.environ.get("CODEGEN_AGENT")
    monkeypatch.setenv("CODEGEN_AGENT", request.param)
    yield request.param
    if previous_value is not None:
        monkeypatch.setenv("CODEGEN_AGENT", previous_value)
    else:
        monkeypatch.delenv("CODEGEN_AGENT", raising=False)

class AgentApiClient:
    """Reusable client for interacting with the Agent API server"""

    def __init__(self, app_instance=None, base_url=None):
        """Initialize the client with an optional app instance or base URL

        Args:
            app_instance: FastAPI app instance for direct ASGI transport
            base_url: External base URL to test against (e.g., "http://18.237.53.81")
        """
        self.app = app_instance or app
        self.base_url = base_url
        self.transport = ASGITransport(app=self.app) if base_url is None else None
        self.client = None

    async def __aenter__(self):
        if self.base_url:
            self.client = AsyncClient(base_url=self.base_url)
        else:
            self.client = AsyncClient(transport=self.transport)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def send_message(self,
                          message: str,
                          application_id: Optional[str] = None,
                          trace_id: Optional[str] = None,
                          agent_state: Optional[Dict[str, Any]] = None,
                          settings: Optional[Dict[str, Any]] = None) -> Tuple[List[AgentSseEvent], AgentRequest]:
        """Send a message to the agent and return the parsed SSE events"""
        request = self.create_request(message, application_id, trace_id, agent_state, settings)

        # Use the base_url if provided, otherwise use the EXTERNAL_SERVER_URL env var or fallback to test URL
        url = "/message" if self.base_url else os.getenv("EXTERNAL_SERVER_URL", "http://test") + "/message"

        response = await self.client.post(
            url,
            json=request.model_dump(by_alias=True),
            headers={"Accept": "text/event-stream"},
            timeout=None
        )

        if response.status_code != 200:
            raise ValueError(f"Request failed with status code {response.status_code}")

        events = await self.parse_sse_events(response)
        return events, request

    async def continue_conversation(self,
                                  previous_events: List[AgentSseEvent],
                                  previous_request: AgentRequest,
                                  message: str,
                                  settings: Optional[Dict[str, Any]] = None) -> Tuple[List[AgentSseEvent], AgentRequest]:
        """Continue a conversation using the agent state from previous events"""
        agent_state = None

        # Extract agent state from the last event
        for event in reversed(previous_events):
            if event.message and event.message.agent_state:
                agent_state = event.message.agent_state
                break

        # If no state was found, use a dummy state
        if agent_state is None:
            agent_state = {"test_state": True, "generated_in_test": True}

        # Use the same trace ID for continuity
        trace_id = previous_request.trace_id
        application_id = previous_request.application_id

        events, request = await self.send_message(
            message=message,
            application_id=application_id,
            trace_id=trace_id,
            agent_state=agent_state,
            settings=settings
        )

        return events, request

    @staticmethod
    def create_request(message: str,
                     application_id: Optional[str] = None,
                     trace_id: Optional[str] = None,
                     agent_state: Optional[Dict[str, Any]] = None,
                     settings: Optional[Dict[str, Any]] = None) -> AgentRequest:
        """Create a request object for the agent API"""
        return AgentRequest(
            allMessages=[
                UserMessage(
                    role="user",
                    content=message
                )
            ],
            applicationId=application_id or f"test-bot-{uuid.uuid4().hex[:8]}",
            traceId=trace_id or uuid.uuid4().hex,
            agentState=agent_state,
            settings=settings or {"max-iterations": 3}
        )

    @staticmethod
    async def parse_sse_events(response) -> List[AgentSseEvent]:
        """Parse the SSE events from a response stream"""
        event_objects = []
        buffer = ""

        async for line in response.aiter_lines():
            buffer += line
            if line.strip() == "":  # End of SSE event marked by empty line
                if buffer.startswith("data:"):
                    data_parts = buffer.split("data:", 1)
                    if len(data_parts) > 1:
                        data_str = data_parts[1].strip()
                        try:
                            # Parse as both raw JSON and model objects
                            event_json = json.loads(data_str)
                            event_obj = AgentSseEvent.from_json(data_str)
                            event_objects.append(event_obj)
                        except json.JSONDecodeError as e:
                            print(f"JSON decode error: {e}, data: {data_str[:100]}...")
                        except Exception as e:
                            print(f"Error parsing SSE event: {e}, data: {data_str[:100]}...")
                # Reset buffer for next event
                buffer = ""

        return event_objects


async def test_async_agent_message_endpoint(agent_type):
    """Test the message endpoint with different agent types."""
    async with AgentApiClient() as client:
        events, request = await client.send_message("Implement a calculator app")

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
        # Initial request
        initial_events, initial_request = await client.send_message("Create a todo app")
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


async def test_session_with_no_state():
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


async def test_agent_reaches_idle_state():
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
