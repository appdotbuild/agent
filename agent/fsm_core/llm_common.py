from typing import Union, TypeVar, Dict, Any, Optional, List, cast, Literal, Protocol, Type, TypedDict, Generic
from anthropic.types import MessageParam, TextBlock, Message
from anthropic import AnthropicBedrock, Anthropic
from anthropic import AsyncAnthropic, AsyncAnthropicBedrock
from functools import partial
import json
import hashlib
import os
import logging
import asyncio
from pathlib import Path
from google import genai
from google.genai import types as genai_types
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

CacheMode = Literal["off", "record", "replay"]


class LLMClient(ABC):
    """Base client class with caching and other common functionality."""
    def __init__(self,
                 backend: Literal["bedrock", "anthropic", "gemini"],
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
        normalized_kwargs = normalize(kwargs)
        key_str = json.dumps(normalized_kwargs, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()

    def __getattr__(self, name):
        if self._client is None:
            raise ValueError("Client not initialized")
        return getattr(self._client, name)

    def handle_cached_response(self, cached_response):
        """Handle reconstructing objects from cached responses."""
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


class AnthropicMixin:
    """Mixin for Anthropic-specific functionality."""

    def init_anthropic_models(self):
        """Initialize the model mapping for Anthropic."""
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


class GeminiMixin:
    """Mixin for Gemini-specific functionality."""

    def init_gemini_models(self, api_key=None):
        """Initialize the Gemini client and model mappings."""
        # Initialize the API key
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY environment variable or api_key parameter is required")

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

    def _convert_messages_to_gemini_format(self, messages):
        """Convert messages from Anthropic format to Gemini format."""
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

        return gemini_contents

    def _format_gemini_response(self, response, model):
        """Format Gemini response to match Anthropic's format."""
        # Handle the response text more robustly
        response_text = ""
        if hasattr(response, "text"):
            response_text = response.text if response.text is not None else ""
        elif hasattr(response, "parts") and len(response.parts) > 0:
            response_text = " ".join([p.text for p in response.parts if hasattr(p, "text") and p.text])
        elif hasattr(response, "candidates") and len(response.candidates) > 0 and hasattr(response.candidates[0], "content"):
            content = response.candidates[0].content
            if hasattr(content, "parts") and len(content.parts) > 0:
                response_text = " ".join([p.text for p in content.parts if hasattr(p, "text") and p.text])

        anthropic_response = {
            "id": f"gemini-{hashlib.md5(str(response).encode()).hexdigest()}",
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": response_text}],
            "model": model,
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": 0,  # Gemini doesn't provide these counts directly
                "output_tokens": 0
            }
        }
        return anthropic_response


class AnthropicClient(AnthropicMixin, LLMClient):
    """Synchronous Anthropic client implementation."""

    def __init__(self,
                backend: Literal["bedrock", "anthropic"] = "bedrock",
                model_name: Literal["sonnet", "haiku"] = "sonnet",
                cache_mode: CacheMode = "off",
                cache_path: str = "anthropic_cache.json"):
        super().__init__(backend, model_name, cache_mode, cache_path)
        self.init_anthropic_models()

        match backend:
            case "bedrock":
                self._client = AnthropicBedrock()
            case "anthropic":
                self._client = Anthropic()
            case _:
                raise ValueError(f"Unknown backend: {backend}")

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
                        return self.handle_cached_response(cached_response)
                    else:
                        raise ValueError(
                            "No cached response found for this request in replay mode. "
                            "Rerun in record mode first to populate the cache if there were relevant changes."
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


class AsyncAnthropicClient(AnthropicMixin, LLMClient):
    """Asynchronous Anthropic client implementation."""

    def __init__(self,
                backend: Literal["bedrock", "anthropic"] = "bedrock",
                model_name: Literal["sonnet", "haiku"] = "sonnet",
                cache_mode: CacheMode = "off",
                cache_path: str = "anthropic_cache.json"):
        super().__init__(backend, model_name, cache_mode, cache_path)
        self.init_anthropic_models()

        match backend:
            case "bedrock":
                self._client = AsyncAnthropicBedrock()
            case "anthropic":
                self._client = AsyncAnthropic()
            case _:
                raise ValueError(f"Unknown backend: {backend}")

    @property
    def messages(self):
        """Access the messages property but with our customized create method."""
        original_messages = self._client.messages
        original_create = original_messages.create

        # Replace the create method with one that automatically uses our model
        # and adds caching support
        async def create_with_model_and_cache(*args, **kwargs):
            model_id = self.models_map[self.short_model_name][self.backend]
            if 'model' not in kwargs:
                kwargs['model'] = model_id

            # Handle different cache modes
            match self.cache_mode:
                case "off":
                    return await original_create(*args, **kwargs)
                case "replay":
                    cache_key = self._get_cache_key(*args, **kwargs)
                    if cache_key in self._cache:
                        logger.info(f"Cache hit: {cache_key}")
                        cached_response = self._cache[cache_key]
                        return self.handle_cached_response(cached_response)
                    else:
                        raise ValueError(
                            "No cached response found for this request in replay mode. "
                            "Rerun in record mode first to populate the cache if there were relevant changes."
                        )
                case "record":
                    response = await original_create(*args, **kwargs)
                    cache_key = self._get_cache_key(**kwargs)
                    logger.info(f"Caching response with key: {cache_key}")
                    serialized_response = response.to_dict()
                    self._cache[cache_key] = serialized_response
                    self._save_cache()
                    return response
                case _:
                    return await original_create(*args, **kwargs)

        original_messages.create = create_with_model_and_cache
        return original_messages


class GeminiClient(GeminiMixin, LLMClient):
    """Synchronous Gemini client implementation."""

    def __init__(self,
                model_name: Literal["gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-thinking", "gemma-3-27b-it"] = "gemini-2.5-pro",
                cache_mode: CacheMode = "off",
                cache_path: str = "gemini_cache.json",
                api_key: str | None = None):
        super().__init__("gemini", model_name, cache_mode, cache_path)
        self.init_gemini_models(api_key)
        self._client = genai.Client(api_key=self._api_key)

    @property
    def messages(self):
        """Provide a compatible messages API like Anthropic's client."""
        class Messages:
            def __init__(self, parent):
                self.parent = parent

            def create(self, **kwargs):
                # Extract parameters
                messages = kwargs.get("messages", [])
                model = kwargs.get("model", self.parent.model_name)
                max_tokens = kwargs.get("max_tokens", 1024)
                temperature = kwargs.get("temperature", 1.0)

                # Handle caching
                if self.parent.cache_mode == "replay":
                    cache_key = self.parent._get_cache_key(**kwargs)
                    if cache_key in self.parent._cache:
                        logger.info(f"Cache hit: {cache_key}")
                        return self.parent.handle_cached_response(self.parent._cache[cache_key])
                    else:
                        raise ValueError(
                            "No cached response found for this request in replay mode. "
                            "Run in record mode first to populate the cache."
                        )

                # Convert messages to Gemini format
                gemini_contents = self.parent._convert_messages_to_gemini_format(messages)

                # Create the generation config
                config = genai_types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    response_mime_type="text/plain",
                )

                # Call the Gemini API
                response = self.parent._client.models.generate_content(
                    model=model,
                    contents=gemini_contents,
                    config=config,
                )

                # Convert the response to Anthropic format
                anthropic_response = self.parent._format_gemini_response(response, model)

                # Handle recording mode
                if self.parent.cache_mode == "record":
                    cache_key = self.parent._get_cache_key(**kwargs)
                    logger.info(f"Caching response with key: {cache_key}")
                    self.parent._cache[cache_key] = anthropic_response
                    self.parent._save_cache()

                return Message.model_validate(anthropic_response)

        return Messages(self)


class AsyncGeminiClient(GeminiMixin, LLMClient):
    """Asynchronous Gemini client implementation using native async API."""

    def __init__(self,
                model_name: Literal["gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-thinking", "gemma-3-27b-it"] = "gemini-2.5-pro",
                cache_mode: CacheMode = "off",
                cache_path: str = "gemini_cache.json",
                api_key: str | None = None):
        super().__init__("gemini", model_name, cache_mode, cache_path)
        self.init_gemini_models(api_key)
        # Use the sync client for init and then access the async client via aio
        self._client = genai.Client(api_key=self._api_key)
        # Store reference to async client
        self._async_client = self._client.aio

    @property
    def messages(self):
        """Provide a compatible messages API like Anthropic's client."""
        # Create a mock messages object with a create method
        class Messages:
            def __init__(self, parent):
                self.parent = parent

            async def create(self, **kwargs):
                # Extract parameters
                messages = kwargs.get("messages", [])
                model = kwargs.get("model", self.parent.model_name)
                max_tokens = kwargs.get("max_tokens", 1024)
                temperature = kwargs.get("temperature", 1.0)

                # Handle caching
                if self.parent.cache_mode == "replay":
                    cache_key = self.parent._get_cache_key(**kwargs)
                    if cache_key in self.parent._cache:
                        logger.info(f"Cache hit: {cache_key}")
                        return self.parent.handle_cached_response(self.parent._cache[cache_key])
                    else:
                        raise ValueError(
                            "No cached response found for this request in replay mode. "
                            "Run in record mode first to populate the cache."
                        )

                # Convert messages to Gemini format
                gemini_contents = self.parent._convert_messages_to_gemini_format(messages)

                # Create the generation config
                config = genai_types.GenerateContentConfig(
                    max_output_tokens=max_tokens,
                    temperature=temperature,
                    response_mime_type="text/plain",
                )

                # Call the Gemini API using the native async client
                response = await self.parent._async_client.models.generate_content(
                    model=model,
                    contents=gemini_contents,
                    config=config,
                )

                # Convert the response to Anthropic format
                anthropic_response = self.parent._format_gemini_response(response, model)

                # Handle recording mode
                if self.parent.cache_mode == "record":
                    cache_key = self.parent._get_cache_key(**kwargs)
                    logger.info(f"Caching response with key: {cache_key}")
                    self.parent._cache[cache_key] = anthropic_response
                    self.parent._save_cache()

                return Message.model_validate(anthropic_response)

        return Messages(self)


def get_sync_client(
    backend: Literal["bedrock", "anthropic", "gemini"] = "bedrock",
    model_name: Literal["sonnet", "haiku", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-thinking", "gemma-3-27b-it"] = "sonnet",
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


def get_async_client(
    backend: Literal["bedrock", "anthropic", "gemini"] = "bedrock",
    model_name: Literal["sonnet", "haiku", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-thinking", "gemma-3-27b-it"] = "sonnet",
    cache_mode: CacheMode = "off",
    cache_path: str = os.path.join(os.path.dirname(__file__), "../../anthropic_cache.json"),
    api_key: str | None = None
) -> LLMClient:
    match backend:
        case "bedrock" | "anthropic":
            return AsyncAnthropicClient(
                backend=backend,
                model_name=model_name,
                cache_mode=cache_mode,
                cache_path=cache_path
            )
        case "gemini":
            gemini_cache_path = os.path.join(os.path.dirname(cache_path), "gemini_cache.json")
            return AsyncGeminiClient(
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
