"""
Pydantic models for the agent server API.

These models define the data structures for API requests and responses,
ensuring consistency with the API specification in `agent_api.tsp`.
They are used by the `async_server.py` for data validation.

Refer to `architecture.puml` for context within the system.
"""
import datetime
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
    STAGE_RESULT = "StageResult"  # tool was used, and FSM state is expected to be updated
    RUNTIME_ERROR = "RuntimeError"  #  things went wrong!
    REFINEMENT_REQUEST = "RefinementRequest"  # no tool was used, meaning the agent is asking for more information
    REVIEW_RESULT = "ReviewResult"  # generation completed successfully
    KEEP_ALIVE = "KeepAlive"  # empty event to keep the connection alive


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


class DiffStatEntry(BaseModel):
    """Summary information about a single file modified in the current step."""

    path: str = Field(..., description="Path of the file that changed (relative to the project root).")
    insertions: int = Field(..., description="Number of lines inserted in this file during the current step.")
    deletions: int = Field(..., description="Number of lines deleted in this file during the current step.")

class ExternalContentBlock(BaseModel):
    """Represents a single content block in an external message."""
    role: Literal["assistant"] = Field("assistant", description="Deprecated. The role of the block. Will be removed in the future.")
    content: str = Field(..., description="The content of the block.")
    timestamp: datetime.datetime = Field(..., description="The timestamp of the block.")

class AgentMessage(BaseModel):
    """The detailed message payload from the agent."""
    role: Literal["assistant"] = Field("assistant", description="Fixed field for client to detect assistant message in the history") 
    kind: MessageKind = Field(..., description="The type of message being sent.")
    # Deprecated field, do not use. Use messages instead.
    content: str = Field(..., description="Deprecated. Formatted content of the message encoded as JSON string for backward compatibility.")
    messages: Optional[List[ExternalContentBlock]] = Field(
        None,
        description="Structured content blocks. Present only for new clients.")
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
    complete_diff_hash: Optional[str] = Field(
        None,
        alias="completeDiffHash",
        description="Hash (e.g., SHA-256) of the complete unified diff for the current application state."
    )
    diff_stat: Optional[List[DiffStatEntry]] = Field(
        None,
        alias="diffStat",
        description="Lightweight per-file summary of changes since the previous message."
    )
    app_name: Optional[str] = Field(
        None,
        description="Generated application name suitable for use as a GitHub repository name."
    )
    commit_message: Optional[str] = Field(
        None,
        description="Generated commit message suitable for use in Git commits."
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


class FileEntry(BaseModel):
    """Represents a single file with its path and content."""
    path: str = Field(..., description="The relative path of the file.")
    content: str = Field(..., description="The content of the file.")


class AgentRequest(BaseModel):
    """Request body for initiating or continuing interaction with the Agent Server."""
    all_messages: List[ConversationMessage] = Field(..., alias="allMessages", description="History of all messages in the current conversation thread.")
    application_id: str = Field(..., alias="applicationId", description="Unique identifier for the application instance.")
    trace_id: str = Field(..., alias="traceId", description="Unique identifier for this request/response cycle.")
    all_files: Optional[List[FileEntry]] = Field(None, alias="allFiles", description="All files in the workspace to be used for diff generation.")
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
