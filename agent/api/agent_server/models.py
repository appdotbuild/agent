from enum import Enum
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    """Defines the status of the Agent Server during processing."""
    RUNNING = "running"
    IDLE = "idle"


class MessageKind(str, Enum):
    """Defines the type of message being sent from the Agent Server."""
    STAGE_RESULT = "StageResult"
    FEEDBACK_RESPONSE = "FeedbackResponse"
    RUNTIME_ERROR = "RuntimeError"


class AgentMessage(BaseModel):
    """The detailed message payload from the agent."""
    kind: MessageKind = Field(..., description="The type of message being sent.")
    content: str = Field(..., description="Formatted content of the message. Can be long and contain formatting.")
    agent_state: Optional[Dict[str, Any]] = Field(
        None, 
        alias="agentState", 
        description="Updated state of the Agent Server for the next request."
    )
    unified_diff: Optional[str] = Field(
        None, 
        alias="unifiedDiff", 
        description="A unified diff format string representing code changes made by the agent."
    )

    class Config:
        populate_by_name = True
        allow_population_by_field_name = True


class AgentSseEvent(BaseModel):
    """Structure of the data payload within each Server-Sent Event (SSE)."""
    status: AgentStatus = Field(..., description="Current status of the agent (running or idle).")
    trace_id: str = Field(..., alias="traceId", description="The trace ID corresponding to the POST request.")
    message: AgentMessage = Field(..., description="The detailed message payload from the agent.")

    class Config:
        populate_by_name = True
        allow_population_by_field_name = True


class AgentRequest(BaseModel):
    """Request body for initiating or continuing interaction with the Agent Server."""
    all_messages: List[str] = Field(..., alias="allMessages", description="History of all user messages.")
    chatbot_id: str = Field(..., alias="chatbotId", description="Unique identifier for the chatbot instance.")
    trace_id: str = Field(..., alias="traceId", description="Unique identifier for this request/response cycle.")
    agent_state: Optional[Dict[str, Any]] = Field(
        None, 
        alias="agentState", 
        description="The full state of the Agent Server to restore from."
    )
    settings: Optional[Dict[str, Any]] = Field(
        None, 
        description="Settings for the agent execution, such as maximum number of iterations."
    )

    class Config:
        populate_by_name = True
        allow_population_by_field_name = True


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str
    details: Optional[str] = None