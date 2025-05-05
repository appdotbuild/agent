BASE_TYPESCRIPT_SCHEMA = """
<file path="server/src/schema.ts">
import { z } from 'zod';

// Input schemas should match database field types
export const myHandlerInputSchema = z.object({
  name: z.string().nullable(), // .nullable() aligns with database .notNull() or not
});

// Consistent type naming pattern
export type MyHandlerInput = z.infer<typeof myHandlerInputSchema>;

// Response schema matching database fields
export const greetingSchema = z.object({
  id: z.number(),
  message: z.string(),
  created_at: z.coerce.date() // Use coerce.date() for timestamp fields
});

export type Greeting = z.infer<typeof greetingSchema>;
</file>
""".strip()


BASE_DRIZZLE_SCHEMA = """
<file path="server/src/db/schema.ts">
import { serial, text, pgTable, timestamp } from 'drizzle-orm/pg-core';

export const greetingsTable = pgTable('greetings', {
  id: serial('id').primaryKey(),
  message: text('message').notNull(),
  created_at: timestamp('created_at').defaultNow().notNull(),
});

// TypeScript type for the table schema
export type Greeting = typeof greetingsTable.$inferSelect;
export type NewGreeting = typeof greetingsTable.$inferInsert;

// Important: Export all tables and relations for proper query building
export const tables = { greetings: greetingsTable };
</file>
""".strip()


BASE_HANDLER_DECLARATION = """
<file path="server/src/handlers/my_handler.ts">
import { type MyHandlerInput } from '../schema';

export declare function myHandler(input: MyHandlerInput): Promise<{ message: string; id: number }>;
</file>
""".strip()


BASE_HANDLER_IMPLEMENTATION = """
<file path="server/src/handlers/my_handler.ts">
import { db } from '../db';
import { greetingsTable } from '../db/schema';
import { type MyHandlerInput } from '../schema';

export const myHandler = async (input: MyHandlerInput) => {
  try {
    // Use nullish coalescing for optional fields
    const message = `hello ${input?.name ?? 'world'}`;
    
    // Insert record and return the inserted id
    const result = await db.insert(greetingsTable)
      .values({ message })
      .returning({ id: greetingsTable.id })
      .execute();
    
    return { message, id: result[0].id };
  } catch (error) {
    console.error('Operation failed:', error);
    throw new Error('Failed to process greeting', { cause: error });
  }
};
</file>
""".strip()


BASE_HANDLER_TEST = """
<file path="server/src/tests/my_handler.test.ts">
import { afterEach, beforeEach, describe, expect, it } from 'bun:test';
import { resetDB, createDB } from '../helpers';
import { db } from '../db';
import { greetingsTable } from '../db/schema';
import { type MyHandlerInput } from '../schema';
import { myHandler } from '../handlers/my_handler';

const testInput: MyHandlerInput = { name: 'Alice' };

describe('greet', () => {
  beforeEach(createDB);

  afterEach(resetDB);

  it('should greet user', async () => {
    const result = await myHandler(testInput);
    expect(result.message).toEqual('hello Alice');
    expect(result.id).toBeDefined();
  });

  it('should save request', async () => {
    await myHandler(testInput);
    const requests = await db.select().from(greetingsTable);
    expect(requests).toHaveLength(1);
    expect(requests[0].message).toEqual('hello Alice');
  });
});
</file>
""".strip()


BASE_SERVER_INDEX = """
<file path="server/src/index.ts">
import { initTRPC } from '@trpc/server';
import { createHTTPServer } from '@trpc/server/adapters/standalone';
import 'dotenv/config';
import cors from 'cors';
import superjson from 'superjson';
import { IncomingMessage, ServerResponse } from 'http';

const t = initTRPC.create({
  transformer: superjson,
});

const publicProcedure = t.procedure;
const router = t.router;

const appRouter = router({
  healthcheck: publicProcedure.query(() => {
    return { status: 'ok', timestamp: new Date().toISOString() };
  }),
});

export type AppRouter = typeof appRouter;

function healthCheckMiddleware(req: IncomingMessage, res: ServerResponse, next: () => void) {
  if (req.url === '/health') {
    res.statusCode = 200;
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ status: 'ok', timestamp: new Date().toISOString() }));
    return;
  }
  next();
}

async function start() {
  const port = process.env['PORT'] || 2022;
  const server = createHTTPServer({
    middleware: (req, res, next) => {
      healthCheckMiddleware(req, res, next);
      cors()(req, res, next);
    },
    router: appRouter,
    createContext() {
      return {};
    },
  });
  server.listen(port);
  console.log(`TRPC server listening at port: ${port}`);
}

start();
</file>
""".strip()


BASE_APP_TSX = """
<file path="client/src/App.tsx">
import { Button } from '@/components/ui/button';
import { trpc } from '@/utils/trpc';
import { useState } from 'react';

function App() {
  const [greeting, setGreeting] = useState<{ message: string; id: number } | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const fetchGreeting = async () => {
    setIsLoading(true);
    const response = await trpc.myHandler.query({ name: 'Alice' });
    setGreeting(response);
    setIsLoading(false);
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-svh">
      <Button onClick={fetchGreeting} disabled={isLoading}>Click me</Button>
      {isLoading ? (
        <p>Loading...</p>
      ) : (
        greeting && <p>{greeting.message} (ID: {greeting.id})</p>
      )}
    </div>
  );
}

export default App;
</file>
""".strip()


TRPC_INDEX_SHIM = """
...
import { myHandlerInputSchema } from './schema';
import { myHandler } from './handlers/my_handler';
...
const appRouter = router({
  myHandler: publicProcedure
    .input(myHandlerInputSchema)
    .query(({ input }) => myHandler(input)),
});
...
""".strip()


BACKEND_DRAFT_PROMPT = f"""
- Define all types using zod in a single file server/src/schema.ts
- Always define schema and corresponding type using z.infer<typeof typeSchemaName>
Example:
{BASE_TYPESCRIPT_SCHEMA}

- Define all database tables using drizzle-orm in server/src/db/schema.ts
- IMPORTANT: Always export all tables to enable relation queries
Example:
{BASE_DRIZZLE_SCHEMA}

- For each handler write its declaration in corresponding file in server/src/handlers/
Example:
{BASE_HANDLER_DECLARATION}

- Generate root TRPC index file in server/src/index.ts
Example:
{BASE_SERVER_INDEX}

# Relevant parts to modify:
- Imports of handlers and schema types
- Registering TRPC routes
{TRPC_INDEX_SHIM}

# CRITICAL Type Alignment Rules:
1. Align Zod and Drizzle types exactly:
   - Drizzle `.notNull()` → Zod should NOT have `.nullable()`
   - Drizzle field without `.notNull()` → Zod MUST have `.nullable()`
   - Never use `.nullish()` in Zod - use `.nullable()` or `.optional()` as appropriate

2. Date handling:
   - For Drizzle `timestamp()` fields → Use Zod `z.coerce.date()` 
   - For Drizzle `date()` fields → Use Zod `z.string()` with date validation
   - Always convert dates to proper format when inserting/retrieving

3. Enum handling:
   - For Drizzle `pgEnum()` → Create matching Zod enum with `z.enum([...])`
   - NEVER accept raw string for enum fields, always validate against enum values

4. Optional vs Nullable:
   - Use `.nullable()` when a field can be explicitly null
   - Use `.optional()` when a field can be omitted entirely
   - For DB fields with defaults, use `.optional()` in input schemas

5. Type exports:
   - Export types for ALL schemas using `z.infer<typeof schemaName>`
   - Create both input and output schema types for handlers

Key project files:
{{{{project_context}}}}

Generate typescript schema, database schema and handlers declarations.
Return code within <file path="server/src/handlers/handler_name.ts">...</file> tags.
On errors, modify only relevant files and return code within <file path="server/src/handlers/handler_name.ts">...</file> tags.

Task:
{{{{user_prompt}}}}
""".strip()


BACKEND_HANDLER_PROMPT = f"""
- Write implementation for the handler function
- Write small but meaningful test set for the handler

Example Handler:
{BASE_HANDLER_IMPLEMENTATION}

Example Test:
{BASE_HANDLER_TEST}

# Important Drizzle Query Patterns:
- ALWAYS store the result of a query operation before chaining additional methods
  let query = db.select().from(myTable);
  if (condition) {{
    query = query.where(eq(myTable.field, value));
  }}
  const results = await query.execute();

- ALWAYS use the proper operators from 'drizzle-orm':
  - Use eq(table.column, value) instead of table.column === value
  - Use and([condition1, condition2]) for multiple conditions
  - Use isNull(table.column), not table.column === null
  - Use desc(table.column) for descending order

- When filtering with multiple conditions, use an array approach:
  const conditions = [];
  if (input.field1) conditions.push(eq(table.field1, input.field1));
  if (input.field2) conditions.push(eq(table.field2, input.field2));
  const query = conditions.length > 0 
    ? db.select().from(table).where(and(conditions))
    : db.select().from(table);
  const results = await query.execute();

# Error Handling & Logging Best Practices:
- Wrap database operations in try/catch blocks
- Log the full error object, not just the message:
  ```
  try {{
    // Database operations
  }} catch (error) {{
    console.error('Operation failed:', error);
    throw new Error('User-friendly message');
  }}
  ```
- Use specific error types or codes to distinguish between error cases
- When rethrowing errors, include the original error as the cause:
  ```
  throw new Error('Failed to process request', {{ cause: error }});
  ```
- Add context to errors including input parameters (but exclude sensitive data!)
- In tests, verify error handling with expect.throws() assertions

Key project files:
{{{{project_context}}}}

Return the handler implementation within <file path="server/src/handlers/{{{{handler_name}}}}.ts">...</file> tags.
Return the test code within <file path="server/src/tests/{{{{handler_name}}}}.test.ts">...</file> tags.
""".strip()


FRONTEND_PROMPT = f"""
- Generate react frontend application using radix-ui components.
- Backend communication is done via TRPC.

Example:
{BASE_APP_TSX}

# Client-Side Tips:
- Always match frontend state types with exactly what the tRPC endpoint returns
- For tRPC queries, store the complete response object before using its properties
- Access nested data correctly based on the server's return structure

Key project files:
{{{{project_context}}}}

Return code within <file path="client/src/components/{{{{component_name}}}}.tsx">...</file> tags.
On errors, modify only relevant files and return code within <file path="...">...</file> tags.

Task:
{{{{user_prompt}}}}
""".strip()


SILLY_PROMPT = """
Files:
{% for file in files_ctx|sort %}{{ file }} {% endfor %}
{% for file in workspace_ctx|sort %}{{ file }} {% endfor %}
Relevant files:
{% for file in workspace_visible_ctx|sort %}{{ file }} {% endfor %}
Allowed files and directories:
{% for file in allowed|sort %}{{ file }} {% endfor %}
Restricted files and directories:
{% for file in protected|sort %}{{ file }} {% endfor %}
Rules:
- Must write small but meaningful tests for newly created handlers.
- Must not modify existing code unless necessary.
TASK:
{{ user_prompt }}
""".strip()
