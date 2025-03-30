from typing import Union, TypeVar, Dict, Any, Optional, List, cast, Literal, Protocol
from anthropic.types import MessageParam, TextBlock, Message
from anthropic import AnthropicBedrock, Anthropic
from functools import partial
import json
import hashlib
import os
import logging
from pathlib import Path
from google import genai
from google.genai import types as genai_types

logger = logging.getLogger(__name__)

CacheMode = Literal["off", "record", "replay"]

# Define a protocol for client implementation
class ClientProtocol(Protocol):
    def messages(self):
        ...

    def __getattr__(self, name: str) -> Any:
        ...


class LLMClient:
    """Base client class with caching and other common functionality."""
    def __init__(self,
                 backend: str,
                 model_name: str,
                 cache_mode: CacheMode = "off",
                 cache_path: str = "llm_cache.json"):
        self.backend = backend
        self.short_model_name = model_name
        self.cache_mode = cache_mode
        self.cache_path = cache_path
        self._cache = self._load_cache() if cache_mode == "replay" else {}
        self._client = None  # Subclasses must initialize this
        self.model_name = None  # Subclasses should set this based on model mappings

        match self.cache_mode:
            case "replay":
                # Check if we have a cache file
                if not Path(self.cache_path).exists():
                    raise ValueError("Cache file not found, cannot run in replay mode")
            case "record":
                # clean up the cache file
                if Path(self.cache_path).exists():
                    Path(self.cache_path).unlink()

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
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with cache_file.open("w") as f:
            json.dump(self._cache, f, indent=2)

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
                case _:
                    return obj

        kwargs = {k: v for k, v in kwargs.items()}  # Make a copy
        kwargs.update({f"arg_{i}": arg for i, arg in enumerate(args)})

        # Extract only relevant parameters for the cache key
        normalized_kwargs = normalize(kwargs)
        key_str = json.dumps(normalized_kwargs, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    def __getattr__(self, name):
        if self._client is None:
            raise ValueError("Client not initialized")
        return getattr(self._client, name)


class AnthropicClient(LLMClient):
    def __init__(self,
                 backend: str = "bedrock",
                 model_name: str = "sonnet",
                 cache_mode: CacheMode = "off",
                 cache_path: str = "anthropic_cache.json"):
        super().__init__(backend, model_name, cache_mode, cache_path)

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
            },
            "haiku": {
                "bedrock": "us.anthropic.claude-3-5-haiku-20241022-v1:0",
                "anthropic": "claude-3-5-haiku-20241022"
            },
        }

        self.model_name = self.models_map[self.short_model_name][self.backend]

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
                    logger.info(f"Caching response with key: {cache_key}")
                    serialized_response = response.to_dict()
                    self._cache[cache_key] = serialized_response
                    self._save_cache()
                    return response
                case _:
                    return original_create(*args, **kwargs)

        original_messages.create = create_with_model_and_cache
        return original_messages


class GeminiClient(LLMClient):
    def __init__(self,
                 model_name: str = "gemini-pro",
                 cache_mode: CacheMode = "off",
                 cache_path: str = "gemini_cache.json",
                 api_key: str | None = None):
        super().__init__("gemini", model_name, cache_mode, cache_path)

        # Initialize the Gemini client
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY environment variable or api_key parameter is required")

        self._client = genai.Client(api_key=self._api_key)

        # Map friendly model names to actual model identifiers
        self.models_map = {
            "gemini-2.5-pro": "gemini-2.5-pro-exp-03-25",  # Using the experimental version from example
            "gemini-2.0-flash": "gemini-2.0-flash",
            "gemini-2.0-flash-thinking": "gemini-2.0-flash-thinking-exp-01-21"
        }

        # Set the model name based on the mapping
        if self.short_model_name in self.models_map:
            self.model_name = self.models_map[self.short_model_name]
        else:
            # If not in mapping, assume it's a direct model identifier
            self.model_name = self.short_model_name

    @property
    def messages(self):
        """Provide a compatible messages API like Anthropic's client."""
        # Create a mock messages object with a create method
        class Messages:
            def __init__(self, client, model_name, cache_mode, cache_path, cache, get_cache_key, save_cache):
                self.client = client
                self.model_name = model_name
                self.cache_mode = cache_mode
                self.cache_path = cache_path
                self._cache = cache
                self._get_cache_key = get_cache_key
                self._save_cache = save_cache

            def create(self, **kwargs):
                # Extract parameters
                messages = kwargs.get("messages", [])
                model = kwargs.get("model", self.model_name)
                max_tokens = kwargs.get("max_tokens", 1024)
                temperature = kwargs.get("temperature", 1.0)

                # Handle caching
                if self.cache_mode == "replay":
                    cache_key = self._get_cache_key(**kwargs)
                    if cache_key in self._cache:
                        logger.info(f"Cache hit: {cache_key}")
                        return self._cache[cache_key]
                    else:
                        raise ValueError(
                            "No cached response found for this request in replay mode. "
                            "Run in record mode first to populate the cache."
                        )

                # Convert messages to Gemini format
                gemini_contents = []
                for message in messages:
                    role = message.get("role", "user")
                    # Map Anthropic roles to Gemini roles
                    gemini_role = "model" if role == "assistant" else "user"

                    # Handle different content formats
                    content = message.get("content", "")
                    if isinstance(content, str):
                        parts = [genai_types.Part.from_text(text=content)]
                    else:
                        # Extract text from the content blocks
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                            elif hasattr(block, "text"):
                                text_parts.append(block.text)
                        parts = [genai_types.Part.from_text(text=" ".join(text_parts))]

                    gemini_contents.append(genai_types.Content(role=gemini_role, parts=parts))

                # Create the generation config
                config = genai_types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    response_mime_type="text/plain",
                )

                # Call the Gemini API
                response = self.client.models.generate_content(
                    model=model,
                    contents=gemini_contents,
                    config=config,
                )

                # Convert the response to a format similar to Anthropic's
                anthropic_response = {
                    "id": f"gemini-{hashlib.md5(str(response).encode()).hexdigest()}",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": response.text}],
                    "model": model,
                    "stop_reason": "end_turn",
                    "usage": {
                        "input_tokens": 0,  # Gemini doesn't provide these counts directly
                        "output_tokens": 0
                    }
                }

                # Handle recording mode
                if self.cache_mode == "record":
                    cache_key = self._get_cache_key(**kwargs)
                    logger.info(f"Caching response with key: {cache_key}")
                    self._cache[cache_key] = anthropic_response
                    self._save_cache()

                return Message.model_validate(anthropic_response)

        return Messages(
            self._client,
            self.model_name,
            self.cache_mode,
            self.cache_path,
            self._cache,
            self._get_cache_key,
            self._save_cache
        )


def get_sync_client(
    backend: str = "bedrock",
    model_name: str = "sonnet",
    cache_mode: CacheMode = "off",
    cache_path: str = os.path.join(os.path.dirname(__file__), "../../anthropic_cache.json"),
    api_key: str | None = None
) -> LLMClient:
    match backend:
        case "bedrock" | "anthropic":
            return AnthropicClient(
                backend=backend,
                model_name=model_name,
                cache_mode=cache_mode,
                cache_path=cache_path
            )
        case "gemini":
            gemini_cache_path = os.path.join(os.path.dirname(cache_path), "gemini_cache.json")
            return GeminiClient(
                model_name=model_name,
                cache_mode=cache_mode,
                cache_path=gemini_cache_path,
                api_key=api_key
            )
        case _:
            raise ValueError(f"Unknown backend: {backend}")


def pop_first_text(message: MessageParam):
    if isinstance(message["content"], str):
        return message["content"]
    for block in message["content"]:
        if isinstance(block, TextBlock):
            return block.text
    return None
