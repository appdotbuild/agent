from typing import TypedDict
import re

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

Make sure to address following TypeSpec compilation errors:
<errors>
{{typespec_errors}}
</errors>
""".strip()


class TypespecInput(TypedDict):
    application_description: str
    application_specification: str


class TypespecOutput(TypedDict):
    reasoning: str
    typespec_definitions: str
    llm_functions: list[str]


def extract_llm_func_names(output: str) -> list[str]:
    pattern = re.compile(
        r'@llm_func\(\d+\)\s*(\w+)\s*\(',
        re.DOTALL,
    )
    return pattern.findall(output)


def parse_output(output: str) -> TypespecOutput:
    pattern = re.compile(
        r"<reasoning>(.*?)</reasoning>.*?<typespec>(.*?)</typespec>",
        re.DOTALL,
    )
    match = pattern.search(output)
    if match is None:
        raise ValueError("Failed to parse output, expected <reasoning> and <typespec> tags")
    reasoning = match.group(1).strip()
    typespec_definitions = match.group(2).strip()
    llm_functions = extract_llm_func_names(output)
    return TypespecOutput(reasoning=reasoning, typespec_definitions=typespec_definitions, llm_functions=llm_functions)
