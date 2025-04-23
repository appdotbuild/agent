"""
Pydantic models for the agent server API.

These models define the data structures for API requests and responses,
ensuring consistency with the API specification in `agent_api.tsp`.
They are used by the `async_server.py` for data validation.

Refer to `architecture.puml` for context within the system.
"""
from enum import Enum
import ujson as json
from typing import Dict, List, Optional, Any, Union, Literal, Type, TypeVar
from pydantic import BaseModel, Field


T = TypeVar('T', bound='BaseModel')


class AgentStatus(str, Enum):
    """Defines the status of the Agent Server during processing."""
    RUNNING = "running"
    IDLE = "idle"


class MessageKind(str, Enum):
    """Defines the type of message being sent from the Agent Server."""
    STAGE_RESULT = "StageResult"
    RUNTIME_ERROR = "RuntimeError"
    FEEDBACK_RESPONSE = "FeedbackResponse"


class UserMessage(BaseModel):
    """Represents a message from the user to the agent."""
    role: Literal["user"] = Field("user", description="Fixed field for client to detect user message in the history")
    content: str = Field(..., description="The content of the user's message.")
    
    def to_json(self) -> str:
        """Serialize the model to JSON string."""
        return self.model_dump_json(by_alias=True)
    
    @classmethod
    def from_json(cls: Type[T], json_str: str) -> T:
        """Deserialize a JSON string to a model instance."""
        return cls.model_validate(json.loads(json_str))


class AgentMessage(BaseModel):
    """The detailed message payload from the agent."""
    role: Literal["assistant"] = Field("assistant", description="Fixed field for client to detect assistant message in the history") 
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
    
    def to_json(self) -> str:
        """Serialize the model to JSON string."""
        return self.model_dump_json(by_alias=True)
    
    @classmethod
    def from_json(cls: Type[T], json_str: str) -> T:
        """Deserialize a JSON string to a model instance."""
        return cls.model_validate(json.loads(json_str))


ConversationMessage = Union[UserMessage, AgentMessage]


def parse_conversation_message(json_str: str) -> ConversationMessage:
    """Parse a JSON string into the appropriate ConversationMessage type."""
    data = json.loads(json_str)
    if data.get("role") == "user":
        return UserMessage.model_validate(data)
    elif data.get("role") == "assistant":
        return AgentMessage.model_validate(data)
    else:
        raise ValueError(f"Unknown role in message: {data.get('role')}")


class AgentSseEvent(BaseModel):
    """Structure of the data payload within each Server-Sent Event (SSE)."""
    status: AgentStatus = Field(..., description="Current status of the agent (running or idle).")
    trace_id: Optional[str] = Field(None, alias="traceId", description="The trace ID corresponding to the POST request.")
    message: AgentMessage = Field(..., description="The detailed message payload from the agent.")
    
    def to_json(self) -> str:
        """Serialize the model to JSON string."""
        return self.model_dump_json(by_alias=True)
    
    @classmethod
    def from_json(cls: Type[T], json_str: str) -> T:
        """Deserialize a JSON string to a model instance."""
        return cls.model_validate(json.loads(json_str))


class AgentRequest(BaseModel):
    """Request body for initiating or continuing interaction with the Agent Server."""
    all_messages: List[ConversationMessage] = Field(..., alias="allMessages", description="History of all messages in the current conversation thread.")
    application_id: str = Field(..., alias="applicationId", description="Unique identifier for the application instance.")
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
    
    def to_json(self) -> str:
        """Serialize the model to JSON string."""
        return self.model_dump_json(by_alias=True)
    
    @classmethod
    def from_json(cls: Type[T], json_str: str) -> T:
        """Deserialize a JSON string to a model instance."""
        return cls.model_validate(json.loads(json_str))


class ErrorResponse(BaseModel):
    """Error response model."""
    error: str
    details: Optional[str] = None
    
    def to_json(self) -> str:
        """Serialize the model to JSON string."""
        return self.model_dump_json()
    
    @classmethod
    def from_json(cls: Type[T], json_str: str) -> T:
        """Deserialize a JSON string to a model instance."""
        return cls.model_validate(json.loads(json_str))
