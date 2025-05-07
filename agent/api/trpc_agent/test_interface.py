"""
Tests for the trpc_agent API interface.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from api.trpc_agent.interface import TrpcAgentInterface
from api.agent_server.models import AgentRequest, AgentSseEvent
from anyio.streams.memory import MemoryObjectSendStream


@pytest.mark.asyncio
async def test_trpc_agent_interface_initialization():
    """Test that the TrpcAgentInterface initializes correctly."""
    mock_session_class = MagicMock()
    mock_session_instance = AsyncMock()
    mock_session_class.return_value = mock_session_instance
    
    with patch.dict('sys.modules', {'trpc_agent.agent_session': MagicMock(TrpcAgentSession=mock_session_class)}):
        interface = TrpcAgentInterface(
            application_id="test-app",
            trace_id="test-trace",
            settings={"key": "value"}
        )
        
        mock_session_class.assert_called_once_with(
            application_id="test-app",
            trace_id="test-trace",
            settings={"key": "value"}
        )


@pytest.mark.asyncio
async def test_trpc_agent_interface_process():
    """Test that the process method delegates to the agent session."""
    mock_session_class = MagicMock()
    mock_session_instance = AsyncMock()
    mock_session_class.return_value = mock_session_instance
    
    request = AgentRequest(
        allMessages=[],
        applicationId="test-app",
        traceId="test-trace",
        agentState=None,
        settings=None
    )
    event_tx = AsyncMock(spec=MemoryObjectSendStream[AgentSseEvent])
    
    with patch.dict('sys.modules', {'trpc_agent.agent_session': MagicMock(TrpcAgentSession=mock_session_class)}):
        interface = TrpcAgentInterface(
            application_id="test-app",
            trace_id="test-trace"
        )
        
        await interface.process(request, event_tx)
        
        mock_session_instance.process.assert_called_once_with(request, event_tx)
