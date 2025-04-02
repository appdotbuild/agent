from typing import Protocol, Self
import re
import jinja2
from anthropic.types import MessageParam
from compiler.core import Compiler, CompileResult
from . import llm_common
from .common import AgentMachine


PROMPT = """
Based on TypeScript and Drizzle schemas application definition generate a unit test suite for {{function_name}} function.

Example:

<typescript>
import { z } from 'zod';

export const greetingRequestSchema = z.object({
  name: z.string(),
  greeting: z.string(),
});

export type GreetingRequest = z.infer<typeof greetingRequestSchema>;

export declare function greet(options: GreetingRequest): Promise<string>;
</typescript>

<drizzle>
import { serial, text, pgTable, timestamp } from "drizzle-orm/pg-core";

export const greetingRequestsTable = pgTable("greeting_requests", {
  id: serial("id").primaryKey(),
  name: text("name").notNull(),
  greeting: text("greeting").notNull(),
  created_at: timestamp("created_at").defaultNow().notNull()
});

export const greetingResponsesTable = pgTable("greeting_responses", {
  id: serial("id").primaryKey(),
  request_id: serial("request_id")
    .references(() => greetingRequestsTable.id)
    .notNull(),
  response_text: text("response_text").notNull(),
  created_at: timestamp("created_at").defaultNow().notNull()
});
</drizzle>

Output:

<imports>
import { expect, it } from "bun:test";
import { db } from "../../db";
import { greetingRequestsTable } from "../../db/schema/application";
import { type GreetingRequest } from "../../common/schema";
</imports>

<test>
it("should return a greeting", async () => {
  const input: GreetingRequest = { name: "Alice", greeting: "Hello" };
  const greeting = await greet(input);
  expect(greeting).toEqual("Hello, Alice!");
});
</test>

<test>
it("should store the greeting request", async () => {
  const input: GreetingRequest = { name: "Alice", greeting: "Hello" };
  await greet(input);
  const requests = await db.select().from(greetingRequestsTable).execute();
  expect(requests).toHaveLength(1);
  expect(requests[0].name).toEqual("Alice");
  expect(requests[0].greeting).toEqual("Hello");
});
</test>

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
* STRICTLY FOLLOW TYPE NAMES FROM TYPESPEC SCHEMA, TABLE NAMES FROM DRIZZLE SCHEMA (e.g., greetingRequestsTable, greetingResponsesTable, not greeting_requests, greeting_responses)
* STRICTLY FOLLOW DATA TYPES FROM DRIZZLE SCHEMA;
* Remember that in Drizzle, JavaScript properties (userId) and SQL column names ("user_id") differ in casing convention
* Drizzle schema imports must always be from "../../db/schema/application", for example: import { customTable } from "../../db/schema/application";,
* Typespec schema imports must always be from "../../common/schema", for example: import { CarPoem } from "../../common/schema";,
* Drizzle ORM operators imports must come from "drizzle-orm" if required: import { eq } from "drizzle-orm";
* If using db instance, use: import { db } from "../../db";,
* Avoid importing "describe", "beforeEach", "afterEach" it will cause a duplicate declaration error.

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
import { type PgSelect } from "drizzle-orm/pg-core";

// Types for type safety
import { type InferSelectModel } from 'drizzle-orm';
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

<typescript>
{{typescript_schema}}
</typescript>

<drizzle>
{{drizzle_schema}}
</drizzle>

Generate unit tests for {{function_name}} function based on the provided TypeScript and Drizzle schemas.
Assume that DB is already initialized, all tables are successfully created and wiped out after each test.

The following imports and setup are handled by the test file template and should **not** be generated by you:

<imports>
import { afterEach, beforeEach, describe } from "bun:test";
import { handle as {{function_name}} } from "../../handlers/{{function_name}}.ts"
</imports>

Ensure real function and database operations are tested, avoid mocks unless necessary.
Match the output format provided in the Example. Return new required imports within <imports> and tests encompassed with <test> tags.
""".strip()


FIX_PROMPT = """
{% if errors %}
Make sure to address following TypeScript compilation, linting and runtime errors:
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
Follow original formatting, return <imports> and corrected complete test suite with each test encompassed within <test> tag.
"""


FEEDBACK_PROMPT = """
Based on TypeScript and Drizzle schemas application definition, revise the unit test suite for {{function_name}} function.

<typescript>
{{typescript_schema}}
</typescript>

<drizzle>
{{drizzle_schema}}
</drizzle>

Here are your previous imports:
<imports>
{{previous_imports}}
</imports>

Here are your previous tests:
{% for test in previous_tests %}
<test>
{{test}}
</test>
{% endfor %}

Please revise the tests based on this feedback:
<feedback>
{{feedback}}
</feedback>

Return revised imports within <imports> and tests encompassed with <test> tags.
""".strip()


HANDLER_TEST_TPL = """
import { afterEach, beforeEach, describe } from "bun:test";
import { resetDB, createDB } from "../../helpers";
{{imports}}
{% if handler_function_import %}
{{handler_function_import}}
{% endif %}

describe("{{handler_name}}", () => {
    beforeEach(async () => {
        await createDB();
    });

    afterEach(async () => {
        await resetDB();
    });
    {% for test in tests %}
    {{test|indent(4)}}
    {% endfor %}
});
"""


class HandlerTestsContext(Protocol):
    compiler: Compiler


class HandlerTestsMachine(AgentMachine[HandlerTestsContext]):
    function_name: str
    typescript_schema: str
    drizzle_schema: str

    @staticmethod
    def parse_output(output: str) -> tuple[str, list[str]]:
        pattern = re.compile(r"<imports>(.*?)</imports>", re.DOTALL)
        match = pattern.search(output)
        if match is None:
            raise ValueError("Failed to parse output, expected <imports> tag")
        imports = match.group(1).strip()
        pattern = re.compile(r"<test>(.*?)</test>", re.DOTALL)
        tests = pattern.findall(output)
        return imports, tests

    def on_message(self: Self, context: HandlerTestsContext, message: MessageParam) -> "HandlerTestsMachine":
        content = llm_common.pop_first_text(message)
        if content is None:
            raise RuntimeError(f"Failed to extract text from message: {message}")
        try:
            imports, tests = self.parse_output(content)
        except ValueError as e:
            return FormattingError(self.function_name, self.typescript_schema, self.drizzle_schema, e)
        test_file_path = f"src/tests/handlers/{self.function_name}.test.ts"
        source = jinja2.Template(HANDLER_TEST_TPL).render(
            function_name=self.function_name,
            handler_function_import=f'import {{ {self.function_name} }} from "../../common/schema";',
            imports=imports,
            tests=tests,
        )
        linting_cmd = ["npx", "eslint", "-c", "eslint.config.mjs", "--fix", test_file_path]
        [ts_feedback, linter_feedback] = context.compiler.compile_typescript({
                test_file_path: source,
                "src/common/schema.ts": self.typescript_schema,
                "src/db/schema/application.ts": self.drizzle_schema,
            }, cmds=[linting_cmd]
        )
        feedback = CompileResult(
            exit_code=ts_feedback["exit_code"] or linter_feedback["exit_code"],
            stdout=(ts_feedback["stdout"] or "") + ("\n" + linter_feedback["stdout"] if linter_feedback["stdout"] else ""),
            stderr=(ts_feedback["stderr"] or "") + ("\n" + linter_feedback["stderr"] if linter_feedback["stderr"] else ""),
        )
        if feedback["exit_code"] != 0:
            return CompileError(self.function_name, self.typescript_schema, self.drizzle_schema, imports, tests, feedback)
        return Success(self.function_name, self.typescript_schema, self.drizzle_schema, imports, tests, feedback)

    @property
    def is_done(self) -> bool:
        return False

    @property
    def score(self) -> float:
        return 0.0


class Entry(HandlerTestsMachine):
    def __init__(self, function_name: str, typescript_schema: str, drizzle_schema: str, feedback: str = None):
        self.function_name = function_name
        self.typescript_schema = typescript_schema
        self.drizzle_schema = drizzle_schema
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
            typescript_schema=self.typescript_schema,
            drizzle_schema=self.drizzle_schema,
        )
        return MessageParam(role="user", content=content)


class FeedbackEntry(HandlerTestsMachine):
    """State for revising existing handler tests with feedback"""
    def __init__(self, function_name: str, typescript_schema: str, drizzle_schema: str, previous_imports: str, previous_tests: list[str], feedback: str):
        self.function_name = function_name
        self.typescript_schema = typescript_schema
        self.drizzle_schema = drizzle_schema
        self.previous_imports = previous_imports
        self.previous_tests = previous_tests
        self.feedback = feedback

    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(FEEDBACK_PROMPT).render(
            function_name=self.function_name,
            typescript_schema=self.typescript_schema,
            drizzle_schema=self.drizzle_schema,
            previous_imports=self.previous_imports,
            previous_tests=self.previous_tests,
            feedback=self.feedback
        )
        return MessageParam(role="user", content=content)


class FormattingError(HandlerTestsMachine):
    def __init__(self, function_name: str, typescript_schema: str, drizzle_schema: str, exception: ValueError):
        self.function_name = function_name
        self.typescript_schema = typescript_schema
        self.drizzle_schema = drizzle_schema
        self.exception = exception

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
        imports: str,
        tests: list[str],
        feedback: CompileResult
    ):
        self.function_name = function_name
        self.typescript_schema = typescript_schema
        self.drizzle_schema = drizzle_schema
        self.imports = imports
        self.tests = tests
        self.feedback = feedback


class CompileError(HandlerTestsMachine, HandlerTestsCompile):
    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(FIX_PROMPT).render(errors=(self.feedback["stdout"] or "") + (self.feedback["stderr"] or ""))
        return MessageParam(role="user", content=content)


class Success(HandlerTestsMachine, HandlerTestsCompile):
    def __init__(
        self,
        function_name: str,
        typescript_schema: str,
        drizzle_schema: str,
        imports: str,
        tests: list[str],
        feedback: CompileResult
    ):
        self.function_name = function_name
        self.typescript_schema = typescript_schema
        self.drizzle_schema = drizzle_schema
        self.imports = imports
        self.tests = tests
        self.feedback = feedback
        self.source = jinja2.Template(HANDLER_TEST_TPL).render(
            function_name=function_name,
            handler_function_import=f'import {{ handle as {function_name} }} from "../../handlers/{function_name}.ts";',
            imports=imports,
            tests=tests,
        )

    @property
    def next_message(self) -> MessageParam | None:
        return None

    @property
    def is_done(self) -> bool:
        return True

    @property
    def score(self) -> float:
        return 1.0
