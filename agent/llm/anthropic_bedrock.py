import anthropic
from llm import common
from llm.anthropic_client import AnthropicLLM, AnthropicParams

class AnthropicBedrockLLM(AnthropicLLM):
    def __init__(self, client: anthropic.AsyncAnthropicBedrock, default_model: str = "us.anthropic.claude-3-7-sonnet-20250219-v1:0"):
        self.client = client
        self.default_model = default_model

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
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": self._messages_into(messages),
        }
        if system_prompt is not None:
            call_args["system"] = system_prompt
        if tools is not None:
            call_args["tools"] = tools # type: ignore
        if tool_choice is not None:
            call_args["tool_choice"] = {"type": "tool", "name": tool_choice}
        completion = await self.client.messages.create(**call_args)
        return self._completion_from(completion)
