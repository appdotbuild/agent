from typing import List

from google import genai
from google.genai import types as genai_types
import os
from llm import common
import anyio
from log import get_logger

logger = get_logger(__name__)


class GeminiLLM(common.AsyncLLM):
    def __init__(self,
                 model_name: str,
                 api_key: str | None = None,
                 client_params: dict = {}
                 ):
        super().__init__()

        _client = genai.Client(api_key=api_key or os.environ["GEMINI_API_KEY"], **(client_params or {}))
        self._async_client = _client.aio

        self.model_name = model_name

    async def completion(
        self,
        messages: list[common.Message],
        max_tokens: int | None = 8192,
        model: str | None = None,
        temperature: float = 1.0,
        tools: list[common.Tool] | None = None,
        tool_choice: str | None = None,
        system_prompt: str | None = None,
        force_tool_use: bool = False,
        *args, # consume unused args passed down
        **kwargs, # consume unused kwargs passed down
    ) -> common.Completion:
        config = genai_types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
            response_mime_type="text/plain",
            system_instruction=system_prompt,
            candidate_count=1,
        )
        if tools:
            declarations = [
                genai_types.FunctionDeclaration(
                    name=tool["name"],
                    description=tool.get("description", None),
                    parameters=tool["input_schema"], # pyright: ignore
                ) for tool in tools
            ]
            config.tools = [genai_types.Tool(function_declarations=declarations)]
            if force_tool_use:
                config.tool_config = genai_types.ToolConfig(
                    function_calling_config=genai_types.FunctionCallingConfig(
                        mode=genai_types.FunctionCallingConfigMode.ANY,
                        allowed_function_names=[tool_choice] if tool_choice else None,
                    )
                )
        while True:
            response = await self._async_client.models.generate_content(
                model=self.model_name,
                contents=self._messages_into(messages),
                config=config,
            )
            try:
                return self._completion_from(response)
            except Exception as e:
                if self.should_retry(response):
                    continue
                raise e
        return self._completion_from(response)

    @staticmethod
    def _completion_from(completion: genai_types.GenerateContentResponse) -> common.Completion:
        if not completion.candidates:
            raise ValueError(f"Empty completion: {completion}")
        if not completion.candidates[0].content:
            raise ValueError(f"Empty content in completion: {completion}")
        if not completion.candidates[0].content.parts:
            raise ValueError(f"Empty parts in content in completion: {completion}")
        ours_content: list[common.TextRaw | common.ToolUse | common.ThinkingBlock] = []
        for block in completion.candidates[0].content.parts:
            if block.text:
                if block.thought:
                    ours_content.append(common.ThinkingBlock(thinking=block.text))
                else:
                    ours_content.append(common.TextRaw(text=block.text))
            if block.function_call and block.function_call.name:
                ours_content.append(common.ToolUse(
                    id=block.function_call.id,
                    name=block.function_call.name,
                    input=block.function_call.args
                ))

        match completion.usage_metadata:
            case genai_types.GenerateContentResponseUsageMetadata(prompt_token_count=input_tokens, candidates_token_count=output_tokens, thoughts_token_count=thinking_tokens):
                usage = (input_tokens, output_tokens, thinking_tokens)
            case genai_types.GenerateContentResponseUsageMetadata(prompt_token_count=input_tokens, candidates_token_count=output_tokens):
                usage = (input_tokens, output_tokens, None)
            case None:
                usage = (0, 0, None)
            case unknown:
                raise ValueError(f"Unexpected usage metadata: {unknown}")
        match completion.candidates[0].finish_reason:
            case genai_types.FinishReason.MAX_TOKENS:
                stop_reason = "max_tokens"
            case genai_types.FinishReason.STOP:
                stop_reason = "end_turn"
            case _:
                stop_reason = "unknown"

        return common.Completion(
            role="assistant",
            content=ours_content,
            input_tokens=usage[0] or 0,
            output_tokens=usage[1] or 0,
            stop_reason=stop_reason,
            thinking_tokens=usage[2],
        )

    @classmethod
    def should_retry(cls, completion: genai_types.GenerateContentResponse) -> bool:
        if completion.candidates:
            match completion.candidates[0].finish_reason:
                case genai_types.FinishReason.MALFORMED_FUNCTION_CALL:
                    return True
                case _:
                    return False
        return False

    @staticmethod
    def _messages_into(messages: list[common.Message]) -> List[genai_types.Content]:
        theirs_messages: List[genai_types.Content] = []
        for message in messages:
            theirs_parts: List[genai_types.Part] = []
            for block in message.content:
                match block:
                    case common.TextRaw(text=text):
                        theirs_parts.append(genai_types.Part.from_text(text=text))
                    case common.ToolUse(name, input):
                        theirs_parts.append(genai_types.Part.from_function_call(name=name, args=input)) # pyright: ignore
                    case common.ToolUseResult(tool_use, tool_result):
                        theirs_parts.append(genai_types.Part.from_function_response(name=tool_use.name, response={"result": tool_result.content}))
                    case _:
                        raise ValueError(f"Unknown block type {type(block)} for {block}")
            theirs_messages.append(genai_types.Content(
                parts=theirs_parts,
                role=message.role if message.role == "user" else "model"
            ))
        return theirs_messages


async def main():
    gemini_llm = GeminiLLM("gemini-2.5-flash-preview-04-17")
    messages = [
        common.Message(role="user", content=[common.TextRaw("Hello, how are you?")]),
    ]
    response = await gemini_llm.completion(messages, max_tokens=1024)
    print(response)

if __name__ == "__main__":
    anyio.run(main)
