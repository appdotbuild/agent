import logging
from typing import Dict, Any, Optional

from anyio.streams.memory import MemoryObjectSendStream
from api.agent_server.interface import AgentInterface
from api.agent_server.models import (
    AgentRequest,
    AgentSseEvent,
    AgentMessage,
    AgentStatus,
    MessageKind
)

logger = logging.getLogger(__name__)


class EmptyDiffAgentImplementation(AgentInterface):
    """
    Minimal implementation of FSMInterface that returns empty dummy results.
    Used for testing the SSE stream functionality.
    """
    
    def __init__(self, chatbot_id: str = None, trace_id: str = None, settings: Optional[Dict[str, Any]] = None):
        """
        Initialize with session information
        
        Args:
            chatbot_id: ID of the chatbot
            trace_id: Trace ID for tracking
            settings: Optional settings
        """
        self.chatbot_id = chatbot_id or "default-bot"
        self.trace_id = trace_id or "default-trace"
        self.settings = settings or {}
        self.has_initialized = False
    
    async def process(self, request: AgentRequest, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        """
        Process the incoming request and send events to the event stream
        
        Args:
            request: Incoming agent request
            event_tx: Event transmission stream
        """
        logger.info(f"Processing request for {self.chatbot_id}:{self.trace_id}")
        async with event_tx:
            agent_message = AgentMessage(
                role="agent",
                kind=MessageKind.STAGE_RESULT,
                content="Agent initialized with EmptyDiffAgentImplementation",
                agent_state=request.agent_state or {},
                unifiedDiff=""
            )
            
            event = AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=agent_message
            )
            await event_tx.send(event)

