BASE_TYPESCRIPT_SCHEMA = """
<file path="server/src/schema.ts">
import { z } from 'zod';

export const myHandlerInputSchema = z.object({
  name: z.string().nullish(),
});

export type myHandlerInput = z.infer<typeof myHandlerInputSchema>;
</file>
""".strip()


BASE_DRIZZLE_SCHEMA = """
<file path="server/src/db/schema.ts">
import { serial, text, pgTable, timestamp } from "drizzle-orm/pg-core";

export const greetingsTable = pgTable("greetings", {
  id: serial("id").primaryKey(),
  message: text("message").notNull(),
  created_at: timestamp("created_at").defaultNow().notNull()
});
</file>
""".strip()


BASE_HANDLER_DECLARATION = """
<file path="server/src/handlers/my_handler.ts">
import { type myHandlerInput } from "../schema";

export declare function myHandler(input: myHandlerInput): Promise<{ message: string }>;
</file>
""".strip()


BASE_HANDLER_IMPLEMENTATION = """
<file path="server/src/handlers/my_handler.ts">
import { db } from '../db';
import { greetingsTable } from '../db/schema';
import { type myHandlerInput } from "../schema";

export const myHandler = async (input: myHandlerInput) => {
  const message = `hello ${input?.name ?? 'world'}`;
  await db.insert(greetingsTable).values({ message }).execute();
  return { message };
};
</file>
""".strip()


BASE_HANDLER_TEST = """
<file path="server/src/handlers/my_handler.test.ts">
import { afterEach, beforeEach, describe, expect, it } from "bun:test";
import { resetDB, createDB } from "../helpers";
import { db } from "../db";
import { greetingsTable } from "../db/schema";
import { type myHandlerInput } from "../schema";
import { myHandler } from "../handlers/my_handler";

const testInput: myHandlerInput = { name: "Alice" };

describe("greet", () => {
  beforeEach(createDB);

  afterEach(resetDB);

  it("should greet user", async () => {
    const { message } = await myHandler(testInput);
    expect(message).toEqual("hello Alice");
  });

  it("should save request", async () => {
    await myHandler(testInput);
    const requests = await db.select().from(greetingsTable);
    expect(requests).toHaveLength(1);
    expect(requests[0].message).toEqual("hello Alice");
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
  const [greeting, setGreeting] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const fetchGreeting = async () => {
    setIsLoading(true);
    const { message } = await trpc.myHandler.query({ name: 'Alice' });
    setGreeting(message);
    setIsLoading(false);
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-svh">
      <Button onClick={fetchGreeting} disabled={isLoading}>Click me</Button>
      {isLoading ? (
        <p>Loading...</p>
      ) : (
        greeting && <p>{greeting}</p>
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

Example:
{BASE_HANDLER_TEST}

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

Key project files:
{{{{project_context}}}}

Return code within <file path="client/src/components/component_name.tsx">...</file> tags.
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


EDIT_SET_PROMPT = """
Files:
{% for file in files_ctx|sort %}{{ file }} {% endfor %}

Task:
- Identify project files required for edits or deletion to implement changes.
- Write draft changes to files if altering `server/src/db/schema.ts` or `server/src/schema.ts`.
- Run checks to validate correctness of changeset.
- Narrow down the scope to the minimum necessary.

Requirements:
{{ user_prompt }}
""".strip()
