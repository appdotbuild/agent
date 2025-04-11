from typing import List, Dict, Any, Optional, Tuple, Protocol, runtime_checkable
import logging
import coloredlogs
import sys
import anyio
from fire import Fire
import uuid
import json
import tempfile
import os
from pathlib import Path
import ast # Use ast for safer literal evaluation

from llm.utils import get_llm_client, AsyncLLM
from llm.common import Message, ToolUse, ToolResult as CommonToolResult
from llm.common import ToolUseResult, TextRaw, Tool
from trpc_agent.application import FSMApplication, FSMEvent, FSMState
from log import get_logger
from asyncio import Lock


# Configure logging to use stderr instead of stdout
coloredlogs.install(level="INFO", stream=sys.stderr)
logger = get_logger(__name__)

@runtime_checkable
class FSMInterface(Protocol):
    """Protocol defining the interface for FSM applications that can be controlled by FSMToolProcessor"""

    @classmethod
    async def from_prompt(cls, user_input: str): ...
    async def start(self, client_callback=None): ...
    async def send_event(self, event, data=None, client_callback=None): ...
    def get_state(self): ...
    def get_context(self): ...
    def is_review_state(self) -> bool: ...
    def is_complete(self) -> bool: ...
    def is_error(self) -> bool: ...


class FSMToolProcessor:
    """
    Thin adapter that exposes FSM functionality as tools for AI agents.

    This class only contains the tool interface definitions and minimal
    logic to convert between tool calls and FSM operations. It works with
    any FSM application that implements the FSMInterface protocol.
    """

    def __init__(self, fsm_app: FSMInterface | None = None):
        """
        Initialize the FSM Tool Processor

        Args:
            fsm_app: FSM application instance to use, or None if it will be created later
        """
        self.fsm_app = fsm_app
        self.work_in_progress = Lock()

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
            self.fsm_app = await FSMApplication.from_prompt(user_prompt=app_description)

            # Start the FSM
            current_state = await self.fsm_app.start(client_callback=None)

            # Check for errors
            if current_state == FSMState.FAILURE:
                context = self.fsm_app.get_context()
                error_msg = context.error or "Unknown error"
                return CommonToolResult(content=f"FSM initialization failed: {error_msg}", is_error=True)

            # Prepare the result
            result = {
                "current_state": current_state,
                "output": self._get_state_output(),
                "available_actions": self._get_available_actions()
            }

            logger.info(f"[FSMTools] Started FSM session")
            return CommonToolResult(content=str(result))

        except Exception as e:
            logger.exception(f"[FSMTools] Error starting FSM: {str(e)}")
            return CommonToolResult(content=f"Failed to start FSM: {str(e)}", is_error=True)

    def _get_revision_event_type(self, state) -> Optional[str]:
        """Map review state to corresponding revision event type"""
        logger.debug(f"Getting revision event type for state: {state}")
        event_map = {
            FSMState.REVIEW_DRAFT: "FEEDBACK_DRAFT",
            FSMState.REVIEW_HANDLERS: "FEEDBACK_HANDLERS",
            FSMState.REVIEW_INDEX: "FEEDBACK_INDEX",
            FSMState.REVIEW_FRONTEND: "FEEDBACK_FRONTEND"
        }
        result = event_map.get(state)
        if result:
            logger.debug(f"Found revision event type: {result}")
        else:
            logger.debug(f"No revision event type found for state: {state}")
        return result

    def _get_available_actions(self) -> Dict[str, str]:
        """Get available actions for current state"""
        if not self.fsm_app:
            return {}

        current_state = self.fsm_app.get_state()
        logger.debug(f"Getting available actions for state: {current_state}")

        actions = {}
        match current_state:
            case FSMState.REVIEW_DRAFT | FSMState.REVIEW_HANDLERS | FSMState.REVIEW_INDEX | FSMState.REVIEW_FRONTEND:
                actions = {
                    "confirm": "Accept current output and continue",
                    "revise": "Provide feedback and revise"
                }
                logger.debug(f"Review state detected: {current_state}, offering confirm/revise actions")
            case FSMState.COMPLETE:
                actions = {"complete": "Finalize and get all artifacts"}
                logger.debug("FSM is in COMPLETE state, offering complete action")
            case FSMState.FAILURE:
                actions = {"get_error": "Get error details"}
                logger.debug("FSM is in FAILURE state, offering get_error action")
            case _:
                actions = {"wait": "Wait for processing to complete"}
                logger.debug(f"FSM is in processing state: {current_state}, offering wait action")

        return actions

    def _get_state_output(self) -> Dict[str, Any]:
        """Extract relevant output for the current state"""
        if not self.fsm_app:
            return {"status": "error", "message": "No active FSM session"}

        current_state = self.fsm_app.get_state()
        logger.debug(f"Getting output for state: {current_state}")

        context = self.fsm_app.get_context()

        try:
            match current_state:
                case FSMState.REVIEW_DRAFT:
                    return {
                        "draft": context.draft
                    }
                case FSMState.REVIEW_HANDLERS:
                    if context.server_files:
                        handler_files = {}
                        for filename, content in context.server_files.items():
                            if '/handlers/' in filename:
                                handler_files[filename] = content
                        return {"handlers": handler_files}
                    return {"status": "handlers_not_found"}
                case FSMState.REVIEW_INDEX:
                    if context.server_files:
                        index_files = {}
                        for filename, content in context.server_files.items():
                            if 'index.ts' in filename:
                                index_files[filename] = content
                        return {"index": index_files}
                    return {"status": "index_not_found"}
                case FSMState.REVIEW_FRONTEND:
                    return {"frontend": context.frontend_files}
                case FSMState.COMPLETE:
                    return {
                        "server_files": context.server_files,
                        "frontend_files": context.frontend_files
                    }
                case FSMState.FAILURE:
                    error_msg = context.error or "Unknown error"
                    logger.error(f"FSM failed with error: {error_msg}")
                    return {"error": error_msg}
                case _:
                    logger.debug(f"State {current_state} is a processing state, returning processing status")
                    return {"status": "processing"}
        except Exception as e:
            logger.exception(f"Error getting state output: {str(e)}")
            return {"status": "error", "message": f"Error retrieving state output: {str(e)}"}

        return {"status": "processing"}

    async def tool_confirm_state(self) -> CommonToolResult:
        """Tool implementation for confirming the current state"""
        try:
            if not self.fsm_app:
                logger.error("[FSMTools] No active FSM session")
                return CommonToolResult(content="No active FSM session", is_error=True)

            # Store previous state for comparison
            previous_state = self.fsm_app.get_state()
            logger.info(f"[FSMTools] Current state before confirmation: {previous_state}")

            # Send confirm event
            logger.info("[FSMTools] Confirming current state")
            await self.fsm_app.send_event(FSMEvent("CONFIRM"))
            current_state = self.fsm_app.get_state()

            # Check for errors
            if current_state == FSMState.FAILURE:
                context = self.fsm_app.get_context()
                error_msg = context.error or "Unknown error"
                return CommonToolResult(content=f"FSM confirmation failed: {error_msg}", is_error=True)

            # Prepare result
            result = {
                "current_state": current_state,
                "output": self._get_state_output(),
                "available_actions": self._get_available_actions()
            }

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
            current_state = self.fsm_app.get_state()
            event_type = self._get_revision_event_type(current_state)
            logger.info(f"[FSMTools] Current state: {current_state}, Revision event type: {event_type}")

            if not event_type:
                logger.error(f"[FSMTools] Cannot provide feedback for state {current_state}")
                return CommonToolResult(content=f"Cannot provide feedback for state {current_state}", is_error=True)

            # Handle feedback
            logger.info(f"[FSMTools] Providing feedback")
            await self.fsm_app.send_event(FSMEvent(event_type), data=feedback)
            new_state = self.fsm_app.get_state()

            # Check for errors
            if new_state == FSMState.FAILURE:
                context = self.fsm_app.get_context()
                error_msg = context.error or "Unknown error"
                return CommonToolResult(content=f"Error while processing feedback: {error_msg}", is_error=True)

            # Prepare result
            result = {
                "current_state": new_state,
                "output": self._get_state_output(),
                "available_actions": self._get_available_actions()
            }

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

            # Handle case when we're still in a review state
            current_state = self.fsm_app.get_state()
            if self.fsm_app.is_review_state():
                # Send a confirm event to move to the next state
                await self.fsm_app.send_event(FSMEvent("CONFIRM"))
                current_state = self.fsm_app.get_state()

            # Get context for outputs
            context = self.fsm_app.get_context()

            # Check for errors
            if current_state == FSMState.FAILURE:
                error_msg = context.error or "Unknown error"
                logger.error(f"[FSMTools] FSM failed with error: {error_msg}")
                return CommonToolResult(content=f"FSM failed: {error_msg}", is_error=True)

            # Check for empty outputs with completed state
            if current_state == FSMState.COMPLETE and not context.server_files and not context.frontend_files:
                error_msg = "FSM completed but didn't generate any artifacts"
                logger.error(f"[FSMTools] {error_msg}")
                return CommonToolResult(content=error_msg, is_error=True)

            # Prepare result based on state
            result = {}
            if current_state == FSMState.COMPLETE:
                # Include all artifacts
                result = {
                    "status": "complete",
                    "final_outputs": {
                        "server_files": context.server_files or {},
                        "frontend_files": context.frontend_files or {}
                    }
                }
            else:
                # Handle error or other states
                result = {
                    "status": "failed",
                    "error": context.error or f"Unexpected state: {current_state}"
                }

            logger.info(f"[FSMTools] FSM completed with status: {result['status']}")
            return CommonToolResult(content=str(result))

        except Exception as e:
            logger.exception(f"[FSMTools] Error completing FSM: {str(e)}")
            return CommonToolResult(content=f"Failed to complete FSM: {str(e)}", is_error=True)

    async def bake(self, app_description: str) -> Dict[str, Dict[str, str]]:
        """
        Generate application code in one go without interactive confirmation steps.
        
        Args:
            app_description: Description of the application to generate
            
        Returns:
            Dictionary containing server_files and frontend_files, or raises an error.
        Raises:
            RuntimeError: If the FSM process fails or produces no artifacts.
        """
        if self.work_in_progress.locked():
             raise RuntimeError("Cannot start baking while another FSM operation is in progress.")
             
        async with self.work_in_progress:
            try:
                logger.info(f"[FSMTools] Baking application from description: {app_description}")
                
                # Reset any existing FSM app - bake is a standalone operation
                self.fsm_app = None 
                    
                # Create a new FSM application
                # Ensure FSMApplication is correctly imported or available in scope
                self.fsm_app = await FSMApplication.from_prompt(user_prompt=app_description)
                
                # Start the FSM
                current_state = await self.fsm_app.start(client_callback=None)
                logger.info(f"[FSMTools] Initial state after start: {current_state}")

                # Check for immediate failure after start
                if self.fsm_app.is_error():
                    context = self.fsm_app.get_context()
                    error_msg = context.error or "Unknown error after start"
                    logger.error(f"[FSMTools] Baking failed immediately after start: {error_msg}")
                    raise RuntimeError(f"Application generation failed after start: {error_msg}")
                
                # Process all review states automatically by confirming
                while self.fsm_app.is_review_state():
                    logger.info(f"[FSMTools] Auto-confirming state: {self.fsm_app.get_state()}")
                    await self.fsm_app.send_event(FSMEvent("CONFIRM"))
                    current_state = self.fsm_app.get_state()
                    logger.info(f"[FSMTools] State after auto-confirm: {current_state}")
                    # Check for errors after each confirmation
                    if self.fsm_app.is_error():
                        context = self.fsm_app.get_context()
                        error_msg = context.error or f"Unknown error during state {current_state}"
                        logger.error(f"[FSMTools] Baking failed during auto-confirmation: {error_msg}")
                        raise RuntimeError(f"Application generation failed during state {current_state}: {error_msg}")

                # Final check for completion and errors
                final_state = self.fsm_app.get_state()
                if final_state != FSMState.COMPLETE:
                     context = self.fsm_app.get_context()
                     error_msg = context.error or f"Ended in unexpected state {final_state}"
                     logger.error(f"[FSMTools] Baking finished unexpectedly in state {final_state}: {error_msg}")
                     raise RuntimeError(f"Application generation finished in unexpected state {final_state}: {error_msg}")
                    
                # Get the generated artifacts
                context = self.fsm_app.get_context()
                server_files = context.server_files or {}
                frontend_files = context.frontend_files or {}
                
                if not server_files and not frontend_files:
                    error_msg = "Application generation completed but didn't produce any artifacts"
                    logger.error(f"[FSMTools] {error_msg}")
                    raise RuntimeError(error_msg)
                    
                logger.info("[FSMTools] Application baking completed successfully")
                return {
                    "server_files": server_files,
                    "frontend_files": frontend_files
                }
                
            except Exception as e:
                # Catch potential exceptions during FSM operations or state transitions
                logger.exception(f"[FSMTools] Unexpected error during baking process: {str(e)}")
                # Re-raise as a runtime error to signal failure to the caller
                raise RuntimeError(f"Error during application baking: {str(e)}") from e
            finally:
                 # Clean up the FSM instance after baking
                 self.fsm_app = None
                 logger.debug("[FSMTools] Cleaned up FSM instance after baking.")

    @property
    def system_prompt(self) -> str:
        return f"""You are a software engineering expert who can generate application code using a code generation framework. This framework uses a Finite State Machine (FSM) to guide the generation process.

Your task is to control the FSM through the following stages of code generation:
{FSMApplication.base_execution_plan}

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

Do not consider the work complete until all components have been generated and the complete_fsm tool has been called."""

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

async def _save_generated_files(server_files: Dict[str, str], frontend_files: Dict[str, str], temp_dir: str):
    """Saves the generated server and frontend files to the specified temporary directory."""
    logger.info(f"[SaveFiles] Saving generated files to temporary directory: {temp_dir}")
    
    temp_dir_path = Path(temp_dir)

    try:
        # Save server files
        server_base_path = temp_dir_path / "server"
        if server_files:
            server_base_path.mkdir(parents=True, exist_ok=True)
            for file_path, content in server_files.items():
                # Sanitize path: remove leading slashes/dots and ensure it's relative
                relative_file_path = Path(file_path.lstrip('/\\.')) 
                full_path = server_base_path / relative_file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.debug(f"[SaveFiles] Saved server file: {full_path}")
                except IOError as e:
                     logger.error(f"[SaveFiles] Error saving server file {full_path}: {e}")

        # Save frontend files
        frontend_base_path = temp_dir_path / "frontend"
        if frontend_files:
            frontend_base_path.mkdir(parents=True, exist_ok=True)
            for file_path, content in frontend_files.items():
                # Sanitize path
                relative_file_path = Path(file_path.lstrip('/\\.'))
                full_path = frontend_base_path / relative_file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.debug(f"[SaveFiles] Saved frontend file: {full_path}")
                except IOError as e:
                     logger.error(f"[SaveFiles] Error saving frontend file {full_path}: {e}")

        logger.info(f"[SaveFiles] Successfully saved {len(server_files)} server files and {len(frontend_files)} frontend files to {temp_dir}")
    except Exception as e:
        logger.exception(f"[SaveFiles] Error during file saving process in {temp_dir}: {e}")

async def main(initial_prompt: str = "A simple greeting app that says hello in five languages"):
    """
    Main entry point for the FSM tools module.
    Initializes an FSM tool processor and interacts with Claude.
    """
    logger.info("[Main] Initializing FSM tools...")
    client = get_llm_client()

    # Create processor without FSM instance - it will be created in start_fsm tool
    processor = FSMToolProcessor()
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
        logger.info(f"[Main] FSM completed successfully. Processing final result...")
        try:
            # Safely evaluate the string representation of the dictionary
            result_data = ast.literal_eval(final_tool_result.content)

            if isinstance(result_data, dict) and result_data.get("status") == "complete":
                final_outputs = result_data.get("final_outputs", {})
                server_files = final_outputs.get("server_files", {})
                frontend_files = final_outputs.get("frontend_files", {})

                if not server_files and not frontend_files:
                    logger.warning("[Main] FSM completed but no files were generated.")
                else:
                    # Create a temporary directory
                    temp_dir = tempfile.mkdtemp(prefix="fsm_generated_")
                    logger.info(f"[Main] Created temporary directory: {temp_dir}")
                    # Call the dedicated save function
                    await _save_generated_files(server_files, frontend_files, temp_dir)
            else:
                error_info = result_data.get('error', 'No error details provided') if isinstance(result_data, dict) else 'Result format not a dictionary'
                status_info = result_data.get('status', 'unknown') if isinstance(result_data, dict) else 'unknown'
                logger.error(f"[Main] FSM completed but status was not 'complete' or result format invalid. Status: {status_info}, Error: {error_info}")
                logger.debug(f"[Main] Raw content for debugging: {final_tool_result.content}")

        except (SyntaxError, ValueError, TypeError) as e:
            logger.exception(f"[Main] Failed to parse final_tool_result.content: {e}")
            logger.error(f"[Main] Raw content: {final_tool_result.content}")
        except Exception as e:
            logger.exception(f"[Main] An unexpected error occurred while processing the final result: {e}")
            
    elif final_tool_result and final_tool_result.is_error:
        logger.error(f"[Main] FSM interaction failed with error: {final_tool_result.content}")
    elif not final_tool_result:
         logger.warning("[Main] FSM interaction finished without a final result object.")
    else:
        logger.warning("[Main] FSM interaction finished, but result indicates neither success nor explicit error in the expected format.")

    logger.info("[Main] FSM interaction processing finished.")

def run_main(initial_prompt: str = "A simple greeting app that says hello in five languages"):
    anyio.run(main, initial_prompt)

if __name__ == "__main__":
    Fire(run_main)
