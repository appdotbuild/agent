from dataclasses import dataclass
from contextlib import contextmanager
import re
import jinja2
from anthropic.types import MessageParam
from langfuse.decorators import observe
from .common import TaskNode
from tracing_client import TracingClient
from compiler.core import Compiler, CompileResult


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


FIX_PROMPT = """
Make sure to address following typescript compilation errors:
<errors>
{{errors}}
</errors>

Return <reasoning> and fixed complete typescript definition encompassed with <typescript> tag.
"""


@dataclass
class TypescriptOutput:
    reasoning: str
    typescript_schema: str
    type_names: list[str]
    feedback: CompileResult


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
                case Exception() as e:
                    content = fix_template.render(errors=str(e))
                case catch_all:
                    raise RuntimeError(f"Received non-matched case: {catch_all}")
            if content:
                messages.append({"role": "user", "content": content})
        return messages            

    @staticmethod
    @observe(capture_input=False, capture_output=False)
    def run(input: list[MessageParam], *args, **kwargs) -> TypescriptData:
        response = typescript_client.call_anthropic(
            model="anthropic.claude-3-5-sonnet-20241022-v2:0",
            max_tokens=8192,
            messages=input,
        )
        try:
            reasoning, typescript_schema, type_names = TypescriptTaskNode.parse_output(response.content[0].text)
            feedback = typescript_compiler.compile_typescript({"src/common/schema.ts": typescript_schema})
            output = TypescriptOutput(
                reasoning=reasoning,
                typescript_schema=typescript_schema,
                type_names=type_names,
                feedback=feedback,
            )
        except Exception as e:
            output = e
        messages = [{"role": "assistant", "content": response.content[0].text}]
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
    def parse_output(output: str) -> tuple[str, str, list[str]]:
        pattern = re.compile(
            r"<reasoning>(.*?)</reasoning>.*?<typescript>(.*?)</typescript>",
            re.DOTALL,
        )
        match = pattern.search(output)
        if match is None:
            raise ValueError("Failed to parse output, expected <reasoning> and <typescript> tags")
        reasoning = match.group(1).strip()
        definitions = match.group(2).strip()
        type_names: list[str] = re.findall(r"export interface (\w+)", definitions)
        return reasoning, definitions, type_names
