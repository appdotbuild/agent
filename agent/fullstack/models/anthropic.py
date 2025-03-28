from typing import Iterable, TypedDict, NotRequired
from anthropic import AsyncAnthropic
from anthropic.types import (
    ToolParam,
    TextBlock,
    ToolUseBlock,
    ThinkingBlock,
    ToolResultBlockParam,
    Message,
    MessageParam,
    TextBlockParam,
    ToolUseBlockParam,
    ToolResultBlockParam,
    ToolChoiceParam,
)
from . import common


class AnthropicParams(TypedDict):
    max_tokens: int
    messages: list[MessageParam]
    model: str
    temperature: float
    tools: NotRequired[Iterable[ToolParam]]
    tool_choice: NotRequired[ToolChoiceParam]


class AnthropicLLM(common.AsyncLLM):
    def __init__(self, client: AsyncAnthropic):
        self.client = client
    
    async def completion(
        self,
        model: str,
        messages: list[common.Message],
        max_tokens: int,
        temperature: float = 1.0,
        tools: list[common.Tool] | None = None,
        tool_choice: str | None = None,
    ) -> common.Completion:
        call_args: AnthropicParams = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": self._messages_into(messages),
        }
        if tools is not None:
            call_args["tools"] = tools # type: ignore
        if tool_choice is not None:
            call_args["tool_choice"] = {"type": "tool", "name": tool_choice}
        completion = await self.client.messages.create(**call_args)
        return self._completion_from(completion)
    
    @staticmethod
    def _completion_from(completion: Message) -> common.Completion:
        ours_content: list[common.TextRaw | common.ToolUse | common.ThinkingBlock] = []
        for block in completion.content:
            match block:
                case TextBlock(text=text):
                    ours_content.append(common.TextRaw(text))
                case ToolUseBlock(name=name, input=input, id=id):
                    ours_content.append(common.ToolUse(name, input, id))
                case ThinkingBlock(thinking=thinking):
                    ours_content.append(common.ThinkingBlock(thinking))
                case unknown:
                    raise ValueError(f"Unknown block type {unknown}")
        assert completion.stop_reason is not None, "stop_reason must be set"
        return common.Completion(
            role="assistant",
            content=ours_content,
            input_tokens=completion.usage.input_tokens,
            output_tokens=completion.usage.output_tokens,
            stop_reason=completion.stop_reason,
        )
    
    @staticmethod
    def _messages_into(messages: list[common.Message]) -> list[MessageParam]:
        theirs_messages: list[MessageParam] = []
        for message in messages:
            theirs_content: list[TextBlockParam | ToolUseBlockParam | ToolResultBlockParam] = []
            for block in message.content:
                match block:
                    case common.TextRaw(text):
                        theirs_content.append({"text": text.rstrip(), "type": "text"})
                    case common.ToolUse(name, input, id) if id is not None:
                        theirs_content.append({"id": id, "input": input, "name": name, "type": "tool_use"})
                    case common.ToolUseResult(tool_use, tool_result) if tool_use.id is not None:
                        theirs_content.append({
                            "tool_use_id": tool_use.id,
                            "type": "tool_result",
                            "content": tool_result.content,
                            "is_error": tool_result.is_error or False
                        })
            theirs_messages.append({"role": message.role, "content": theirs_content})
        return theirs_messages
