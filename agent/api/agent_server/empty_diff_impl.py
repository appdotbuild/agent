import asyncio
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
    
    def __init__(self, application_id: str = None, trace_id: str = None, settings: Optional[Dict[str, Any]] = None):
        """
        Initialize with session information
        
        Args:
            application_id: ID of the application
            trace_id: Trace ID for tracking
            settings: Optional settings
        """
        self.application_id = application_id or "default-bot"
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
        logger.info(f"Processing request for {self.application_id}:{self.trace_id}")
        async with event_tx:
            # Create a test state that includes the input request info
            agent_state = {
                "test_state": True,
                "last_message": request.all_messages[-1].content if request.all_messages else "",
                "application_id": self.application_id,
                "trace_id": self.trace_id,
                "timestamp": str(asyncio.get_event_loop().time())
            }
            
            if request.agent_state:
                agent_state = request.agent_state
                
            logger.debug(f"Setting agent_state: {agent_state}")
            
            # Make sure agent_state is not None to enable tests to pass
            if agent_state is None:
                agent_state = {
                    "test_state": True,
                    "timestamp": str(asyncio.get_event_loop().time()),
                    "application_id": self.application_id,
                    "trace_id": self.trace_id
                }
                
            # Use the Python attribute names, not the JSON serialized aliases
            agent_message = AgentMessage(
                role="agent",
                kind=MessageKind.STAGE_RESULT,
                content="Agent initialized with EmptyDiffAgentImplementation",
                agent_state=agent_state,  # Use snake_case as defined in the class
                unified_diff=""
            )
            
            event = AgentSseEvent(
                status=AgentStatus.IDLE,
                traceId=self.trace_id,
                message=agent_message
            )
            await event_tx.send(event)

