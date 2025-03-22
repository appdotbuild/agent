from typing import Literal, Protocol, Iterable, TypedDict, Required, NotRequired
from dataclasses import dataclass
from typing import Dict

@dataclass
class TextRaw:
    text: str


@dataclass
class ToolUse:
    name: str
    input: object
    id: str | None = None


@dataclass
class ToolResult:
    content: str
    tool_use_id: str | None = None
    name: str | None = None
    is_error: bool | None = None


@dataclass
class ThinkingBlock:
    thinking: str


@dataclass
class ToolUseResult:
    tool_use: ToolUse
    tool_result: ToolResult


@dataclass
class Message:
    role: Literal["user", "assistant"]
    content: Iterable[TextRaw | ToolUse | ToolUseResult | ThinkingBlock]


@dataclass
class Completion:
    role: Literal["assistant"]
    content: Iterable[TextRaw | ToolUse | ThinkingBlock]
    input_tokens: int
    output_tokens: int
    stop_reason: Literal["end_turn", "max_tokens", "stop_sequence", "tool_use"]
    thinking_tokens: int | None = None


class ToolSchema(TypedDict):
    type: Literal["object"]
    properties: NotRequired[object | None]#NotRequired[object]


class Tool(TypedDict, total=False):
    name: Required[str]
    description: str
    input_schema: Required[Dict[str, object]]#Required[ToolSchema]


class AsyncLLM(Protocol):
    async def completion(
        self,
        model: str,
        messages: list[Message],
        max_tokens: int,
        temperature: float = 1.0,
        tools: list[Tool] | None = None,
        tool_choice: str | None = None,
        *args,
        **kwargs,
    ) -> Completion:
        ...
