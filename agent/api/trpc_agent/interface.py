"""
Interface implementation for the trpc_agent.

This module provides an implementation of the AgentInterface protocol
that delegates to the existing TrpcAgentSession in the trpc_agent module.
"""
from typing import Dict, Any, Optional

from anyio.streams.memory import MemoryObjectSendStream

from api.agent_server.interface import AgentInterface
from api.agent_server.models import AgentRequest, AgentSseEvent

from log import get_logger

logger = get_logger(__name__)


class TrpcAgentInterface(AgentInterface):
    """
    API interface for the trpc_agent functionality.
    
    This class implements the AgentInterface protocol by delegating
    to the existing TrpcAgentSession in the trpc_agent module.
    """
    
    def __init__(self, application_id: str, trace_id: str, settings: Optional[Dict[str, Any]] = None):
        """
        Initialize the TrpcAgentInterface.
        
        Args:
            application_id: Unique identifier for the application
            trace_id: Trace ID for tracking the request
            settings: Optional settings for the agent
        """
        from trpc_agent.agent_session import TrpcAgentSession
        
        self.agent_session = TrpcAgentSession(
            application_id=application_id,
            trace_id=trace_id,
            settings=settings
        )
        logger.info(f"Initialized TrpcAgentInterface for application {application_id}, trace {trace_id}")
        
    async def process(self, request: AgentRequest, event_tx: MemoryObjectSendStream[AgentSseEvent]) -> None:
        """
        Process the agent request by delegating to the TrpcAgentSession.
        
        Args:
            request: The agent request containing messages and context
            event_tx: Channel to send events back to the client
        """
        logger.info(f"Processing request with TrpcAgentInterface for application {request.application_id}, trace {request.trace_id}")
        await self.agent_session.process(request, event_tx)
