from typing import Union, TypeVar
from anthropic.types import MessageParam, TextBlock
from anthropic import AnthropicBedrock, Anthropic

# Define a generic type for Anthropic clients that can be extended in the future
AnthropicClient = Union[Anthropic, AnthropicBedrock]
T = TypeVar('T', bound=AnthropicClient)

def get_sync_client(backend: str = "bedrock") -> AnthropicClient:
    match backend:
        case "bedrock":
            return AnthropicBedrock()
        case "anthropic":
            return Anthropic()
        case _:
            raise ValueError(f"Unknown backend: {backend}")


def pop_first_text(message: MessageParam):
    if isinstance(message["content"], str):
        return message["content"]
    for block in message["content"]:
        if isinstance(block, TextBlock):
            return block.text
    return None
