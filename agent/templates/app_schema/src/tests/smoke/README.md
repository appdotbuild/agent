# Smoke Tests

This directory contains smoke tests that verify the basic functionality of the application.

## What's Tested

The smoke tests verify:

1. Handler functionality - testing that our basic handlers work correctly
2. Parameter validation - testing that Zod schemas correctly validate inputs
3. Mock storage - testing that we can store and retrieve messages
4. Mock LLM responses - testing that we can mock LLM responses

## Testing Approach

We use a combination of techniques for our smoke tests:

1. **Basic Smoke Tests**: We test core functionality of our handlers and message storage in isolation
   - These tests don't depend on the full application stack
   - They use in-memory mocks for database and LLM clients
   - They're fast and reliable for quick checks

2. **Integration Tests (Future)**: For more comprehensive testing, we'll need:
   - A SQLite or PostgreSQL database with a test schema
   - Mocked LLM responses 
   - Full HTTP server testing

## Running Tests

Run the basic smoke tests with:

```bash
npm run test:smoke
# or
bun run test:smoke
```

## Extending Tests

To add more tests:

1. Add new test cases to `basic-smoke.test.js` for core functionality tests
2. When creating full integration tests, ensure you're properly mocking external dependencies
3. For PostgreSQL dependency, consider using SQLite for testing since it's lightweight and doesn't require a server