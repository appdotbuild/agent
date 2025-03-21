from typing import Protocol, Self
import re
import jinja2
from anthropic.types import MessageParam
from compiler.core import Compiler, CompileResult
from . import llm_common
from .common import AgentMachine


PROMPT = """
Based on TypeSpec models and interfaces, generate Drizzle schema for the application.
Ensure that the schema is compatible with PostgreSQL database.
Encompass output with <drizzle> tag.

Example output:

<reasoning>
    The application operates on users and messages and processes them with LLM.
    The users are identified by their ids.
    The messages have roles and content.
</reasoning>

<drizzle>
import { integer, pgTable, pgEnum, text } from "drizzle-orm/pg-core";

export const usersTable = pgTable("users", {
  id: text().primaryKey(),
});

export const msgRolesEnum = pgEnum("msg_roles", ["user", "assistant"]);

export const messagesTable = pgTable("messages", {
  id: integer().primaryKey().generatedAlwaysAsIdentity(),
  user_id: text().references(() => usersTable.id),
  role: msgRolesEnum(),
  content: text(),
});
</drizzle>

Application TypeSpec:

{{typespec_definitions}}
""".strip()


FIX_PROMPT = """
{% if errors %}
Make sure to address following drizzle schema errors:
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

Return <reasoning> and fixed complete drizzle schema encompassed with <drizzle> tag.
""".strip()


FEEDBACK_PROMPT = """
Based on TypeSpec models and interfaces, revise the Drizzle schema for the application.
Ensure that the schema is compatible with PostgreSQL database.

Application TypeSpec:
{{typespec_definitions}}

Here is your previous Drizzle schema:
<previous-schema>
{{previous_schema}}
</previous-schema>

Please revise the schema based on this feedback:
<feedback>
{{feedback}}
</feedback>

Return your revised schema with:
<reasoning>
Your reasoning for each change you made based on the feedback
</reasoning>

<drizzle>
// Your revised Drizzle schema
</drizzle>
""".strip()


class DrizzleContext(Protocol):
    compiler: Compiler


class DrizzleMachine(AgentMachine[DrizzleContext]):
    @staticmethod
    def parse_output(output: str) -> tuple[str, str]:
        pattern = re.compile(
            r"<reasoning>(.*?)</reasoning>.*?<drizzle>(.*?)</drizzle>",
            re.DOTALL,
        )
        match = pattern.search(output)
        if match is None:
            raise ValueError("Failed to parse output, expected <reasoning> and <drizzle> tags")
        reasoning = match.group(1).strip()
        drizzle_schema = match.group(2).strip()
        return reasoning, drizzle_schema
    
    def on_message(self: Self, context: DrizzleContext, message: MessageParam) -> "DrizzleMachine":
        content = llm_common.pop_first_text(message)
        if content is None:
            raise RuntimeError(f"Failed to extract text from message: {message}")
        try:
            reasoning, drizzle_schema = self.parse_output(content)
        except ValueError as e:
            return FormattingError(e)
        feedback = context.compiler.compile_drizzle(drizzle_schema)
        if feedback["exit_code"] != 0:
            return TypecheckError(reasoning, drizzle_schema, feedback)
        if feedback["stderr"]:
            return CompileError(reasoning, drizzle_schema, feedback)
        return Success(reasoning, drizzle_schema, feedback)

    @property
    def is_done(self) -> bool:
        return False
    
    @property
    def score(self) -> float:
        return 0.0   


class Entry(DrizzleMachine):
    """Initial state for creating a new Drizzle schema from TypeSpec definitions"""
    def __init__(self, typespec_definitions: str):
        self.typespec_definitions = typespec_definitions
    
    @property
    def next_message(self) -> MessageParam | None:
        # Create initial schema based on TypeSpec definitions
        content = jinja2.Template(PROMPT).render(typespec_definitions=self.typespec_definitions)
        return MessageParam(role="user", content=content)


class FeedbackEntry(DrizzleMachine):
    """State for revising an existing Drizzle schema with feedback"""
    def __init__(self, typespec_definitions: str, previous_schema: str, feedback: str):
        self.typespec_definitions = typespec_definitions
        self.previous_schema = previous_schema
        self.feedback = feedback
    
    @property
    def next_message(self) -> MessageParam | None:
        # Generate revision based on previous schema and feedback
        content = jinja2.Template(FEEDBACK_PROMPT).render(
            typespec_definitions=self.typespec_definitions,
            previous_schema=self.previous_schema,
            feedback=self.feedback
        )
        return MessageParam(role="user", content=content)


class FormattingError(DrizzleMachine):
    def __init__(self, exception: ValueError):
        self.exception = exception

    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(FIX_PROMPT).render(errors=self.exception)
        return MessageParam(role="user", content=content)


class DrizzleCompile:
    def __init__(self, reasoning: str, drizzle_schema: str, feedback: CompileResult):
        self.reasoning = reasoning
        self.drizzle_schema = drizzle_schema
        self.feedback = feedback


class CompileError(DrizzleMachine, DrizzleCompile):
    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(FIX_PROMPT).render(errors=self.feedback["stderr"])
        return MessageParam(role="user", content=content)
    

class TypecheckError(DrizzleMachine, DrizzleCompile):
    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(FIX_PROMPT).render(errors=self.feedback["stdout"])
        return MessageParam(role="user", content=content)


class Success(DrizzleMachine, DrizzleCompile):
    @property
    def next_message(self) -> MessageParam | None:
        return None
    
    @property
    def is_done(self) -> bool:
        return True
    
    @property
    def score(self) -> float:
        return 1.0
