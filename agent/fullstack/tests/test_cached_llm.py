import pytest
import tempfile
import anthropic
from models.cached import CachedLLM
from models.anthropic_bedrock import AnthropicBedrockLLM
from models.common import Message, TextRaw

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_cached_llm():
    with tempfile.NamedTemporaryFile(delete_on_close=False) as tmp_file:
        base_llm = AnthropicBedrockLLM(anthropic.AsyncAnthropicBedrock())
        record_llm = CachedLLM(
            client=base_llm,
            cache_mode="record",
            cache_path=tmp_file.name,
        )

        call_args = {
            "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            "messages": [Message(role="user", content=[TextRaw("Hello, world!")])],
            "max_tokens": 100,
        }

        recorded = await record_llm.completion(**call_args)

        replay_llm = CachedLLM(
            client=base_llm,
            cache_mode="replay",
            cache_path=tmp_file.name,
        )
        replayed = await replay_llm.completion(**call_args)

        assert recorded == replayed
