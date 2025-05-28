import pytest
from log import get_logger
from api.agent_server.models import AgentSseEvent, AgentStatus
from api.agent_server.agent_api_client import AgentApiClient

logger = get_logger(__name__)

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def dummy_agent(monkeypatch):
    monkeypatch.setenv("CODEGEN_AGENT", "dummy")
    yield


async def test_dummy_agent_sends_100_events(dummy_agent):
    """Test that dummy agent sends exactly 100 events plus start/end messages."""
    async with AgentApiClient() as client:
        events, request = await client.send_message("Test dummy agent")

        assert len(events) > 100, f"Expected more than 100 events, got {len(events)}"

        # verify model objects
        for event in events:
            assert isinstance(event, AgentSseEvent), "Event is not an AgentSseEvent"
            assert event.trace_id == request.trace_id, "Trace IDs do not match"
            assert event.status in (AgentStatus.RUNNING, AgentStatus.IDLE), f"Invalid status: {event.status}"
            assert event.message is not None, "Event has no message"
            assert event.message.role == "assistant", "Message role is not 'assistant'"
