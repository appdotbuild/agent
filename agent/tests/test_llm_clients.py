import asyncio
import json
import pytest
from anthropic.types import Message
from fsm_core.llm_common import get_sync_client
import os
from unittest.mock import patch, MagicMock


# Mark all tests in this module as anyio tests with asyncio backend only
pytestmark = pytest.mark.anyio(backends=["asyncio"])

@pytest.fixture
def anyio_backend():
    return "asyncio"


def make_basic_test_prompt():
    return [
        {"role": "user", "content": "Hello, what's your model name? Respond in just 5 words."}
    ]


def skip_if_no_api_key(key_name):
    return pytest.mark.skipif(os.getenv(key_name) is None, reason="No API key provided")


@skip_if_no_api_key("ANTHROPIC_API_KEY")
def test_anthropic_client_sync():
    """Test the Anthropic client with synchronous API."""
    client = get_sync_client(backend="anthropic", model_name="haiku", cache_mode="off")
    response = client.messages.create(
        messages=make_basic_test_prompt(),
        max_tokens=20,
        stream=False,
    )
    assert response is not None
    assert response.content[0].text
    assert isinstance(response, Message)


@skip_if_no_api_key("GEMINI_API_KEY")
@pytest.mark.parametrize("model_name", ["gemini-2.0-flash", "gemma-3-27b-it"])
def test_gemini_client_sync(model_name):
    """Test the Gemini client with synchronous API."""
    client = get_sync_client(backend="gemini", model_name=model_name, cache_mode="off")
    response = client.messages.create(
        messages=make_basic_test_prompt(),
        max_tokens=20
    )
    assert response is not None
    assert response.content[0].text
    assert isinstance(response, Message)

@skip_if_no_api_key("AWS_ACCESS_KEY_ID")
def test_deepseek_client_integration():
    """Integration test for Deepseek client."""
    client = get_sync_client(
        backend="bedrock",
        model_name="deepseek-r1",
        cache_mode="off",
    )
    response = client.messages.create(
        messages=make_basic_test_prompt(),
        max_tokens=20
    )
    assert response is not None
    assert response.content[0].text
    assert isinstance(response, Message)


@skip_if_no_api_key("ANTHROPIC_API_KEY")
async def test_anthropic_client_async():
    """Test the Anthropic client with async API."""
    client = get_sync_client(backend="anthropic", model_name="haiku", cache_mode="off")
    create_fn = await client.async_create
    response = await create_fn(
        messages=make_basic_test_prompt(),
        max_tokens=20,
        stream=False,
    )
    assert response is not None
    assert response.content
    assert isinstance(response, Message)


@skip_if_no_api_key("GEMINI_API_KEY")
@pytest.mark.parametrize("model_name", ["gemini-2.0-flash", "gemma-3-27b-it"])
async def test_gemini_client_async(model_name):
    """Test the Gemini client with async API."""
    client = get_sync_client(backend="gemini", model_name=model_name, cache_mode="off")
    create_fn = await client.async_create
    response = await create_fn(
        messages=make_basic_test_prompt(),
        max_tokens=20,
    )
    assert response is not None
    assert response.content
    assert isinstance(response, Message)
