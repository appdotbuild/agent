import os
import pytest
import subprocess

import anyio
from tests.test_e2e import run_e2e, DEFAULT_APP_REQUEST
from fire import Fire
import coloredlogs
from api.agent_server.agent_api_client import cli as _run_interactive


def _current_dir():
    return os.path.dirname(os.path.abspath(__file__))

def _n_workers():
    return str(min(os.cpu_count() or 1, 4))


def run_tests_with_cache(dest=".", n_workers=_n_workers()):
    os.environ["LLM_VCR_CACHE_MODE"] = "replay"
    os.chdir(_current_dir())
    pytest.main(["-v", "-n", n_workers, dest])


def update_cache(dest="."):
    os.environ["LLM_VCR_CACHE_MODE"] = "record"
    os.chdir(_current_dir())
    pytest.main(["-v", "-n", "0", dest])


def run_lint():
    os.chdir(_current_dir())
    subprocess.run("ruff check . --fix".split())

def run_e2e_tests():
    run_tests_with_cache("tests/test_e2e.py", n_workers="0")

def generate():
    return Fire(_generate)

def _generate(prompt=DEFAULT_APP_REQUEST):
    coloredlogs.install(level="INFO")
    anyio.run(run_e2e, prompt, True)

def interactive():
    os.environ["LLM_VCR_CACHE_MODE"] = "lru"
    Fire(_run_interactive)
