from enum import Enum
from typing import Dict, List, Optional, Any, Union, Literal
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


class UserMessage(BaseModel):
    """Represents a message from the user to the agent."""
    role: Literal["user"] = Field("user", description="Fixed field for client to detect user message in the history")
    content: str = Field(..., description="The content of the user's message.")


class AgentMessage(BaseModel):
    """The detailed message payload from the agent."""
    role: Literal["agent"] = Field("agent", description="Fixed field for client to detect agent message in the history") 
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


ConversationMessage = Union[UserMessage, AgentMessage]


class AgentSseEvent(BaseModel):
    """Structure of the data payload within each Server-Sent Event (SSE)."""
    status: AgentStatus = Field(..., description="Current status of the agent (running or idle).")
    trace_id: str = Field(..., alias="traceId", description="The trace ID corresponding to the POST request.")
    message: AgentMessage = Field(..., description="The detailed message payload from the agent.")


class AgentRequest(BaseModel):
    """Request body for initiating or continuing interaction with the Agent Server."""
    all_messages: List[ConversationMessage] = Field(..., alias="allMessages", description="History of all messages in the current conversation thread.")
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


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str
    details: Optional[str] = None