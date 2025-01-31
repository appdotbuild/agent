from typing import TypedDict
import re

PROMPT = """
Based on TypeSpec models and interfaces, generate TypeScript data types for the application.
Ensure that the data types follow the TypeScript syntax.
Encompass output with <typescript> tag.

Example output:

<reasoning>
    The application operates on users and messages and processes them with LLM.
    The users are identified by their ids.
    The messages have roles and content.
</reasoning>

<typescript>
export interface User {
    id: string;
}

export interface Message {
    role: 'user' | 'assistant';
    content: string;
}
</typescript>

Application TypeSpec:

{{typespec_definitions}}
""".strip()


class TypeScriptSchemaInput(TypedDict):
    typespec_definitions: str


class TypeScriptSchemaOutput(TypedDict):
    reasoning: str
    typescript_schema: str


def parse_output(output: str) -> TypeScriptSchemaOutput:
    pattern = re.compile(
        r"<reasoning>(.*?)</reasoning>.*?<typescript>(.*?)</typescript>",
        re.DOTALL,
    )
    match = pattern.search(output)
    if match is None:
        raise ValueError("Failed to parse output, expected <reasoning> and <typescript> tags")
    reasoning = match.group(1).strip()
    typescript_schema = match.group(2).strip()
    typescript_schema_type_names = re.findall(r"export interface (\w+)", typescript_schema)
    return TypeScriptSchemaOutput(reasoning=reasoning, typescript_schema=typescript_schema, typescript_schema_type_names=typescript_schema_type_names)


def parse_typescript_schema_type_names(typescript_schema: str) -> list[str]:
    typescript_schema_type_names = re.findall(r"export interface (\w+)", typescript_schema)
    return typescript_schema_type_names