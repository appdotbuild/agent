from typing import Protocol, Self
import re
import jinja2
from anthropic.types import MessageParam
from compiler.core import Compiler, CompileResult
from . import llm_common
from .common import AgentMachine


PROMPT = """
Based on TypeScript application definition and drizzle schema, generate a handler for {{function_name}} function.

Example:
<typespec>
model GreetRequest {
    name: string;
}

interface GreetBot {
    @llm_func(1)
    greet(options: GreetRequest): string;
}
</typespec>

<typescript>
import { z } from 'zod';

const greetRequestSchema = z.object({
    name: z.string(),
});

export type GreetRequest = z.infer<typeof greetRequestSchema>;

declare function greet(options: GreetRequest): string;
</typescript>

<drizzle>
import { integer, pgTable, text, timestamp } from "drizzle-orm/pg-core";

export const greetRequestsTable = pgTable("greet_requests", {
  id: integer().primaryKey().generatedAlwaysAsIdentity(),
  name: text().notNull(),
  created_at: timestamp().notNull().defaultNow(),
});

export const greetResponsesTable = pgTable("greet_responses", {
  id: integer().primaryKey().generatedAlwaysAsIdentity(),
  request_id: integer().references(() => greetRequestsTable.id),
  response_text: text().notNull(),
  created_at: timestamp().notNull().defaultNow(),
});
</drizzle>

<handler>
import { db } from "../db";
import { greetUser, type GreetRequest } from "../common/schema";
import { greetingsTable } from "../db/schema/application";

export const handle: typeof greetUser = async (options: GreetRequest): Promise<string> => {
    await db.insert(greetingsTable).values({
        name: options.name,
        response: `Hello, ${options.name}!`,
    }).execute();

    return `Hello, ${options.name}!`;
}
</handler>

Handler function code should make use of:
1. TypeScript schema types and interfaces,
2. Handler input and interfaces and
3. drizzle schema types and interfaces and
must contain to handle user input:
1. explicit business logic
such as:
1. database operations,
2. performing calculations etc.

Code style:
1. Always use quotes "" not '' for strings,
2. TypeScript types must be imported using a type-only import since 'verbatimModuleSyntax' is enabled,
3. Use underscored names (i.e. _options) if they not used in the code (e.g. in function parameters).
4. Make sure to consistently use nullability and never assign null to non-nullable types. For example:
    - If a field is defined as `string` in an interface, don't assign `null` or `undefined` to it
    - If a field can be null, explicitly define it as `string | null` in the interface
    - When working with arrays of objects, ensure each object property matches the interface type exactly
    - Use optional properties with `?` instead of allowing null values where appropriate
5. Use PascalCase for all type names (e.g. `UserProfile`, `WorkoutRoutine`, `ProgressMetrics`) and camelCase for variables/properties. For example:
    - Interface names should be PascalCase: `interface UserProfile`
    - Type aliases should be PascalCase: `type ResponseData`
    - Generic type parameters should be PascalCase: `Array<UserData>`
    - Enum names should be PascalCase: `enum UserRole`


Note on imports:
* Use only required imports, reread the code to make sure you are importing only required files,
* STRICTLY FOLLOW EXACT NAMES OF TABLES TO DRIZZLE SCHEMA, TYPE NAMES FROM TYPESPEC SCHEMA,
* Drizzle schema imports must always be from "../db/schema/application", for example: import { customTable } from "../db/schema/application";,
* Typespec schema imports must always be from "../common/schema", for example: import { CarPoem } from "../common/schema";,
* Drizzle ORM operators imports must come from "drizzle-orm" if required: import { eq } from "drizzle-orm";
* If using db instance, use: import { db } from "../db";,

Drizzle style guide:

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

Application Definitions:

<typespec>
{{typespec_schema}}
</typespec>

<typescript>
{{typescript_schema}}
</typescript>

<drizzle>
{{drizzle_schema}}
</drizzle>

Generate handler code for the function {{function_name}} based on the provided TypeSpec, TypeScript and Drizzle schema.
Include ```import { {{function_name}} } from "../common/schema";``` in the handler code. Ensure that handle is : typeof {{function_name}}.
Return complete handler code encompassed with <handler> tag.
""".strip()


FIX_PROMPT = """
{% if errors %}
Make sure to address following errors:

<errors>
{{errors}}
</errors>
{% endif %}

{% if additional_feedback %}
Additional feedback:
<feedback>
{{additional_feedback}}
</feedback>
{% endif %}

Verify absence of reserved keywords in property names, type names, and function names.
Return fixed complete TypeScript definition encompassed with <handler> tag.
""".strip()


FEEDBACK_PROMPT = """
Based on TypeScript application definition and drizzle schema, revise the handler for {{function_name}} function.

<typescript>
{{typescript_schema}}
</typescript>

<drizzle>
{{drizzle_schema}}
</drizzle>

Here is your previous handler implementation:
<previous_handler>
{{previous_source}}
</previous_handler>

Please revise the handler based on this feedback:
<feedback>
{{feedback}}
</feedback>

Return your revised handler code encompassed with <handler> tag.
""".strip()


class HandlersContext(Protocol):
    compiler: Compiler


class HandlersMachine(AgentMachine[HandlersContext]):
    function_name: str
    typescript_schema: str
    drizzle_schema: str
    test_suite: str | None

    _HANDLER_PATTERN = re.compile(r"<handler>(.*?)</handler>", re.DOTALL)

    def parse_output(self, output: str) -> str:
        matches = self._HANDLER_PATTERN.findall(output)
        if not matches:
            raise ValueError("Failed to parse output, expected <handler> tags.")
        # Get the last match
        handler = matches[-1].strip()
        return handler

    def on_message(self: Self, context: HandlersContext, message: MessageParam) -> "HandlersMachine":
        content = llm_common.pop_first_text(message)
        if content is None:
            raise RuntimeError(f"Failed to extract text from message: {message}")
        try:
            source = self.parse_output(content)
        except ValueError as e:
            return FormattingError(self.function_name, self.typescript_schema, self.drizzle_schema, e)
        bundle = {
            f"src/handlers/{self.function_name}.ts": source,
            "src/common/schema.ts": self.typescript_schema,
            "src/db/schema/application.ts": self.drizzle_schema,
        }
        if self.test_suite is None:
            feedback = context.compiler.compile_typescript(bundle)
            if feedback["exit_code"] != 0:
                return TypecheckError(self.function_name, self.typescript_schema, self.drizzle_schema, source, feedback)
            return Success(self.function_name, self.typescript_schema, self.drizzle_schema, source, feedback)
        else:
            test_path = f"src/tests/handlers/{self.function_name}.test.ts"
            [feedback, test_feedback] = context.compiler.compile_typescript(
                {**bundle, test_path: self.test_suite},
                cmds=[["bun", "test", test_path]]
            )
            if feedback["exit_code"] != 0:
                return TypecheckError(self.function_name, self.typescript_schema, self.drizzle_schema, source, feedback, self.test_suite, test_feedback)
            if test_feedback["exit_code"] != 0:
                return TestsError(self.function_name, self.typescript_schema, self.drizzle_schema, source, feedback, self.test_suite, test_feedback)
            return Success(self.function_name, self.typescript_schema, self.drizzle_schema, source, feedback, self.test_suite, test_feedback)

    @property
    def is_done(self) -> bool:
        return False

    @property
    def score(self) -> float:
        return 0.0


class Entry(HandlersMachine):
    def __init__(self, function_name: str, typescript_schema: str, drizzle_schema: str, test_suite: str | None = None, feedback: str = None):
        self.function_name = function_name
        self.typescript_schema = typescript_schema
        self.drizzle_schema = drizzle_schema
        self.test_suite = test_suite
        self.feedback = feedback

    @property
    def next_message(self) -> MessageParam | None:
        if self.feedback:
            # If we have feedback, use the fix prompt with the feedback
            return MessageParam(role="user", content=jinja2.Template(FIX_PROMPT).render(
                errors="",
                additional_feedback=self.feedback
            ))
        # Otherwise use the standard prompt
        content = jinja2.Template(PROMPT).render(
            function_name=self.function_name,
            typespec_schema=self.typescript_schema,
            drizzle_schema=self.drizzle_schema,
        )
        return MessageParam(role="user", content=content)


class FeedbackEntry(HandlersMachine):
    """State for revising an existing handler with feedback"""
    def __init__(self, function_name: str, typescript_schema: str, drizzle_schema: str, previous_source: str, feedback: str, test_suite: str | None = None):
        self.function_name = function_name
        self.typescript_schema = typescript_schema
        self.drizzle_schema = drizzle_schema
        self.previous_source = previous_source
        self.feedback = feedback
        self.test_suite = test_suite

    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(FEEDBACK_PROMPT).render(
            function_name=self.function_name,
            typescript_schema=self.typescript_schema,
            drizzle_schema=self.drizzle_schema,
            previous_source=self.previous_source,
            feedback=self.feedback
        )
        return MessageParam(role="user", content=content)


class FormattingError(HandlersMachine):
    def __init__(self, function_name: str, typescript_schema: str, drizzle_schema: str, exception: ValueError, test_suite: str | None = None):
        self.function_name = function_name
        self.typescript_schema = typescript_schema
        self.drizzle_schema = drizzle_schema
        self.exception = exception
        self.test_suite = test_suite

    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(FIX_PROMPT).render(errors=self.exception)
        return MessageParam(role="user", content=content)


class HandlerTestsCompile:
    def __init__(
        self,
        function_name: str,
        typescript_schema: str,
        drizzle_schema: str,
        source: str,
        feedback: CompileResult,
        test_suite: str | None = None,
        test_feedback: CompileResult | None = None,
    ):
        self.function_name = function_name
        self.typescript_schema = typescript_schema
        self.drizzle_schema = drizzle_schema
        self.source = source
        self.feedback = feedback
        self.test_suite = test_suite
        self.test_feedback = test_feedback


class TypecheckError(HandlersMachine, HandlerTestsCompile):
    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(FIX_PROMPT).render(errors=self.feedback["stdout"])
        return MessageParam(role="user", content=content)


class TestsError(HandlersMachine, HandlerTestsCompile):
    def __init__(
        self,
        function_name: str,
        typescript_schema: str,
        drizzle_schema: str,
        source: str,
        feedback: CompileResult,
        test_suite: str,
        test_feedback: CompileResult,
    ):
        self.function_name = function_name
        self.typescript_schema = typescript_schema
        self.drizzle_schema = drizzle_schema
        self.source = source
        self.feedback = feedback
        self.test_suite = test_suite
        self.test_feedback = test_feedback

    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(FIX_PROMPT).render(errors=self.test_feedback["stderr"])
        return MessageParam(role="user", content=content)

    @property
    def score(self) -> float:
        if not self.test_feedback["stderr"]:
            return 0.0
        pattern = re.compile(r"(\d+) pass\s+(\d+) fail", re.DOTALL)
        result = pattern.search(self.test_feedback["stderr"])
        if result is None:
            return 0.0
        num_pass, num_fail = int(result.group(1)), int(result.group(2))
        return num_pass / (num_pass + num_fail)


class Success(HandlersMachine, HandlerTestsCompile):
    @property
    def next_message(self) -> MessageParam | None:
        return None

    @property
    def is_done(self) -> bool:
        return True

    @property
    def score(self) -> float:
        return 1.0
