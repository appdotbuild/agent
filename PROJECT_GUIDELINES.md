# Project Guidelines

This file contains the core guidelines for working with code in this repository.
AI assistants (Cursor, Claude, Devin, etc.) should refer to this file for context.

# Project Overview

This project implements an AI codegen agent system with various components for handling API interactions, core logic, and specific agent implementations. The system is built primarily in Python with some TypeScript components.

Refer to `agent/architecture.puml` for a visual representation of the system architecture.

# Project Structure

- `agent` - Contains the main codegen agent code
  - `api` - IO layer for the agent
    - `agent_server` - API of the agent server
      - `models.py` - Models for the agent server consistent with agent_api.tsp
      - `agent_api.tsp` - Server type specification for the agent server
      - `async_server.py` - Agent server implementation
    - `cli` - CLI entrypoint (Note: Interacted via test clients, not a dedicated CLI app)
  - `core` - Core framework logic (base classes, state machine, etc.)
  - `trpc_agent` - Agent for fullstack code generation (new agents follow this pattern)
  - `llm` - LLM wrappers
  - `stash_bot` - Deprecated!
  - `log.py` - Global logging and tracing

# Development Workflow

Commands should typically be run from the `./agent` directory:

- **Run all tests**: `uv run pytest -v .`
- **Lint code**: `uv run ruff check` 
- **Format code**: `uv run ruff format`
- **Run tests in isolated env**: `docker build --target test -t agent-test:latest . && docker run --rm agent-test:latest`
- **Build Docker image**: `docker build -t agent:latest .`
- **Run Docker container**: `docker run --rm -p 8000:8000 agent:latest`

# Lessons

## User Specified Lessons
- Using `anyio` instead of `asyncio` for async operations is preferred in this codebase
- Always activate the Python virtual environment before installing packages
- Never use mocks in tests unless explicitly required

## Cursor Learned
- The state machine pattern in `core` requires explicit state transitions
- The logger setup requires using the `get_logger` function from `agent.log`
- Always check for existing patterns before implementing new functionality
# Code Style Guidelines

## Python

### Key Libraries and Dependencies

- `anyio` - Preferred async library
- `pytest` - Testing framework
- `ruff` - Linting and formatting
- `uv` - Package management tool

### Code Organization

#### File Structure
- Keep modules focused on a single responsibility
- Group related functions/classes within a module
- Use `__init__.py` to expose public interfaces

### Formatting and Structure

### Imports
- **Order**: Standard library imports → Third-party library imports → Local/project imports
- **Example**:
  ```python
  import json
  import os
  from typing import Dict, List, Optional
  
  import anyio
  import pytest
  
  from agent.core import BaseClass
  from agent.log import get_logger
  ```

### Language Features

### Async Code
- **Preferred Library**: Use `anyio` rather than `asyncio`
- **Context Managers**: Use async context managers for resource management
- **Task Groups**: Group related async operations when possible
  ```python
  async with anyio.create_task_group() as tg:
      tg.start_soon(task_1)
      tg.start_soon(task_2)
  ```

### Type Annotations
- Annotate all function parameters and return values
- Use `Optional[Type]` or `Type | None` for parameters that can be None (prefer `Type | None`)
- Use union types with the pipe operator: `str | None`
- Use `TypedDict` for dictionary structures
- **Example**:
  ```python
  from typing import TypedDict, Any
  
  class Result(TypedDict):
      status: str
      data: Any
      
  def process_request(data: Dict[str, Any], timeout: float | None = None) -> Result:
      """
      Process the incoming request data.
      
      Args:
          data: The request data to process
          timeout: Optional timeout in seconds
          
      Returns:
          Result object containing processed data
      """
      # ... implementation ...
      return {"status": "success", "data": {}}
  ```

### Error Handling and Logging
- **Exception Types**: Use specific exception types rather than generic `Exception`. Avoid `except:` without specifying types.
- **Custom Exceptions**: Create custom exceptions for domain-specific errors.
- **Logging**: Always log exceptions with context using `logger.exception("message")` from `agent.log`.
- **Example**:
  ```python
  from agent.log import get_logger
  logger = get_logger(__name__)
  
  class InvalidDataError(ValueError):
      pass
  
  async def process_data(input_data):
      # ... processing ...
      if not valid:
          raise InvalidDataError("Input data failed validation")
      return processed_data
  
  async def handle_request(input_data):
      try:
          result = await process_data(input_data)
      except InvalidDataError as e:
          logger.exception("Invalid data format received")
          # Re-raise or handle specific error
          raise
      except Exception as e:
          logger.exception("An unexpected error occurred during processing")
          # Handle generic error
          raise
  ```

### Testing
- **Framework**: Use `pytest`
- **Structure**: 
    - Use descriptive test names starting with `test_`.
    - Group tests by functionality.
    - Use fixtures for common test setups.
- **Mocks**: Avoid mocks unless absolutely necessary.
- **Example**:
  ```python
  import pytest
  from your_module import process_request # Assuming process_request is defined elsewhere
  
  @pytest.fixture
  def sample_data():
      return {"key": "value"}
  
  def test_process_request_with_valid_data(sample_data):
      result = process_request(sample_data)
      assert result["status"] == "success"
  ```

### Common Pitfalls
- Avoid global state; use dependency injection.
- Be careful with default mutable arguments (e.g., `def func(arg=[]): ...`). Use `arg: list | None = None` and `if arg is None: arg = []` instead.
- Always close resources explicitly or use context managers.

## TypeScript

### Key Libraries and Dependencies

- `zod` - Schema validation
- `trpc` - API framework (Note: Primarily used for potential future frontend/backend interactions, not core agent logic)

### Code Organization

#### File Structure
- Use a modular approach with clear separation of concerns.
- Group related functionality in directories.
- Naming pattern: 
  - React components: `ComponentName.tsx` (If applicable)
  - Utility files: `utility-name.ts`
  - Type definitions: `types.ts` or within the module.

#### Import Order
1. React and framework imports (If applicable)
2. Third-party libraries (`zod`, `trpc`, etc.)
3. Local components and utilities
4. Types and interfaces
5. Styles and assets (If applicable)
- **Example**:
  ```typescript
  // import React, { useState, useEffect } from 'react'; // If using React
  
  import { z } from 'zod';
  // import { trpc } from 'trpc'; // If using tRPC client
  
  // import { Button } from '../components/Button'; // If using React components
  import { formatData } from '../utils/formatter';
  
  import type { User, UserPreferences } from '../types';
  
  // import styles from './styles.module.css'; // If using CSS Modules
  ```

### Types
- **Best Practices**: 
    - Use explicit interfaces over type aliases for objects.
    - Use Zod schemas for runtime validation, especially for API boundaries.
    - Export types from a central location or alongside their usage.
    - Use generics for reusable components and functions.
- **Example**:
  ```typescript
  import { z } from 'zod';
  
  // Define Zod schema for runtime validation
  export const userPreferencesSchema = z.object({
    theme: z.enum(['light', 'dark']),
    notifications: z.boolean(),
  });
  
  // Define interface using inferred type from Zod
  export type UserPreferences = z.infer<typeof userPreferencesSchema>;
  
  // Define main interface
  export interface User {
    id: string;
    name: string;
    email: string;
    preferences?: UserPreferences;
  }
  
  // Define Zod schema for User
  export const userSchema = z.object({
    id: z.string().uuid(),
    name: z.string().min(1),
    email: z.string().email(),
    preferences: userPreferencesSchema.optional(),
  });
  
  // Type for function arguments
  function updateUser(user: User, updates: Partial<User>): User {
    // Zod validation can be added here if needed
    // const validatedUpdates = userSchema.partial().parse(updates);
    return { ...user, ...updates }; 
  }
  ```

### Variables
- Prefer `const` over `let`.

### Naming
- Variables/Functions: `camelCase`
- Types/Interfaces: `PascalCase`

### Imports
- No renamed imports unless necessary for clarity or collision avoidance.

### API Integration (tRPC Example - If Applicable)
- **Patterns**: 
    - Define router schemas explicitly.
    - Use input validation for all procedures.
    - Centralize error handling.
- **Example**:
  ```typescript
  import { z } from 'zod';
  // Assume setup for router, procedure, TRPCError, and ctx (context) exists
  // import { router, procedure, TRPCError } from '../trpc'; 
  // import { db } from '../db'; // Example database context
  
  export const userRouter = router({
    getUser: procedure
      .input(z.object({ id: z.string() }))
      .query(async ({ input, ctx }) => {
        try {
          // Replace with actual data fetching logic
          // return await ctx.db.user.findUnique({ where: { id: input.id } });
          return { id: input.id, name: 'Dummy User' }; // Example return
        } catch (error) {
          console.error("Failed to fetch user:", error); // Use proper logging
          throw new TRPCError({
            code: 'INTERNAL_SERVER_ERROR',
            message: 'Failed to fetch user',
            // cause: error, // Optional: include original error
          });
        }
      }),
  });
  ```

### Component Structure (React Example - If Applicable)
- **Patterns**:
    - Use functional components with hooks.
    - Destructure props at the component level.
    - Define prop types using interfaces.
    - Use `React.FC` sparingly (prefer explicit return types like `JSX.Element`).
- **Example**:
  ```typescript
  import React from 'react'; // Assuming React is used
  // import styles from './styles.module.css'; // Example CSS Modules

  interface ButtonProps {
    label: string;
    onClick: () => void;
    disabled?: boolean;
  }
  
  function Button({ label, onClick, disabled = false }: ButtonProps): JSX.Element {
    return (
      <button 
        onClick={onClick}
        disabled={disabled}
        // className={styles.button} // Example styling
      >
        {label}
      </button>
    );
  }
  ```

### State Management (React Example - If Applicable)
- **Best Practices**: 
    - Use React hooks (`useState`, `useReducer`) for local state.
    - Consider context (`useContext`) for simple shared state.
    - Use dedicated state management libraries (like Zustand, Redux) for complex global state.
    - Keep state normalized.
- **Example using `useReducer`**:
  ```typescript
  // Assume reducer, initialState are defined
  // const [state, dispatch] = useReducer(reducer, initialState);
  
  // // Later in component
  // dispatch({ type: 'UPDATE_USER', payload: { id, data } });
  ```

### Error Handling
- **Patterns**: 
    - Use `try/catch` blocks for async operations.
    - Create custom error classes for domain-specific errors.
    - Use error boundaries for component errors (in React).
- **Example**:
  ```typescript
  class ApiError extends Error {
    constructor(message: string) {
      super(message);
      this.name = 'ApiError';
    }
  }
  
  async function fetchData() {
    // ... fetch logic that might throw ...
  }
  
  async function process() {
    let data;
    let error = null;
    try {
      data = await fetchData();
    } catch (err) {
      if (err instanceof ApiError) {
        error = `API Error: ${err.message}`;
      } else if (err instanceof Error) {
        error = `An unexpected error occurred: ${err.message}`;
        console.error(err); // Use proper logging
      } else {
        error = 'An unknown error occurred';
        console.error(err);
      }
    }
    // ... handle data or error ...
  }
  ```

### Testing (Example using Jest/React Testing Library - If Applicable)
- **Patterns**:
    - Use Jest and React Testing Library for UI components.
    - Test component behavior, not implementation details.
    - Mock API calls and external dependencies.
    - Use `data-testid` attributes for reliable test selectors.
- **Example**:
  ```typescript
  // import { render, screen, fireEvent } from '@testing-library/react';
  // import { UserProfile } from './UserProfile'; // Example component
  
  // const mockUser = { id: '1', name: 'Test User', email: 'test@example.com' };
  
  // test('displays user information correctly', () => {
  //   render(<UserProfile user={mockUser} />);
  
  //   expect(screen.getByText(mockUser.name)).toBeInTheDocument();
  //   expect(screen.getByText(mockUser.email)).toBeInTheDocument();
  
  //   // Example interaction
  //   // fireEvent.click(screen.getByRole('button', { name: /Edit Profile/i }));
  //   // expect(screen.getByTestId('edit-form')).toBeInTheDocument();
  // });
  ```

### Common Pitfalls
- Avoid `any` type; use `unknown` if type is truly unknown and perform checks.
- Be careful with nullish values; use optional chaining (`?.`) and nullish coalescing (`??`).
- Avoid type assertions (`as Type`) when possible; prefer type guards or narrowing.
- Don't use `==`; always use `===` for strict equality checks.
- Remember that empty objects (`{}`) are truthy.

