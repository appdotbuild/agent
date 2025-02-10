from dataclasses import dataclass
from contextlib import contextmanager
import re
import jinja2
from anthropic.types import MessageParam
from langfuse.decorators import observe, langfuse_context
from .common import TaskNode
from tracing_client import TracingClient
from compiler.core import Compiler, CompileResult


PROMPT = """
Based on TypeSpec models and interfaces, generate Gherkin test cases for the application.
Ensure that the output follows the Gherkin syntax.
Provide reasoning within <reasoning> tag.
Encompass output with <gherkin> tag.

Make sure to follow gherkin-lint rules:
{
  "no-files-without-scenarios": "on",
  "no-unnamed-features": "on",
  "no-unnamed-scenarios": "on",
  "no-dupe-scenario-names": "on",
  "no-dupe-feature-names": "on",
  "no-empty-file": "on",
  "no-trailing-spaces": "on",
  "new-line-at-eof": ["on", "yes"],
  "no-multiple-empty-lines": "on",
  "no-empty-background": "on",
  "indentation": [
    "on", 
    {
      "Feature": 0,
      "Background": 2,
      "Scenario": 2,
      "Step": 4,
      "Examples": 4,
      "example": 6
    }
  ]
}

Example output:

<reasoning>
    The application operates on users and messages and processes them with LLM.
    The users are identified by their ids.
    The messages have roles and content.
</reasoning>

<gherkin>
Feature: Car Poetry Bot
  As a user of the Car Poetry Bot
  I want to generate and manage car-themed poems
  So that I can create artistic content about vehicles

  Background:
    Given the CarPoetBot service is running
    And the current time is "2024-03-20T10:00:00Z"

  Scenario: Generate a poem about a sports car
    Given I have the following car details:
      | make     | modelName | year | type      |
      | Ferrari  | F8        | 2023 | sports    |
    And I want a poem with style:
      | styleType | length | mood    |
      | haiku     | 3      | excited |
    When I call generatePoem with the car and style
    Then I should receive a Poem with:
      | field     | value                    |
      | id        | {any string}             |
      | content   | {non-empty string}       |
      | car       | {matching car details}   |
      | style     | {matching style details} |
      | createdAt | {valid UTC timestamp}    |

  Scenario: Save a generated poem
    Given I have a poem:
      | id        | content           | car                              | style                                | createdAt            |
      | poem-123  | Sample poem text  | {"make":"BMW","modelName":"M3"}  | {"styleType":"free","mood":"sporty"} | 2024-03-20T10:00:00Z |
    When I call savePoem with the poem
    Then the operation should complete successfully

  Scenario: Get favorite poems within date range
    Given there are saved poems in the system
    When I call getFavoritePoems with:
      | fromDate               | toDate                 |
      | 2024-03-19T00:00:00Z  | 2024-03-20T23:59:59Z  |
    Then I should receive an array of Poem objects
    And each poem should have all required fields
    And each poem's createdAt should be within the specified date range
</gherkin>

Application TypeSpec:

{{typespec_schema}}
""".strip()


FIX_PROMPT = """
Make sure to address following gherkin errors:
<errors>
{{errors}}
</errors>

Return <reasoning> and fixed complete gherkin definition encompassed with <gherkin> tag.
"""


@dataclass
class GherkinOutput:
    reasoning: str
    gherkin: str
    feedback: CompileResult

    @property
    def error_or_none(self) -> str | None:
        return self.feedback["stdout"] if self.feedback["exit_code"] != 0 else None


@dataclass
class GherkinData:
    messages: list[MessageParam]
    output: GherkinOutput | Exception


class GherkinTaskNode(TaskNode[GherkinData, list[MessageParam]]):
    @property
    def run_args(self) -> list[MessageParam]:
        fix_template = gherkin_jinja_env.from_string(FIX_PROMPT)
        messages = []
        for node in self.get_trajectory():
            messages.extend(node.data.messages)
            content = None
            match node.data.output:
                case GherkinOutput(feedback={"exit_code": exit_code, "stdout": stdout}) if exit_code != 0:
                    content = fix_template.render(errors=stdout)
                case GherkinOutput():
                    continue
                case Exception() as e:
                    content = fix_template.render(errors=str(e))
            if content:
                messages.append({"role": "user", "content": content})
        return messages            

    @staticmethod
    @observe(capture_input=False, capture_output=False)
    def run(input: list[MessageParam], *args, **kwargs) -> GherkinData:
        response = gherkin_client.call_anthropic(
            model="anthropic.claude-3-5-sonnet-20241022-v2:0",
            max_tokens=8192,
            messages=input,
        )
        try:
            reasoning, gherkin = GherkinTaskNode.parse_output(response.content[0].text)
            feedback = gherkin_compiler.compile_gherkin(gherkin)
            output = GherkinOutput(
                reasoning=reasoning,
                gherkin=gherkin,
                feedback=feedback
            )
        except Exception as e:
            output = e
        messages = [{"role": "assistant", "content": response.content[0].text}]
        langfuse_context.update_current_observation(output=output)
        return GherkinData(messages=messages, output=output)
    
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
            global gherkin_client
            global gherkin_compiler
            global gherkin_jinja_env
            gherkin_client = client
            gherkin_compiler = compiler
            gherkin_jinja_env = jinja_env
            yield
        finally:
            del gherkin_client
            del gherkin_compiler
            del gherkin_jinja_env
    
    @staticmethod
    def parse_output(output: str) -> tuple[str, str, list[str]]:
        pattern = re.compile(
            r"<reasoning>(.*?)</reasoning>.*?<gherkin>(.*?)</gherkin>",
            re.DOTALL,
        )
        match = pattern.search(output)
        if match is None:
            raise ValueError("Failed to parse output, expected <reasoning> and <gherkin> tags")
        reasoning = match.group(1).strip()
        gherkin = match.group(2).strip()
        #test_cases = re.findall(r"Scenario: (.*?)\n(.*?)\n", gherkin, re.DOTALL)
        return reasoning, gherkin #, test_cases
