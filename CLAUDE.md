# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Structure
- agent - Contains the main codegen agent code
- agent/api - IO layer for the agent
- agent/api/agent_server - API of the agent server
- agent/api/agent_server/models.py - Models for the agent server consistent with agent_api.tsp
- agent/api/agent_server/agent_api.tsp - Server type specification for the agent server
- agent/api/agent_server/async_server.py - Agent server implementation using models.py and consistent with agent_api.tsp
- agent/api/cli - CLI entrypoint
- agent/core - core framework logic (base classes, statemachine etc.)
- agent/trpc_agent - agent for fullstack code generation. New agents may be added on the same pattern.
- agent/llm - LLM wrappers
- agent/stash_bot - deprecated!
- agent/log.py - global logging and tracing

### CI and tests

We use GitHub Actions, triggered on PRs and pushes to main. .github/workflows/build_and_test.yml is responsible for configuration.

## Build/Test/Lint Commands
Typically run from `./agent` directory.

- **Run all tests**: `uv run pytest -v .`
- **Lint code**: `uv run ruff check` # not used for now
- **Format code**: `uv run ruff check` # not used for now
- **Run tests in isolated env**: `docker build --target test -t agent-test:latest . && docker run --rm agent-test:latest`

## Code Style Guidelines

### Python
- **Imports**: Standard library → third-party → local modules
- **Types**: Use modern typing: `def func(param: str | None = None)` not `param: str = None`
- **Logging**: Use `logger = get_logger(__name__)` and `logger.exception()` for errors
- **Error Handling**: Prefer `logger.exception("message")` over `logger.error(str(e))`
- **Async code**: Use `anyio` over `asyncio` for async code
- **Pattern Matching**: Prefer `match/case` over lengthy if/elif chains
- **Testing**: Use `pytest` for unit tests, never use mocks unless explicitly asked.
- **Naming**: snake_case for variables/functions, PascalCase for classes, UPPER_SNAKE_CASE for constants
- **Line Length**: 120 characters max
- **Quotes**: Double quotes
- use snake_case for variable names
- use snake_case for function names
- use PascalCase for class names and for json keys as well as for API payload fields that must be hidden behind the models.py with its own from_json/to_json methods
- use UPPER_SNAKE_CASE for constant names
- use triple double quotes (`"""`) for docstrings
- use single quotes (`'`) for strings that don't contain any special characters or apostrophes
- use double quotes (`"`) for strings that do contain special characters or apostrophes

### TypeScript
- **Types**: Use explicit interfaces and Zod for schema validation
- **Variables**: Prefer `const` over `let`
- **Naming**: camelCase for variables/functions, PascalCase for types/interfaces
- **Imports**: No renamed imports
