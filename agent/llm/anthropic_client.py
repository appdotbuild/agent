from typing import Iterable, TypedDict, NotRequired
import anyio
import random
import anthropic
from anthropic.types import (
    ToolParam,
    TextBlock,
    ToolUseBlock,
    ThinkingBlock,
    Message,
    MessageParam,
    TextBlockParam,
    ToolUseBlockParam,
    ToolResultBlockParam,
    ToolChoiceParam,
)
from llm import common
from log import get_logger

logger = get_logger(__name__)


class AnthropicParams(TypedDict):
    max_tokens: int
    messages: list[MessageParam]
    model: str
    temperature: float
    tools: NotRequired[Iterable[ToolParam]]
    tool_choice: NotRequired[ToolChoiceParam]
    system: NotRequired[Iterable[TextBlockParam] | str]


class AnthropicLLM(common.AsyncLLM):
    def __init__(self, client: anthropic.AsyncAnthropic | anthropic.AsyncAnthropicBedrock, default_model: str):
        self.client = client
        self.default_model = default_model
        self.use_prompt_caching = "bedrock" not in self.client.__class__.__name__.lower()
        # this is a workaround for the fact that the bedrock client does not support caching yet

    async def completion(
        self,
        messages: list[common.Message],
        max_tokens: int,
        model: str | None = None,
        temperature: float = 1.0,
        tools: list[common.Tool] | None = None,
        tool_choice: str | None = None,
        system_prompt: str | None = None,
    ) -> common.Completion:
        call_args: AnthropicParams = {
            "model": model or self.default_model,
            "max_tokens": max_tokens or 8192,
            "temperature": temperature,
            "messages": self._messages_into(messages),
        }

        if system_prompt is not None:
            if self.use_prompt_caching:
                call_args["system"] = [{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"}
                }]
            else:
                call_args["system"] = system_prompt
        if tools is not None:
            if self.use_prompt_caching:
                tools[-1]["cache_control"] = {"type": "ephemeral"}
            call_args["tools"] = tools # type: ignore
        if tool_choice is not None:
            call_args["tool_choice"] = {"type": "tool", "name": tool_choice}

        completion = None
        while completion is None:
            try:
                completion = await self.client.messages.create(**call_args)
                return self._completion_from(completion)
            except anthropic.APIStatusError as exc:
                if exc.status_code >= 413:
                    # errors meaning we can retry
                    delay = random.randint(1, 5)
                    logger.warning(f"Rate limit error, retrying in {delay} seconds")
                    await anyio.sleep(delay)
                else:
                    raise RuntimeError(f"Anthropic API error: {exc.status_code} {exc.message}") from exc

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
                    case common.TextRaw(text) if text.rstrip():
                        theirs_content.append({"text": text.rstrip(), "type": "text"})
                    case common.TextRaw(text) if not text.rstrip():
                        continue
                    case common.ToolUse(name, input, id) if id is not None:
                        theirs_content.append({"id": id, "input": input, "name": name, "type": "tool_use"})
                    case common.ToolUseResult(tool_use, tool_result) if tool_use.id is not None:
                        theirs_content.append({
                            "tool_use_id": tool_use.id,
                            "type": "tool_result",
                            "content": tool_result.content,
                            "is_error": tool_result.is_error or False
                        })
                    case _:
                        raise ValueError(f"Unknown block type {type(block)} for {block}")
            if theirs_content:
                theirs_messages.append({"role": message.role, "content": theirs_content})
        return theirs_messages
