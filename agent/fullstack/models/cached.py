from typing import Literal, Dict, Any, List, Optional
import json
import hashlib
import logging
import asyncio
from pathlib import Path

from models.common import AsyncLLM, Completion, Message, Tool, TextRaw, ToolUse, ThinkingBlock

logger = logging.getLogger(__name__)

CacheMode = Literal["off", "record", "replay"]


class CachedLLM(AsyncLLM):
    """A wrapper around AsyncLLM that provides caching functionality with three modes:
    - off: No caching, pass-through to wrapped client
    - record: Record all requests and responses to cache file
    - replay: Replay responses from cache file without making real requests
    """

    def __init__(
        self,
        client: AsyncLLM,
        cache_mode: CacheMode = "off",
        cache_path: str = "llm_cache.json",
    ):
        self.client = client
        self.cache_mode = cache_mode
        self.cache_path = cache_path
        self._cache = self._load_cache() if cache_mode != "off" else {}

        # Handle caching modes
        match self.cache_mode:
            case "replay":
                # Check if we have a cache file
                if not Path(self.cache_path).exists():
                    raise ValueError("cache file not found, cannot run in replay mode")
            case "record":
                # Clean up the cache file if it exists
                if Path(self.cache_path).exists():
                    Path(self.cache_path).unlink()

    def _load_cache(self) -> Dict[str, Any]:
        """load cache from file if it exists, otherwise return empty dict."""
        cache_file = Path(self.cache_path)

        if cache_file.exists():
            try:
                with cache_file.open("r") as f:
                    return json.load(f)
            except Exception:
                logger.exception("failed to load cache file")
                return {}
        return {}

    def _save_cache(self) -> None:
        """save cache to file."""
        cache_file = Path(self.cache_path)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with cache_file.open("w") as f:
            json.dump(self._cache, f, indent=2)

    def _get_cache_key(self, **kwargs) -> str:
        """generate a consistent cache key from request parameters."""
        # Convert objects to dictionaries and sort recursively for consistent ordering
        def normalize(obj):
            match obj:
                case list() | tuple():
                    return [normalize(item) for item in obj]
                case dict():
                    return {k: normalize(v) for k, v in sorted(obj.items())}
                case _ if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
                    return normalize(obj.to_dict())
                case _:
                    return obj

        normalized_kwargs = normalize(kwargs)
        key_str = json.dumps(normalized_kwargs, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    async def completion(
        self,
        model: str,
        messages: List[Message],
        max_tokens: int,
        temperature: float = 1.0,
        tools: List[Tool] | None = None,
        tool_choice: str | None = None,
        *args,
        **kwargs,
    ) -> Completion:
        """performs LLM completion with caching support."""
        # Create a dict of all parameters for caching
        request_params = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        if tools is not None:
            request_params["tools"] = tools
        if tool_choice is not None:
            request_params["tool_choice"] = tool_choice

        # Handle additional kwargs
        for key, value in kwargs.items():
            request_params[key] = value

        # Handle different cache modes
        match self.cache_mode:
            case "off":
                # Just pass through to the real client
                return await self.client.completion(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    tools=tools,
                    tool_choice=tool_choice,
                    *args,
                    **kwargs
                )

            case "replay":
                # Try to get from cache
                cache_key = self._get_cache_key(**request_params)
                if cache_key in self._cache:
                    logger.info(f"cache hit: {cache_key}")
                    cached_response = self._cache[cache_key]

                    # Deserialize the cached completion
                    try:
                        # Reconstruct content items
                        content = []
                        for block in cached_response.get("content", []):
                            match block:
                                case {"type": "text", "text": text}:
                                    content.append(TextRaw(text))
                                case {"type": "tool_use", "name": name, "input": input, "id": id}:
                                    content.append(ToolUse(name, input, id))
                                case {"type": "thinking", "thinking": thinking}:
                                    content.append(ThinkingBlock(thinking))

                        return Completion(
                            role="assistant",
                            content=content,
                            input_tokens=cached_response.get("input_tokens", 0),
                            output_tokens=cached_response.get("output_tokens", 0),
                            stop_reason=cached_response.get("stop_reason", "end_turn"),
                            thinking_tokens=cached_response.get("thinking_tokens")
                        )
                    except Exception:
                        logger.exception("failed to reconstruct completion from cache")
                        raise ValueError(
                            "failed to reconstruct cached response; cache may be corrupted"
                        )
                else:
                    raise ValueError(
                        "no cached response found for this request in replay mode; "
                        "run in record mode first to populate the cache"
                    )

            case "record":
                # Call the client and store the result
                response = await self.client.completion(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    tools=tools,
                    tool_choice=tool_choice,
                    *args,
                    **kwargs
                )

                # Serialize the response for caching
                cache_key = self._get_cache_key(**request_params)
                logger.info(f"caching response with key: {cache_key}")

                # Serialize the content blocks
                content_dicts = []
                for block in response.content:
                    match block:
                        case TextRaw(text):
                            content_dicts.append({"type": "text", "text": text})
                        case ToolUse(name, input, id):
                            content_dicts.append({"type": "tool_use", "name": name, "input": input, "id": id})
                        case ThinkingBlock(thinking):
                            content_dicts.append({"type": "thinking", "thinking": thinking})

                # Create a serializable representation of the completion
                serialized = {
                    "role": response.role,
                    "content": content_dicts,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "stop_reason": response.stop_reason,
                }

                if response.thinking_tokens is not None:
                    serialized["thinking_tokens"] = response.thinking_tokens

                self._cache[cache_key] = serialized
                self._save_cache()
                return response

            case _:
                raise ValueError(f"unknown cache mode: {self.cache_mode}")


if __name__ == "__main__":
    import anthropic
    from models.anthropic_bedrock import AnthropicBedrockLLM

    async def test_cached_llm():
        # Create a base anthropic client
        client = anthropic.AsyncAnthropicBedrock()
        anthropic_llm = AnthropicBedrockLLM(client)

        # Wrap it with caching - record mode
        cache_path = "/tmp/test_cache.json"
        cached_llm = CachedLLM(
            client=anthropic_llm,
            cache_mode="record",
            cache_path=cache_path
        )

        # Create a simple test message
        test_message = Message(
            role="user",
            content=[TextRaw("Hello, world!")]
        )

        # Test with record mode
        print("Testing in record mode...")
        response = await cached_llm.completion(
            model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            messages=[test_message],
            max_tokens=100
        )
        print(f"Response received, tokens: {response.input_tokens} in, {response.output_tokens} out")
        for block in response.content:
            if isinstance(block, TextRaw):
                print(f"Response text: {block.text}...")

        # Now test with replay mode using the same cache file
        print("\nTesting in replay mode...")
        replay_cached_llm = CachedLLM(
            client=anthropic_llm,
            cache_mode="replay",
            cache_path=cache_path
        )

        replay_response = await replay_cached_llm.completion(
            model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            messages=[test_message],
            max_tokens=100
        )
        print(f"Cached response retrieved, tokens: {replay_response.input_tokens} in, {replay_response.output_tokens} out")
        for block in replay_response.content:
            if isinstance(block, TextRaw):
                print(f"Response text: {block.text}...")

        # test in off mode
        cached_llm_off = CachedLLM(
            client=anthropic_llm,
            cache_mode="off",
            cache_path=cache_path
        )
        off_response = await cached_llm_off.completion(
            model="us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            messages=[test_message],
            max_tokens=100
        )
        print(f"Off mode response received, tokens: {off_response.input_tokens} in, {off_response.output_tokens} out")
        for block in off_response.content:
            if isinstance(block, TextRaw):
                print(f"Response text: {block.text}...")

        print("Cache test successful!")

    # Run the test
    asyncio.run(test_cached_llm())
