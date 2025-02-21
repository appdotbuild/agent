from typing import TypedDict
from dataclasses import dataclass


@dataclass
class LLMFunction:
    name: str
    description: str


@dataclass
class TypespecOut:
    reasoning: str | None
    typespec_definitions: str | None
    llm_functions: list[LLMFunction] | None
    error_output: str | None


@dataclass
class TypescriptFunction:
    name: str
    argument_type: str
    argument_schema: str
    return_type: str


@dataclass
class TypescriptOut:
    reasoning: str | None
    typescript_schema: str | None
    functions: list[TypescriptFunction] | None
    error_output: str | None


@dataclass
class GherkinOut:
    reasoning: str | None
    gherkin: str | None
    error_output: str | None


@dataclass
class DrizzleOut:
    reasoning: str | None
    drizzle_schema: str | None
    error_output: str | None


class RouterFunc(TypedDict):
    name: str
    description: str
    examples: list[str]


@dataclass
class RouterOut:
    functions: list[RouterFunc] | None
    error_output: str | None


@dataclass
class HandlerTestsOut:
    name: str | None
    content: str | None
    error_output: str | None


@dataclass
class HandlerOut:
    name: str | None
    handler: str | None
    argument_schema: str | None
    error_output: str | None


@dataclass
class RefineOut:
    refined_description: str
    error_output: str | None


@dataclass
class ApplicationOut:
    refined_description: RefineOut
    typespec: TypespecOut
    drizzle: DrizzleOut
    handlers: dict[str, HandlerOut]
    handler_tests: dict[str, HandlerTestsOut]
    typescript_schema: TypescriptOut
    gherkin: GherkinOut
    trace_id: str