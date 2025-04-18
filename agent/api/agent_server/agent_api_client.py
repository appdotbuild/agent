import json
import uuid
import anyio
from httpx import AsyncClient, ASGITransport
import os
import traceback
from typing import List, Dict, Any, Tuple, Optional
from log import get_logger
from api.agent_server.async_server import app, CONFIG
from api.agent_server.models import AgentSseEvent, AgentRequest, UserMessage


logger = get_logger(__name__)

if os.getenv("BUILDER_TOKEN") is None:
    os.environ["BUILDER_TOKEN"] = "dummy_token"


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
                          auth_token: Optional[str] = CONFIG.builder_token) -> Tuple[List[AgentSseEvent], AgentRequest]:

        """Send a message to the agent and return the parsed SSE events"""

        if request is None:
            request = self.create_request(message, application_id, trace_id, agent_state, settings)
        else:
            logger.info(f"Using existing request with trace ID: {request.trace_id}, ignoring the message parameter")

        # Use the base_url if provided, otherwise use the EXTERNAL_SERVER_URL env var or fallback to test URL
        url = "/message" if self.base_url else os.getenv("EXTERNAL_SERVER_URL", "http://test") + "/message"
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


async def run_chatbot_client(host: str, port: int, state_file: str, autosave=False) -> None:
    """
    Async interactive Agent CLI chat.
    """
    import json
    from datetime import datetime

    # Prepare state and settings
    state_file = os.path.expanduser(state_file)
    previous_events: List[AgentSseEvent] = []
    previous_messages: List[str] = []
    request = None

    # Load saved state if available
    if os.path.exists(state_file):
        try:
            with open(state_file, "r") as f:
                saved = json.load(f)
                previous_events = [
                    AgentSseEvent.model_validate(e) for e in saved.get("events", [])
                ]
                previous_messages = saved.get("messages", [])
                print(f"Loaded conversation with {len(previous_messages)} messages")
        except Exception as e:
            print(f"Warning: could not load state: {e}")

    # Banner
    divider = "=" * 60
    print(divider)
    print("Interactive Agent CLI Chat")
    print("Type '/help' for commands.")
    print(divider)

    if host:
        base_url = f"http://{host}:{port}"
        print(f"Connected to {base_url}")
    else:
        base_url = None # Use ASGI transport for local testing
    async with AgentApiClient(base_url=base_url) as client:
        while True:
            try:
                ui = input("\033[94mYou> \033[0m")
                if ui.startswith("+"):
                    ui = "A simple greeting app that says hello in five languages and stores history of greetings"
            except (EOFError, KeyboardInterrupt):
                print("\nExiting…")
                return

            cmd = ui.strip()
            if not cmd:
                continue
            action, *rest = cmd.split(None, 1)
            match action.lower():
                case "/exit" | "/quit":
                    print("Goodbye!")
                    return
                case "/help":
                    print(
                        "Commands:\n"
                        "/help       Show this help\n"
                        "/exit, /quit Exit chat\n"
                        "/clear      Clear conversation\n"
                        "/save       Save state to file"
                    )
                    continue
                case "/clear":
                    previous_events.clear()
                    previous_messages.clear()
                    request = None
                    print("Conversation cleared.")
                    continue
                case "/save":
                    with open(state_file, "w") as f:
                        json.dump({
                            "events": [e.model_dump() for e in previous_events],
                            "messages": previous_messages,
                            "agent_state": request.agent_state if request else None,
                            "timestamp": datetime.now().isoformat()
                        }, f, indent=2)
                    print(f"State saved to {state_file}")
                    continue
                case _:
                    content = cmd

            # Send or continue conversation
            try:
                print("\033[92mBot> \033[0m", end="", flush=True)
                if request is None:
                    logger.warning("Sending new message")
                    events, request = await client.send_message(content)
                else:
                    logger.warning("Sending continuation")
                    events, request = await client.continue_conversation(previous_events, request, content)

                for evt in events:
                    if evt.message and evt.message.content:
                        print(evt.message.content, end="", flush=True)
                print()

                previous_messages.append(content)
                previous_events.extend(events)

                if autosave:
                    with open(state_file, "w") as f:
                        json.dump({
                            "events": [e.model_dump() for e in previous_events],
                            "messages": previous_messages,
                            "agent_state": request.agent_state,
                            "timestamp": datetime.now().isoformat()
                        }, f, indent=2)
            except Exception as e:
                print(f"Error: {e}")
                traceback.print_exc()

def cli(host: str = "",
        port: int = 8001,
        state_file: str = "/tmp/agent_chat_state.json",
        ):
    anyio.run(run_chatbot_client, host, port, state_file, backend="asyncio")

if __name__ == "__main__":
    from fire import Fire
    Fire(cli)