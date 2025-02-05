from dataclasses import dataclass
from contextlib import contextmanager
import re
import uuid
import jinja2
from anthropic.types import MessageParam
from langfuse.decorators import observe
from .common import TaskNode
from tracing_client import TracingClient
from compiler.core import Compiler, CompileResult


PROMPT = """
Based on TypeScript application definition and drizzle schema, generate a handler for {{function_name}} function.
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
import { customTable } from "../db/schema/application"; // all drizzle tables are defined in this file

interface Options {
    content: string;
};

export const handle = (options: Options): string => {
    await db.insert(customTable).values({ content: options.content }).execute();
    return input;
};

</handler>

Application Definitions:

<typespec>
{{typesspec_schema}}
</typespec>

<typescript>
{{typescript_schema}}
</typescript>

<drizzle>
{{drizzle_schema}}
</drizzle>

Handler to implement: {{function_name}}

Return output within <handler> tag.

Generate only:
1. The handler export function with Options, Output interfaces,
2. Required table imports from drizzle schema (STRICTLY FOLLOW EXACT NAMES OF TABLES TO DRIZZLE SCHEMA): 'import { customTable } from "../db/schema/application"; // all drizzle tables are defined in this file',
3. Statement if required: 'import { db } from "../db";',
4. Relevant imports from Drizzle ORM if required: 'import { eq } from "drizzle-orm";',
5. Required only imports from typespec schema (STRICTLY FOLLOW EXACT NAMES OF TYPES TO TYPESCRIPT SCHEMA): 'import { CarPoem } from "../common/schema";'.

Omit in generated code:
1. Avoid generating Pre- and Post-processors,
2. Avoid adding unused imports,
3. Avoid importing any other other files.

Handler function code should make use of TypeScript schema types and interfaces and drizzle schema types and interfaces and contain just explicit logic such as database operations, performing calculations etc.

Code style:
1. Always use quotes "" not '' for strings,
2. TypeScript types must be imported using a type-only import since 'verbatimModuleSyntax' is enabled.

Drizzle guide:

<drizzle_guide>
# Drizzle ORM Quick Reference

## Essential Commands

### Query Operations
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

### Relations & Joins
// Get related data
const usersWithPosts = await db.query.users.findMany({
  with: { posts: true }
});

// Join in SQL style
const joined = await db.select()
  .from(users)
  .leftJoin(posts, eq(users.id, posts.userId));

### Transactions
const result = await db.transaction(async (tx) => {
  const user = await tx.insert(users).values({ name: 'John' });
  await tx.insert(posts).values({ userId: user.id, title: 'Post' });
});

### Common Filters
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

## Troubleshooting Common TypeScript Errors

### 1. Operator Imports
// Always import operators from drizzle-orm
import { eq, and, or, like, gt, lt } from 'drizzle-orm';

// For PostgreSQL specific operators
import { eq } from 'drizzle-orm/pg-core';

### 2. Proper Query Building
// Correct way to build queries
const query = db.select()
  .from(table)
  .where(eq(table.column, value));

// For dynamic queries
let baseQuery = db.select().from(table);
if (condition) {
  baseQuery = baseQuery.where(eq(table.column, value));
}

### 3. Array Operations
// For array comparisons, use 'in' operator instead of 'eq'
import { inArray } from "drizzle-orm";

// Correct way to query array of values
const query = db.select()
  .from(table)
  .where(inArray(table.id, ids));

// Alternative using SQL template literal
const query = db.select()
  .from(table)
  .where(sql`${table.id} = ANY(${ids})`);

### 4. Type-Safe Pattern
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

#### 2. Proper Query Building Pattern
import { db } from '../db';
import { eq } from 'drizzle-orm';
import { type PgSelect } from "drizzle-orm/pg-core";

// Define interface for your options
interface QueryOptions {
  exerciseName?: string;
  limit?: number;
}

// Type-safe query builder function
function buildWorkoutQuery(
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

#### 3. Real-World Example: Progress Tracking
import { eq } from "drizzle-orm";
import { progressTable } from "../db/schema/application";
import { db } from '../db';

interface ProgressQueryOptions {
  exerciseName?: string;
  limit?: number;
}

export async function getProgress(
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

#### 4. Real-World Example: Workout History
import { eq } from "drizzle-orm";
import { exerciseRecordsTable } from "../db/schema/application";
import { db } from '../db';

interface WorkoutHistoryOptions {
  exerciseId?: number;
  limit?: number;
}

export async function listWorkoutHistory(
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

### Common Type Error Fixes

1. Lost Type Inference:
   - Use const assertions for base queries
   - Chain conditions using ternary operators
   - Use `$dynamic()` for dynamic queries

2. Import Issues:
// ✅ Correct imports for PostgreSQL
import { eq, and, or } from "drizzle-orm";
import type { PgSelect } from "drizzle-orm/pg-core";

// Types for type safety
import type { InferSelectModel } from 'drizzle-orm';
import { db } from '../db';

3. Type Definitions:
// Define table types
type Progress = InferSelectModel<typeof progressTable>;
type ExerciseRecord = InferSelectModel<typeof exerciseRecordsTable>;

// Type-safe options
interface QueryOptions<T> {
  where?: Partial<T>;
  limit?: number;
}

4. Error Prevention Checklist:
   - Import operators explicitly (`eq`, `and`, etc.)
   - Use proper type imports for your database
   - Maintain query chain type inference
   - Use `$dynamic()` for dynamic queries
   - Define explicit interfaces for options
   - Use type assertions when necessary

These patterns will help prevent common TypeScript errors while working with Drizzle ORM, especially in workout tracking and progress monitoring systems.
</drizzle_guide>

""".strip()


FIX_PROMPT = """
Make sure to address following TypeScript compilation errors:
<errors>
{{errors}}
</errors>

Verify absence of reserved keywords in property names, type names, and function names.
Return fixed complete TypeScript definition encompassed with <typescript> tag.
"""

@dataclass
class HandlerOutput:
    handler: str
    feedback: CompileResult

@dataclass
class HandlerData:
    messages: list[MessageParam]
    #function_name: str
    output: HandlerOutput | Exception

class HandlerTaskNode(TaskNode[HandlerData, list[MessageParam]]):
    @property
    def run_args(self) -> list[MessageParam]:
        fix_template = typescript_jinja_env.from_string(FIX_PROMPT)
        messages = []
        for node in self.get_trajectory():
            messages.extend(node.data.messages)
            content = None
            match node.data.output:
                case HandlerOutput(feedback={"exit_code": exit_code, "stdout": stdout}) if exit_code != 0:
                    content = fix_template.render(errors=stdout)
                case Exception() as e:
                    content = fix_template.render(errors=str(e))
                case catch_all:
                    raise RuntimeError(f"Received non-matched case: {catch_all}")
            if content:
                messages.append({"role": "user", "content": content})
        return messages #, self.data.function_name            

    @staticmethod
    @observe(capture_input=False, capture_output=False)
    def run(input: list[MessageParam], *args, **kwargs) -> HandlerData:
        response = typescript_client.call_anthropic(
            model="anthropic.claude-3-5-sonnet-20241022-v2:0",
            max_tokens=8192,
            messages=input,
        )
        try:
            handler = HandlerTaskNode.parse_output(response.content[0].text)
            #feedback = typescript_compiler.compile_typescript({f"src/handlers/{kwargs['function_name']}.ts": handler})
            handler_filename = str(uuid.uuid4())
            feedback = typescript_compiler.compile_typescript({f"src/handlers/{kwargs['function_name']}.ts": handler, 
                                                               "src/common/schema.ts": kwargs['typescript_schema'], 
                                                               "src/db/schema/application.ts": kwargs['drizzle_schema']})
            output = HandlerOutput(
                handler=handler,
                feedback=feedback,
            )
        except Exception as e:
            output = e
        messages = [{"role": "assistant", "content": response.content[0].text}]
        #return HandlerData(messages=messages, output=output, function_name=kwargs['function_name'])
        return HandlerData(messages=messages, output=output)
    @property
    def is_successful(self) -> bool:
        return (
            not isinstance(self.data.output, Exception)
            and self.data.output.feedback["exit_code"] == 0
        )
    
    @staticmethod
    @contextmanager
    def platform(client: TracingClient, compiler: Compiler, jinja_env: jinja2.Environment):
        try:
            global typescript_client
            global typescript_compiler
            global typescript_jinja_env
            typescript_client = client
            typescript_compiler = compiler
            typescript_jinja_env = jinja_env
            yield
        finally:
            del typescript_client
            del typescript_compiler
            del typescript_jinja_env
    
    @staticmethod
    def parse_output(output: str) -> HandlerOutput:
        pattern = re.compile(r"<handler>(.*?)</handler>", re.DOTALL)
        match = pattern.search(output)
        if match is None:
            raise ValueError("Failed to parse output")
        handler = match.group(1).strip()
        return handler
