from typing import Union, TypeVar, Dict, Any, Optional, List, cast, Literal
from anthropic.types import MessageParam, TextBlock, Message
from anthropic import AnthropicBedrock, Anthropic
from functools import partial
import json
import hashlib
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Define cache modes
CacheMode = Literal["off", "record", "replay"]

# Define a generic type for Anthropic clients

class AnthropicClient:
    def __init__(self,
                 backend: str = "bedrock",
                 model_name: str = "sonnet",
                 cache_mode: CacheMode = "off",
                 cache_path: str = "anthropic_cache.json"):
        self.backend = backend
        self.short_model_name = model_name
        self.cache_mode = cache_mode
        self.cache_path = cache_path
        self._cache = self._load_cache() if cache_mode == "replay" else {}

        match backend:
            case "bedrock":
                self._client = AnthropicBedrock()
            case "anthropic":
                self._client = Anthropic()
            case _:
                raise ValueError(f"Unknown backend: {backend}")

        self.models_map = {
            "sonnet": {
                "bedrock": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
                "anthropic": "claude-3-7-sonnet-20250219"
            }
        }

        self.model_name = self.models_map[self.short_model_name][self.backend]

    def _load_cache(self) -> Dict[str, Any]:
        """Load cache from file if it exists, otherwise return empty dict."""
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
        """Save cache to file."""
        cache_file = Path(self.cache_path)

        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with cache_file.open("w") as f:
                json.dump(self._cache, f, indent=2)
        except Exception:
            logger.exception("failed to save cache file")

    def _get_cache_key(self, *args, **kwargs) -> str:
        """Generate a consistent cache key from request parameters."""
        # Convert objects to dictionaries and sort recursively for consistent ordering
        def normalize(obj):
            match obj:
                case list() | tuple():
                    return [normalize(item) for item in obj]
                case dict():
                    return {k: normalize(v) for k, v in sorted(obj.items())}
                case _ if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict")):
                    return normalize(obj.to_dict())
                case _ if hasattr(obj, "model_dump") and callable(getattr(obj, "model_dump")):
                    return normalize(obj.model_dump())
                case _:
                    return obj

        kwargs = {k: v for k, v in kwargs.items()}  # Make a copy
        kwargs.update({f"arg_{i}": arg for i, arg in enumerate(args)})

        # Extract only relevant parameters for the cache key
        normalized_kwargs = normalize(kwargs)
        key_dict = {
            "model": normalized_kwargs.get("model", ""),
            "messages": normalized_kwargs.get("messages", []),
            "system": normalized_kwargs.get("system", ""),
            "max_tokens": normalized_kwargs.get("max_tokens", None),
            "temperature": normalized_kwargs.get("temperature", None),
            "tools": normalized_kwargs.get("tools", []),
        }

        # Use a stable string representation and hash it
        try:
            key_str = json.dumps(key_dict, sort_keys=True)
            return hashlib.md5(key_str.encode()).hexdigest()
        except (TypeError, ValueError) as e:
            logger.exception("failed to create cache key")
            # Fallback: use a unique timestamp if serialization fails
            return f"fallback-{hash(str(key_dict))}"

    @property
    def messages(self):
        """Access the messages property but with our customized create method."""
        original_messages = self._client.messages
        original_create = original_messages.create

        # Replace the create method with one that automatically uses our model
        # and adds caching support
        def create_with_model_and_cache(*args, **kwargs):
            model_id = self.models_map[self.short_model_name][self.backend]
            if 'model' not in kwargs:
                kwargs['model'] = model_id

            # Handle different cache modes
            match self.cache_mode:
                case "off":
                    return original_create(*args, **kwargs)

                case "replay":
                    cache_key = self._get_cache_key(*args, **kwargs)
                    if cache_key in self._cache:
                        logger.info(f"Cache hit: {cache_key}")
                        cached_response = self._cache[cache_key]

                        # Check if we need to reconstruct an object
                        if isinstance(cached_response, dict) and "type" in cached_response:
                            # This is likely a serialized Anthropic response
                            try:
                                from anthropic.types import Message
                                # Try to reconstruct the Message object
                                if cached_response.get("type") == "message":
                                    return Message.model_validate(cached_response)
                            except (ImportError, ValueError):
                                logger.warning("failed to reconstruct response object, returning raw cache")

                        return cached_response
                    else:
                        raise ValueError(
                            "No cached response found for this request in replay mode. "
                            "Run in record mode first to populate the cache."
                        )

                case "record":
                    response = original_create(*args, **kwargs)
                    cache_key = self._get_cache_key(**kwargs)

                    # Try to serialize the response
                    try:
                        if hasattr(response, "to_dict") and callable(getattr(response, "to_dict")):
                            serialized_response = response.to_dict()
                        else:
                            # Check if directly serializable
                            json.dumps(response)
                            serialized_response = response

                        self._cache[cache_key] = serialized_response
                        self._save_cache()
                    except (TypeError, ValueError):
                        logger.exception("response not serializable for cache")
                        raise ValueError("Response cannot be serialized for caching. "
                                         "Implement to_dict() method for custom objects.")

                    return response

                case _:
                    return original_create(*args, **kwargs)

        original_messages.create = create_with_model_and_cache
        return original_messages

    def __getattr__(self, name):
        return getattr(self._client, name)


def get_sync_client(
    backend: str = "bedrock",
    model_name: str = "sonnet",
    cache_mode: CacheMode = "off",
    cache_path: str = "anthropic_cache.json"
) -> AnthropicClient:
    return AnthropicClient(
        backend=backend,
        model_name=model_name,
        cache_mode=cache_mode,
        cache_path=cache_path
    )


def pop_first_text(message: MessageParam):
    if isinstance(message["content"], str):
        return message["content"]
    for block in message["content"]:
        if isinstance(block, TextBlock):
            return block.text
    return None
