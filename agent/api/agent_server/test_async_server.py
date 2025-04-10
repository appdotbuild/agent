import asyncio
import json
import uuid
import pytest
from httpx import AsyncClient, ASGITransport
import os

from api.agent_server.async_server import app

def create_test_request(message: str) -> dict:
    return {
        "allMessages": [
            {
                "role": "user",
                "content": message
            }
        ],
        "chatbotId": f"test-bot-{uuid.uuid4().hex[:8]}",
        "traceId": uuid.uuid4().hex,
        "settings": {"max-iterations": 3}
    }


@pytest.mark.skipif(os.getenv("TEST_ASYNC_AGENT_SERVER") != "true", reason="Skipping async agent server test")
@pytest.mark.asyncio
async def test_async_agent_message_endpoint():
    test_request = create_test_request("hello")

    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport) as client:
        # Post the test request to the /message endpoint expecting an SSE stream.
        response = await client.post(
            "http://test/message",
            json=test_request,
            headers={"Accept": "text/event-stream"},
            timeout=None  # Disable timeout to allow for streaming events
        )
        assert response.status_code == 200
        events = []
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                # Remove the "data:" and any leading whitespace
                data_str = line.split("data:", 1)[1].strip()
                try:
                    event_json = json.loads(data_str)
                    events.append(event_json)
                except json.JSONDecodeError:
                    # Skip lines that are not valid JSON
                    continue

        assert len(events), "No SSE events received"
        for event in events:
            assert "traceId" in event, "Missing traceId in SSE payload"
            assert event["traceId"] == test_request["traceId"], "Trace IDs do not match"

        # FixMe: add test for restoring state and continuing the conversation


if __name__ == "__main__":
    asyncio.run(test_async_agent_message_endpoint())
