import ujson as json
import uuid
from typing import List, Dict, Any, Tuple, Optional, Callable
from httpx import AsyncClient, ASGITransport

from api.agent_server.models import AgentSseEvent, AgentRequest, UserMessage, ConversationMessage, AgentMessage, MessageKind, FileEntry
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
                          messages_history: Optional[List[ConversationMessage]] = None,
                          request: Optional[AgentRequest] = None,
                          application_id: Optional[str] = None,
                          trace_id: Optional[str] = None,
                          agent_state: Optional[Dict[str, Any]] = None,
                          all_files: Optional[List[Dict[str, str]]] = None,
                          settings: Optional[Dict[str, Any]] = None,
                          auth_token: Optional[str] = CONFIG.builder_token,
                          stream_cb: Optional[Callable[[AgentSseEvent], None]] = None
                         ) -> Tuple[List[AgentSseEvent], AgentRequest]:

        """Send a message to the agent and return the parsed SSE events"""

        if request is None:
            request = self.create_request(message, messages_history, application_id, trace_id, agent_state, all_files, settings)
        else:
            logger.info(f"Using existing request with trace ID: {request.trace_id}, ignoring some parameters like message, all_files")
            if all_files is not None:
                request.all_files = [FileEntry(**f) for f in all_files]

        url = self.base_url or "http://test"
        url += "/message"
        headers={"Accept": "text/event-stream"}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
            logger.debug("Added authorization header")
        else:
            logger.info("No auth token available for authorization")

        async with self.client.stream(
            "POST",
            url,
            json=request.model_dump(by_alias=True),
            headers=headers,
            timeout=None
        ) as response:
            if response.status_code != 200:
                await response.aread()
                raise ValueError(f"Request failed with status code {response.status_code}: {response.json()}")
            events = await self.parse_sse_events(response, stream_cb)
        return events, request

    async def continue_conversation(self,
                                  previous_events: List[AgentSseEvent],
                                  previous_request: AgentRequest,
                                  message: str,
                                  all_files: Optional[List[Dict[str, str]]] = None,
                                  settings: Optional[Dict[str, Any]] = None,
                                  stream_cb: Optional[Callable[[AgentSseEvent], None]] = None
                                 ) -> Tuple[List[AgentSseEvent], AgentRequest]:
        """Continue a conversation using the agent state from previous events"""
        agent_state = None
        messages_history_json_str: Optional[str] = None

        for event in reversed(previous_events):
            if event.message:
                agent_state = event.message.agent_state
                if isinstance(event.message.content, str):
                    messages_history_json_str = event.message.content
                break

        messages_history_casted: List[ConversationMessage] = []
        if messages_history_json_str:
            try:
                history_list_raw = json.loads(messages_history_json_str)
                for m_raw in history_list_raw:
                    role = m_raw.get("role")
                    raw_content = m_raw.get("content", "")

                    current_content_str = ""
                    if isinstance(raw_content, str):
                        current_content_str = raw_content
                    elif isinstance(raw_content, list) and len(raw_content) > 0 and isinstance(raw_content[0], dict) and "text" in raw_content[0]:
                        # If content is a list of dicts like [{'text': ..., 'type': ...}], extract text from first element for simplicity in history
                        current_content_str = raw_content[0].get("text", "")
                    else:
                        # Fallback for other unexpected content structures
                        current_content_str = str(raw_content)

                    if role == "user":
                        messages_history_casted.append(UserMessage(role="user", content=current_content_str))
                    elif role == "assistant":
                        messages_history_casted.append(AgentMessage(
                            role="assistant",
                            content=current_content_str, # AgentMessage.content is also a string, potentially JSON string of blocks
                            kind=MessageKind.STAGE_RESULT,
                            agentState=None, unifiedDiff=None, app_name=None, commit_message=None
                        ))
            except json.JSONDecodeError:
                logger.error("Failed to decode messages_history from event content.")
            except Exception as e:
                logger.error(f"Error processing message history: {e}")

        trace_id = previous_request.trace_id
        application_id = previous_request.application_id

        events, request = await self.send_message(
            message=message,
            messages_history=messages_history_casted,
            application_id=application_id,
            trace_id=trace_id,
            agent_state=agent_state,
            all_files=all_files,
            settings=settings,
            stream_cb=stream_cb
        )

        return events, request

    @staticmethod
    def create_request(message: str,
                     messages_history: Optional[List[ConversationMessage]] = None,
                     application_id: Optional[str] = None,
                     trace_id: Optional[str] = None,
                     agent_state: Optional[Dict[str, Any]] = None,
                     all_files: Optional[List[Dict[str, str]]] = None,
                     settings: Optional[Dict[str, Any]] = None) -> AgentRequest:
        """Create a request object for the agent API"""

        all_messages_list = list(messages_history) if messages_history else []
        all_messages_list.append(UserMessage(role="user", content=message))

        file_entries: Optional[List[FileEntry]] = None
        if all_files is not None:
            file_entries = [FileEntry(**f) for f in all_files]

        return AgentRequest(
            allMessages=all_messages_list,
            applicationId=application_id or f"test-bot-{uuid.uuid4().hex[:8]}",
            traceId=trace_id or uuid.uuid4().hex,
            agentState=agent_state,
            allFiles=file_entries,
            settings=settings or {"max-iterations": 3}
        )

    @staticmethod
    async def parse_sse_events(response, stream_cb: Optional[Callable[[AgentSseEvent], None]] = None) -> List[AgentSseEvent]:
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
                            if stream_cb:
                                try:
                                    stream_cb(event_obj)
                                except Exception:
                                    logger.exception("Callback failed")
                        except json.JSONDecodeError as e:
                            logger.warning(f"JSON decode error: {e}, data: {data_str[:100]}...")
                        except Exception as e:
                            logger.warning(f"Error parsing SSE event: {e}, data: {data_str[:100]}...")
                buffer = ""

        return event_objects
