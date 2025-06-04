from typing import Literal, Dict, Any, List, Tuple
import ujson as json
from pathlib import Path
from llm.common import AsyncLLM, Completion, Message, Tool
import os
import anyio
from collections import OrderedDict
import hashlib
import difflib

from log import get_logger

logger = get_logger(__name__)

CacheMode = Literal["off", "record", "replay", "auto", "lru"]


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
                elif k == "cache_control":
                    # ignore cache_control field used to control caching
                    pass
                elif hasattr(v, "cache_key"):
                    normalized_dict[k] = v.cache_key
                else:
                    normalized_dict[k] = normalize(v)
            return normalized_dict
        case _ if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
            return normalize(obj.to_dict())
        case _:
            return obj


def find_closest_dict(target: dict, candidates: list[dict]):
    if not candidates:
        return None

    target_str = json.dumps(target, sort_keys=True)
    candidate_strs = [json.dumps(c, sort_keys=True) for c in candidates]
    similarity = [difflib.SequenceMatcher(None, target_str, c_str).ratio()
                  for c_str in candidate_strs]

    max_index = similarity.index(max(similarity))
    return max_index


def find_closest_str(s: str, index: list[str]) -> str:
    # can be used for debugging cache issues; disable the hashing in _get_cache_key before
    similarity = [difflib.SequenceMatcher(None, s, i).ratio() for i in index]
    max_index = similarity.index(max(similarity))
    return index[max_index]


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
        self._pending_requests: Dict[str, anyio.Event] = {}

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
                if content := f.read():
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

    @staticmethod
    def _get_cache_key(**kwargs) -> Tuple[Any, str]:
        """generate a consistent cache key from request parameters."""
        normalized_kwargs = normalize(kwargs)
        key_str = json.dumps(normalized_kwargs, sort_keys=True)
        return normalized_kwargs, hashlib.md5(key_str.encode()).hexdigest()

    def report_closest_cache_key(self, cache_key: str, norm_params: dict) -> None:
        cache = list(self._cache.items())
        idx = find_closest_dict(norm_params, [x[1]['params'] for x in cache])
        if idx is None:
            logger.error(f"Cache miss by {self.client.__class__.__name__} - probably empty cache")
            return
        cache_params = cache[idx][1]['params']

        def _compare(x, y, prefix=""):
            if isinstance(x, dict):
                for k in x:
                    _compare(x[k], y[k], prefix + f"['{k}']")
            elif isinstance(x, list):
                if not len(x) == len(y):
                    logger.info(f"Length mismatch at {prefix}: {len(x)} != {len(y)}")
                for i in range(min(len(x), len(y))):
                    _compare(x[i], y[i], prefix + f"[{i}]")
            elif isinstance(x, str):
                try:
                    x_dec = eval(x)
                    y_dec = eval(y)
                    _compare(x_dec, y_dec, prefix + "(eval)")
                except (SyntaxError, NameError, UnicodeEncodeError):
                    eq = x == y
                    if not eq:
                        logger.info(f"Mismatch at {prefix}")
            else:
                eq = x == y
                if not eq:
                    logger.info(f"Mismatch at {prefix}")

        _compare(norm_params, cache_params)
        return cache_params

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
                    **kwargs,
                )
                return response

            case "record":
                norm_params, cache_key = self._get_cache_key(**request_params)
                logger.info(f"Caching response with key: {cache_key}")
                
                # Check cache and pending requests
                event = None
                make_request = False
                async with self.lock:
                    if cache_key in self._cache:
                        logger.info("Fetching from cache")
                        return Completion.from_dict(self._cache[cache_key]["data"])
                    elif cache_key in self._pending_requests:
                        # Another coroutine is already making this request
                        event = self._pending_requests[cache_key]
                    else:
                        # We'll make the request
                        event = anyio.Event()
                        self._pending_requests[cache_key] = event
                        make_request = True
                
                if not make_request:
                    # Wait for the other coroutine to complete
                    await event.wait()
                    async with self.lock:
                        return Completion.from_dict(self._cache[cache_key]["data"])
                
                try:
                    # Make API call without holding lock
                    response = await self.client.completion(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        tools=tools,
                        tool_choice=tool_choice,
                        **kwargs,
                    )
                    
                    # Update cache with lock
                    async with self.lock:
                        self._cache[cache_key] = {"data": response.to_dict(), "params": norm_params}
                        self._save_cache()
                        del self._pending_requests[cache_key]
                    
                    # Signal waiting coroutines
                    event.set()
                    return response
                except Exception:
                    # Clean up on error
                    async with self.lock:
                        del self._pending_requests[cache_key]
                    event.set()
                    raise

            case "lru":
                norm_params, cache_key = self._get_cache_key(**request_params)
                
                # Check cache and pending requests
                event = None
                make_request = False
                async with self.lock:
                    if cache_key in self._cache:
                        logger.info(f"lru cache hit: {cache_key}")
                        self._update_lru_cache(cache_key)
                        return Completion.from_dict(self._cache[cache_key]['data'])
                    elif cache_key in self._pending_requests:
                        # Another coroutine is already making this request
                        event = self._pending_requests[cache_key]
                    else:
                        # We'll make the request
                        event = anyio.Event()
                        self._pending_requests[cache_key] = event
                        make_request = True
                
                logger.info(f"lru cache miss: {cache_key}")
                
                if not make_request:
                    # Wait for the other coroutine to complete
                    await event.wait()
                    async with self.lock:
                        self._update_lru_cache(cache_key)
                        return Completion.from_dict(self._cache[cache_key]['data'])
                
                try:
                    # Make API call without holding lock
                    response = await self.client.completion(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        tools=tools,
                        tool_choice=tool_choice,
                        **kwargs,
                    )
                    
                    # Update cache with lock
                    async with self.lock:
                        self._cache[cache_key] = {"data": response.to_dict(), "params": norm_params}
                        self._update_lru_cache(cache_key)
                        del self._pending_requests[cache_key]
                    
                    # Signal waiting coroutines
                    event.set()
                    return response
                except Exception:
                    # Clean up on error
                    async with self.lock:
                        del self._pending_requests[cache_key]
                    event.set()
                    raise

            case "replay":
                norm_params, cache_key = self._get_cache_key(**request_params)
                if cache_key in self._cache:
                    logger.info(f"cache hit: {cache_key}")
                    cached_response = self._cache[cache_key]["data"]
                    return Completion.from_dict(cached_response)
                else:
                    self.report_closest_cache_key(cache_key, norm_params)
                    logger.error(f"Cache miss by {self.client.__class__.__name__}: {normalize(request_params)}")
                    raise ValueError(
                        f"No cached response found for this request in replay mode; "
                        f"run in record mode first to populate the cache. Cache_key: {cache_key}"
                    )
            case _:
                raise ValueError(f"unknown cache mode: {self.cache_mode}")
