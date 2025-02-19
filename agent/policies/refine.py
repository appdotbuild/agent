from dataclasses import dataclass
from contextlib import contextmanager
import re
import jinja2
from anthropic.types import MessageParam
from langfuse.decorators import observe, langfuse_context
from .common import TaskNode
from tracing_client import TracingClient
import logging

logger = logging.getLogger(__name__)

PROMPT = """
Refine the following prompt to well-defined requirements for the minimalistic MVP.
It will be used by the app that generates chatbots.
This chatbot will be able to use LLM under the hood.
Do not focus on technical implementation and data infrastructure (assuming it will be handled downstream), only refine the user requirements so they are not ambiguous.
Do not overcomplicate the requirements, keep them concise and focused on the MVP.
Final output should not be more than three times longer than initial user prompt.

Example input:
<requirements>
Bot that records my diet and calculates calories.
</requirements>

<think>
Okay, so the user wants to refine their prompt into requirements for an MVP of a diet-recording, calorie-calculating chatbot. Let me start by understanding the original idea. The core features are recording diet and calculating calories using an LLM. The user mentioned not focusing on technical stuff, just the user requirements.

First, I need to outline the main user interactions. The MVP should be minimal, so only essential features. The chatbot needs to let users input their diet entries. Maybe through text or voice, since LLMs can handle that. But wait, the user said not to overcomplicate. So maybe just text input for now.
Next, the bot should understand the entries. The LLM can parse the food items and quantities. Then calculate calories. But how? The bot needs a database or some lookup. But the user said to assume data infrastructure is handled downstream. So just state that the bot should retrieve calorie data based on entries.
Then, the user might want a daily summary. Total calories, maybe breakdown by meal. But keep it simple. Just total calories per day, and a breakdown by meal if possible. No need for macros or nutrients in MVP.
User should be able to edit entries. So correction feature. Maybe via commands like "remove" or "edit". Also, data persistence. The bot should remember entries, but technical details are handled later. So just state that entries are stored between sessions.
Error handling is important. If the bot doesn't understand an entry, it should ask for clarification. But how to phrase that as a requirement? Maybe the bot prompts the user for missing info like quantity or specific food items.
Accessibility? Maybe voice input, but the user wants minimal. Hmm. The original prompt says "assuming it will be handled downstream", so maybe mention text or voice input as options, but not necessary to implement both. Wait, the user said do not focus on technical implementation, so just allow both input methods as possibilities without specifying how.
Wait, the example answer the user provided includes text and voice input. So maybe include that. But keep it high-level. So the bot should accept both text and voice inputs.
Putting it all together. The MVP requirements should be:
Input methods (only text for now).
Log food with details.
Calorie calculation using a database.
Daily summary with total and meals.
Edit/delete entries.
Error handling for unclear inputs.
Data persistence.
But need to make sure they're concise and not ambiguous. Let me check each point. Input methods: specify that the bot allows both. Logging entries: user can specify food, quantity, meal time. The bot parses this. Calorie calculation: uses a standard database, mention common items but allow custom entries. Daily summary: total calories, per meal. Correction: simple commands. Error handling: prompt user for missing info. Data: stored between sessions.
Yes, that covers the MVP without technical details. Keep each requirement brief and focused on user actions and outcomes.
</think>
<requirements>
An application to track user's diet and calculate calories using an LLM.
Input Methods:
- Users can log meals via text, specifying food items, optional quantities (e.g., "200g oats"), and meal times (optional).
Automatic Calorie Calculation
- The bot parses entries, identifies food items/quantities, and calculates total calories using a standard nutritional database (e.g., "1 banana" = ~105 kcal).
- Supports manual calorie entry for unlisted items (e.g., "Homemade curry, 300 kcal").
Daily Summary
- Provides a daily total calorie count and breakdown by meal (breakfast/lunch/dinner/snacks).
Corrections & Persistence
- Users can edit/delete entries using simple commands (e.g., "Remove my 3 PM snack").
Data persists between sessions.
Clarification Prompts
- The bot requests missing details (e.g., quantity, specific food type) if inputs are ambiguous (e.g., "I ate salad" → "What type of salad and portion size?").
Excluded from MVP: Meal planning, nutrient tracking (carbs/protein/fat), integrations (fitness apps), voice mode or advanced analytics.
Focus: Core logging, calorie math, and error-free user interaction.
</requirements>

Please provide detailed requirements for:
{{application_description}}

Return requirements encompassed with <requirements> tag.
""".strip()

@dataclass
class RefinementOutput:
    requirements: str
    feedback: dict[str, str]

    @property
    def error_or_none(self) -> str | None:
        return self.feedback.get("errors")

@dataclass
class RefinementData:
    messages: list[MessageParam]
    output: RefinementOutput | Exception

class RefinementTaskNode(TaskNode[RefinementData, list[MessageParam]]):
    @property
    def run_args(self) -> list[MessageParam]:
        raise RuntimeError("Should never happen")

    @staticmethod
    @observe(capture_input=False, capture_output=False)
    def run(input: list[MessageParam], *args, **kwargs) -> RefinementData:
        response = refinement_client.call_anthropic(
            model="anthropic.claude-3-5-sonnet-20241022-v2:0",
            max_tokens=8192,
            messages=input,
        )
        try:
            requirements = RefinementTaskNode.parse_output(response.content[0].text)
            feedback = {}
            output = RefinementOutput(
                requirements=requirements,
                feedback=feedback,
            )
        except Exception as e:
            output = e
        messages = [{"role": "assistant", "content": response.content[0].text}]
        langfuse_context.update_current_observation(output=output)
        return RefinementData(messages=messages, output=output)

    @property
    def is_successful(self) -> bool:
        return (
            not isinstance(self.data.output, Exception)
            and not self.data.output.feedback.get("errors")
        )

    @staticmethod
    def parse_output(output: str) -> str:
        pattern = re.compile(
            r"<requirements>(.*?)</requirements>",
            re.DOTALL,
        )
        match = pattern.search(output)
        if match is None:
            raise ValueError("Failed to parse output, expected <requirements> tag")
        return match.group(1).strip()

    @staticmethod
    @contextmanager
    def platform(client: TracingClient, jinja_env: jinja2.Environment):
        try:
            global refinement_client
            global refinement_jinja_env
            refinement_client = client
            refinement_jinja_env = jinja_env
            yield
        finally:
            del refinement_client
            del refinement_jinja_env
