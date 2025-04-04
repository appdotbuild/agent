import asyncio
import json
import uuid
import pytest
from httpx import AsyncClient, ASGITransport

from api.agent_server.server import app

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


@pytest.mark.asyncio
async def test_agent_message_endpoint():
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
            # SSE lines can be empty or have the "data:" prefix.
            # We only care about lines starting with "data:".
            if line.startswith("data:"):
                # Remove the "data:" and any leading whitespace
                data_str = line.split("data:", 1)[1].strip()
                try:
                    event_json = json.loads(data_str)
                    events.append(event_json)
                except json.JSONDecodeError:
                    # Skip lines that are not valid JSON
                    continue

        assert len(events) > 0, "No SSE events received"
        print(f"Received {len(events)} events")

        for event in events:
            assert "traceId" in event, "Missing traceId in SSE payload"
            assert event["traceId"] == test_request["traceId"], "Trace IDs do not match"

        response = await client.post(
            "http://test/message",
            json=create_test_request("make me an app that tracks my lunches"),
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 200

        events = []
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                data_str = line.split("data:", 1)[1].strip()
                try:
                    event_json = json.loads(data_str)
                    events.append(event_json)
                except json.JSONDecodeError:
                    continue

        assert len(events) > 0, "No SSE events received"
        print(f"Received {len(events)} events")


if __name__ == "__main__":
    asyncio.run(test_agent_message_endpoint())
