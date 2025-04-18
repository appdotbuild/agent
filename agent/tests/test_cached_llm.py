import pytest
import tempfile
import os
import json
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


async def test_lru_cache_hit():
    with tempfile.NamedTemporaryFile(delete_on_close=False) as tmp_file:
        base_llm = get_llm_client(cache_mode="off", model_name="haiku")
        
        lru_llm = CachedLLM(
            client=base_llm,
            cache_mode="lru",
            cache_path=tmp_file.name,
            max_cache_size=2
        )

        call_args = {
            "messages": [Message(role="user", content=[TextRaw("LRU test message")])],
            "max_tokens": 100,
        }
        
        # First call populates the cache
        response1 = await lru_llm.completion(**call_args)
        
        # Second call with same args should hit the cache and return the same response
        response2 = await lru_llm.completion(**call_args)
        
        # Responses should be identical since the second one comes from cache
        assert response1 == response2
        
        # Check the cache file was created and contains at least one entry
        with open(tmp_file.name, 'r') as f:
            cache_data = json.load(f)
            assert len(cache_data) == 1


async def test_lru_cache_size_limit():
    with tempfile.NamedTemporaryFile(delete_on_close=False) as tmp_file:
        base_llm = get_llm_client(cache_mode="off", model_name="haiku")
        
        # Set max cache size to 2
        lru_llm = CachedLLM(
            client=base_llm,
            cache_mode="lru",
            cache_path=tmp_file.name,
            max_cache_size=2
        )

        # Make 3 different calls to exceed the cache size
        call_args1 = {
            "messages": [Message(role="user", content=[TextRaw("LRU Message 1")])],
            "max_tokens": 100,
        }
        call_args2 = {
            "messages": [Message(role="user", content=[TextRaw("LRU Message 2")])],
            "max_tokens": 100,
        }
        call_args3 = {
            "messages": [Message(role="user", content=[TextRaw("LRU Message 3")])],
            "max_tokens": 100,
        }
        
        # Make the calls in sequence
        await lru_llm.completion(**call_args1)
        await lru_llm.completion(**call_args2)
        await lru_llm.completion(**call_args3)
        
        # Check the cache only contains 2 entries (since max_cache_size=2)
        with open(tmp_file.name, 'r') as f:
            cache_data = json.load(f)
            assert len(cache_data) == 2
        
        # Make a new call to push out another entry
        call_args4 = {
            "messages": [Message(role="user", content=[TextRaw("LRU Message 4")])],
            "max_tokens": 100,
        }
        await lru_llm.completion(**call_args4)
        
        # Check we still have only 2 entries
        with open(tmp_file.name, 'r') as f:
            updated_cache_data = json.load(f)
            assert len(updated_cache_data) == 2


async def test_lru_cache_persistence():
    with tempfile.NamedTemporaryFile(delete_on_close=False) as tmp_file:
        base_llm = get_llm_client(cache_mode="off", model_name="haiku")
        
        # First client writes to cache
        lru_llm1 = CachedLLM(
            client=base_llm,
            cache_mode="lru",
            cache_path=tmp_file.name,
            max_cache_size=5
        )

        call_args = {
            "messages": [Message(role="user", content=[TextRaw("LRU Persistent message")])],
            "max_tokens": 100,
        }
        
        # Call and populate cache
        response1 = await lru_llm1.completion(**call_args)
        
        # Create a new client that reads from the same cache file
        lru_llm2 = CachedLLM(
            client=base_llm,
            cache_mode="lru",
            cache_path=tmp_file.name,
            max_cache_size=5
        )
        
        # Should return the cached response
        response2 = await lru_llm2.completion(**call_args)
        
        # Responses should be identical since the second one comes from cache
        assert response1 == response2
