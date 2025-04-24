"""
Tests for the Config class from the rusty extension.
"""
import os
import pytest

from rusty import Config


def test_agent_type():
    os.environ["CODEGEN_AGENT"] = "omg"
    assert Config.agent_type == "omg"
    os.environ.pop("CODEGEN_AGENT")
    assert Config.agent_type == "trpc_agent"


def test_builder_token():
    os.environ["BUILDER_TOKEN"] = "omg"
    assert Config.builder_token == "omg"
    os.environ.pop("BUILDER_TOKEN")
    assert Config.builder_token is None
