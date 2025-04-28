from typing import Literal, Dict, Any, List
import ujson as json
import hashlib
from pathlib import Path
from llm.common import AsyncLLM, Completion, Message, Tool
import os
import anyio
from collections import OrderedDict

from log import get_logger
logger = get_logger(__name__)

CacheMode = Literal["off", "record", "replay", "auto", "lru"]


class CachedLLM(AsyncLLM):
    """A wrapper around AsyncLLM that provides caching functionality with four modes:
    - off: No caching, pass-through to wrapped client
    - record: Record all requests and responses to cache file
    - replay: Replay responses from cache file without making real requests
    - lru: Keep cache of N most recent invocations using LRU strategy; use cached response if available, otherwise call the model
    """

    def __init__(
        self,
        client: AsyncLLM,
        cache_path: str,
        cache_mode: CacheMode = "off",
        max_cache_size: int = 256,
    ):
        self.client = client
        match cache_mode:
            case "auto":
                effective_cache_mode = self._infer_cache_mode()
                logger.info(f"Inferred cache mode {effective_cache_mode}")
            case "replay" | "record" | "off" | "lru":
                effective_cache_mode = cache_mode
        self.cache_mode = effective_cache_mode
        self.cache_path = cache_path
        self.max_cache_size = max_cache_size
        self._cache: Dict[str, Any] = {}
        self._cache_lru: OrderedDict[str, None] = OrderedDict()
        self.lock = anyio.Lock()

        match (self.cache_mode, Path(self.cache_path)):
            case ("replay", file) if not file.exists():
                raise ValueError(f"cache file missing: {file}")
            case ("replay", file):
                logger.info(f"cache file found: {file}")
                self._cache = self._load_cache()
            case ("record", file):
                if file.exists():
                    logger.info(f"cache file already exists: {file}; wiping")
                    file.unlink()
                self._save_cache()
            case ("lru", file) if file.exists():
                logger.info(f"loading lru cache from: {file}")
                self._cache = self._load_cache()
                # Initialize LRU order from existing cache
                for key in self._cache:
                    self._cache_lru[key] = None

    @staticmethod
    def _infer_cache_mode():
        if env_mode := os.getenv("LLM_VCR_CACHE_MODE"):
            if env_mode in ["off", "record", "replay", "lru"]:
                return env_mode
            raise ValueError(f"invalid cache mode from env: {env_mode}")
        return "off"

    def _load_cache(self) -> Dict[str, Any]:
        """load cache from file if it exists, otherwise return empty dict."""
        if (cache_file := Path(self.cache_path)).exists():
            with cache_file.open("r") as f:
                if (content := f.read()):
                    return json.loads(content)
        return {}

    def _save_cache(self) -> None:
        """save cache to file."""
        cache_file = Path(self.cache_path)
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with cache_file.open("w") as f:
            json.dump(self._cache, f, indent=2)

    def _update_lru_cache(self, key: str) -> None:
        """Update the LRU cache order and ensure it stays within size limit."""
        # Move to end (most recently used) or add if not present
        self._cache_lru.pop(key, None)
        self._cache_lru[key] = None

        # Evict oldest entries if we exceed max cache size
        while len(self._cache_lru) > self.max_cache_size:
            oldest_key, _ = self._cache_lru.popitem(last=False)
            self._cache.pop(oldest_key, None)
            logger.debug(f"Evicted oldest cache entry: {oldest_key}")

    def _get_cache_key(self, **kwargs) -> str:
        """generate a consistent cache key from request parameters."""
        # Convert objects to dictionaries and sort recursively for consistent ordering
        def normalize(obj):
            match obj:
                case list() | tuple():
                    return [normalize(item) for item in obj]
                case dict():
                    # Replace 'id' values with a placeholder
                    normalized_dict = {}
                    for k, v in sorted(obj.items()):
                        if k == "id":
                            normalized_dict[k] = "__ID_PLACEHOLDER__"
                        else:
                            normalized_dict[k] = normalize(v)
                    return normalized_dict
                case _ if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
                    return normalize(obj.to_dict())
                case _:
                    return obj

        normalized_kwargs = normalize(kwargs)
        key_str = json.dumps(normalized_kwargs, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    async def completion(
        self,
        messages: List[Message],
        max_tokens: int = 8192,
        model: str | None = None,
        temperature: float = 1.0,
        tools: List[Tool] | None = None,
        tool_choice: str | None = None,
        *args,
        **kwargs,
    ) -> Completion:
        """performs LLM completion with caching support."""
        if args:
            raise RuntimeError("args are not expected in this method, use kwargs instead")
        # Create a dict of all parameters for caching
        request_params = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "tools": tools,
            "tool_choice": tool_choice,
            **kwargs,
        }

        match self.cache_mode:
            case "off":
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
                return response

            case "record":
                async with self.lock:
                    cache_key = self._get_cache_key(**request_params)
                    logger.info(f"Caching response with key: {cache_key}")
                    if cache_key in self._cache:
                        logger.info("Fetching from cache")
                        return Completion.from_dict(self._cache[cache_key])
                    else:
                        response = await self.client.completion(
                            model=model,
                            messages=messages,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            tools=tools,
                            tool_choice=tool_choice,
                            **kwargs
                        )
                        self._cache[cache_key] = response.to_dict()
                        self._save_cache()
                    return response

            case "lru":
                async with self.lock:
                    cache_key = self._get_cache_key(**request_params)
                    if cache_key in self._cache:
                        logger.info(f"lru cache hit: {cache_key}")
                        self._update_lru_cache(cache_key)
                        return Completion.from_dict(self._cache[cache_key])
                    else:
                        logger.info(f"lru cache miss: {cache_key}")
                        response = await self.client.completion(
                            model=model,
                            messages=messages,
                            max_tokens=max_tokens,
                            temperature=temperature,
                            tools=tools,
                            tool_choice=tool_choice,
                            **kwargs
                        )
                        self._cache[cache_key] = response.to_dict()
                        self._update_lru_cache(cache_key)
                        return response

            case "replay":
                cache_key = self._get_cache_key(**request_params)
                if cache_key in self._cache:
                    logger.info(f"cache hit: {cache_key}")
                    cached_response = self._cache[cache_key]
                    return Completion.from_dict(cached_response)
                else:
                    raise ValueError(
                        "no cached response found for this request in replay mode; "
                        f"run in record mode first to populate the cache. cache_key: {cache_key}"
                    )
            case _:
                raise ValueError(f"unknown cache mode: {self.cache_mode}")
