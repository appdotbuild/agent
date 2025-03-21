from typing import List, Dict, Any, Optional, Tuple
import uuid
import logging
import coloredlogs
import sys
from dataclasses import dataclass
from anthropic import AnthropicBedrock
from anthropic.types import MessageParam
from fire import Fire

from fsm_api import (
    start_fsm,
    confirm_state,
    provide_feedback,
    complete_fsm, 
    is_active
)
from application import FsmState

# Configure logging to use stderr instead of stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
coloredlogs.install(level="INFO", stream=sys.stderr)
logger = logging.getLogger("FSM_TOOLS")

@dataclass
class ToolResult:
    """Result of a tool execution"""
    success: bool
    data: Dict[str, Any] = None
    error: str = None

    def to_dict(self) -> Dict[str, Any]:
        result = {"success": self.success}
        if self.data is not None:
            result["data"] = self.data
        if self.error is not None:
            result["error"] = self.error
        return result


class FSMToolProcessor:
    """Processor for FSM-related tools that can be used by AI agents"""

    def __init__(self):
        # For tracking last session updates
        self.last_update = None
        self.current_state = None

        # Define tool definitions for the AI agent
        self.tool_definitions = [
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
        self.tool_mapping = {
            "start_fsm": self.tool_start_fsm,
            "confirm_state": self.tool_confirm_state,
            "provide_feedback": self.tool_provide_feedback,
            "complete_fsm": self.tool_complete_fsm
        }

    def tool_start_fsm(self, app_description: str) -> ToolResult:
        """Tool implementation for starting a new FSM session"""
        try:
            logger.info(f"[FSMTools] Starting new FSM session with description: {app_description}")
            
            # Check if there's an active session first
            if is_active():
                logger.warning("[FSMTools] There's an active FSM session already. Completing it before starting a new one.")
                complete_fsm()
                
            result = start_fsm(user_input=app_description)
            
            # Check for any form of failure
            has_error = False
            error_msg = ""
            
            # Check for explicit errors
            if "error" in result:
                error_msg = result["error"]
                logger.error(f"[FSMTools] Error starting FSM: {error_msg}")
                has_error = True
            
            # Check state - might be failure or complete (indicates something went wrong)
            current_state = result.get("current_state")
            if current_state == "failure" or current_state == FsmState.FAILURE:
                error_msg = "FSM entered FAILURE state during initialization"
                logger.error(f"[FSMTools] {error_msg}")
                has_error = True
            elif current_state == "complete" or current_state == FsmState.COMPLETE:
                error_msg = "FSM immediately entered COMPLETE state, which indicates the process did not run properly"
                logger.error(f"[FSMTools] {error_msg}")
                has_error = True
                
            # Return error if any checks failed
            if has_error:
                return ToolResult(success=False, error=error_msg, data=result)
                
            # Success case
            self.last_update = uuid.uuid4().hex
            self.current_state = current_state
                
            logger.info(f"[FSMTools] Started FSM session")
            return ToolResult(success=True, data=result)

        except Exception as e:
            logger.error(f"[FSMTools] Error starting FSM: {str(e)}")
            return ToolResult(success=False, error=f"Failed to start FSM: {str(e)}")

    def tool_confirm_state(self) -> ToolResult:
        """Tool implementation for confirming the current state"""
        try:
            if not is_active():
                logger.error("[FSMTools] No active FSM session")
                return ToolResult(success=False, error="No active FSM session")
                
            logger.info("[FSMTools] Confirming current state")
            result = confirm_state()

            # Update session tracking
            current_state = result.get("current_state")
            
            # Check for FAILURE state or errors
            if current_state == "failure" or "error" in result:
                error_msg = result.get("error", "Unknown error occurred")
                logger.error(f"[FSMTools] FSM entered FAILURE state: {error_msg}")
                success = False
                # If we're in a failure state, include detailed error information
                if "error" not in result:
                    result["error"] = f"FSM entered FAILURE state: {error_msg}"
            else:
                self.current_state = current_state
                self.last_update = uuid.uuid4().hex
                success = True
                
            logger.info(f"[FSMTools] FSM advanced to state {current_state}")
            return ToolResult(success=success, data=result,
                             error=result.get("error"))

        except Exception as e:
            logger.error(f"[FSMTools] Error confirming state: {str(e)}")
            return ToolResult(success=False, error=f"Failed to confirm state: {str(e)}")

    def tool_provide_feedback(self, feedback: str, component_name: str = None) -> ToolResult:
        """Tool implementation for providing feedback"""
        try:
            if not is_active():
                logger.error("[FSMTools] No active FSM session")
                return ToolResult(success=False, error="No active FSM session")

            logger.info(f"[FSMTools] Providing feedback")

            result = provide_feedback(
                feedback=feedback,
                component_name=component_name
            )

            # Update session tracking
            if "error" not in result:
                self.current_state = result.get("current_state")
                self.last_update = uuid.uuid4().hex

            logger.info(f"[FSMTools] FSM updated with feedback, now in state {result.get('current_state', 'error')}")
            return ToolResult(success="error" not in result, data=result,
                             error=result.get("error"))

        except Exception as e:
            logger.error(f"[FSMTools] Error providing feedback: {str(e)}")
            return ToolResult(success=False, error=f"Failed to provide feedback: {str(e)}")

    def tool_complete_fsm(self) -> ToolResult:
        """Tool implementation for completing the FSM and getting all artifacts"""
        try:
            if not is_active():
                logger.error("[FSMTools] No active FSM session")
                return ToolResult(success=False, error="No active FSM session")

            logger.info("[FSMTools] Completing FSM session")

            result = complete_fsm()

            # Check for both explicit errors and "silent failures"
            if "error" in result:
                logger.error(f"[FSMTools] FSM completion failed with error: {result['error']}")
                success = False
            elif result.get("status") == "failed":
                logger.error("[FSMTools] FSM completion failed with status 'failed'")
                success = False
            elif result.get("final_outputs") == {} or not result.get("final_outputs"):
                # Empty outputs typically indicate a failure
                error_msg = "FSM completed without generating any artifacts"
                logger.error(f"[FSMTools] {error_msg}")
                result["error"] = error_msg
                result["status"] = "failed" 
                success = False
            else:
                # Success case
                self.current_state = None
                self.last_update = None
                success = True

            logger.info(f"[FSMTools] FSM completed with status {result.get('status', 'error')}")
            return ToolResult(success=success, data=result,
                             error=result.get("error"))

        except Exception as e:
            logger.error(f"[FSMTools] Error completing FSM: {str(e)}")
            return ToolResult(success=False, error=f"Failed to complete FSM: {str(e)}")

def run_with_claude(processor: FSMToolProcessor, client: AnthropicBedrock,
                   messages: List[MessageParam]) -> Tuple[List[MessageParam], bool]:
    """
    Send messages to Claude with FSM tool definitions and process tool use responses.

    Args:
        processor: FSMToolProcessor instance with tool implementation
        client: AnthropicBedrock client instance
        messages: List of messages to send to Claude

    Returns:
        Tuple of (followup_messages, is_complete)
    """
    response = client.messages.create(
        messages=messages,
        max_tokens=1024 * 16,
        model="anthropic.claude-3-5-haiku-20241022-v1:0",
        stream=False,
        tools=processor.tool_definitions,
    )

    # Record if any tool was used (requiring further processing)
    is_complete = True
    tool_results = []

    # Process all content blocks in the response
    for message in response.content:
        if message.type == "text":
            is_complete = True  # No tools used, so the task is complete
            logger.info(f"[Claude Response] Message: {message.text}")
        elif message.type == "tool_use":
            is_complete = False  # Tool was used, so we need to continue
            tool_use = message.to_dict()
            logger.info(f"[Claude Response] Tool use: {tool_use['name']}")

            tool_params = tool_use['input']
            tool_method = processor.tool_mapping.get(tool_use['name'])

            if tool_method:
                result = tool_method(**tool_params)
                logger.info(f"[Claude Response] Tool result: {result.to_dict()}")

                # Check if the tool execution failed
                if not result.success:
                    logger.error(f"[Claude Response] Tool {tool_use['name']} failed: {result.error}")
                    # For tool failures, we should return the error information but still consider
                    # the interaction complete to prevent loops
                    is_complete = True

                # Special cases for determining if the interaction is complete
                if tool_use["name"] == "complete_fsm" and result.success:
                    is_complete = True

                # Add result to the tool results list
                tool_results.append({
                    "tool": tool_use['name'],
                    "result": result.to_dict()
                })
            else:
                logger.error(f"[Claude Response] Unknown tool: {tool_use['name']}")
                tool_results.append({
                    "tool": tool_use['name'],
                    "result": {"success": False, "error": f"Unknown tool '{tool_use['name']}'"}
                })

    # Create a single new message with all tool results
    if tool_results:
        # Format the tool results nicely
        formatted_results = []
        for result in tool_results:
            tool_name = result["tool"]
            tool_result = result["result"]
            
            # Explicitly check for success and failure conditions
            # A result might claim success but contain error data
            success = tool_result.get("success", False)
            if "data" in tool_result and tool_result["data"]:
                data = tool_result["data"]
                if "error" in data or data.get("status") == "failed":
                    success = False
                    
            status = "SUCCESS" if success else "FAILURE"
            
            result_str = f"Tool: {tool_name} - Status: {status}\n"
            
            # Handle error cases
            if not success:
                # For failures, always show the error prominently
                if "error" in tool_result:
                    result_str += f"Error: {tool_result['error']}\n"
                
                # Include data even for failures to help with debugging
                if "data" in tool_result and tool_result["data"]:
                    data = tool_result["data"]
                    if "error" in data:
                        result_str += f"Detailed error: {data['error']}\n"
                    if "current_state" in data:
                        result_str += f"Current state: {data['current_state']}\n"
                    
                # Add guidance for failures
                if tool_name == "start_fsm":
                    result_str += "Guidance: The FSM initialization failed. Please analyze the error and report it. Consider restarting with a simpler app description.\n"
                elif tool_name == "confirm_state":
                    result_str += "Guidance: The state transition failed. Please analyze the error and report it. The FSM encountered an error while processing.\n"
                elif tool_name == "provide_feedback":
                    result_str += "Guidance: The feedback could not be processed. Please analyze the error and report it.\n"
            else:
                # Success cases
                if "data" in tool_result and tool_result["data"]:
                    data = tool_result["data"]
                    if "current_state" in data:
                        result_str += f"Current state: {data['current_state']}\n"
                    if "status" in data:
                        result_str += f"Status: {data['status']}\n"
                    # Still show errors even for "successful" operations if they exist in the data
                    if "error" in data:
                        result_str += f"Warning: Operation succeeded but returned error: {data['error']}\n"
            
            formatted_results.append(result_str)
        
        results_text = "\n\n".join(formatted_results)
        
        # Add a summary of errors at the top for easy reference
        has_errors = any(not result["result"].get("success", True) for result in tool_results)
        
        if has_errors:
            error_summary = "❌ ERRORS DETECTED: The FSM encountered critical errors:\n"
            for result in tool_results:
                if not result["result"].get("success", True):
                    tool_name = result["tool"]
                    error = result["result"].get("error", "Unknown error")
                    error_summary += f"- {tool_name}: {error}\n"
            error_summary += "\nThis indicates issues with the FSM that must be fixed before proceeding.\n\n"
            results_text = error_summary + results_text
        
        new_message = {
            "role": "user",
            "content": f"Tool execution results:\n\n{results_text}\n\nPlease continue based on these results, addressing any failures or errors if they exist."
        }
        return messages + [new_message], is_complete
    else:
        # No tools were used
        return messages, is_complete

def main(initial_prompt: str = "A simple greeting app that says hello in five languages"):
    """
    Main entry point for the FSM tools module.
    Initializes an FSM tool processor and interacts with Claude.
    """
    logger.info("[Main] Initializing FSM tools...")
    client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
    processor = FSMToolProcessor()
    logger.info("[Main] FSM tools initialized successfully")

    # Create the initial prompt for the AI agent

    logger.info("[Main] Sending request to Claude...")
    current_messages = [{
        "role": "user",
        "content": f"""You are a software engineering expert who can generate application code using a code generation framework. This framework uses a Finite State Machine (FSM) to guide the generation process.

Your task is to control the FSM through the generation process for this application:

<app_description>
{initial_prompt}
</app_description>

To do this, you should:
1. First, start a new FSM session using the start_fsm tool
2. Review each output at every stage
3. Either:
   - Confirm the output if it looks good (using confirm_state)
   - OR provide feedback to improve it (using provide_feedback)
4. Once complete, use complete_fsm to get all artifacts

The FSM generates these components in sequence:
- TypeSpec schema (API specification)
- Drizzle schema (database models)
- TypeScript types and interfaces
- Handler test files
- Handler implementation files

Be thoughtful in your reviews. Look for:
- Does the code correctly implement the app requirements?
- Are there any errors or inconsistencies?
- Could anything be improved or clarified?
- Does it match other requirements mentioned in the dialogue?

Provide specific, actionable feedback when requesting revisions.

When in doubt, you show ask for clarification or more information and later continue guiding the FSM based on the new information.
        """
    }]
    is_complete = False

    # Main interaction loop
    while not is_complete:
        current_messages, is_complete = run_with_claude(
            processor,
            client,
            current_messages
        )
        logger.info(f"[Main] Iteration completed: {len(current_messages) - 1}")

    logger.info("[Main] FSM interaction completed successfully")

if __name__ == "__main__":
    Fire(main)