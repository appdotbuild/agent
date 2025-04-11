import asyncio
import json
import uuid
from typing import List, Dict, Any, Tuple, Optional

from httpx import AsyncClient, ASGITransport

from api.agent_server.async_server import app
from api.agent_server.models import AgentSseEvent, AgentRequest, UserMessage


class AgentApiClient:
    """Reusable client for interacting with the Agent API server"""

    def __init__(self, app_instance=None):
        """Initialize the client with an optional app instance"""
        self.app = app_instance or app
        self.transport = ASGITransport(app=self.app)
        self.client = None

    async def __aenter__(self):
        self.client = AsyncClient(transport=self.transport)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def send_message(self,
                          message: str,
                          chatbot_id: Optional[str] = None,
                          trace_id: Optional[str] = None,
                          agent_state: Optional[Dict[str, Any]] = None,
                          settings: Optional[Dict[str, Any]] = None) -> Tuple[Tuple[List[AgentSseEvent], List[Dict[str, Any]]], AgentRequest]:
        """Send a message to the agent and return the parsed SSE events"""
        request = self.create_request(message, chatbot_id, trace_id, agent_state, settings)

        response = await self.client.post(
            "http://test/message",
            json=request.model_dump(by_alias=True),
            headers={"Accept": "text/event-stream"},
            timeout=None
        )

        if response.status_code != 200:
            raise ValueError(f"Request failed with status code {response.status_code}")

        events, event_dicts = await self.parse_sse_events(response)
        return (events, event_dicts), request

    async def continue_conversation(self,
                                  previous_events: List[AgentSseEvent],
                                  previous_request: AgentRequest,
                                  message: str,
                                  settings: Optional[Dict[str, Any]] = None) -> Tuple[Tuple[List[AgentSseEvent], List[Dict[str, Any]]], AgentRequest]:
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
        chatbot_id = previous_request.chatbot_id

        return await self.send_message(
            message=message,
            chatbot_id=chatbot_id,
            trace_id=trace_id,
            agent_state=agent_state,
            settings=settings
        )

    @staticmethod
    def create_request(message: str,
                     chatbot_id: Optional[str] = None,
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
            chatbotId=chatbot_id or f"test-bot-{uuid.uuid4().hex[:8]}",
            traceId=trace_id or uuid.uuid4().hex,
            agentState=agent_state,
            settings=settings or {"max-iterations": 3}
        )

    @staticmethod
    async def parse_sse_events(response) -> Tuple[List[AgentSseEvent], List[Dict[str, Any]]]:
        """Parse the SSE events from a response stream"""
        event_objects = []
        event_dicts = []
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
                            event_dicts.append(event_json)
                            event_obj = AgentSseEvent.from_json(data_str)
                            event_objects.append(event_obj)
                        except json.JSONDecodeError as e:
                            print(f"JSON decode error: {e}, data: {data_str[:100]}...")
                        except Exception as e:
                            print(f"Error parsing SSE event: {e}, data: {data_str[:100]}...")
                # Reset buffer for next event
                buffer = ""

        return event_objects, event_dicts 