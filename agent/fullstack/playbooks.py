BASE_TYPESCRIPT_SCHEMA = """
<file path="src/schema.ts">
import { z } from 'zod';

export const myHandlerInputSchema = z.object({
  name: z.string().nullish(),
});

export type myHandlerInput = z.infer<typeof myHandlerInputSchema>;
</file>
""".strip()


BASE_DRIZZLE_SCHEMA = """
<file path="src/db/schema.ts">
import { serial, text, pgTable, timestamp } from "drizzle-orm/pg-core";

export const greetingsTable = pgTable("greetings", {
  id: serial("id").primaryKey(),
  message: text("message").notNull(),
  created_at: timestamp("created_at").defaultNow().notNull()
});
</file>
""".strip()


BASE_HANDLER_DECLARATION = """
<file path="src/handlers/my_handler.ts">
import { type myHandlerInput } from "../schema";

export declare function myHandler(input: myHandlerInput): Promise<{ message: string }>;
</file>
""".strip()


BASE_HANDLER_IMPLEMENTATION = """
<file path="src/handlers/my_handler.ts">
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
<file path="src/handlers/my_handler.test.ts">
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
<file path="src/index.ts">
import { initTRPC } from '@trpc/server';
import { createHTTPServer } from '@trpc/server/adapters/standalone';
import 'dotenv/config';
import cors from 'cors';
import superjson from 'superjson';
import { myHandlerInputSchema } from './schema';
import { myHandler } from './handlers/my_handler';

const t = initTRPC.create({
  transformer: superjson,
});

const publicProcedure = t.procedure;
const router = t.router;

const appRouter = router({
  myHandler: publicProcedure
    .input(myHandlerInputSchema)
    .query(({ input }) => myHandler(input)),
});

export type AppRouter = typeof appRouter;

async function start() {
  const port = process.env['PORT'] || 2022;
  const server = createHTTPServer({
    middleware: cors(),
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
<file path="src/App.tsx">
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
