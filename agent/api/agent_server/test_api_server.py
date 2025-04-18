import pytest
from httpx import AsyncClient
import os
from log import get_logger
from api.agent_server.agent_api_client import AgentApiClient

logger = get_logger(__name__)

pytestmark = pytest.mark.anyio

@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def empty_token(monkeypatch):
    monkeypatch.delenv("BUILDER_TOKEN")
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


async def test_empty_token():
    async with AgentApiClient() as client:
        with pytest.raises(ValueError, match="Request failed with status code 401"):
            await client.send_message("Hello", auth_token=None)


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
            assert final_event.status == "IDLE", "Agent did not reach IDLE state"

            print(f"Successfully tested external server at {external_server_url}")
        except Exception as e:
            pytest.fail(f"Error testing external server: {e}")
