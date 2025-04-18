import json
import uuid
import os
from typing import List, Dict, Any, Tuple, Optional
from httpx import AsyncClient, ASGITransport

from api.agent_server.models import AgentSseEvent, AgentRequest, UserMessage
from api.agent_server.async_server import app, CONFIG
from log import get_logger

logger = get_logger(__name__)

class AgentApiClient:
    """Reusable client for interacting with the Agent API server"""

    def __init__(self, app_instance=None, base_url=None):
        """Initialize the client with an optional app instance or base URL

        Args:
            app_instance: FastAPI app instance for direct ASGI transport
            base_url: External base URL to test against (e.g., "http://18.237.53.81")
        """
        self.app = app_instance or app
        self.base_url = base_url
        self.transport = ASGITransport(app=self.app) if base_url is None else None
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
                          request: Optional[AgentRequest] = None,
                          application_id: Optional[str] = None,
                          trace_id: Optional[str] = None,
                          agent_state: Optional[Dict[str, Any]] = None,
                          settings: Optional[Dict[str, Any]] = None,
                          auth_token: Optional[str] = None) -> Tuple[List[AgentSseEvent], AgentRequest]:

        """Send a message to the agent and return the parsed SSE events"""
        
        # Use builder token from environment or CONFIG if auth_token not explicitly provided
        if auth_token is None:
            auth_token = os.environ.get("BUILDER_TOKEN") or CONFIG.builder_token
            logger.debug(f"Using auth token from environment: {auth_token is not None}")

        if request is None:
            request = self.create_request(message, application_id, trace_id, agent_state, settings)
        else:
            logger.info(f"Using existing request with trace ID: {request.trace_id}, ignoring the message parameter")

        # Use the base_url if provided, otherwise use the EXTERNAL_SERVER_URL env var or fallback to test URL
        url = "/message" if self.base_url else os.getenv("EXTERNAL_SERVER_URL", "http://test") + "/message"
        headers={"Accept": "text/event-stream"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
            logger.debug("Added authorization header")
        else:
            logger.warning("No auth token available for authorization")

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
                            # Parse as both raw JSON and model objects
                            event_obj = AgentSseEvent.from_json(data_str)
                            event_objects.append(event_obj)
                        except json.JSONDecodeError as e:
                            print(f"JSON decode error: {e}, data: {data_str[:100]}...")
                        except Exception as e:
                            print(f"Error parsing SSE event: {e}, data: {data_str[:100]}...")
                # Reset buffer for next event
                buffer = ""

        return event_objects 