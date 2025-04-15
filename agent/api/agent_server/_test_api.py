#!/usr/bin/env python3
"""
Test script for the Agent Server API.

This script sends a test request to the Agent Server API
and streams the SSE response.
"""

import asyncio
import aiohttp
import argparse
import json
import uuid
import sys
import os
from typing import Dict, Any, List, Optional

# Add parent directory to path to enable imports
parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(parent_dir)

async def test_message_endpoint(
    server_url: str,
    messages: List[str],
    application_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    agent_state: Optional[Dict[str, Any]] = None,
    settings: Optional[Dict[str, Any]] = None,
    verbose: bool = False,
):
    """Test the SSE /message endpoint."""
    if not application_id:
        application_id = f"test-bot-{uuid.uuid4().hex[:8]}"
    
    if not trace_id:
        trace_id = uuid.uuid4().hex
    
    formatted_messages = [{
        "role": "user",
        "content": msg
    } for msg in messages]
    
    request_data = {
        "allMessages": formatted_messages,
        "applicationId": application_id,
        "traceId": trace_id,
    }
    
    if agent_state:
        request_data["agentState"] = agent_state
    
    if settings:
        request_data["settings"] = settings
    
    print(f"Sending request to {server_url}:")
    print(json.dumps(request_data, indent=2))
    print("\nReceiving SSE events:")
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                server_url,
                json=request_data,
                headers={"Accept": "text/event-stream"},
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    print(f"Error {response.status}: {error_text}")
                    return None
                
                buffer = ""
                last_agent_state = None
                
                try:
                    async for line in response.content:
                        line = line.decode('utf-8')
                        buffer += line
                        
                        if buffer.endswith('\n\n'):
                            event_data = None
                            for part in buffer.split('\n'):
                                if part.startswith('data: '):
                                    event_data = part[6:]  # Remove 'data: ' prefix
                            
                            if event_data:
                                try:
                                    event_json = json.loads(event_data)
                                    print(f"Event received:")
                                    
                                    if verbose:
                                        print(json.dumps(event_json, indent=2))
                                    else:
                                        # Print a simplified version
                                        # Parse the event using the models from models.py
                                        from models import AgentSseEvent
                                        
                                        event = AgentSseEvent.from_json(event_data)
                                        status = event.status
                                        message = event.message
                                        kind = message.kind
                                        content = message.content
                                        diff = message.unified_diff
                                        
                                        if content and len(content) > 1000:
                                            content = content[:997] + "..."
                                        
                                        print(f"Status: {status}, Kind: {kind}")
                                        print(f"Content: {content}")
                                        print(f"Diff: {diff} (type: {type(diff).__name__})")
                                    
                                    print("-" * 40)
                                    
                                    last_agent_state = event.message.agent_state
                                    
                                except json.JSONDecodeError:
                                    print(f"Invalid JSON in event: {event_data}")
                            
                            buffer = ""
                except asyncio.TimeoutError:
                    print("Connection timed out while receiving events")
                except Exception as e:
                    print(f"Error receiving events: {str(e)}")
                
                return {
                    "application_id": application_id,
                    "trace_id": trace_id,
                    "agentState": last_agent_state
                }
        except aiohttp.ClientError as e:
            print(f"Connection error: {str(e)}")
            return None

async def interactive_session(server_url: str):
    """Run an interactive session with the Agent Server API."""
    print("Starting an interactive session with the Agent Server API")
    print("Enter messages one at a time. Type 'exit' to quit.")
    
    # Initial state
    state = None
    message = input("> ")
    
    while message.lower() != "exit":
        if state is None:
            # First message
            state = await test_message_endpoint(
                server_url=server_url,
                messages=[message],
                settings={"max-iterations": 3},
                verbose=False
            )
        else:
            # Continue conversation
            state = await test_message_endpoint(
                server_url=server_url,
                messages=[message],
                application_id=state["application_id"],
                trace_id=state["trace_id"],
                agent_state=state["agentState"],
                settings={"max-iterations": 3},
                verbose=False
            )
        
        # Get next message
        message = input("> ")

async def main():
    parser = argparse.ArgumentParser(description="Test the Agent Server API")
    parser.add_argument("--url", default="http://localhost:8000/message", help="Server URL")
    parser.add_argument("--message", help="Message to send")
    parser.add_argument("--application-id", help="Application ID (default: auto-generated)")
    parser.add_argument("--trace-id", help="Trace ID (default: auto-generated)")
    parser.add_argument("--max-iterations", type=int, default=3, help="Maximum iterations")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    
    args = parser.parse_args()
    
    settings = {
        "max-iterations": args.max_iterations
    }
    
    if args.interactive:
        await interactive_session(args.url)
    else:
        if not args.message:
            print("Error: --message is required when not in interactive mode")
            parser.print_help()
            return
            
        await test_message_endpoint(
            server_url=args.url,
            messages=[args.message],
            application_id=args.application_id,
            trace_id=args.trace_id,
            settings=settings,
            verbose=args.verbose,
        )

if __name__ == "__main__":
    asyncio.run(main())
