from typing import TypedDict
import re


PROMPT_PRE = """
Given TypeSpec application definition examine arguments of {{function_name}} function.
Generate 3 to 5 pairs of example user inputs and outputs matching the function signature.

TypeSpec definition:
<typespec>
{{typespec_definitions}}
</typespec>

Return output in the format:
<instructions>
// General instruction for LLM when handling user input for {{function_name}} function.
// Includes rules for imputing arguments that might be missing in the user input.
</instructions>

<example>
<input>
// Example user input. Plain text messages such as what is the time? bench press 80x6 etc.
</input>
<output>
// Expected structured JSON output of the arguments.
// Follow proper JSON format, undefined values should be null.
</output>
</example>
""".strip()


class PreprocessorInput(TypedDict):
    typespec_definitions: str
    function_name: str


class PreprocessorOutput(TypedDict):
    instructions: str
    examples: list[tuple[str, str]]


def parse_output(output: str) -> PreprocessorOutput:
    pattern = re.compile(r"<instructions>(.*?)</instructions>", re.DOTALL)
    match = pattern.search(output)
    if match is None:
        raise ValueError("Failed to parse output", output)
    instructions = match.group(1).strip()
    examples = re.findall(r"<example>\s*<input>(.*?)</input>\s*<output>(.*?)</output>\s*</example>", output, re.DOTALL)
    return PreprocessorOutput(instructions=instructions, examples=examples)