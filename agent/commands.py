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


def _run_tests_with_cache(dest=".", n_workers=_n_workers(), verbose=False):
    os.environ["LLM_VCR_CACHE_MODE"] = "replay"
    os.chdir(_current_dir())
    flag = "-vs" if verbose else "-v"
    code = pytest.main([flag, "-n", str(n_workers), dest])
    if code != 0:
        raise RuntimeError(f"pytest failed with code {code}")


def run_tests_with_cache():
    Fire(_run_tests_with_cache)

def update_cache(dest="."):
    os.environ["LLM_VCR_CACHE_MODE"] = "record"
    os.chdir(_current_dir())
    code = pytest.main(["-v", "-n", "0", dest])
    if code != 0:
        raise RuntimeError(f"pytest failed with code {code}")


def run_lint():
    os.chdir(_current_dir())
    code = subprocess.run("ruff check . --fix".split())
    if code.returncode != 0:
        raise RuntimeError(f"ruff failed with code {code.returncode}")

def run_e2e_tests():
    coloredlogs.install(level="INFO")
    _run_tests_with_cache("tests/test_e2e.py", n_workers="0", verbose=True)

def generate():
    return Fire(_generate)

def _generate(prompt=DEFAULT_APP_REQUEST):
    coloredlogs.install(level="INFO")
    anyio.run(run_e2e, prompt, True)

def interactive():
    coloredlogs.install(level="INFO")
    os.environ["LLM_VCR_CACHE_MODE"] = "lru"
    Fire(_run_interactive)
