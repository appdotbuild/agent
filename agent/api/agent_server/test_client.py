import asyncio
import json
import uuid
import aiohttp
import argparse
from typing import Dict, Any, List, Optional

async def test_message_endpoint(
    server_url: str,
    messages: List[str],
    chatbot_id: Optional[str] = None,
    agent_state: Optional[Dict[str, Any]] = None,
    settings: Optional[Dict[str, Any]] = None
):
    """Test the SSE /message endpoint."""
    if not chatbot_id:
        chatbot_id = f"test-bot-{uuid.uuid4().hex[:8]}"
    
    trace_id = uuid.uuid4().hex
    
    request_data = {
        "allMessages": messages,
        "chatbotId": chatbot_id,
        "traceId": trace_id,
    }
    
    if agent_state:
        request_data["agentState"] = agent_state
    
    if settings:
        request_data["settings"] = settings
    
    print(f"Sending request to {server_url}/message:")
    print(json.dumps(request_data, indent=2))
    print("\nReceiving SSE events:")
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{server_url}/message",
            json=request_data,
            headers={"Accept": "text/event-stream"}
        ) as response:
            if response.status != 200:
                error_text = await response.text()
                print(f"Error {response.status}: {error_text}")
                return
            
            # Process SSE stream
            buffer = ""
            async for line in response.content:
                line = line.decode('utf-8')
                buffer += line
                
                if buffer.endswith('\n\n'):
                    # Process complete event
                    event_data = None
                    for part in buffer.split('\n'):
                        if part.startswith('data: '):
                            event_data = part[6:]  # Remove 'data: ' prefix
                    
                    if event_data:
                        try:
                            event_json = json.loads(event_data)
                            print(f"Event received:")
                            print(json.dumps(event_json, indent=2))
                            print("-" * 40)
                            
                            # For the last event (idle), extract the agent state
                            if event_json.get("status") == "idle":
                                agent_state = event_json.get("message", {}).get("agentState")
                                if agent_state:
                                    print("\nFinal agent state for next request:")
                                    print(f"Agent state size: {len(json.dumps(agent_state))} bytes")
                        except json.JSONDecodeError:
                            print(f"Invalid JSON in event: {event_data}")
                    
                    buffer = ""

async def main():
    parser = argparse.ArgumentParser(description="Test the Agent Server API")
    parser.add_argument("--url", default="http://localhost:8000", help="Server URL")
    parser.add_argument("--message", required=True, help="Message to send")
    parser.add_argument("--chatbot-id", help="Chatbot ID (default: auto-generated)")
    parser.add_argument("--max-iterations", type=int, default=3, help="Maximum iterations")
    
    args = parser.parse_args()
    
    settings = {
        "max-iterations": args.max_iterations
    }
    
    await test_message_endpoint(
        server_url=args.url,
        messages=[args.message],
        chatbot_id=args.chatbot_id,
        settings=settings
    )

if __name__ == "__main__":
    asyncio.run(main())