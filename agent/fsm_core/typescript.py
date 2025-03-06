from typing import Protocol, Self
from dataclasses import dataclass
import re
from anthropic.types import MessageParam
from compiler.core import Compiler, CompileResult
from . import llm_common
from .common import AgentMachine


PROMPT = """
Based on TypeSpec models and interfaces, generate Zod TypeScript data types for the application.
Ensure that the data types follow the TypeScript syntax.
For each function in the <typespec> interfaces generate function declarations in the TypeScript output.
Encompass output with <typescript> tag.

Rules:
- Always use coerce of Zod date and time types.
- For functions emit declarations only, omit function bodies ```export declare function funtionName(parameter: SomeType): Promise<SomeOutput>;```
- Function names in emitted TypeScript should match the function names in the <typespec> interfaces.

Example:
<typespec>
model User {
    id: string;
}

model Message {
    role: 'user' | 'assistant';
    content: string;
}

interface GreeterBot {
    @llm_func("Greets the user")
    greetUser(user: User): Message;
}
</typespec>

<reasoning>
    The application operates on users and messages and processes them with LLM.
    The users are identified by their ids.
    The messages have roles and content.
    Application greets user and responds with a message.
</reasoning>

<typescript>
import { z } from 'zod';

export const userSchema = z.object({
    id: z.string(),
});

export type User = z.infer<typeof userSchema>;

export const messageSchema = z.object({
    role: z.literal('user').or(z.literal('assistant')),
    content: z.string(),
});

export type Message = z.infer<typeof messageSchema>;

export declare function greetUser(user: User): Promise<Message>;
</typescript>

Application TypeSpec:

<typespec>
%(typespec_definitions)s
</typespec>

Return <reasoning> and TypeSpec definition encompassed with <typescript> tag.
""".strip()


FIX_PROMPT = """
Make sure to address following typescript compilation errors:
<errors>
%(errors)s
</errors>

Return <reasoning> and fixed complete typescript definition encompassed with <typescript> tag.
"""


@dataclass
class FunctionDeclaration:
    name: str
    argument_type: str
    argument_schema: str
    return_type: str


class TypescriptContext(Protocol):
    compiler: Compiler


class TypescriptMachine(AgentMachine[TypescriptContext]):
    @staticmethod
    def parse_output(output: str) -> tuple[str, str, list[FunctionDeclaration], dict[str, str]]:
        pattern = re.compile(
            r"<reasoning>(.*?)</reasoning>.*?<typescript>(.*?)</typescript>",
            re.DOTALL,
        )
        match = pattern.search(output)
        if match is None:
            raise ValueError("Failed to parse output, expected <reasoning> and <typescript> tags")
        reasoning = match.group(1).strip()
        definitions = match.group(2).strip()

        pattern = re.compile(
            r"export\s+type\s+(?P<typeName>\w+)\s*=\s*z\.infer\s*<\s*typeof\s+(?P<schemaName>\w+)\s*>",
            re.MULTILINE
        )
        type_to_zod = {
            match.group("typeName"): match.group("schemaName")
            for match in pattern.finditer(definitions)
        }
        pattern = re.compile(
            r"declare\s+function\s+(?P<functionName>\w+)\s*\(\s*\w+\s*:\s*(?P<argumentType>\w+)\s*\)\s*:\s*(?P<returnType>\w+.*)\s*;",
            re.MULTILINE
        )
        functions = []
        for match in pattern.finditer(definitions):
            argument_type = match.group("argumentType")
            if argument_type not in type_to_zod:
                raise ValueError(f"Missing schema for argument type {argument_type}")
            functions.append(FunctionDeclaration(
                name=match.group("functionName"),
                argument_type=argument_type,
                argument_schema=type_to_zod[argument_type],
                return_type=match.group("returnType"),
            ))
        return reasoning, definitions, functions, type_to_zod
    
    def on_message(self: Self, context: TypescriptContext, message: MessageParam) -> "TypescriptMachine":
        content = llm_common.pop_first_text(message)
        if content is None:
            raise RuntimeError(f"Failed to extract text from message: {message}")
        try:
            reasoning, typescript_schema, functions, type_to_zod = self.parse_output(content)
        except ValueError as e:
            return FormattingError(e)
        feedback = context.compiler.compile_typescript({"src/common/schema.ts": typescript_schema})
        if feedback["exit_code"] != 0:
            return CompileError(reasoning, typescript_schema, functions, type_to_zod, feedback)
        return Success(reasoning, typescript_schema, functions, type_to_zod, feedback)

    @property
    def is_done(self) -> bool:
        return False
    
    @property
    def score(self) -> float:
        return 0.0   


class Entry(TypescriptMachine):
    def __init__(self, typespec_definitions: str):
        self.typespec_definitions = typespec_definitions
    
    @property
    def next_message(self) -> MessageParam | None:
        content = PROMPT % {"typespec_definitions": self.typespec_definitions}
        return MessageParam(role="user", content=content)


class FormattingError(TypescriptMachine):
    def __init__(self, exception: ValueError):
        self.exception = exception

    @property
    def next_message(self) -> MessageParam | None:
        content = FIX_PROMPT % {"errors": self.exception}
        return MessageParam(role="assistant", content=content)


class TypescriptCompile:
    def __init__(
        self,
        reasoning: str,
        typescript_schema: str,
        functions: list[FunctionDeclaration],
        type_to_zod: dict[str, str],
        feedback: CompileResult,
    ):
        self.reasoning = reasoning
        self.typescript_schema = typescript_schema
        self.functions = functions
        self.type_to_zod = type_to_zod
        self.feedback = feedback


class CompileError(TypescriptMachine, TypescriptCompile):
    @property
    def next_message(self) -> MessageParam | None:
        content = FIX_PROMPT % {"errors": self.feedback["stdout"]}
        return MessageParam(role="assistant", content=content)


class Success(TypescriptMachine, TypescriptCompile):
    @property
    def next_message(self) -> MessageParam | None:
        return None
    
    @property
    def is_done(self) -> bool:
        return True
    
    @property
    def score(self) -> float:
        return 1.0
