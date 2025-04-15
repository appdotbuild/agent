import logging
from typing import Iterable, TypedDict, NotRequired, cast, Literal, List

from google import genai
from google.genai import types as genai_types
import os
from llm import common
import anyio
from log import get_logger

logger = get_logger(__name__)


class GeminiLLM(common.AsyncLLM):
    def __init__(self,
                 model_name: Literal["gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-thinking", "gemma-3-27b-it"] = "gemini-2.0-flash",
                 api_key: str | None = None,
                 client_params: dict = {}
                 ):
        super().__init__()

        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], **(client_params or {}))
        self._async_client = _client.aio

        # Map friendly model names to actual model identifiers
        self.models_map = {
            "gemini-2.5-pro": "gemini-2.5-pro-exp-03-25",  # Using the experimental version from example
            "gemini-2.0-flash": "gemini-2.0-flash",
            "gemini-2.0-flash-thinking": "gemini-2.0-flash-thinking-exp-01-21"
        }

        if model_name in self.models_map:
            self.model_name = self.models_map[model_name]
        else:
            self.model_name = model_name

    async def completion(
        self,
        messages: list[common.Message],
        max_tokens: int,
        model: str | None = None,
        temperature: float = 1.0,
        tools: list[common.Tool] | None = None,
        tool_choice: str | None = None,
        system_prompt: str | None = None,
        *args, # consume unused args passed down
        **kwargs, # consume unused kwargs passed down
    ) -> common.Completion:

        if tools:
            raise ValueError("Gemini client does not support tools atm.")

        gemini_contents = self._convert_messages_to_gemini(messages)
        config = genai_types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
            response_mime_type="text/plain",
        )
        response = await self._async_client.models.generate_content(
            model=self.model_name,
            contents=gemini_contents,
            config=config,
        )

        return self._convert_messages_from_gemini(response)

    @staticmethod
    def _convert_messages_to_gemini(messages: List[common.Message]) -> List[genai_types.Content]:
        gemini_contents = []
        for message in messages:
            new_content = genai_types.Content(
                parts=[
                    genai_types.Part(
                        text=x.text if message.content else "",
                    )
                    for x in message.content
                    if isinstance(x, common.TextRaw)
                ],
                role="user" if message.role == "user" else "model",
            )

            gemini_contents.append(new_content)
        return gemini_contents

    @staticmethod
    def _convert_messages_from_gemini(response: genai_types.GenerateContentResponse) -> common.Completion:
        text_blocks = []
        match response.usage_metadata:
            case genai_types.GenerateContentResponseUsageMetadata():
                input_tokens = response.usage_metadata.prompt_token_count or 0
                if hasattr(response.usage_metadata, "thinking_token_count"):
                    # backward compatibility with older versions
                    thinking_tokens = response.usage_metadata.thoughts_token_count or 0
                else:
                    thinking_tokens = None
            case None:
                input_tokens = 0
                thinking_tokens = 0
            case _:
                raise ValueError("Invalid usage metadata in response")

        output_tokens = 0
        stop_reason = "unknown"

        match response.candidates:
            case [*candidates]:
                candidates = response.candidates
            case None:
                raise ValueError("No candidates in response")

        for candidate in candidates:
            match candidate.content:
                case None:
                    pass
                case _:
                    text_blocks += [common.TextRaw(part.text) for part in (candidate.content.parts or []) if part.text]
                    output_tokens += candidate.token_count or 0

            fr = genai_types.FinishReason
            match candidate.finish_reason:
                case None:
                    pass
                case fr.MAX_TOKENS:
                    stop_reason = "max_tokens"
                case fr.STOP:
                    stop_reason = "stop_sequence"
                case _:
                    stop_reason = "unknown"

        if len(text_blocks) == 0:
            raise ValueError(f"No text blocks in response: {response}")

        return common.Completion(
            role="assistant",
            content=text_blocks,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=stop_reason,
            thinking_tokens=thinking_tokens,
        )


async def main():
    gemini_llm = GeminiLLM()
    messages = [
        common.Message(role="user", content=[common.TextRaw("Hello, how are you?")]),
    ]
    response = await gemini_llm.completion(messages, max_tokens=50)
    print(response)

if __name__ == "__main__":
    anyio.run(main)
