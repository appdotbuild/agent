from typing import Union, TypeVar, Dict, Any, Optional, List, cast
from anthropic.types import MessageParam, TextBlock, Message
from anthropic import AnthropicBedrock, Anthropic
from functools import partial

# Define a generic type for Anthropic clients

class AnthropicClient:
    def __init__(self, backend: str = "bedrock", model_name: str = "sonnet"):
        self.backend = backend
        self.model_name = model_name

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

    @property
    def messages(self):
        """Access the messages property but with our customized create method."""
        original_messages = self._client.messages
        original_create = original_messages.create

        # Replace the create method with one that automatically uses our model
        def create_with_model(*args, **kwargs):
            model_id = self.models_map[self.model_name][self.backend]
            if 'model' not in kwargs:
                kwargs['model'] = model_id
            return original_create(*args, **kwargs)

        original_messages.create = create_with_model
        return original_messages

    def __getattr__(self, name):
        return getattr(self._client, name)


def get_sync_client(backend: str = "bedrock", model_name: str = "sonnet") -> AnthropicClient:
    return AnthropicClient(backend=backend, model_name=model_name)


def pop_first_text(message: MessageParam):
    if isinstance(message["content"], str):
        return message["content"]
    for block in message["content"]:
        if isinstance(block, TextBlock):
            return block.text
    return None
