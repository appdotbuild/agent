from typing import List, Dict, Any, Optional, Self, Tuple, Protocol, runtime_checkable
import logging
import coloredlogs
import sys
import anyio
from fire import Fire
import uuid

from llm.utils import get_llm_client, AsyncLLM
from llm.common import Message, ToolUse, ToolResult as CommonToolResult
from llm.common import ToolUseResult, TextRaw, Tool
from log import get_logger


# Configure logging to use stderr instead of stdout
coloredlogs.install(level="INFO", stream=sys.stderr)
logger = get_logger(__name__)


@runtime_checkable
class FSMInterface(Protocol):
    @classmethod
    def base_execution_plan(cls) -> str: ...
    @classmethod
    async def start_fsm(cls, user_input: str) -> Self: ...
    async def confirm_state(self): ...
    async def provide_feedback(self, feedback: str, component_name: str | None): ...
    async def complete_fsm(self): ...
    @property
    def current_state(self) -> str: ...
    @property
    def state_output(self) -> dict: ...
    @property
    def available_actions(self) -> dict[str, str]: ...
    def maybe_error(self) -> str | None: ...


class FSMToolProcessor[T: FSMInterface]:
    """
    Thin adapter that exposes FSM functionality as tools for AI agents.

    This class only contains the tool interface definitions and minimal
    logic to convert between tool calls and FSM operations. It works with
    any FSM application that implements the FSMInterface protocol.
    """

    fsm_class: type[T]
    fsm_app: T | None

    def __init__(self, fsm_class: type[T]):
        """
        Initialize the FSM Tool Processor

        Args:
            fsm_class: FSM application class to use
        """
        self.fsm_class = fsm_class

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
                "name": "provide_feedback",
                "description": "Submit feedback for the current FSM state and trigger revision",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "feedback": {
                            "type": "string",
                            "description": "Feedback to provide for the current output"
                        },
                        "component_name": {
                            "type": "string",
                            "description": "Optional component name for handler-specific feedback"
                        }
                    },
                    "required": ["feedback", "component_name"]
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
        self.tool_mapping = {
            "start_fsm": self.tool_start_fsm,
            "confirm_state": self.tool_confirm_state,
            "provide_feedback": self.tool_provide_feedback,
            "complete_fsm": self.tool_complete_fsm
        }

    async def tool_start_fsm(self, app_description: str) -> CommonToolResult:
        """Tool implementation for starting a new FSM session"""
        try:
            logger.info(f"[FSMTools] Starting new FSM session with description: {app_description}")

            # Check if there's an active session first
            if self.fsm_app:
                logger.warning("[FSMTools] There's an active FSM session already. Completing it before starting a new one.")
                return CommonToolResult(content="An active FSM session already exists. Please explain why do you even need to create a new one instead of using existing one", is_error=True)

            # Create a new FSM application
            self.fsm_app = await self.fsm_class.start_fsm(user_input=app_description)

            # Check for errors
            if (error_msg := self.fsm_app.maybe_error()):
                return CommonToolResult(content=f"FSM initialization failed: {error_msg}", is_error=True)

            # Prepare the result
            result = self.fsm_as_result()
            logger.info(f"[FSMTools] Started FSM session")
            return CommonToolResult(content=str(result))

        except Exception as e:
            logger.exception(f"[FSMTools] Error starting FSM: {str(e)}")
            return CommonToolResult(content=f"Failed to start FSM: {str(e)}", is_error=True)

    async def tool_confirm_state(self) -> CommonToolResult:
        """Tool implementation for confirming the current state"""
        try:
            if not self.fsm_app:
                logger.error("[FSMTools] No active FSM session")
                return CommonToolResult(content="No active FSM session", is_error=True)

            # Store previous state for comparison
            previous_state = self.fsm_app.current_state
            logger.info(f"[FSMTools] Current state before confirmation: {previous_state}")

            # Send confirm event
            logger.info("[FSMTools] Confirming current state")
            await self.fsm_app.confirm_state()
            current_state = self.fsm_app.current_state

            # Check for errors
            if (error_msg := self.fsm_app.maybe_error()):
                return CommonToolResult(content=f"FSM confirmation failed: {error_msg}", is_error=True)

            # Prepare result
            result = self.fsm_as_result()
            logger.info(f"[FSMTools] FSM advanced to state {current_state}")
            return CommonToolResult(content=str(result))

        except Exception as e:
            logger.exception(f"[FSMTools] Error confirming state: {str(e)}")
            return CommonToolResult(content=f"Failed to confirm state: {str(e)}", is_error=True)

    async def tool_provide_feedback(self, feedback: str, component_name: str | None = None) -> CommonToolResult:
        """Tool implementation for providing feedback"""
        try:
            if not self.fsm_app:
                logger.error("[FSMTools] No active FSM session")
                return CommonToolResult(content="No active FSM session", is_error=True)

            # Determine current state and feedback event type
            current_state = self.fsm_app.current_state
            logger.info(f"[FSMTools] Current state: {current_state}")

            # Handle feedback
            logger.info(f"[FSMTools] Providing feedback")
            await self.fsm_app.provide_feedback(feedback, component_name)
            new_state = self.fsm_app.current_state

            # Check for errors
            if (error_msg := self.fsm_app.maybe_error()):
                return CommonToolResult(content=f"FSM while processing feedback: {error_msg}", is_error=True)

            # Prepare result
            result = self.fsm_as_result()
            logger.info(f"[FSMTools] FSM updated with feedback, now in state {new_state}")
            return CommonToolResult(content=str(result))

        except Exception as e:
            logger.exception(f"[FSMTools] Error providing feedback: {str(e)}")
            return CommonToolResult(content=f"Failed to provide feedback: {str(e)}", is_error=True)

    async def tool_complete_fsm(self) -> CommonToolResult:
        """Tool implementation for completing the FSM and getting all artifacts"""
        try:
            if not self.fsm_app:
                logger.error("[FSMTools] No active FSM session")
                return CommonToolResult(content="No active FSM session", is_error=True)

            logger.info("[FSMTools] Completing FSM session")

            # Check for errors
            if (error_msg := self.fsm_app.maybe_error()):
                return CommonToolResult(content=f"FSM failed with error: {error_msg}", is_error=True)

            # Prepare result based on state
            result = self.fsm_as_result()
            logger.info(f"[FSMTools] FSM completed in state: {self.fsm_app.current_state}")
            return CommonToolResult(content=str(result))

        except Exception as e:
            logger.exception(f"[FSMTools] Error completing FSM: {str(e)}")
            return CommonToolResult(content=f"Failed to complete FSM: {str(e)}", is_error=True)

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
        return f"""You are a software engineering expert who can generate application code using a code generation framework. This framework uses a Finite State Machine (FSM) to guide the generation process.

Your task is to control the FSM through the following stages of code generation:
{self.fsm_class.base_execution_plan()}

To successfully complete this task, follow these steps:

1. Start a new FSM session using the start_fsm tool.
2. For each component generated by the FSM:
a. Carefully review the output.
b. Decide whether to confirm the output or provide feedback for improvement.
c. Use the appropriate tool (confirm_state or provide_feedback) based on your decision.
3. Repeat step 2 until all components have been generated and confirmed.
4. Use the complete_fsm tool to finalize the process and retrieve all artifacts.

During your review process, consider the following questions:
- Does the code correctly implement the application requirements?
- Are there any errors or inconsistencies?
- Could anything be improved or clarified?
- Does it match other requirements mentioned in the dialogue?

When providing feedback, be specific and actionable. If you're unsure about any aspect, ask for clarification before proceeding.

Do not consider the work complete until all components have been generated and the complete_fsm tool has been called.""".strip()

async def run_with_claude(processor: FSMToolProcessor, client: AsyncLLM,
                   messages: List[Message]) -> Tuple[List[Message], bool, CommonToolResult | None]:
    """
    Send messages to Claude with FSM tool definitions and process tool use responses.

    Args:
        processor: FSMToolProcessor instance with tool implementation
        client: LLM client instance
        messages: List of messages to send to Claude

    """
    response = await client.completion(
        messages=messages,
        max_tokens=1024 * 16,
        tools=processor.tool_definitions,
        system_prompt=processor.system_prompt,
    )

    # Record if any tool was used (requiring further processing)
    is_complete = False
    final_tool_result = None
    tool_results = []

    # Process all content blocks in the response
    for message in response.content:
        match message:
            case TextRaw():
                logger.info(f"[Claude Response] Message: {message.text}")
            case ToolUse():
                await processor.work_in_progress.acquire()
                tool_use_obj = message
                tool_params = message.input
                logger.info(f"[Claude Response] Tool use: {message.name}, params: {tool_params}")
                tool_method = processor.tool_mapping.get(message.name)

                if tool_method:
                    # Call the async method and await the result
                    result: CommonToolResult = await tool_method(**tool_params)
                    logger.info(f"[Claude Response] Tool result: {result.content}")


                    # Special cases for determining if the interaction is complete
                    if message.name == "complete_fsm" and not result.is_error:
                        is_complete = True
                        final_tool_result = result

                    # Add result to the tool results list
                    tool_results.append({
                        "tool": message.name,
                        "result": result
                    })
                else:
                    raise ValueError(f"Unexpected tool name: {message.name}")

                processor.work_in_progress.release()
            case _:
                raise ValueError(f"Unexpected message type: {message.type}")

    # Create new messages based on response
    new_messages = []

    # Handle tool results if any
    for result_item in tool_results:
        tool_name = result_item["tool"]
        result = result_item["result"]

        # Create a ToolUse object
        tool_use = ToolUse(name=tool_name, input={}, id=uuid.uuid4().hex)

        # Create a ToolUseResult object
        tool_use_result = ToolUseResult.from_tool_use(
            tool_use=tool_use,
            content=result.content,
            is_error=result.is_error
        )
        new_messages.append(Message(
            role="assistant",
            content=[tool_use]
        ))
        new_messages.append(Message(
            role="user",
            content=[
                tool_use_result,
                TextRaw("Please continue based on these results, addressing any failures or errors if they exist.")
            ]
        ))

    if not tool_results:
        text_responses = [msg for msg in response.content if isinstance(msg, TextRaw)]
        if text_responses:
            new_messages = [Message(
                role="assistant",
                content=text_responses
            )]

    return new_messages, is_complete, final_tool_result

async def main(initial_prompt: str = "A simple greeting app that says hello in five languages"):
    """
    Main entry point for the FSM tools module.
    Initializes an FSM tool processor and interacts with Claude.
    """
    from trpc_agent.application import FSMApplication
    logger.info("[Main] Initializing FSM tools...")
    client = get_llm_client()

    # Create processor without FSM instance - it will be created in start_fsm tool
    processor = FSMToolProcessor(FSMApplication)
    logger.info("[Main] FSM tools initialized successfully")

    # Create the initial prompt for the AI agent
    logger.info("[Main] Sending request to Claude...")
    current_messages = [
        Message(role="user", content=[TextRaw(initial_prompt)]),
    ]
    is_complete = False
    final_tool_result = None

    # Main interaction loop
    while not is_complete:
        new_messages, is_complete, final_tool_result = await run_with_claude(
            processor,
            client,
            current_messages
        )

        logger.info(f"[Main] New messages: {new_messages}")
        if new_messages:
            current_messages += new_messages

        logger.info(f"[Main] Iteration completed: {len(current_messages) - 1}")

    if final_tool_result and not final_tool_result.is_error:
        # Parse the content to extract the structured data
        logger.info(f"[Main] FSM completed with result: {final_tool_result.content}")

    logger.info("[Main] FSM interaction completed successfully")

def run_main(initial_prompt: str = "A simple greeting app that says hello in five languages"):
    anyio.run(main, initial_prompt)

if __name__ == "__main__":
    Fire(run_main)
