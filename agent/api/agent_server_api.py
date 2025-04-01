"""
Agent Server API

This module provides a REST+SSE endpoint for communication 
between the Platform (Backend) and the Agent Server.
"""

from api.agent_server import (
    app,
    AgentStatus,
    MessageKind,
    AgentMessage,
    AgentSseEvent,
    AgentRequest,
    ErrorResponse
)

def get_app():
    """
    Returns the FastAPI application instance.
    """
    return app

__all__ = [
    'get_app',
    'app',
    'AgentStatus',
    'MessageKind',
    'AgentMessage',
    'AgentSseEvent',
    'AgentRequest',
    'ErrorResponse'
]