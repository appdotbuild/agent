# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Structure
- agent - Contains the main codegen agent code
- agent/api - IO layer for the agent
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

### TypeScript
- **Types**: Use explicit interfaces and Zod for schema validation
- **Variables**: Prefer `const` over `let`
- **Naming**: camelCase for variables/functions, PascalCase for types/interfaces
- **Imports**: No renamed imports
