import openai
from typing import List, TypedDict, NotRequired, Union
from llm import common


class OpenAIParams(TypedDict, total=False):
    model: str
    messages: List[dict]
    max_tokens: int
    temperature: float
    functions: NotRequired[List[dict]]
    function_call: NotRequired[Union[str, dict]]


class OpenAILLM(common.AsyncLLM):
    """
    Async client for OpenAI ChatCompletion API, conforming to common.AsyncLLM.
    Supports basic chat and optional function-calling (tools).
    """
    def __init__(self, api_key: str | None = None, default_model: str = "gpt-4o"):
        self.default_model = default_model
        self.cli = openai.AsyncOpenAI()

    async def completion(
        self,
        messages: List[common.Message],
        max_tokens: int,
        model: str | None = None,
        temperature: float = 1.0,
        tools: List[common.Tool] | None = None,
        tool_choice: str | None = None,
        system_prompt: str | None = None,
    ) -> common.Completion:
        # Prepare call parameters
        params: OpenAIParams = {
            "model": model or self.default_model,
            "messages": self._messages_to_payload(messages, system_prompt),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # Optional function-calling support
        if tools is not None:
            params["functions"] = [
                {"name": t["name"], "description": t.get("description", ""), "parameters": t["input_schema"]}
                for t in tools  # type: ignore
            ]
        if tool_choice is not None:
            params["function_call"] = {"name": tool_choice}

        response = await self.cli.chat.completions.create(**params)
        return self._completion_from_response(response)

    def _messages_to_payload(
        self,
        messages: List[common.Message],
        system_prompt: str | None,
    ) -> List[dict]:
        payload: List[dict] = []
        if system_prompt is not None:
            payload.append({"role": "system", "content": system_prompt})
        for msg in messages:
            # concatenate TextRaw blocks; ignore non-text
            text = "".join(
                blk.text for blk in msg.content if isinstance(blk, common.TextRaw)
            )
            payload.append({"role": msg.role, "content": text})
        return payload

    @staticmethod
    def _completion_from_response(response) -> common.Completion:
        # Pick first choice
        choice, = response.choices
        content_text = choice.message.content or ""
        # Build content blocks
        blocks = [common.TextRaw(content_text)]
        # Determine stop reason
        finish = choice.finish_reason
        if finish == "length":
            stop_reason = "max_tokens"
        elif finish == "stop":
            stop_reason = "stop_sequence"
        else:
            stop_reason = "unknown"
        # Extract usage
        usage = response.usage
        return common.Completion(
            role="assistant",
            content=blocks,
            input_tokens=usage.prompt_tokens,
            output_tokens=usage.completion_tokens,
            stop_reason=stop_reason,
        )

async def main():  # simple smoke test for OpenAI client
    llm = OpenAILLM()
    messages = [common.Message(role="user", content=[common.TextRaw("Hello, world!")])]
    response = await llm.completion(messages, max_tokens=10)
    print(response)

if __name__ == "__main__":
    import anyio
    anyio.run(main)
