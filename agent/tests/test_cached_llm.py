import pytest
import tempfile
from llm.cached import CachedLLM
from llm.utils import get_llm_client
from llm.common import Message, TextRaw

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


async def test_cached_llm():
    with tempfile.NamedTemporaryFile(delete_on_close=False) as tmp_file:
        base_llm = get_llm_client(cache_mode="off", model_name="haiku")
        record_llm = CachedLLM(
            client=base_llm,
            cache_mode="record",
            cache_path=tmp_file.name,
        )

        call_args = {
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
