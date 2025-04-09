import itertools
import os
import logging
from typing import Literal
import anthropic
from anthropic import AnthropicBedrock, Anthropic, AsyncAnthropic, AsyncAnthropicBedrock
from .common import AsyncLLM, Message, TextRaw, ToolUse, ThinkingBlock
from .anthropic_client import AnthropicLLM
from .anthropic_bedrock import AnthropicBedrockLLM
from .cached import CachedLLM, CacheMode

logger = logging.getLogger(__name__)


def merge_text(content: list[TextRaw | ToolUse | ThinkingBlock]) -> list[TextRaw | ToolUse | ThinkingBlock]:
    merged = []
    for k, g in itertools.groupby(content, lambda x: isinstance(x, TextRaw)):
        if k and (text := "".join([x.text for x in g])) != "":
            merged.append(TextRaw(text))
        else:
            merged.extend(g)
    return merged


async def loop_completion(m_client: AsyncLLM, messages: list[Message], **kwargs) -> Message:
    content: list[TextRaw | ToolUse | ThinkingBlock] = []
    while True:
        payload = messages + [Message(role="assistant", content=content)] if content else messages
        completion = await m_client.completion(messages=payload, **kwargs)
        content.extend(completion.content)
        if completion.stop_reason != "max_tokens":
            break
    return Message(role="assistant", content=merge_text(content))


def get_llm_client(
    backend: Literal["bedrock", "anthropic"] = "bedrock",
    model_name: Literal["sonnet", "haiku"] = "sonnet",
    cache_mode: CacheMode = "off",
    cache_path: str = os.path.join(os.path.dirname(__file__), "../../../anthropic_cache.json"),
    client_params: dict | None = None,
) -> AsyncLLM:
    """Get a configured LLM client for the fullstack application.

    Args:
        backend: LLM backend provider, either "bedrock" or "anthropic"
        model_name: Model name to use, either "sonnet" or "haiku"
        cache_mode: Cache mode, either "off", "record", or "replay"
        cache_path: Path to the cache file
        client_params: Additional parameters to pass to the client constructor

    Returns:
        An AsyncLLM instance
    """
    models_map = {
        "sonnet": {
            "bedrock": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            "anthropic": "claude-3-7-sonnet-20250219"
        },
        "haiku": {
            "bedrock": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
            "anthropic": "claude-3-5-haiku-20241022"
        },
    }

    client_params = client_params or {}

    match backend:
        case "bedrock":
            base_client = AsyncAnthropicBedrock(**(client_params or {}))
            client = AnthropicBedrockLLM(base_client)
        case "anthropic":
            base_client = AsyncAnthropic(**(client_params or {}))
            client = AnthropicLLM(base_client)
        case _:
            raise ValueError(f"Unknown backend: {backend}")

    if cache_mode != "off":
        return CachedLLM(client, cache_mode, cache_path)

    return client
