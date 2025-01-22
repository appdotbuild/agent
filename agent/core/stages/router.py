from typing import TypedDict

EXTRACT_USER_FUNCTIONS_TOOL_NAME = "extract_user_functions"

PROMPT = """
Given TypeSpec application definition for all functions decorated with @llm_func
generate prompt for the LLM to classify which function should handle user request.

Structure your response according to the schema, with each @llm_func function having:
- name: The function name
- description: A clear description of its purpose and description of user intent
- examples: Example user requests that should route to this function

Use {EXTRACT_USER_FUNCTIONS_TOOL_NAME} tool to extract functions from the TypeSpec.

Example input:

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
    @llm_func("pre", 1)
    recordDish(dish: Dish): void;
    @llm_func("wrap", 1)
    listDishes(from: Date, to: Date): Dish[];
}
</typespec>

Example output:
{
  "user_functions": [
    {
      "name": "logUsersDish",
      "description": "Log users dish.",
      "examples": [
        "I ate a burger.",
        "I had a salad for lunch.",
        "Chili con carne"]
      ]
    }
  ]
}

Application TypeSpec:

<typespec>
{{typespec_definitions}}
</typespec>

User request:

{{user_request}}
""".strip()

TOOLS =[
        {
            "name": EXTRACT_USER_FUNCTIONS_TOOL_NAME,
            "description": "Extracts user functions from the specification.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "user_functions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "The extracted function name."},
                                "description": {"type": "string", "description": "A clear description of its purpose and description of user intent."},
                                "examples": {"type": "array", "items": {"type": "string"}, "description": "Example user requests that should route to this function."}
                            },
                            "required": ["name", "description", "examples"]
                        }
                    }
                },
                "required": ["user_functions"]
            }
        }
    ]

class RouterInput(TypedDict):
    application_description: str


class Function(TypedDict):
    name: str
    description: str


class RouterOutput(TypedDict):
    functions: list[Function]


def parse_outputs(content_blocks) -> RouterOutput:
    for content in content_blocks:
        if content.type == "tool_use" and content.name == EXTRACT_USER_FUNCTIONS_TOOL_NAME:
            return content.input

