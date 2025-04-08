from typing import List, Dict, Any, Optional, Tuple
import logging
import coloredlogs
import sys
import anyio
from fire import Fire

from llm.utils import get_llm_client, AsyncLLM
from llm.common import Message, ToolUse, ToolResult as CommonToolResult
from llm.common import ToolUseResult, TextRaw, Tool
from api.fsm_api import FSMManager
from trpc_agent.application import FSMState as FsmState
from common import get_logger

# Configure logging to use stderr instead of stdout
coloredlogs.install(level="INFO", stream=sys.stderr)
logger = get_logger(__name__)


class FSMToolProcessor:
    """
    Thin adapter that exposes FSM functionality as tools for AI agents.

    This class only contains the tool interface definitions and minimal
    logic to convert between tool calls and FSM API calls.
    """

    def __init__(self, fsm_api: FSMManager):
        """
        Initialize the FSM Tool Processor

        Args:
            fsm_api: FSM API implementation to use
        """
        self.fsm_api = fsm_api

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
            if self.fsm_api.is_active():
                logger.warning("[FSMTools] There's an active FSM session already. Completing it before starting a new one.")
                await self.fsm_api.complete_fsm()

            result = await self.fsm_api.start_fsm(user_input=app_description)

            # Return error if result contains error
            if "error" in result:
                return CommonToolResult(content=result["error"], is_error=True)

            logger.info(f"[FSMTools] Started FSM session")
            return CommonToolResult(content=str(result))

        except Exception as e:
            logger.exception(f"[FSMTools] Error starting FSM: {str(e)}")
            return CommonToolResult(content=f"Failed to start FSM: {str(e)}", is_error=True)

    async def tool_confirm_state(self) -> CommonToolResult:
        """Tool implementation for confirming the current state"""
        try:
            if not self.fsm_api.is_active():
                logger.error("[FSMTools] No active FSM session")
                return CommonToolResult(content="No active FSM session", is_error=True)

            logger.info("[FSMTools] Confirming current state")
            result = await self.fsm_api.confirm_state()

            # Return error if result contains error
            if "error" in result:
                return CommonToolResult(content=result["error"], is_error=True)

            logger.info(f"[FSMTools] FSM advanced to state {result.get('current_state')}")
            return CommonToolResult(content=str(result))

        except Exception as e:
            logger.exception(f"[FSMTools] Error confirming state: {str(e)}")
            return CommonToolResult(content=f"Failed to confirm state: {str(e)}", is_error=True)

    async def tool_provide_feedback(self, feedback: str, component_name: str | None = None) -> CommonToolResult:
        """Tool implementation for providing feedback"""
        try:
            if not self.fsm_api.is_active():
                logger.error("[FSMTools] No active FSM session")
                return CommonToolResult(content="No active FSM session", is_error=True)

            logger.info(f"[FSMTools] Providing feedback")

            result = await self.fsm_api.provide_feedback(
                feedback=feedback,
                component_name=component_name
            )

            # Return error if result contains error
            if "error" in result:
                return CommonToolResult(content=result["error"], is_error=True)

            logger.info(f"[FSMTools] FSM updated with feedback, now in state {result.get('current_state')}")
            return CommonToolResult(content=str(result))

        except Exception as e:
            logger.exception(f"[FSMTools] Error providing feedback: {str(e)}")
            return CommonToolResult(content=f"Failed to provide feedback: {str(e)}", is_error=True)

    async def tool_complete_fsm(self) -> CommonToolResult:
        """Tool implementation for completing the FSM and getting all artifacts"""
        try:
            if not self.fsm_api.is_active():
                logger.error("[FSMTools] No active FSM session")
                return CommonToolResult(content="No active FSM session", is_error=True)

            logger.info("[FSMTools] Completing FSM session")

            result = await self.fsm_api.complete_fsm()

            # Check for errors in result
            if "error" in result:
                logger.error(f"[FSMTools] FSM completion failed with error: {result['error']}")
                return CommonToolResult(content=result["error"], is_error=True)

            # Check for silent failures
            if result.get("status") == "failed":
                error_msg = "FSM completion failed with status 'failed'"
                logger.error(f"[FSMTools] {error_msg}")
                return CommonToolResult(content=error_msg, is_error=True)

            # Check for empty outputs
            if result.get("final_outputs") == {} or not result.get("final_outputs"):
                error_msg = "FSM completed without generating any artifacts"
                logger.error(f"[FSMTools] {error_msg}")
                return CommonToolResult(content=error_msg, is_error=True)

            # Simply return the raw results
            logger.info(f"[FSMTools] FSM completed successfully")
            return CommonToolResult(content=str(result))

        except Exception as e:
            logger.exception(f"[FSMTools] Error completing FSM: {str(e)}")
            return CommonToolResult(content=f"Failed to complete FSM: {str(e)}", is_error=True)


async def run_with_claude(processor: FSMToolProcessor, client: AsyncLLM,
                   messages: List[Message]) -> Tuple[Message, bool, CommonToolResult | None]:
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
            case _:
                raise ValueError(f"Unexpected message type: {message.type}")

    # Create a single new message with all tool results
    if tool_results:
        # Convert the results to ToolUseResult objects
        formatted_results = []
        for result_item in tool_results:
            tool_name = result_item["tool"]
            result = result_item["result"]

            # Create a ToolUse object
            tool_use = ToolUse(name=tool_name, input={})

            # Create a ToolUseResult object
            tool_use_result = ToolUseResult.from_tool_use(
                tool_use=tool_use,
                content=result.content,
                is_error=result.is_error
            )

            formatted_results.append(tool_use_result)

        # Create a new Message with the tool results
        new_message = Message(
            role="user",
            content=[
                TextRaw("Tool execution results:"),
                *formatted_results,
                TextRaw("Please continue based on these results, addressing any failures or errors if they exist.")
            ]
        )

        return new_message, is_complete, final_tool_result
    else:
        # No tools were used
        return None, is_complete, final_tool_result

async def main(initial_prompt: str = "A simple greeting app that says hello in five languages"):
    """
    Main entry point for the FSM tools module.
    Initializes an FSM tool processor and interacts with Claude.
    """
    logger.info("[Main] Initializing FSM tools...")
    client = get_llm_client()
    fsm_manager = FSMManager(
        client=client,
    )
    processor = FSMToolProcessor(fsm_api=fsm_manager)
    logger.info("[Main] FSM tools initialized successfully")

    # Create the initial prompt for the AI agent
    logger.info("[Main] Sending request to Claude...")
    current_messages = [Message.from_dict({
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": f"""You are a software engineering expert who can generate application code using a code generation framework. This framework uses a Finite State Machine (FSM) to guide the generation process.

Here is the description of the application you need to generate:
<app_description>
{initial_prompt}
</app_description>

Your task is to control the FSM through the following stages of code generation:
1. Draft app design
2. Implement handlers
3. Create index file
4. Build frontend

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

Do not consider the work complete until all components have been generated and the complete_fsm tool has been called.
            """
            }
        ]
    })]
    is_complete = False
    final_tool_result = None

    # Main interaction loop
    while not is_complete:
        new_message, is_complete, final_tool_result = await run_with_claude(
            processor,
            client,
            current_messages
        )

        logger.info(f"[Main] New message: {new_message}")
        if new_message:
            current_messages.append(new_message)

        logger.info(f"[Main] Iteration completed: {len(current_messages) - 1}")

    if final_tool_result and not final_tool_result.is_error:
        # Parse the content to extract the structured data
        import json
        try:
            # Try to parse the content as JSON
            result_data = json.loads(final_tool_result.content)
            final_outputs = result_data.get("final_outputs", {})
            server_files = final_outputs.get("server_files", {})
            frontend_files = final_outputs.get("frontend_files", {})
            logger.info(f"[Main] Generated {len(server_files)} server files and {len(frontend_files)} frontend files")
        except json.JSONDecodeError:
            # If not JSON, just log the completion
            logger.info(f"[Main] FSM completed with result: {final_tool_result.content}")

    logger.info("[Main] FSM interaction completed successfully")

def run_main(initial_prompt: str = "A simple greeting app that says hello in five languages"):
    """
    Entrypoint for Fire CLI that runs the async main function
    """
    anyio.run(main, initial_prompt)

if __name__ == "__main__":
    Fire(run_main)
