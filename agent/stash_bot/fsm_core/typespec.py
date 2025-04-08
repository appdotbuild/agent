from typing import Protocol, Self
from dataclasses import dataclass
import re
import jinja2
from anthropic.types import MessageParam
from dag_compiler import Compiler, CompileResult
from . import llm_common
from .common import AgentMachine


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
- void: Represents no value (NEVER use this as a return type for functions/operations - always return meaningful values that provide useful information to the caller)
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
<user_requests>
Bot that records my diet and calculates calories.
</user_requests>

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
- recordDish(options: Dish): DishRecord;

model DishRecord {
    timestamp: utcDateTime;
    name: string;
    calories: integer;
}
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
    recordDish(options: Dish): DishRecord;

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

<user_requests>
{% for request in user_requests %}
{{request}}
{% endfor %}
</user_requests>

Return <reasoning> and TypeSpec definition encompassed with <typespec> tag.
""".strip()


FIX_PROMPT = """
Make sure to address following TypeSpec compilation errors:
<errors>
{{errors}}
</errors>

Verify absence of reserved keywords in property names, type names, and function names.
Return <reasoning> and fixed complete TypeSpec definition encompassed with <typespec> tag.
""".strip()


FEEDBACK_PROMPT = """
Given a history of a chat with user, revise the TypeSpec models and interface for the application.

<user_requests>
{% for request in user_requests %}
{{request}}
{% endfor %}
</user_requests>

Here is your previous TypeSpec schema:
<previous_schema>
{{previous_schema}}
</previous_schema>

Please revise the schema based on this feedback:
<feedback>
{{feedback}}
</feedback>

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

Return your revised schema with:
<reasoning>
Your reasoning for each change you made based on the feedback
</reasoning>

<typespec>
// Your revised TypeSpec schema
</typespec>
""".strip()


@dataclass
class LLMFunction:
    name: str
    description: str
    scenario: str


class TypespecContext(Protocol):
    compiler: Compiler


class TypespecMachine(AgentMachine[TypespecContext]):
    @staticmethod
    def parse_output(output: str) -> tuple[str, str, list[LLMFunction]]:
        pattern = re.compile(
            r"<reasoning>(.*?)</reasoning>.*?<typespec>(.*?)</typespec>",
            re.DOTALL,
        )
        match = pattern.search(output)
        if match is None:
            raise ValueError("Failed to parse output, expected <reasoning> and <typespec> tags")
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

        if not functions:
            raise ValueError("Failed to parse output, expected at least one function definition")
        return reasoning, definitions, functions

    async def on_message(self: Self, context: TypespecContext, message: MessageParam) -> "TypespecMachine":
        content = llm_common.pop_first_text(message)
        if content is None:
            raise RuntimeError(f"Failed to extract text from message: {message}")
        try:
            reasoning, typespec, llm_functions = self.parse_output(content)
        except ValueError as e:
            return FormattingError(e)
        typespec_schema = "\n".join([
            'import "./helpers.js";',
            "",
            "extern dec llm_func(target: unknown, description: string);",
            "",
            "extern dec scenario(target: unknown, gherkin: string);",
            "",
            typespec
        ])
        feedback = await context.compiler.compile_typespec(typespec_schema)
        if feedback["exit_code"] != 0:
            return CompileError(reasoning, typespec, llm_functions, feedback)
        return Success(reasoning, typespec, llm_functions, feedback)

    @property
    def is_done(self) -> bool:
        return False

    @property
    def score(self) -> float:
        return 0.0


class Entry(TypespecMachine):
    """Initial state for creating a new TypeSpec schema without feedback"""
    def __init__(self, user_requests: list[str]):
        self.user_requests = user_requests

    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(PROMPT).render(user_requests=self.user_requests)
        return MessageParam(role="user", content=content)


class FeedbackEntry(TypespecMachine):
    """State for revising an existing TypeSpec schema with feedback"""
    def __init__(self, user_requests: list[str], previous_schema: str, feedback: str):
        self.user_requests = user_requests
        self.previous_schema = previous_schema
        self.feedback = feedback

    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(FEEDBACK_PROMPT).render(
            user_requests=self.user_requests,
            previous_schema=self.previous_schema,
            feedback=self.feedback
        )
        return MessageParam(role="user", content=content)


class FormattingError(TypespecMachine):
    def __init__(self, exception: ValueError):
        self.exception = exception

    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(FIX_PROMPT).render(errors=self.exception)
        return MessageParam(role="user", content=content)


class TypespecCompile:
    def __init__(self, reasoning: str, typespec: str, llm_functions: list[LLMFunction], feedback: CompileResult):
        self.reasoning = reasoning
        self.typespec = typespec
        self.llm_functions = llm_functions
        self.feedback = feedback


class CompileError(TypespecMachine, TypespecCompile):
    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(FIX_PROMPT).render(errors=self.feedback["stdout"])
        return MessageParam(role="user", content=content)


class UserFeedback(TypespecMachine, TypespecCompile):
    def __init__(self, reasoning: str, typespec: str, llm_functions: list[LLMFunction], feedback: CompileResult, additional_feedback: str):
        super().__init__(reasoning, typespec, llm_functions, feedback)
        self.additional_feedback = additional_feedback

    @property
    def next_message(self) -> MessageParam | None:
        content = jinja2.Template(FIX_PROMPT).render(errors=self.feedback["stdout"], additional_feedback=self.additional_feedback)
        return MessageParam(role="user", content=content)


class Success(TypespecMachine, TypespecCompile):
    @property
    def next_message(self) -> MessageParam | None:
        return None

    @property
    def is_done(self) -> bool:
        return True

    @property
    def score(self) -> float:
        return 1.0
