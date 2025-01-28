from typing import TypedDict
import re

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


class DrizzleInput(TypedDict):
    typespec_definitions: str


class DrizzleOutput(TypedDict):
    reasoning: str
    drizzle_schema: str


def parse_output(output: str) -> DrizzleOutput:
    pattern = re.compile(
        r"<reasoning>(.*?)</reasoning>.*?<drizzle>(.*?)</drizzle>",
        re.DOTALL,
    )
    match = pattern.search(output)
    if match is None:
        raise ValueError("Failed to parse output, expected <reasoning> and <drizzle> tags")
    reasoning = match.group(1).strip()
    drizzle_schema = match.group(2).strip()
    return DrizzleOutput(reasoning=reasoning, drizzle_schema=drizzle_schema)