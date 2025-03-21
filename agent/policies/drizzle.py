from dataclasses import dataclass
from contextlib import contextmanager
import re
import jinja2
from anthropic.types import MessageParam
from langfuse.decorators import observe, langfuse_context
from .common import TaskNode, PolicyException
from tracing_client import TracingClient
from compiler.core import Compiler, CompileResult


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
Make sure to address following drizzle schema errors:
<errors>
{{errors}}
</errors>

Return <reasoning> and fixed complete drizzle schema encompassed with <drizzle> tag.
"""


@dataclass
class DrizzleOutput:
    reasoning: str
    drizzle_schema: str
    feedback: CompileResult

    @property
    def error_or_none(self) -> str | None:
        return self.feedback["stderr"] or None


@dataclass
class DrizzleData:
    messages: list[MessageParam]
    output: DrizzleOutput | Exception


class DrizzleTaskNode(TaskNode[DrizzleData, list[MessageParam]]):
    @property
    def run_args(self) -> list[MessageParam]:
        fix_template = drizzle_jinja_env.from_string(FIX_PROMPT)
        messages = []
        for node in self.get_trajectory():
            messages.extend(node.data.messages)
            content = None
            match node.data.output:
                case Exception() as e:
                    content = fix_template.render(errors=str(e))
                case DrizzleOutput(feedback={"stderr": stderr}) if stderr is not None:
                    content = fix_template.render(errors=stderr)
                case DrizzleOutput(feedback={"exit_code": exit_code, "stdout": stdout, "stderr": None}) if exit_code != 0:
                    content = fix_template.render(errors=stdout)
                case _:
                    continue
            if content:
                messages.append({"role": "user", "content": content})
        return messages

    @staticmethod
    @observe(capture_input=False, capture_output=False)
    def run(input: list[MessageParam], *args, init: bool = False, **kwargs) -> DrizzleData:
        response = drizzle_client.call_anthropic(
            max_tokens=8192,
            messages=input,
        )
        try:
            reasoning, drizzle_schema = DrizzleTaskNode.parse_output(response.content[-1].text)
            feedback = drizzle_compiler.compile_drizzle(drizzle_schema)
            output = DrizzleOutput(
                reasoning=reasoning,
                drizzle_schema=drizzle_schema,
                feedback=feedback,
            )
        except PolicyException as e:
            output = e
        messages = [] if not init else input
        messages.append({"role": "assistant", "content": response.content[-1].text})
        langfuse_context.update_current_observation(output=output)
        return DrizzleData(messages=messages, output=output)

    @property
    def is_successful(self) -> bool:
        return (
            not isinstance(self.data.output, Exception)
            and self.data.output.feedback["exit_code"] == 0
            and self.data.output.feedback["stderr"] is None
        )

    @staticmethod
    @contextmanager
    def platform(client: TracingClient, compiler: Compiler, jinja_env: jinja2.Environment):
        try:
            global drizzle_client
            global drizzle_compiler
            global drizzle_jinja_env
            drizzle_client = client
            drizzle_compiler = compiler
            drizzle_jinja_env = jinja_env
            yield
        finally:
            del drizzle_client
            del drizzle_compiler
            del drizzle_jinja_env

    @staticmethod
    def parse_output(output: str) -> tuple[str, str]:
        pattern = re.compile(
            r"<reasoning>(.*?)</reasoning>.*?<drizzle>(.*?)</drizzle>",
            re.DOTALL,
        )
        match = pattern.search(output)
        if match is None:
            raise PolicyException("Failed to parse output, expected <reasoning> and <typespec> tags")
        reasoning = match.group(1).strip()
        drizzle_schema = match.group(2).strip()
        return reasoning, drizzle_schema
