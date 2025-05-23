from typing import Awaitable, Callable, Self, Protocol, runtime_checkable, Dict, Any, Tuple
import anyio
from fire import Fire

import enum
from core.application import ApplicationBase
from llm.utils import AsyncLLM
from llm.common import Message, ToolUse, ToolResult as CommonToolResult
from llm.common import ToolUseResult, TextRaw, Tool
from log import get_logger
import ujson as json

logger = get_logger(__name__)


@runtime_checkable
class FSMInterface(ApplicationBase, Protocol):
    @classmethod
    async def start_fsm(cls, user_prompt: str, settings: Dict[str, Any]) -> Self: ...
    async def confirm_state(self): ...
    async def apply_changes(self, feedback: str): ...
    async def complete_fsm(self): ...
    @classmethod
    def base_execution_plan(cls) -> str: ...
    @property
    def available_actions(self) -> dict[str, str]: ...# FSMTools Specific



class FSMStatus(enum.Enum):
    WIP = "WIP"
    IDLE = "IDLE"


class FSMToolProcessor[T: FSMInterface]:
    """
    Thin adapter that exposes FSM functionality as tools for AI agents.

    This class only contains the tool interface definitions and minimal
    logic to convert between tool calls and FSM operations. It works with
    any FSM application that implements the FSMInterface protocol.
    """

    fsm_class: type[T]
    fsm_app: T | None
    settings: Dict[str, Any]

    def __init__(self, fsm_class: type[T], fsm_app: T | None = None, settings: Dict[str, Any] | None = None):
        """
        Initialize the FSM Tool Processor

        Args:
            fsm_class: FSM application class to use
            fsm_app: Optional existing FSM application instance
            settings: Optional dictionary of settings for the FSM/LLM
        """
        self.fsm_class = fsm_class
        self.fsm_app = fsm_app
        self.settings = settings or {}

        # Define tool definitions for the AI agent using the common Tool structure
        self.tool_definitions: list[Tool] = [
            {
                "name": "start_fsm",
                "description": "Start a new interactive FSM session for application generation",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "app_description": {
                            "type": "string",
                            "description": "Description for the application to generate"
                        }
                    },
                    "required": ["app_description"]
                }
            },
            {
                "name": "confirm_state",
                "description": "Accept the current FSM state output and advance to the next state",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "change",
                "description": "Submit changes to modify output of the current state",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "feedback": {
                            "type": "string",
                            "description": "Complete and improved instructions to produce the desired output"
                        },
                    },
                    "required": ["feedback"]
                }
            },
            {
                "name": "complete_fsm",
                "description": "Finalize and return all generated artifacts from the FSM",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        ]

        # Map tool names to their implementation methods
        self.tool_mapping: dict[str, Callable[..., Awaitable[CommonToolResult]]] = {
            "start_fsm": self.tool_start_fsm,
            "confirm_state": self.tool_confirm_state,
            "change": self.tool_change,
            "complete_fsm": self.tool_complete_fsm
        }

    async def tool_start_fsm(self, app_description: str) -> CommonToolResult:
        """Tool implementation for starting a new FSM session"""
        try:
            logger.info(f"Starting new FSM session with description: {app_description}")

            # Check if there's an active session first
            if self.fsm_app:
                logger.warning("There's an active FSM session already. Completing it before starting a new one.")
                return CommonToolResult(content="An active FSM session already exists. Please explain why do you even need to create a new one instead of using existing one. Should you use `change` tool instead?", is_error=True)

            self.fsm_app = await self.fsm_class.start_fsm(user_prompt=app_description, settings=self.settings)

            # Check for errors
            if (error_msg := self.fsm_app.maybe_error()):
                return CommonToolResult(content=f"FSM initialization failed: {error_msg}", is_error=True)

            # Prepare the result
            result = self.fsm_as_result()
            logger.info("Started FSM session")
            return CommonToolResult(content=json.dumps(result, sort_keys=True))

        except Exception as e:
            logger.exception(f"Error starting FSM: {str(e)}")
            return CommonToolResult(content=f"Failed to start FSM: {str(e)}", is_error=True)

    async def tool_confirm_state(self) -> CommonToolResult:
        """Tool implementation for confirming the current state"""
        try:
            if not self.fsm_app:
                logger.error("No active FSM session")
                return CommonToolResult(content="No active FSM session", is_error=True)

            # Store previous state for comparison
            previous_state = self.fsm_app.current_state
            logger.info(f"Current state before confirmation: {previous_state}")

            # Send confirm event
            logger.info("Confirming current state")
            await self.fsm_app.confirm_state()
            current_state = self.fsm_app.current_state

            # Check for errors
            if (error_msg := self.fsm_app.maybe_error()):
                return CommonToolResult(content=f"FSM confirmation failed: {error_msg}", is_error=True)

            # Prepare result
            result = self.fsm_as_result()
            logger.info(f"FSM advanced to state {current_state}")
            return CommonToolResult(content=json.dumps(result, sort_keys=True))

        except Exception as e:
            logger.exception(f"Error confirming state: {str(e)}")
            return CommonToolResult(content=f"Failed to confirm state: {str(e)}", is_error=True)

    async def tool_change(self, feedback: str) -> CommonToolResult:
        """Tool implementation for applying changes"""
        try:
            if not self.fsm_app:
                logger.error("No active FSM session")
                return CommonToolResult(content="No active FSM session", is_error=True)

            # Determine current state and feedback event type
            current_state = self.fsm_app.current_state
            logger.info(f"Current state: {current_state}")

            # Handle feedback
            logger.info("Providing feedback")
            await self.fsm_app.apply_changes(feedback)
            new_state = self.fsm_app.current_state

            # Check for errors
            if (error_msg := self.fsm_app.maybe_error()):
                return CommonToolResult(content=f"FSM while processing feedback: {error_msg}", is_error=True)

            # Prepare result
            result = self.fsm_as_result()
            logger.info(f"FSM updated with feedback, now in state {new_state}")
            return CommonToolResult(content=json.dumps(result, sort_keys=True))

        except Exception as e:
            logger.exception(f"Error providing feedback: {str(e)}")
            return CommonToolResult(content=f"Failed to provide feedback: {str(e)}", is_error=True)

    async def tool_complete_fsm(self) -> CommonToolResult:
        """Tool implementation for completing the FSM and getting all artifacts"""
        try:
            if not self.fsm_app:
                logger.error("No active FSM session")
                return CommonToolResult(content="No active FSM session", is_error=True)

            logger.info("Completing FSM session")
            await self.fsm_app.complete_fsm()

            # Check for errors
            if (error_msg := self.fsm_app.maybe_error()):
                return CommonToolResult(content=f"FSM failed with error: {error_msg}", is_error=True)

            # Prepare result based on state
            result = self.fsm_as_result()
            logger.info(f"FSM completed in state: {self.fsm_app.current_state}")
            return CommonToolResult(content=json.dumps(result, sort_keys=True))

        except Exception as e:
            logger.exception(f"Error completing FSM: {str(e)}")
            return CommonToolResult(content=f"Failed to complete FSM: {str(e)}", is_error=True)

    async def step(self, messages: list[Message], llm: AsyncLLM, model_params: dict) -> Tuple[list[Message], FSMStatus]:
        model_args = {
            "system_prompt": self.system_prompt,
            "tools": self.tool_definitions,
            **model_params,
        }
        response = await llm.completion(messages, **model_args)
        tool_results = []
        for block in response.content:
            match block:
                case TextRaw(text):
                    logger.info(f"LLM Message: {text}")
                case ToolUse(name):
                    match self.tool_mapping.get(name):
                        case None:
                            tool_results.append(ToolUseResult.from_tool_use(
                                tool_use=block,
                                content=f"Unknow tool name: {name}",
                                is_error=True,
                            ))
                        case tool_method if isinstance(block.input, dict):
                            result = await tool_method(**block.input)
                            logger.info(f"Tool call: {name} with input: {block.input}")
                            logger.debug(f"Tool result: {result.content}")
                            tool_results.append(ToolUseResult.from_tool_use(
                                tool_use=block,
                                content=result.content
                            ))
                        case _:
                            raise RuntimeError(f"Invalid tool call: {block}")

        thread = [Message(role="assistant", content=response.content)]
        if tool_results:
            thread += [Message(role="user", content=[*tool_results, TextRaw("Analyze tool results.")])]
        match (tool_results, self.fsm_app):
            case (_, app) if app and (app.is_completed or app.maybe_error()):
                fsm_status = FSMStatus.IDLE # app in terminal state, always exit
            case ([], app):
                fsm_status = FSMStatus.IDLE # no tools used, always exit
            case _:
                fsm_status = FSMStatus.WIP # continue processing
        return thread, fsm_status

    def fsm_as_result(self) -> dict:
        if self.fsm_app is None:
            raise RuntimeError("Attempt to get result with uninitialized fsm application.")

        return {
            "current_state": self.fsm_app.current_state,
            "output": self.fsm_app.state_output,
            "available_actions": self.fsm_app.available_actions,
        }

    @property
    def system_prompt(self) -> str:
        return f"""You are a software engineering expert who can generate application code using a code generation framework based on Typescript, tRPC and Drizzle. This framework uses a Finite State Machine (FSM) to guide the generation process.

Your task is to control the FSM through the following stages of code generation:
{self.fsm_class.base_execution_plan()}

To successfully complete this task, follow these steps:

1. Start a new FSM session using the start_fsm tool.
2. For each component generated by the FSM:
2.a. Carefully review the output.
2.b. Decide whether to confirm the output or provide feedback for improvement.
2.c. Use the appropriate tool (confirm_state or change) based on your decision.
3. Repeat step 2 until all components have been generated and confirmed.
4. Use the complete_fsm tool to finalize the process and retrieve all artifacts.

During your review process, consider the following questions:
- Does the code correctly implement the application requirements?
- Are there any errors or inconsistencies?
- Could anything be improved or clarified?
- Does it match other requirements mentioned in the dialogue?

When providing feedback, be specific and actionable. If you're unsure about any aspect, always ask for clarification before proceeding.
FSM is an internal API, you don't need to know how it works under the hood or expose its details to the user.
Prefer simple solutions, build an app with very basic features only first unless the user explicitly asks for something more complex.

Do not consider the work complete until all components have been generated and the complete_fsm tool has been called.""".strip()


async def main(initial_prompt: str = "A simple greeting app that says hello in five languages"):
    """
    Main entry point for the FSM tools module.
    Initializes an FSM tool processor and interacts with top-level agent.
    """
    import os
    import dagger
    from trpc_agent.application import FSMApplication
    from llm.utils import get_llm_client
    logger.info("Initializing FSM tools...")
    client = get_llm_client()
    model_params = {"max_tokens": 8192 }

    # Create processor without FSM instance - it will be created in start_fsm tool
    processor = FSMToolProcessor(FSMApplication)
    logger.info("FSM tools initialized successfully")

    # Create the initial prompt for the AI agent
    logger.info("Sending request to LLM...")
    current_messages = [
        Message(role="user", content=[TextRaw(initial_prompt)]),
    ]

    async with dagger.connection(dagger.Config(log_output=open(os.devnull, "w"))):
        # Main interaction loop
        while True:
            new_messages = await processor.step(current_messages, client, model_params)

            logger.debug(f"New messages: {new_messages}")
            if new_messages:
                current_messages += new_messages

            logger.info(f"Iteration completed: {len(current_messages) - 1}")

            break # Early out until feedback is wired to component name

    logger.info("FSM interaction completed successfully")
    return new_messages

def run_main(initial_prompt: str = "A simple greeting app that says hello in five languages and stores history of greetings"):
    return anyio.run(main, initial_prompt)

if __name__ == "__main__":
    Fire(run_main)
