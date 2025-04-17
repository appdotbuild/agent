"""
Reusable client for interacting with the Agent API server.
This module provides a client class for making requests to the Agent API
and parsing the Server-Sent Events (SSE) responses.
"""
import json
import uuid
import os
from typing import List, Dict, Any, Tuple, Optional

from httpx import AsyncClient, ASGITransport

from api.agent_server.models import AgentSseEvent, AgentRequest, UserMessage


class AgentApiClient:
    """Reusable client for interacting with the Agent API server"""

    def __init__(self, app_instance=None, base_url=None):
        """Initialize the client with an optional app instance or base URL

        Args:
            app_instance: FastAPI app instance for direct ASGI transport
            base_url: External base URL to test against (e.g., "http://18.237.53.81")
        """
        self.app = app_instance or None
        self.base_url = base_url
        self.transport = ASGITransport(app=self.app) if base_url is None and app_instance is not None else None
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
                          settings: Optional[Dict[str, Any]] = None,
                          auth_token: Optional[str] = None) -> Tuple[List[AgentSseEvent], AgentRequest]:

        """Send a message to the agent and return the parsed SSE events"""
        request = self.create_request(message, application_id, trace_id, agent_state, settings)

        url = "/message" if self.base_url or self.transport else os.getenv("EXTERNAL_SERVER_URL", "http://localhost:8001") + "/message"
        headers={"Accept": "text/event-stream"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"

        response = await self.client.post(
            url,
            json=request.model_dump(by_alias=True),
            headers=headers,
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

        for event in reversed(previous_events):
            if event.message and event.message.agent_state:
                agent_state = event.message.agent_state
                break

        if agent_state is None:
            agent_state = {"test_state": True, "generated_in_test": True}

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
                            event_obj = AgentSseEvent.from_json(data_str)
                            event_objects.append(event_obj)
                        except json.JSONDecodeError as e:
                            print(f"JSON decode error: {e}, data: {data_str[:100]}...")
                        except Exception as e:
                            print(f"Error parsing SSE event: {e}, data: {data_str[:100]}...")
                buffer = ""

        return event_objects
