import pytest
import tempfile
import anthropic
from llm.cached import CachedLLM
from llm.anthropic_client import AnthropicLLM
from llm.common import Message, TextRaw

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_cached_llm():
    with tempfile.NamedTemporaryFile(delete_on_close=False) as tmp_file:
        base_llm = AnthropicLLM(anthropic.AsyncAnthropic())
        record_llm = CachedLLM(
            client=base_llm,
            cache_mode="record",
            cache_path=tmp_file.name,
        )

        call_args = {
            "model": "claude-3-5-haiku-20241022",
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
