from typing import Union, TypeVar, Dict, Any, Optional, List, cast, Literal, Protocol, TypedDict, NotRequired
from anthropic.types import MessageParam, TextBlock, Message
from anthropic import AnthropicBedrock, Anthropic, AsyncAnthropic, AsyncAnthropicBedrock
from functools import partial
import json
import hashlib
import os
import logging
from pathlib import Path
from google import genai
from google.genai import types as genai_types
import boto3
from abc import abstractmethod

logger = logging.getLogger(__name__)

CacheMode = Literal["off", "record", "replay"]

GeminiModelType = Literal["gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-thinking", "gemma-3-27b-it"]
AnthropicModelType = Literal["sonnet", "haiku"]
DeepseekModelType = Literal["deepseek-r1"]
BackendType = Literal["bedrock", "anthropic", "gemini"]


class LLMClient:
    """Base client class with caching and other common functionality."""
    def __init__(self,
                 backend: BackendType,
                 model_name: str,
                 cache_mode: CacheMode = "off",
                 cache_path: str = "llm_cache.json",
                 client_params: dict = {}):
        self.backend = backend
        self.short_model_name = model_name
        self.cache_mode = cache_mode
        self.cache_path = cache_path
        self._client_params = client_params or {}
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

    @abstractmethod
    def async_create(self, *args, **kwargs):
        raise NotImplementedError("async_create method must be implemented in subclass")


class AnthropicClient(LLMClient):
    def __init__(self,
                 backend: Literal["bedrock", "anthropic"] = "bedrock",
                 model_name: Literal["sonnet", "haiku"] = "sonnet",
                 cache_mode: CacheMode = "off",
                 cache_path: str = "anthropic_cache.json",
                 client_params: dict = {}):
        super().__init__(backend, model_name, cache_mode, cache_path, client_params=client_params)

        match backend:
            case "bedrock":
                self._client = AnthropicBedrock(**(client_params or {}))
                self._async_client = AsyncAnthropicBedrock(**(client_params or {}))
            case "anthropic":
                self._client = Anthropic(**(client_params or {}))
                self._async_client = AsyncAnthropic(**(client_params or {}))
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
                    raise ValueError(f"Unknown cache mode: {self.cache_mode}")

        original_messages.create = create_with_model_and_cache
        return original_messages

    @property
    async def async_create(self):
        """Access the async_messages property but with our customized async_create method."""

        async def original_create(*args, **kwargs):
            return await self._async_client.messages.create(*args, **kwargs)

        # Replace the async_create method with one that automatically uses our model
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
                    response = await original_create(*args, **kwargs)
                    cache_key = self._get_cache_key(**kwargs)
                    logger.info(f"Caching response with key: {cache_key}")
                    serialized_response = response.to_dict()
                    self._cache[cache_key] = serialized_response
                    self._save_cache()
                    return response
                case _:
                    raise ValueError(f"Unknown cache mode: {self.cache_mode}")

        return create_with_model_and_cache

class GeminiClient(LLMClient):
    def __init__(self,
                 model_name: Literal["gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-thinking", "gemma-3-27b-it"] = "gemini-2.5-pro",
                 cache_mode: CacheMode = "off",
                 cache_path: str = "gemini_cache.json",
                 api_key: str | None = None,
                 client_params: dict = {}
                 ):
        super().__init__("gemini", model_name, cache_mode, cache_path, client_params=client_params)

        # Initialize the Gemini client
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY environment variable or api_key parameter is required")

        self._client = genai.Client(api_key=self._api_key, **(client_params or {}))
        self._async_client = self._client.aio

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



    def _convert_message(self, message: dict) -> genai_types.Content:
        match message.get("role", "user"):
            case "assistant":
                gemini_role = "model"
            case _:
                gemini_role = "user"
        content = message.get("content", "")
        match content:
            case str():
                parts = [genai_types.Part.from_text(text=content)]
            case list():
                text_parts = []
                for block in content:
                    match block:
                        case dict() if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        case _ if hasattr(block, "text"):
                            text_parts.append(block.text)
                        case _:
                            ...
                parts = [genai_types.Part.from_text(text=" ".join(text_parts))]
            case _:
                parts = [genai_types.Part.from_text(text=str(content))]
        return genai_types.Content(role=gemini_role, parts=parts)

    def _convert_messages_to_gemini(self, messages: List[dict]) -> List[genai_types.Content]:
        return [self._convert_message(message) for message in messages]

    def _build_anthropic_response(self, response, model_id: str) -> dict:
        response_id = f"gemini-{hashlib.md5(str(response).encode()).hexdigest()}"
        return {
            "id": response_id,
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": response.text}],
            "model": model_id,
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 0, "output_tokens": 0}
        }

    @property
    def messages(self):
        def create_with_model_and_cache(**kwargs):
            kwargs.setdefault("model", self.model_name)
            match self.cache_mode:
                case "replay":
                    cache_key = self._get_cache_key(**kwargs)
                    if cache_key in self._cache:
                        logger.info(f"Cache hit: {cache_key}")
                        cached_response = self._cache[cache_key]
                        match cached_response:
                            case dict() if cached_response.get("type") == "message":
                                try:
                                    return Message.model_validate(cached_response)
                                except (ImportError, ValueError):
                                    logger.warning("Reconstruction failed, returning raw cache")
                            case _:
                                return cached_response
                    raise ValueError(
                        "No cached response found in replay mode. Populate cache in record mode first."
                    )
                case "record":
                    gemini_contents = self._convert_messages_to_gemini(kwargs.get("messages", []))
                    config = genai_types.GenerateContentConfig(
                        max_output_tokens=kwargs.get("max_tokens", 1024),
                        temperature=kwargs.get("temperature", 1.0),
                        response_mime_type="text/plain",
                    )
                    response = self._client.models.generate_content(
                        model=kwargs["model"],
                        contents=gemini_contents,
                        config=config,
                    )
                    anthropic_response = self._build_anthropic_response(response, kwargs["model"])
                    cache_key = self._get_cache_key(**kwargs)
                    logger.info(f"Caching response with key: {cache_key}")
                    self._cache[cache_key] = anthropic_response
                    self._save_cache()
                    return Message.model_validate(anthropic_response)
                case _:
                    gemini_contents = self._convert_messages_to_gemini(kwargs.get("messages", []))
                    config = genai_types.GenerateContentConfig(
                        max_output_tokens=kwargs.get("max_tokens", 1024),
                        temperature=kwargs.get("temperature", 1.0),
                        response_mime_type="text/plain",
                    )
                    response = self._client.models.generate_content(
                        model=kwargs["model"],
                        contents=gemini_contents,
                        config=config,
                    )
                    anthropic_response = self._build_anthropic_response(response, kwargs["model"])
                    return Message.model_validate(anthropic_response)

        class GeminiMessages:
            def __init__(self, create_func):
                self.create = create_func

        return GeminiMessages(create_with_model_and_cache)

    @property
    async def async_create(self):
        async def create_with_model_and_cache(**kwargs):
            kwargs.setdefault("model", self.model_name)
            match self.cache_mode:
                case "replay":
                    cache_key = self._get_cache_key(**kwargs)
                    if cache_key in self._cache:
                        logger.info(f"Cache hit: {cache_key}")
                        cached_response = self._cache[cache_key]
                        match cached_response:
                            case dict() if cached_response.get("type") == "message":
                                try:
                                    return Message.model_validate(cached_response)
                                except (ImportError, ValueError):
                                    logger.warning("Reconstruction failed, returning raw cache")
                            case _:
                                return cached_response
                    raise ValueError(
                        "No cached response found in replay mode. Populate cache in record mode first."
                    )
                case "record":
                    gemini_contents = self._convert_messages_to_gemini(kwargs.get("messages", []))
                    config = genai_types.GenerateContentConfig(
                        max_output_tokens=kwargs.get("max_tokens", 1024),
                        temperature=kwargs.get("temperature", 1.0),
                        response_mime_type="text/plain",
                    )
                    response = await self._async_client.models.generate_content(
                        model=kwargs["model"],
                        contents=gemini_contents,
                        config=config,
                    )
                    anthropic_response = self._build_anthropic_response(response, kwargs["model"])
                    cache_key = self._get_cache_key(**kwargs)
                    logger.info(f"Caching response with key: {cache_key}")
                    self._cache[cache_key] = anthropic_response
                    self._save_cache()
                    return Message.model_validate(anthropic_response)
                case _:
                    gemini_contents = self._convert_messages_to_gemini(kwargs.get("messages", []))
                    config = genai_types.GenerateContentConfig(
                        max_output_tokens=kwargs.get("max_tokens", 1024),
                        temperature=kwargs.get("temperature", 1.0),
                        response_mime_type="text/plain",
                    )
                    response = await self._async_client.models.generate_content(
                        model=kwargs["model"],
                        contents=gemini_contents,
                        config=config,
                    )
                    anthropic_response = self._build_anthropic_response(response, kwargs["model"])
                    return Message.model_validate(anthropic_response)
        return create_with_model_and_cache


class DeepseekParams(TypedDict):
    max_tokens: int
    messages: List[Dict[str, Any]]
    model: str
    temperature: float
    tools: NotRequired[List[Dict[str, Any]]]
    tool_choice: NotRequired[Dict[str, Any]]


class DeepseekClient(LLMClient):
    """Client for Deepseek models on AWS Bedrock with caching support."""

    def __init__(self,
                 model_name: DeepseekModelType = "deepseek-r1",
                 cache_mode: CacheMode = "off",
                 cache_path: str = "deepseek_cache.json",
                 client_params: dict = {}):
        super().__init__("bedrock", model_name, cache_mode, cache_path, client_params=client_params)

        # Initialize the Bedrock client
        region_name = os.getenv("AWS_REGION", "us-west-2")
        self._client = boto3.client("bedrock-runtime", region_name=region_name, **(client_params or {}))

        # Map friendly model names to actual model identifiers - must match exact model ID
        self.models_map = {
            "deepseek-r1": "us.deepseek.r1-v1:0"
        }

        # Set the model name based on the mapping
        if self.short_model_name in self.models_map:
            self.model_name = self.models_map[self.short_model_name]
        else:
            # If not in mapping, assume it's a direct model identifier
            self.model_name = self.short_model_name


    @property
    def messages(self):
        """Access the messages property with customized create method."""
        class Messages:
            def __init__(self, parent):
                self.parent = parent

            def create(self, **kwargs):
                # Use the model ID from kwargs if provided, otherwise use the default from parent
                model_id = kwargs.get("model", self.parent.model_name)

                # Handle different cache modes
                match self.parent.cache_mode:
                    case "off":
                        return self._invoke_model(model_id, **kwargs)
                    case "replay":
                        cache_key = self.parent._get_cache_key(**kwargs)
                        if cache_key in self.parent._cache:
                            logger.info(f"Cache hit: {cache_key}")
                            cached_response = self.parent._cache[cache_key]

                            # Check if we need to reconstruct an object
                            if isinstance(cached_response, dict) and "type" in cached_response:
                                # This is likely a serialized response
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
                        response = self._invoke_model(model_id, **kwargs)
                        cache_key = self.parent._get_cache_key(**kwargs)
                        logger.info(f"Caching response with key: {cache_key}")
                        serialized_response = response.to_dict() if hasattr(response, "to_dict") else response
                        self.parent._cache[cache_key] = serialized_response
                        self.parent._save_cache()
                        return response

            def _invoke_model(self, model_id, **kwargs):
                # Format messages in Deepseek's expected format
                messages = kwargs.get("messages", [])

                # Create Deepseek-compatible request for Bedrock
                request_body = {
                    "prompt": self._format_messages(messages),
                    "max_tokens": kwargs.get("max_tokens", 512),
                    "temperature": kwargs.get("temperature", 0.7),
                    "top_p": kwargs.get("top_p", 0.9)
                }

                # Handle stop sequences if present (optional)
                if "stop" in kwargs:
                    request_body["stop"] = kwargs.get("stop", [])

                # Convert to JSON for the Bedrock invoke_model API
                body = json.dumps(request_body)

                try:
                    # Remove debugging breakpoint that might be causing issues
                    response = self.parent._client.invoke_model(
                        modelId=model_id,
                        contentType="application/json",
                        accept="application/json",
                        body=body.encode("utf-8")
                    )
                except Exception as e:
                    logger.exception(f"error invoking deepseek model {model_id}")
                    raise

                response_body = response["body"].read()
                response_json = json.loads(response_body.decode("utf-8"))

                # Extract text from the Deepseek response format
                response_text = ""
                if "choices" in response_json and len(response_json["choices"]) > 0:
                    response_text = response_json["choices"][0].get("text", "")

                # Get stop reason - map to valid Anthropic stop reasons
                stop_reason = "end_turn"  # Default valid value
                if "choices" in response_json and len(response_json["choices"]) > 0:
                    deepseek_stop = response_json["choices"][0].get("stop_reason")
                    if deepseek_stop == "length":
                        stop_reason = "max_tokens"  # Anthropic uses max_tokens, not length

                # Estimate token count based on characters (rough approximation)
                input_chars = len(self._format_messages(messages))
                output_chars = len(response_text) if response_text else 0

                # Very rough estimate: ~4 characters per token on average
                est_input_tokens = max(1, input_chars // 4)
                est_output_tokens = max(1, output_chars // 4)

                # Format response to match Anthropic's format for compatibility
                formatted_response = {
                    "id": f"deepseek-{hashlib.md5(str(response_json).encode()).hexdigest()}",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": response_text}],
                    "model": model_id,
                    "stop_reason": stop_reason,
                    "usage": {
                        "input_tokens": est_input_tokens,
                        "output_tokens": est_output_tokens
                    }
                }

                return Message.model_validate(formatted_response)

            def _format_messages(self, messages):
                """Convert messages to Deepseek's expected format for Bedrock."""
                # Follow the format shown in AWS documentation for Deepseek
                conversation = "<｜begin▁of▁sentence｜>"
                for message in messages:
                    role = message.get("role", "user")

                    # Extract content
                    content = message.get("content", "")
                    if isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                        content = " ".join(text_parts)

                    # Format based on role using Deepseek's specific format
                    if role == "user":
                        conversation += f"<｜User｜>{content}"
                    elif role == "assistant":
                        conversation += f"<｜Assistant｜>{content}"

                # Add the final tag for the assistant to respond
                if not conversation.endswith("<｜Assistant｜>"):
                    conversation += "<｜Assistant｜>"

                # Add the thinking instruction as shown in AWS example
                conversation += "<think>\n"

                return conversation

            def _format_tools(self, tools):
                """
                Convert tools to Deepseek's format.
                Note: DeepSeek R1 on Bedrock doesn't support tools in the standard format.
                This method is kept for future compatibility.
                """
                # Tool calling is not supported in the current DeepSeek R1 version on Bedrock
                # This is maintained for future compatibility when tool support is added
                logger.warning("Tool calling is not supported by DeepSeek on Bedrock in this version")
                return []

        return Messages(self)

    def async_create(self, **kwargs):
        raise NotImplementedError("boto3 does not support async methods")


def get_sync_client(
    backend: BackendType = "bedrock",
    model_name: Literal["sonnet", "haiku", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-thinking", "gemma-3-27b-it", "deepseek-r1"] = "sonnet",
    cache_mode: CacheMode = "off",
    cache_path: str = os.path.join(os.path.dirname(__file__), "../../anthropic_cache.json"),
    api_key: str | None = None,
    client_params: dict = None,
    region_name: str = "us-east-1"
) -> LLMClient:
    match backend, model_name:
        case "bedrock" | "anthropic", "sonnet" | "haiku":
            return AnthropicClient(
                backend=backend,
                model_name=model_name,
                cache_mode=cache_mode,
                cache_path=cache_path,
                client_params=client_params
            )
        case "bedrock", "deepseek-r1":
            return DeepseekClient(
                model_name=model_name,
                cache_mode=cache_mode,
                cache_path=cache_path,
                client_params=client_params
            )
        case "gemini", _:
            gemini_cache_path = os.path.join(os.path.dirname(cache_path), "gemini_cache.json")
            return GeminiClient(
                model_name=model_name,
                cache_mode=cache_mode,
                cache_path=gemini_cache_path,
                api_key=api_key,
                client_params=client_params
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
