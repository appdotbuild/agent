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
{{typespec_definitions}}
</typespec>

Return <reasoning> and TypeSpec definition encompassed with <typescript> tag.
""".strip()


FIX_PROMPT = """
Make sure to address following typescript compilation errors:
<errors>
{{errors}}
</errors>

{% if additional_feedback %}
Additional feedback:
<feedback>
{{additional_feedback}}
</feedback>
{% endif %}

{% if typescript %}
Current version:
<typescript>
{{typescript}}
</typescript>
{% endif %}

Return <reasoning> and fixed complete typescript definition encompassed with <typescript> tag.
"""

@dataclass
class FunctionDeclaration:
    name: str
    argument_type: str
    argument_schema: str
    return_type: str


@dataclass
class TypescriptOutput:
    reasoning: str
    typescript_schema: str
    functions: list[FunctionDeclaration]
    type_to_zod: dict[str, str]
    feedback: CompileResult

    @property
    def error_or_none(self) -> str | None:
        return self.feedback["stdout"] if self.feedback["exit_code"] != 0 else None


@dataclass
class TypescriptData:
    messages: list[MessageParam]
    output: TypescriptOutput | Exception


class TypescriptTaskNode(TaskNode[TypescriptData, list[MessageParam]]):
    @property
    def run_args(self) -> list[MessageParam]:
        fix_template = typescript_jinja_env.from_string(FIX_PROMPT)
        messages = []
        for node in self.get_trajectory():
            messages.extend(node.data.messages)
            content = None
            match node.data.output:
                case TypescriptOutput(feedback={"exit_code": exit_code, "stdout": stdout}) if exit_code != 0:
                    content = fix_template.render(errors=stdout)
                case TypescriptOutput():
                    continue
                case Exception() as e:
                    content = fix_template.render(errors=str(e))
            if content:
                messages.append({"role": "user", "content": content})
        return messages

    @staticmethod
    @observe(capture_input=False, capture_output=False)
    def run(input: list[MessageParam], *args, init: bool = False, **kwargs) -> TypescriptData:
        response = typescript_client.call_anthropic(
            max_tokens=8192,
            messages=input,
        )
        try:
            reasoning, typescript_schema, functions, type_to_zod = TypescriptTaskNode.parse_output(response.content[-1].text)
            feedback = typescript_compiler.compile_typescript({"src/common/schema.ts": typescript_schema})
            output = TypescriptOutput(
                reasoning=reasoning,
                typescript_schema=typescript_schema,
                functions=functions,
                type_to_zod=type_to_zod,
                feedback=feedback,
            )
        except PolicyException as e:
            output = e
        messages = [] if not init else input
        messages.append({"role": "assistant", "content": response.content[-1].text})
        langfuse_context.update_current_observation(output=output)
        return TypescriptData(messages=messages, output=output)

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
                raise PolicyException(f"Missing schema for argument type {argument_type}")
            functions.append(FunctionDeclaration(
                name=match.group("functionName"),
                argument_type=argument_type,
                argument_schema=type_to_zod[argument_type],
                return_type=match.group("returnType"),
            ))
        return reasoning, definitions, functions, type_to_zod
