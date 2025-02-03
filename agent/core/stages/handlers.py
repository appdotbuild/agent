from typing import TypedDict
import re


PROMPT = """
Based on TypeSpec application definition and drizzle schema, generate a handler for {{function_name}} function.
Handler always accepts single argument. It should be declared at the beginning as interface Options;
Handler should satisfy following interface:

<handler>
interface Message {
    role: 'user' | 'assistant';
    content: string;
};

interface Handler<Options, Output> {
    preProcessor: (input: Message[]) => Options | Promise<Options>;
    handle: (options: Options) => Output | Promise<Output>;
    postProcessor: (output: Output, input: Message[]) => Message[] | Promise<Message[]>;
}

class GenericHandler<Options, Output> implements Handler<Options, Output> {
    constructor(
        public handle: (options: Options) => Output | Promise<Output>,
        public preProcessor: (input: Message[]) => Options | Promise<Options>,
        public postProcessor: (output: Output, input: Message[]) => Message[] | Promise<Message[]>
    ) {}

    async execute(input: Message[]): Promise<Message[] | Output> {
        const options = await this.preProcessor(input);
        const result = await this.handle(options);
        return this.postProcessor ? await this.postProcessor(result, input) : result;
    }
}
</handler>

Example handler implementation:

<handler>
import { db } from "../db";
import { customTable } from '../db/schema/application'; // all drizzle tables are defined in this file

interface Options {
    content: string;
};

const handle = (options: Options): string => {
    await db.insert(customTable).values({ content: options.content }).execute();
    return input;
};
</handler>

TypeSpec is extended with special decorator that indicates that this function
is processed by language model parametrized with number of previous messages passed to the LLM.

extern dec llm_func(target: unknown, history: valueof int32);

Application Definitions:

<typescript_schema>
{{typescript_schema}}
</typescript_schema>

<drizzle>
{{drizzle_schema}}
</drizzle>

Drizzle guide:

<drizzle_guide>
# Drizzle ORM Quick Reference

## Essential Commands

### Query Operations
```typescript
// Select
const all = await db.select().from(users);
const one = await db.select().from(users).where(eq(users.id, 1));
const custom = await db.select({
  id: users.id,
  name: users.name
}).from(users);

// Insert
const single = await db.insert(users).values({ name: 'John' });
const multi = await db.insert(users).values([
  { name: 'Alice' },
  { name: 'Bob' }
]);

// Update 
await db.update(users)
  .set({ name: 'John' })
  .where(eq(users.id, 1));

// Delete
await db.delete(users).where(eq(users.id, 1));
```

### Relations & Joins
```typescript
// Get related data
const usersWithPosts = await db.query.users.findMany({
  with: { posts: true }
});

// Join in SQL style
const joined = await db.select()
  .from(users)
  .leftJoin(posts, eq(users.id, posts.userId));
```

### Transactions
```typescript
const result = await db.transaction(async (tx) => {
  const user = await tx.insert(users).values({ name: 'John' });
  await tx.insert(posts).values({ userId: user.id, title: 'Post' });
});
```

### Migrations
```bash
# Create migration
drizzle-kit generate:pg

# Apply migration
drizzle-kit push:pg
```

### Common Filters
```typescript
where(eq(users.id, 1))           // equals
where(ne(users.id, 1))           // not equals
where(gt(users.age, 18))         // greater than
where(lt(users.age, 65))         // less than
where(gte(users.age, 18))        // greater or equal
where(lte(users.age, 65))        // less or equal
where(like(users.name, '%John%')) // LIKE
where(ilike(users.name, '%john%')) // ILIKE
where(and(...))                   // AND
where(or(...))                    // OR
```

## Troubleshooting Common TypeScript Errors

### 1. Operator Imports
```typescript
// Always import operators from drizzle-orm
import { eq, and, or, like, gt, lt } from 'drizzle-orm';

// For PostgreSQL specific operators
import { eq } from 'drizzle-orm/pg-core';
```

### 2. Proper Query Building
```typescript
// Correct way to build queries
const query = db.select()
  .from(table)
  .where(eq(table.column, value));

// For dynamic queries
let baseQuery = db.select().from(table);
if (condition) {
  baseQuery = baseQuery.where(eq(table.column, value));
}
```

### 3. Array Operations
```typescript
// For array comparisons, use 'in' operator instead of 'eq'
import { inArray } from 'drizzle-orm';

// Correct way to query array of values
const query = db.select()
  .from(table)
  .where(inArray(table.id, ids));

// Alternative using SQL template literal
const query = db.select()
  .from(table)
  .where(sql`${table.id} = ANY(${ids})`);
```

### 4. Type-Safe Pattern
```typescript
// Define proper types for your data
interface QueryOptions {
  exercise?: string;
  muscleGroup?: string;
}

// Type-safe query building
function buildQuery(options: QueryOptions) {
  let query = db.select().from(table);
  
  if (options.exercise) {
    query = query.where(eq(table.exercise, options.exercise));
  }
  
  if (options.muscleGroup) {
    query = query.where(eq(table.muscleGroup, options.muscleGroup));
  }
  
  return query;
}
```

### Common Fixes for TypeScript Errors

1. Missing Operators:
   - Always import operators explicitly
   - Use correct import path for your database

2. Query Chain Breaks:
   - Maintain proper query chain
   - Store intermediate query in variable for conditionals

3. Array Operations:
   - Use `inArray` for array comparisons
   - Consider using SQL template literals for complex cases

4. Type Safety:
   - Define interfaces for query options
   - Use TypeScript's type inference with proper imports

## Advanced Troubleshooting

### Query Builder Type Issues

#### 1. Missing 'where' and 'limit' Properties
This common error occurs when TypeScript loses type inference in query chains:

```typescript
// ❌ Incorrect - Type inference is lost
let query = db.select().from(table);
if (condition) {
  query = query.where(eq(table.column, value)); // Error: Property 'where' is missing
}
query = query.limit(10); // Error: Property 'limit' is missing

// ✅ Correct - Preserve type inference
const baseQuery = db.select().from(table);
const whereQuery = condition 
  ? baseQuery.where(eq(table.column, value))
  : baseQuery;
const finalQuery = whereQuery.limit(10);

// ✅ Alternative - Type assertion
let query = db.select().from(table) as typeof baseQuery;
```

#### 2. Proper Query Building Pattern
```typescript
import { eq } from 'drizzle-orm';
import { type PgSelect } from 'drizzle-orm/pg-core';

// Define interface for your options
interface QueryOptions {
  exerciseName?: string;
  limit?: number;
}

// Type-safe query builder function
function buildWorkoutQuery(
  db: Database,
  table: typeof progressTable,
  options: QueryOptions
): PgSelect {
  const baseQuery = db.select().from(table);
  
  let query = baseQuery;
  
  if (options.exerciseName) {
    query = query.where(
      eq(table.exercise_name, options.exerciseName)
    );
  }
  
  if (options.limit) {
    query = query.limit(options.limit);
  }
  
  return query;
}
```

#### 3. Real-World Example: Progress Tracking
```typescript
import { eq } from 'drizzle-orm';
import { progressTable } from './schema';
import type { Database } from './db';

interface ProgressQueryOptions {
  exerciseName?: string;
  limit?: number;
}

export async function getProgress(
  db: Database,
  options: ProgressQueryOptions
) {
  // ✅ Correct implementation
  const baseQuery = db
    .select()
    .from(progressTable);
  
  const withExercise = options.exerciseName
    ? baseQuery.where(
        eq(progressTable.exercise_name, options.exerciseName)
      )
    : baseQuery;
    
  const withLimit = options.limit
    ? withExercise.limit(options.limit)
    : withExercise;
    
  return await withLimit;
}
```

#### 4. Real-World Example: Workout History
```typescript
import { eq } from 'drizzle-orm';
import { exerciseRecordsTable } from './schema';
import type { Database } from './db';

interface WorkoutHistoryOptions {
  exerciseId?: number;
  limit?: number;
}

export async function listWorkoutHistory(
  db: Database,
  options: WorkoutHistoryOptions
) {
  // ✅ Correct implementation with type preservation
  const query = db
    .select()
    .from(exerciseRecordsTable)
    .$dynamic();  // Enable dynamic queries
    
  const withExercise = options.exerciseId
    ? query.where(
        eq(exerciseRecordsTable.exercise_id, options.exerciseId)
      )
    : query;
    
  const withLimit = options.limit
    ? withExercise.limit(options.limit)
    : withExercise;
    
  return await withLimit;
}
```

### Common Type Error Fixes

1. Lost Type Inference:
   - Use const assertions for base queries
   - Chain conditions using ternary operators
   - Use `$dynamic()` for dynamic queries

2. Import Issues:
```typescript
// ✅ Correct imports for PostgreSQL
import { eq, and, or } from 'drizzle-orm';
import type { PgSelect } from 'drizzle-orm/pg-core';

// Types for type safety
import type { InferSelectModel } from 'drizzle-orm';
import type { Database } from './db';
```

3. Type Definitions:
```typescript
// Define table types
type Progress = InferSelectModel<typeof progressTable>;
type ExerciseRecord = InferSelectModel<typeof exerciseRecordsTable>;

// Type-safe options
interface QueryOptions<T> {
  where?: Partial<T>;
  limit?: number;
}
```

4. Error Prevention Checklist:
   - Import operators explicitly (`eq`, `and`, etc.)
   - Use proper type imports for your database
   - Maintain query chain type inference
   - Use `$dynamic()` for dynamic queries
   - Define explicit interfaces for options
   - Use type assertions when necessary

These patterns will help prevent common TypeScript errors while working with Drizzle ORM, especially in workout tracking and progress monitoring systems.
</drizzle_guide>

Handler to implement: {{function_name}}

Return output within <handler> tag. Generate only the handler function and table imports from drizzle schema, omit pre- and post-processors.
Handler code should contain just explicit logic such as database operations, performing calculations etc.
""".strip()


class HandlerInput(TypedDict):
    typespec_definitions: str
    drizzle_schema: str
    function_name: str


class HandlerOutput(TypedDict):
    handler: str


def parse_output(output: str) -> HandlerOutput:
    pattern = re.compile(r"<handler>(.*?)</handler>", re.DOTALL)
    match = pattern.search(output)
    if match is None:
        raise ValueError("Failed to parse output")
    handler = match.group(1).strip()
    return HandlerOutput(handler=handler)
