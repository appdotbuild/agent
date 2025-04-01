"""
Agent Server API Client

This module provides a client for the Agent Server API,
making it easy to interact with the API from other applications.
"""

import json
import uuid
import asyncio
import aiohttp
from typing import Dict, List, Any, Optional, AsyncGenerator, Callable, Awaitable

from .models import AgentSseEvent, AgentStatus, MessageKind


class AgentServerClient:
    """Client for the Agent Server API."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Initialize the client.
        
        Args:
            base_url: Base URL of the Agent Server API
        """
        self.base_url = base_url.rstrip("/")
        self.message_url = f"{self.base_url}/agent/message"
    
    async def send_message(
        self,
        messages: List[str],
        chatbot_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        agent_state: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
        callback: Optional[Callable[[AgentSseEvent], Awaitable[None]]] = None
    ) -> AsyncGenerator[AgentSseEvent, None]:
        """
        Send a message to the Agent Server and stream the response.
        
        Args:
            messages: List of messages to send
            chatbot_id: Optional chatbot ID (default: auto-generated)
            trace_id: Optional trace ID (default: auto-generated)
            agent_state: Optional agent state (default: None)
            settings: Optional settings (default: {"max-iterations": 3})
            callback: Optional callback function to process each event
            
        Yields:
            SSE events from the Agent Server
        """
        if not chatbot_id:
            chatbot_id = f"client-{uuid.uuid4().hex[:8]}"
        
        if not trace_id:
            trace_id = uuid.uuid4().hex
        
        if not settings:
            settings = {"max-iterations": 3}
        
        request_data = {
            "allMessages": messages,
            "chatbotId": chatbot_id,
            "traceId": trace_id,
        }
        
        if agent_state is not None:
            request_data["agentState"] = agent_state
        
        if settings is not None:
            request_data["settings"] = settings
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.message_url,
                json=request_data,
                headers={"Accept": "text/event-stream"}
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise ValueError(f"Error {response.status}: {error_text}")
                
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
                                sse_event = AgentSseEvent.parse_obj(event_json)
                                
                                # Call callback if provided
                                if callback:
                                    await callback(sse_event)
                                
                                yield sse_event
                                
                            except json.JSONDecodeError:
                                raise ValueError(f"Invalid JSON in event: {event_data}")
                        
                        buffer = ""


class AgentServerSession:
    """
    A session for interacting with the Agent Server API.
    
    This class maintains state between requests, making it easy
    to have a conversation with the agent.
    """
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Initialize the session.
        
        Args:
            base_url: Base URL of the Agent Server API
        """
        self.client = AgentServerClient(base_url)
        self.chatbot_id = f"session-{uuid.uuid4().hex[:8]}"
        self.trace_id = uuid.uuid4().hex
        self.agent_state = None
        self.messages = []
        self.settings = {"max-iterations": 3}
    
    async def send_message(
        self,
        message: str,
        callback: Optional[Callable[[AgentSseEvent], Awaitable[None]]] = None
    ) -> List[AgentSseEvent]:
        """
        Send a message to the Agent Server and get the response.
        
        This method adds the message to the conversation history
        and maintains the session state.
        
        Args:
            message: Message to send
            callback: Optional callback function to process each event
            
        Returns:
            List of SSE events from the Agent Server
        """
        # Add message to history
        self.messages.append(message)
        
        # Generate new trace ID for each request
        self.trace_id = uuid.uuid4().hex
        
        # Send request
        events = []
        
        async for event in self.client.send_message(
            messages=self.messages,
            chatbot_id=self.chatbot_id,
            trace_id=self.trace_id,
            agent_state=self.agent_state,
            settings=self.settings,
            callback=callback
        ):
            events.append(event)
            
            # Update agent state
            self.agent_state = event.message.agent_state
        
        return events


async def example_usage():
    """Example usage of the client."""
    # Simple usage
    client = AgentServerClient()
    
    messages = ["Build me an app to plan my meals"]
    
    print("Sending request...")
    async for event in client.send_message(messages=messages):
        print(f"Event: {event.status} - {event.message.kind}")
        print(f"Content: {event.message.content[:100]}...")
        print("-" * 40)
    
    # Session usage
    session = AgentServerSession()
    
    # Callback to process events
    async def event_callback(event: AgentSseEvent):
        print(f"Callback received event: {event.status} - {event.message.kind}")
    
    print("\nStarting session...")
    events = await session.send_message("Build me an app to plan my meals", callback=event_callback)
    
    # Continue conversation
    if events[-1].status == AgentStatus.IDLE and events[-1].message.kind == MessageKind.FEEDBACK_RESPONSE:
        print("\nContinuing conversation...")
        events = await session.send_message("Yes, include dietary restrictions", callback=event_callback)


if __name__ == "__main__":
    asyncio.run(example_usage())