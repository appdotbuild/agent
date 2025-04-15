import itertools
import os
import logging
from typing import Literal, Dict, Tuple, Any
import anthropic
from anthropic import AnthropicBedrock, Anthropic, AsyncAnthropic, AsyncAnthropicBedrock
from llm.common import AsyncLLM, Message, TextRaw, ToolUse, ThinkingBlock, ContentBlock
from llm.anthropic_client import AnthropicLLM
from llm.anthropic_bedrock import AnthropicBedrockLLM
from llm.cached import CachedLLM, CacheMode
from log import get_logger

logger = get_logger(__name__)

# Cache for LLM clients
_llm_clients: Dict[Tuple[str, str, CacheMode, str, frozenset], AsyncLLM] = {}

LLMBackend = Literal["bedrock", "anthropic"]


def merge_text(content: list[ContentBlock]) -> list[ContentBlock]:
    merged = []
    for k, g in itertools.groupby(content, lambda x: isinstance(x, TextRaw)):
        if k and (text := "".join([x.text for x in g if isinstance(x, TextRaw)])) != "":
            merged.append(TextRaw(text))
        else:
            merged.extend(g)
    return merged


async def loop_completion(m_client: AsyncLLM, messages: list[Message], **kwargs) -> Message:
    content: list[ContentBlock] = []
    while True:
        payload = messages + [Message(role="assistant", content=content)] if content else messages
        completion = await m_client.completion(messages=payload, **kwargs)
        content.extend(completion.content)
        if completion.stop_reason != "max_tokens":
            break
    return Message(role="assistant", content=merge_text(content))


def _guess_llm_backend(model_name: str) -> LLMBackend:
    match model_name:
        case ("sonnet" | "haiku"):
            if os.getenv("AWS_SECRET_ACCESS_KEY") or os.getenv("PREFER_BEDROCK"):
                return "bedrock"
            if os.getenv("ANTHROPIC_API_KEY"):
                return "anthropic"
            # that is rare case, but may be non-trivial AWS config, try Bedrock again
            return "bedrock"
        case _:
            raise ValueError(f"Unknown model name: {model_name}")


def get_llm_client(
    backend: Literal["auto"] | LLMBackend = "auto",
    model_name: Literal["sonnet", "haiku"] = "sonnet",
    cache_mode: CacheMode = "off",
    cache_path: str = os.path.join(os.path.dirname(__file__), "../../../anthropic_cache.json"),
    client_params: dict | None = None,
) -> AsyncLLM:
    """Get a configured LLM client for the fullstack application.

    Creates a singleton LLM client based on the provided parameters.
    If a client with the same parameters already exists, it will be returned.

    Args:
        backend: LLM backend provider, either "bedrock" or "anthropic"
        model_name: Model name to use, either "sonnet" or "haiku"
        cache_mode: Cache mode, either "off", "record", or "replay"
        cache_path: Path to the cache file
        client_params: Additional parameters to pass to the client constructor

    Returns:
        An AsyncLLM instance
    """
    # Convert client_params dict to frozenset for caching
    client_params = client_params or {}
    params_key = frozenset(client_params.items())

    if backend == "auto":
        backend = _guess_llm_backend(model_name)
        logger.info(f"Auto-detected backend: {backend}")

    # Create a unique key for this client configuration
    cache_key = (backend, model_name, cache_mode, cache_path, params_key)

    # Return existing client if one exists with the same configuration
    if cache_key in _llm_clients:
        logger.debug(f"Returning existing LLM client for {backend}/{model_name}")
        return _llm_clients[cache_key]

    # Otherwise create a new client
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

    match backend:
        case "bedrock":
            base_client = AsyncAnthropicBedrock(**client_params)
            client = AnthropicBedrockLLM(base_client)
        case "anthropic":
            base_client = AsyncAnthropic(**client_params)
            client = AnthropicLLM(base_client)
        case _:
            raise ValueError(f"Unknown backend: {backend}")

    if cache_mode != "off":
        client = CachedLLM(client, cache_mode, cache_path)

    # Store the client in the cache
    _llm_clients[cache_key] = client
    logger.debug(f"Created new LLM client for {backend}/{model_name}")

    return client
