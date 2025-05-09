import os
import pytest
import subprocess
import tomllib
from pathlib import Path

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

def help_command():
    """Displays all available custom uv run commands with examples."""
    if tomllib is None:
        print("Cannot display help: tomllib module is not available. Please use Python 3.11+ or install 'toml'.")
        return

    print("Available custom commands (run with 'uv run <command>'):\n")

    # Fallback examples, primarily for commands not documented in pyproject.toml
    fallback_examples = {
        "generate": "uv run generate --prompt='your app description' (Generates code based on a prompt)",
        "interactive": "uv run interactive (Starts an interactive CLI session with the agent)",
    }

    try:
        current_script_path = Path(__file__).resolve()
        pyproject_path = current_script_path.parent / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)

        scripts = data.get("project", {}).get("scripts", {})
        command_docs = data.get("tool", {}).get("agent", {}).get("command_docs", {})

        if not scripts:
            print("No custom scripts found in pyproject.toml.")
            # Ensure help command itself can be shown if pyproject.toml is minimal/empty
            # and has a doc string in command_docs or fallback_examples
            scripts = {"help": "commands:help_command"}
            if "help" not in command_docs and "help" not in fallback_examples:
                 # Provide a very basic default if no doc is available anywhere
                 command_docs["help"] = "Displays this help message. Example: uv run help"


        # Ensure help is in the list for display, especially if pyproject.toml is empty or lacks it.
        if "help" not in scripts:
            scripts["help"] = "commands:help_command"

        all_command_names = set(scripts.keys())
        if not all_command_names:
             max_len = len("Command") + 2
        else:
            max_len = max(len(name) for name in all_command_names) + 2


        print(f"{'Command':<{max_len}} {'Description / Example'}")
        print(f"{'=' * max_len} {'=' * 40}") # Using '=' for a slightly different look

        for name, target in sorted(scripts.items()):
            # Prioritize help string from [tool.agent.command_docs]
            help_text = command_docs.get(name)
            if not help_text:
                # Fallback to the python dictionary
                help_text = fallback_examples.get(name)
            if not help_text:
                # Generic fallback if no specific help string is found
                help_text = f"uv run {name} (Target: {target})"
            
            print(f"{name:<{max_len}} {help_text}")

        print("\nNote: Some commands might accept additional arguments. Refer to their implementations or detailed docs.")

    except FileNotFoundError:
        print(f"Error: pyproject.toml not found at expected location: {pyproject_path}")
    except Exception as e:
        print(f"An error occurred while reading pyproject.toml: {e}")
