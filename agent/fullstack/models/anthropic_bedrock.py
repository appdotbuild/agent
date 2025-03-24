from anthropic import AsyncAnthropicBedrock
from . import common
from .anthropic import AnthropicLLM, AnthropicParams

class AnthropicBedrockLLM(AnthropicLLM):
    def __init__(self, client: AsyncAnthropicBedrock):
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
