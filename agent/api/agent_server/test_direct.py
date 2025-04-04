
import asyncio
import json
import uuid
import pytest
from httpx import AsyncClient, ASGITransport

from api.agent_server.server import app

# A helper function to simulate a user message request.
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
            "/message",
            json=test_request,
            headers={"Accept": "text/event-stream"},
            timeout=None  # Disable timeout to allow for streaming events
        )
        breakpoint()
        # Verify that the response status code is 200
        assert response.status_code == 200

        # The response is a streaming response. We iterate over the streamed text lines.
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

        # Assert that at least one event was received.
        assert len(events) > 0, "No SSE events received"

        # Verify that the received events contain the expected fields.
        for event in events:
            # The helper _get_agent_state_by_messages in the server puts "traceId" into the payload
            assert "traceId" in event, "Missing traceId in SSE payload"
            # For our test, we expect the traceId to match the one we sent
            assert event["traceId"] == test_request["traceId"], "Trace IDs do not match"



# Simple main so you can also run the test manually if desired.
if __name__ == "__main__":
    asyncio.run(test_agent_message_endpoint())
