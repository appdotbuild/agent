# Smoke Tests

This directory contains smoke tests that verify the basic functionality of the application.

## What's Tested

The smoke tests verify:

1. The server can start up correctly
2. The health endpoint responds correctly
3. The chat endpoint processes messages using mocked LLM responses
4. The JSON chat endpoint returns the expected format
5. The tool/handler endpoints process requests correctly

## Mocks Used

These tests use mocked dependencies:

- **Database**: We mock the database operations to avoid requiring a real database connection
- **LLM**: We mock the Anthropic LLM client to provide predetermined responses
- **Environment**: We mock environment variables to ensure consistent test conditions

## Running Tests

Run the smoke tests with:

```bash
npm run test:smoke
# or
bun run test:smoke
```

## Extending Tests

To add more tests:

1. Add new test cases to `app.test.ts`
2. If needed, enhance the mock implementations for new features
3. Add tests for any new API endpoints or handlers