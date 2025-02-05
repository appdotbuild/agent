from typing import TypedDict
from dataclasses import dataclass
from contextlib import contextmanager
import jinja2
from anthropic.types import MessageParam, ContentBlock
from langfuse.decorators import observe
from .common import TaskNode
from tracing_client import TracingClient


EXTRACT_USER_FUNCTIONS_TOOL_NAME = "extract_user_functions"


PROMPT = """
Given TypeSpec application definition for all functions decorated with @llm_func
generate prompt for the LLM to classify which function should handle user request.

Structure your response according to the schema, with each @llm_func function having:
- name: The function name
- description: A clear description of its purpose and description of user intent
- examples: Example user requests that should route to this function

Use extract_user_functions tool to extract functions from the TypeSpec.

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
""".strip()


TOOLS = [
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


FIX_PROMPT = """
Address following function definition errors:
<errors>
{{errors}}
</errors>
""".strip()


class Function(TypedDict):
    name: str
    description: str
    examples: list[str]


@dataclass
class RouterOutput:
    functions: list[Function]


@dataclass
class RouterData:
    messages: list[MessageParam]
    output: RouterOutput | Exception


class RouterTaskNode(TaskNode[RouterData, list[MessageParam]]):
    @property
    def run_args(self) -> list[MessageParam]:
        fix_template = router_jinja_env.from_string(FIX_PROMPT)
        messages = []
        for node in self.get_trajectory():
            messages.extend(node.data.messages)
            content = None
            match node.data.output:
                case RouterOutput():
                    continue
                case Exception() as e:
                    content = fix_template.render(errors=str(e))
                case catch_all:
                    raise RuntimeError(f"Received non-matched case: {catch_all}")
            if content:
                messages.append({"role": "user", "content": content})
        return messages            

    @staticmethod
    @observe(capture_input=False, capture_output=False)
    def run(input: list[MessageParam], *args, **kwargs) -> RouterData:
        response = router_client.call_anthropic(
            model="anthropic.claude-3-5-sonnet-20241022-v2:0",
            max_tokens=8192,
            messages=input,
            tools = TOOLS,
            tool_choice = {"type": "tool", "name": EXTRACT_USER_FUNCTIONS_TOOL_NAME},
        )
        try:
            functions = RouterTaskNode.parse_output(response.content)
            output = RouterOutput(functions=functions)
        except Exception as e:
            output = e
        messages = [{"role": "assistant", "content": response.content}]
        return RouterData(messages=messages, output=output)
    
    @property
    def is_successful(self) -> bool:
        return not isinstance(self.data.output, Exception)
    
    @staticmethod
    @contextmanager
    def platform(client: TracingClient, jinja_env: jinja2.Environment):
        try:
            global router_client
            global router_jinja_env
            router_client = client
            router_jinja_env = jinja_env
            yield
        finally:
            del router_client
            del router_jinja_env
    
    @staticmethod
    def parse_output(content_blocks: list[ContentBlock]) -> list[Function]:
        for content in content_blocks:
            if content.type == "tool_use" and content.name == EXTRACT_USER_FUNCTIONS_TOOL_NAME:
                return content.input["user_functions"]
        raise ValueError(f"Failed to parse output, expected {EXTRACT_USER_FUNCTIONS_TOOL_NAME} tool use")
