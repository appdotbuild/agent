from typing import TypedDict
import re

PROMPT = """
Given user application description generate TypeSpec models and interface for the application. Output just a single interface.
Every decorated @llm_func operates on free-form text messages and its arguments should be
easily extractable from chat messages. Keep argument complexity within what can be extracted / inferred
from the chat messages directly. When designing the interface expect that every function has a pre- and post-processor.

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
    name: String
    ingredients: Ingredient[]
}

model Ingredient {
    name: String
    calories: Int
}

interface DietBot {
    @llm_func(1)
    recordDish(dish: Dish): void;
    @llm_func(1)
    listDishes(from: Date, to: Date): Dish[];
}
</typespec>

User application description:
{{application_description}}

Return <reasoning> and TypeSpec definition encompassed with <typespec> tag.
""".strip()


class TypespecInput(TypedDict):
    application_description: str
    application_specification: str


class TypespecOutput(TypedDict):
    reasoning: str
    typespec_definitions: str
    llm_functions: list[str]


def parse_output(output: str) -> TypespecOutput:
    pattern = re.compile(
        r"<reasoning>(.*?)</reasoning>.*?<typespec>(.*?)</typespec>",
        re.DOTALL,
    )
    match = pattern.search(output)
    if match is None:
        raise ValueError("Failed to parse output")
    reasoning = match.group(1).strip()
    typespec_definitions = match.group(2).strip()
    llm_functions = re.findall(
        r'@llm_func\(\d+\)\s*(\w+)\s*\(',
        typespec_definitions
    )
    return TypespecOutput(reasoning=reasoning, typespec_definitions=typespec_definitions, llm_functions=llm_functions)