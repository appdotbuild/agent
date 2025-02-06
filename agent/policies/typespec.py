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
Given user application description generate TypeSpec models and interface for the application. Output just a single interface.
Every decorated @llm_func operates on free-form text messages and its arguments should be
easily extractable from chat messages. Keep argument complexity within what can be extracted / inferred
from the chat messages directly. When designing the interface expect that every function has a pre- and post-processor.

Make sure using correct TypeSpec types for date and time:
Dates and Times
- plainDate: A date on a calendar without a time zone, e.g. “April 10th”
- plainTime: A time on a clock without a time zone, e.g. “3:00 am”
- utcDateTime: Represents a date and time in Coordinated Universal Time (UTC)
- offsetDateTime: Represents a date and time with a timezone offset
- duration:	A duration/time period. e.g 5s, 10h
NOTE: There are NO other types for date and time in TypeSpec.

TypeSpec basic types:
- numeric: Represents any possible number
- integer: Represents any integer
- float: Represents any floating-point number
- decimal: Represents a decimal number with arbitrary precision
- string: Represents a sequence of characters
- boolean: Represents true and false values
bytes: Represents a sequence of bytes
null: Represents a null value
-unknown: Represents a value of any type
-void: Used to indicate no return value for functions/operations
NOTE: Avoid using other types.

TypeSpec RESERVED keywords:
- model: Used to define a model
- interface: Used to define an interface
NOTE: Avoid using reserved keywords for property names, type names, and function names.

TypeSpec is extended with special decorator that indicates that this function
is processed by language model parametrized with number of previous messages passed to the LLM.

extern dec llm_func(target: unknown, history: valueof int32);

Example input:
<description>
Bot that records my diet and calculates calories.
</description>

Output:
<reasoning>
I expect user to send messages like "I ate a burger" or "I had a salad for lunch".
LLM can extract and infer the arguments from plain text and pass them to the handler
"I ate a burger" -> recordDish({name: "burger", ingredients: [
    {name: "bun", calories: 200},
    {name: "patty", calories: 300},
    {name: "lettuce", calories: 10},
    {name: "tomato", calories: 20},
    {name: "cheese", calories: 50},
]})
- recordDish(dish: Dish): void;
...
</reasoning>

<typespec>
model Dish {
    name: string;
    ingredients: Ingredient[];
}

model Ingredient {
    name: string;
    calories: integer;
}

interface DietBot {
    @llm_func(1)
    recordDish(dish: Dish): void;
    @llm_func(1)
    listDishes(from: utcDateTime, to: utcDateTime): Dish[];
}
</typespec>

User application description:
{{application_description}}

Return <reasoning> and TypeSpec definition encompassed with <typespec> tag.
""".strip()


FIX_PROMPT = """
Make sure to address following TypeSpec compilation errors:
<errors>
{{errors}}
</errors>

Verify absence of reserved keywords in property names, type names, and function names.
Return <reasoning> and fixed complete TypeSpec definition encompassed with <typespec> tag.
"""


@dataclass
class TypespecOutput:
    reasoning: str
    typespec_definitions: str
    llm_functions: list[str]
    feedback: CompileResult

    @property
    def error_or_none(self) -> str | None:
        return self.feedback["stdout"] if self.feedback["exit_code"] != 0 else None


@dataclass
class TypespecData:
    messages: list[MessageParam]
    output: TypespecOutput | Exception


class TypespecTaskNode(TaskNode[TypespecData, list[MessageParam]]):
    @property
    def run_args(self) -> list[MessageParam]:
        fix_template = typespec_jinja_env.from_string(FIX_PROMPT)
        messages = []
        for node in self.get_trajectory():
            messages.extend(node.data.messages)
            content = None
            match node.data.output:
                case TypespecOutput(feedback={"exit_code": exit_code, "stdout": stdout}) if exit_code != 0:
                    content = fix_template.render(errors=stdout)
                case TypespecOutput():
                    continue
                case Exception() as e:
                    content = fix_template.render(errors=str(e))
            if content:
                messages.append({"role": "user", "content": content})
        return messages            

    @staticmethod
    @observe(capture_input=False, capture_output=False)
    def run(input: list[MessageParam], *args, **kwargs) -> TypespecData:
        response = typespec_client.call_anthropic(
            model="anthropic.claude-3-5-sonnet-20241022-v2:0",
            max_tokens=8192,
            messages=input,
        )
        try:
            reasoning, typespec_definitions, llm_functions = TypespecTaskNode.parse_output(response.content[0].text)
            typespec_schema = "\n".join(['import "./helpers.js";', "", typespec_definitions])
            feedback = typespec_compiler.compile_typespec(typespec_schema)
            output = TypespecOutput(
                reasoning=reasoning,
                typespec_definitions=typespec_definitions,
                llm_functions=llm_functions,
                feedback=feedback,
            )
        except Exception as e:
            output = e
        messages = [{"role": "assistant", "content": response.content[0].text}]
        return TypespecData(messages=messages, output=output)
    
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
            global typespec_client
            global typespec_compiler
            global typespec_jinja_env
            typespec_client = client
            typespec_compiler = compiler
            typespec_jinja_env = jinja_env
            yield
        finally:
            del typespec_client
            del typespec_compiler
            del typespec_jinja_env
    
    @staticmethod
    def parse_output(output: str) -> tuple[str, str, list[str]]:
        pattern = re.compile(
            r"<reasoning>(.*?)</reasoning>.*?<typespec>(.*?)</typespec>",
            re.DOTALL,
        )
        match = pattern.search(output)
        if match is None:
            raise ValueError("Failed to parse output, expected <reasoning> and <typespec> tags")
        reasoning = match.group(1).strip()
        definitions = match.group(2).strip()
        pattern = re.compile(r'@llm_func\(\d+\)\s*(\w+)\s*\(', re.DOTALL)
        functions = pattern.findall(output)
        return reasoning, definitions, functions
