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
Given a history of a chat with user, generate TypeSpec models and interface for the application.

TypeSpec is extended with an @llm_func decorator that defines a single sentence description for the function use case.
extern dec llm_func(target: unknown, description: string);

TypeSpec is extended with an @scenario decorator that defines gherkin scenario for the function use case.
extern dec scenario(target: unknown, gherkin: string);

Rules:
- Output contains a single interface.
- Functions in the interface should be decorated with @llm_func decorator.
- Each function in the interface should be decorated with at least one @scenario decorator.
- Each function must have a complete set of scenarios defined with @scenario decorator.
- Each function should have a single argument "options".
- The "options" parameter must always be an object model type, never a primitive type.
- Data model for the function argument should be simple and easily inferable from chat messages.
- Using reserved keywords for property names, type names, and function names is not allowed.

Make sure using correct TypeSpec types for date and time:
Dates and Times
- plainDate: A date on a calendar without a time zone, e.g. "April 10th"
- plainTime: A time on a clock without a time zone, e.g. "3:00 am"
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
- bytes: Represents a sequence of bytes
- null: Represents a null value
- unknown: Represents a value of any type
- void: Used to indicate no return value for functions/operations
NOTE: Avoid using other types.

TypeSpec RESERVED keywords:
- model: Used to define a model
- interface: Used to define an interface
NOTE: Avoid using these keywords as property names, type names, and function names.

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
- recordDish(options: Dish): void;
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

model ListDishesRequest {
    from: utcDateTime;
    to: utcDateTime;
}

interface DietBot {
    @scenario(
\"\"\"
Scenario: Single dish entry
When user says "I ate a cheeseburger with fries"
Then system should extract:
    - Dish: "cheeseburger"
    - Dish: "fries"
    - Ingredients for cheeseburger: [patty, bun, cheese]
    - Ingredients for fries: [potatoes, oil]
Examples:
    | Input                                  | Expected Dishes |
    | "I had a salad for lunch"              | ["salad"]       |
    | "Just drank a protein shake"           | ["protein shake"] |
\"\"\")
    @llm_func("Extract food entries from natural language")
    recordDish(options: Dish): void;

    @scenario(
\"\"\"
Scenario: Historical query
When user asks "What did I eat last Thursday?"
Then system returns entries from 2024-02-15
With full meal breakdown
\"\"\")
    @llm_func("Retrieve and summarize dietary history")
    listDishes(options: ListDishesRequest): Dish[];
}
</typespec>

<user-requests>
{% for request in user_requests %}
{{request}}
{% endfor %}
</user-requests>

Return <reasoning> and TypeSpec definition encompassed with <typespec> tag.
""".strip()


FIX_PROMPT = """
Make sure to address following TypeSpec compilation errors:
{% if errors %}
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

{% if typespec %}
Current version:
<typespec>
{{typespec}}
</typespec>
{% endif %}


Verify absence of reserved keywords in property names, type names, and function names.
Return <reasoning> and fixed complete TypeSpec definition encompassed with <typespec> tag.
"""


@dataclass
class LLMFunction:
    name: str
    description: str
    scenario: str

@dataclass
class TypespecOutput:
    reasoning: str
    typespec_definitions: str
    llm_functions: list[LLMFunction]
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
    def run(input: list[MessageParam], *args, init: bool = False, **kwargs) -> TypespecData:
        response = typespec_client.call_anthropic(
            max_tokens=8192,
            messages=input,
        )
        try:
            reasoning, typespec_definitions, llm_functions = TypespecTaskNode.parse_output(response.content[-1].text)
            typespec_schema = "\n".join([
                'import "./helpers.js";',
                "",
                "extern dec llm_func(target: unknown, description: string);",
                "",
                "extern dec scenario(target: unknown, gherkin: string);",
                "",
                typespec_definitions
            ])
            feedback = typespec_compiler.compile_typespec(typespec_schema)
            output = TypespecOutput(
                reasoning=reasoning,
                typespec_definitions=typespec_definitions,
                llm_functions=llm_functions,
                feedback=feedback,
            )
        except PolicyException as e:
            output = e
        messages = [] if not init else input
        messages.append({"role": "assistant", "content": response.content[-1].text})
        langfuse_context.update_current_observation(output=output)
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
    def parse_output(output: str) -> tuple[str, str, list[LLMFunction]]:
        pattern = re.compile(
            r"<reasoning>(.*?)</reasoning>.*?<typespec>(.*?)</typespec>",
            re.DOTALL,
        )
        match = pattern.search(output)
        if match is None:
            raise PolicyException("Failed to parse output, expected <reasoning> and <typespec> tags")
        reasoning = match.group(1).strip()
        definitions = match.group(2).strip()

        # Find functions with their metadata
        functions = []

        # Find all function declarations in the interface
        func_pattern = re.compile(r'(\s*)(\w+)\s*\(\s*\w+\s*:', re.DOTALL)
        func_matches = list(func_pattern.finditer(definitions))

        for i, func_match in enumerate(func_matches):
            func_name = func_match.group(2)

            # Determine search scope - from previous function to current function
            start_pos = 0 if i == 0 else func_matches[i-1].end()
            end_pos = func_match.start()
            search_text = definitions[start_pos:end_pos]

            # Find the preceding llm_func decorator
            llm_func_pattern = re.compile(r'@llm_func\(\s*"(.+?)"\s*\)', re.DOTALL)
            llm_func_match = llm_func_pattern.search(search_text)
            if not llm_func_match:
                continue

            description = llm_func_match.group(1)

            # Find the scenarios
            scenario_pattern = re.compile(r'@scenario\(\s*"""(.*?)"""\s*\)', re.DOTALL)
            scenario_matches = list(scenario_pattern.finditer(search_text))

            if not scenario_matches:
                continue

            # Use the last scenario as the representative one
            scenario = scenario_matches[-1].group(1).strip()

            functions.append(LLMFunction(name=func_name, description=description, scenario=scenario))

        return reasoning, definitions, functions
