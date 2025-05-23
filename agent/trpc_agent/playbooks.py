BASE_TYPESCRIPT_SCHEMA = """
<file path="server/src/schema.ts">
import { z } from 'zod';

// Product schema with proper numeric handling
export const productSchema = z.object({
  id: z.number(),
  name: z.string(),
  description: z.string().nullable(), // Nullable field, not optional (can be explicitly null)
  price: z.number(), // Stored as numeric in DB, but we use number in TS
  stock_quantity: z.number().int(), // Ensures integer values only
  created_at: z.coerce.date() // Automatically converts string timestamps to Date objects
});

export type Product = z.infer<typeof productSchema>;

// Input schema for creating products
export const createProductInputSchema = z.object({
  name: z.string(),
  description: z.string().nullable(), // Explicit null allowed, undefined not allowed
  price: z.number().positive(), // Validate that price is positive
  stock_quantity: z.number().int().nonnegative() // Validate that stock is non-negative integer
});

export type CreateProductInput = z.infer<typeof createProductInputSchema>;

// Input schema for updating products
export const updateProductInputSchema = z.object({
  id: z.number(),
  name: z.string().optional(), // Optional = field can be undefined (omitted)
  description: z.string().nullable().optional(), // Can be null or undefined
  price: z.number().positive().optional(),
  stock_quantity: z.number().int().nonnegative().optional()
});

export type UpdateProductInput = z.infer<typeof updateProductInputSchema>;
</file>
""".strip()


BASE_DRIZZLE_SCHEMA = """
<file path="server/src/db/schema.ts">
import { serial, text, pgTable, timestamp, numeric, integer } from 'drizzle-orm/pg-core';

export const productsTable = pgTable('products', {
  id: serial('id').primaryKey(),
  name: text('name').notNull(),
  description: text('description'), // Nullable by default, matches Zod schema
  price: numeric('price', { precision: 10, scale: 2 }).notNull(), // Use numeric for monetary values with precision
  stock_quantity: integer('stock_quantity').notNull(), // Use integer for whole numbers
  created_at: timestamp('created_at').defaultNow().notNull(),
});

// TypeScript type for the table schema
export type Product = typeof productsTable.$inferSelect; // For SELECT operations
export type NewProduct = typeof productsTable.$inferInsert; // For INSERT operations

// Important: Export all tables and relations for proper query building
export const tables = { products: productsTable };
</file>
""".strip()


BASE_HANDLER_DECLARATION = """
<file path="server/src/handlers/create_product.ts">
import { type CreateProductInput, type Product } from '../schema';

export declare function createProduct(input: CreateProductInput): Promise<Product>;
</file>
""".strip()


BASE_HANDLER_IMPLEMENTATION = """
<file path="server/src/handlers/create_product.ts">
import { db } from '../db';
import { productsTable } from '../db/schema';
import { type CreateProductInput, type Product } from '../schema';

export const createProduct = async (input: CreateProductInput): Promise<Product> => {
  try {
    // Insert product record
    const result = await db.insert(productsTable)
      .values({
        name: input.name,
        description: input.description,
        price: input.price, // Type safely passed to numeric column
        stock_quantity: input.stock_quantity // Type safely passed to integer column
      })
      .returning()
      .execute();

    // Return product data with proper typing
    return result[0];
  } catch (error) {
    // Log the detailed error
    console.error('Product creation failed:', error);

    // Re-throw the original error to preserve stack trace
    throw error;
  }
};
</file>
""".strip()


BASE_HANDLER_TEST = """
<file path="server/src/tests/create_product.test.ts">
import { afterEach, beforeEach, describe, expect, it } from 'bun:test';
import { resetDB, createDB } from '../helpers';
import { db } from '../db';
import { productsTable } from '../db/schema';
import { type CreateProductInput } from '../schema';
import { createProduct } from '../handlers/create_product';
import { eq, gte, between, and } from 'drizzle-orm';

// Simple test input
const testInput: CreateProductInput = {
  name: 'Test Product',
  description: 'A product for testing',
  price: 19.99,
  stock_quantity: 100
};

describe('createProduct', () => {
  beforeEach(createDB);
  afterEach(resetDB);

  it('should create a product', async () => {
    const result = await createProduct(testInput);

    // Basic field validation
    expect(result.name).toEqual('Test Product');
    expect(result.description).toEqual(testInput.description);
    expect(result.price).toEqual(19.99);
    expect(result.stock_quantity).toEqual(100);
    expect(result.id).toBeDefined();
    expect(result.created_at).toBeInstanceOf(Date);
  });

  it('should save product to database', async () => {
    const result = await createProduct(testInput);

    // Query using proper drizzle syntax
    const products = await db.select()
      .from(productsTable)
      .where(eq(productsTable.id, result.id))
      .execute();

    expect(products).toHaveLength(1);
    expect(products[0].name).toEqual('Test Product');
    expect(products[0].description).toEqual(testInput.description);
    expect(products[0].price).toEqual(19.99);
    expect(products[0].created_at).toBeInstanceOf(Date);
  });

  it('should query products by date range correctly', async () => {
    // Create test product
    await createProduct(testInput);

    // Test date filtering - demonstration of correct date handling
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);

    // Proper query building - step by step
    let query = db.select()
      .from(productsTable);

    // Apply date filter - Date objects work directly with timestamp columns
    query = query.where(
      and([
        gte(productsTable.created_at, today),
        between(productsTable.created_at, today, tomorrow)
      ])
    );

    const products = await query.execute();

    expect(products.length).toBeGreaterThan(0);
    products.forEach(product => {
      expect(product.created_at).toBeInstanceOf(Date);
      expect(product.created_at >= today).toBe(true);
      expect(product.created_at <= tomorrow).toBe(true);
    });
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
  const port = process.env['SERVER_PORT'] || 2022;
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
// Using type-only import for better TypeScript compliance
import type { Product } from '../../../server/src/schema';

function App() {
  // Explicit typing with Product interface
  const [product, setProduct] = useState<Product | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const createSampleProduct = async () => {
    setIsLoading(true);
    try {
      // Send numeric values directly - tRPC handles validation via Zod
      const response = await trpc.createProduct.mutate({
        name: 'Sample Product',
        description: 'A sample product created from the UI',
        price: 29.99,
        stock_quantity: 50
      });
      // Complete response with proper types thanks to tRPC
      setProduct(response);
    } catch (error) {
      console.error('Failed to create product:', error);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col items-center justify-center min-h-svh gap-4">
      <h1 className="text-2xl font-bold">Product Management</h1>

      <Button onClick={createSampleProduct} disabled={isLoading}>
        Create Sample Product
      </Button>

      {isLoading ? (
        <p>Creating product...</p>
      ) : product ? (
        <div className="border p-4 rounded-md">
          <h2 className="text-xl font-semibold">{product.name}</h2>
          <p className="text-gray-600">{product.description}</p>
          <div className="flex justify-between mt-2">
            <span>${product.price.toFixed(2)}</span>
            <span>In stock: {product.stock_quantity}</span>
          </div>
          <p className="text-xs text-gray-400 mt-2">
            {/* created_at is a Date object thanks to z.coerce.date() */}
            Created: {product.created_at.toLocaleDateString()}
          </p>
        </div>
      ) : (
        <p>No product created yet. Click the button to create one.</p>
      )}
    </div>
  );
}

export default App;
</file>
""".strip()


TRPC_INDEX_SHIM = """
...
import { createProductInputSchema } from './schema';
import { createProduct } from './handlers/create_product';
...
const appRouter = router({
  createProduct: publicProcedure
    .input(createProductInputSchema)
    .mutation(({ input }) => createProduct(input)),
});
...
""".strip()

TYPE_ALIGNMENT_RULES = """# CRITICAL Type Alignment Rules:
1. Align Zod and Drizzle types exactly:
   - Drizzle `.notNull()` → Zod should NOT have `.nullable()`
   - Drizzle field without `.notNull()` → Zod MUST have `.nullable()`
   - Never use `.nullish()` in Zod - use `.nullable()` or `.optional()` as appropriate

2. Numeric type handling:
   - Drizzle `real()` and `integer()` return native number values from the database
   - Define your Zod schema with `z.number()` for these column types
   - For integer values, use `z.number().int()` for proper validation
   - Example: for `integer('quantity')`, use `z.number().int()`
   - Example: for `real('price')`, use `z.number()`

3. Date handling:
   - For Drizzle `timestamp()` fields → Use Zod `z.coerce.date()`
   - For Drizzle `date()` fields → Use Zod `z.string()` with date validation
   - Always convert dates to proper format when inserting/retrieving

4. Enum handling:
   - For Drizzle `pgEnum()` → Create matching Zod enum with `z.enum([...])`
   - NEVER accept raw string for enum fields, always validate against enum values

5. Optional vs Nullable:
   - Use `.nullable()` when a field can be explicitly null
   - Use `.optional()` when a field can be omitted entirely
   - For DB fields with defaults, use `.optional()` in input schemas

6. Type exports:
   - Export types for ALL schemas using `z.infer<typeof schemaName>`
   - Create both input and output schema types for handlers

7. Database query patterns:
   - Always build queries step-by-step, applying `.where()` before `.limit()`, `.offset()`, or `.orderBy()`
   - For conditional queries, initialize the query first, then apply filters conditionally
   - When filtering with multiple conditions, collect conditions in an array and apply `.where(and([...conditions]))`
   - Example pattern for conditional filters:
     ```typescript
     // Good pattern for conditional filters
     let query = db.select().from(productsTable);

     const conditions: SQL<unknown>[] = [];

     if (filters.minPrice !== undefined) {
       conditions.push(gte(productsTable.price, filters.minPrice));
     }

     if (filters.category) {
       conditions.push(eq(productsTable.category, filters.category));
     }

     if (conditions.length > 0) {
       query = query.where(conditions.length === 1 ? conditions[0] : and(conditions));
     }

     // Apply other query modifiers AFTER where clause
     if (orderBy) {
       query = query.orderBy(desc(productsTable[orderBy]));
     }

     // Apply pagination LAST
     query = query.limit(limit).offset(offset);

     const results = await query.execute();
     ```

8. Testing Best Practices:
   - Create reliable test setup with prerequisite data:
     ```typescript
     beforeEach(async () => {
       // Always create prerequisite data first (users, categories, etc.)
       const user = await db.insert(usersTable)
         .values({ name: 'Test User', email: 'test@example.com' })
         .returning()
         .execute();

       testUserId = user[0].id; // Store IDs for relationships

       // Then create dependent data referencing the prerequisites
       await db.insert(clientsTable)
         .values({ name: 'Test Client', user_id: testUserId })
         .returning()
         .execute();
     });
     ```
   - Clean up after tests to prevent test interference:
     ```typescript
     afterEach(resetDB); // Use a reliable database reset function
     ```
   - Use flexible error assertions:
     ```typescript
     // Avoid brittle exact message checks
     expect(() => deleteInvoice(999)).rejects.toThrow(/not found/i);
     ```
   - Verify both application state and database state in tests
   - Explicitly define expected test inputs with proper types
"""

BACKEND_DRAFT_SYSTEM_PROMPT = f"""
You are software engineer, follow those rules:

- Define all types using zod in a single file server/src/schema.ts
- Always define schema and corresponding type using z.infer<typeof typeSchemaName>
Example:
{BASE_TYPESCRIPT_SCHEMA}

- Define all database tables using drizzle-orm in server/src/db/schema.ts
- IMPORTANT: Always export all tables to enable relation queries
Example:
{BASE_DRIZZLE_SCHEMA}

- For each handler write its declaration in corresponding file in server/src/handlers/; prefer simple handlers, follow single responsibility principle
Example:
{BASE_HANDLER_DECLARATION}

- Generate root TRPC index file in server/src/index.ts
Example:
{BASE_SERVER_INDEX}

# Relevant parts to modify:
- Imports of handlers and schema types
- Registering TRPC routes
{TRPC_INDEX_SHIM}

{TYPE_ALIGNMENT_RULES}

Keep the things simple and do not create entities that are not explicitly required by the task.
""".strip()

BACKEND_DRAFT_USER_PROMPT = """
Key project files:
{{project_context}}

Generate typescript schema, database schema and handlers declarations.
Return code within <file path="server/src/handlers/handler_name.ts">...</file> tags.
On errors, modify only relevant files and return code within <file path="server/src/handlers/handler_name.ts">...</file> tags.

Task:
{{user_prompt}}
""".strip()


BACKEND_HANDLER_SYSTEM_PROMPT = f"""
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
- When rethrowing errors, include the original error as the cause:
  ```
  throw new Error('Failed to process request', {{ cause: error }});
  ```
- Add context to errors including input parameters (but exclude sensitive data!)
- Error handling does not need to be tested in unit tests.
""".strip()

BACKEND_HANDLER_USER_PROMPT = """
Key project files:
{{project_context}}

Return the handler implementation within <file path="server/src/handlers/{{handler_name}}.ts">...</file> tags.
Return the test code within <file path="server/src/tests/{{handler_name}}.test.ts">...</file> tags.
""".strip()


FRONTEND_SYSTEM_PROMPT = f"""You are software engineer, follow those rules:
- Generate react frontend application using radix-ui components.
- Backend communication is done via TRPC.

Example:
{BASE_APP_TSX}

# Client-Side Tips:
- Always match frontend state types with exactly what the tRPC endpoint returns
- For tRPC queries, store the complete response object before using its properties
- Access nested data correctly based on the server's return structure
- Always use type-only imports for TypeScript type definitions
- For numeric values coming from DB via Drizzle, ensure your schemas properly transform string values to numbers
- Remember that Date objects coming from the server can be directly used with methods like `.toLocaleDateString()`
- Use proper TypeScript typing for all state variables and function parameters
""".strip()

FRONTEND_USER_PROMPT = """
Key project files:
{{project_context}}

Return code within <file path="client/src/components/example_component_name.tsx">...</file> tags.
On errors, modify only relevant files and return code within <file path="...">...</file> tags.

Task:
{{user_prompt}}
""".strip()


FRONTEND_VALIDATION_PROMPT = """Given the attached screenshot, decide where the frontend code is correct and relevant to the original prompt. Keep in mind that the backend is currently not implemented, so you can only validate the frontend code and ignore the backend part.
Original prompt to generate this website: {{ user_prompt }}.

Console logs from the browsers:
{{ console_logs }}

Answer "yes" or "no" wrapped in <answer> tag. Follow the example below.

Example 1:
<reason>the website looks valid</reason>
<answer>yes</answer>

Example 2:
<reason>there is nothing on the screenshot, could be rendering issue</reason>
<answer>no</answer>

Example 3:
<reason>the website looks okay, but displays database connection error. Given it is not frontend-related, I should answer yes</reason>
<answer>yes</answer>
"""
FULL_UI_VALIDATION_PROMPT = """Given the attached screenshot and browser logs, decide where the app is correct and working.
{% if user_prompt %} User prompt: {{ user_prompt }} {% endif %}
Console logs from the browsers:
{{ console_logs }}

Answer "yes" or "no" wrapped in <answer> tag. Follow the example below.

Example 1:
<reason>the website looks okay, but displays database connection error. Given we evaluate full app, I should answer no</reason>
<answer>no</answer>

Example 2:
<reason>there is nothing on the screenshot, could be rendering issue</reason>
<answer>no</answer>

Example 3:
<reason>the website looks valid</reason>
<answer>yes</answer>
"""

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
