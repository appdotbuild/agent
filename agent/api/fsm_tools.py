from typing import List, Dict, Any, Optional, Tuple, TypedDict
import logging
import coloredlogs
import sys
from dataclasses import dataclass
from anthropic.types import MessageParam
from fire import Fire
import jinja2
from fsm_core.llm_common import LLMClient, get_sync_client

from api.fsm_api import FSMManager
from application import FsmState, Application
from core.datatypes import ApplicationOut
from core.interpolator import Interpolator
from common import get_logger

# Configure logging to use stderr instead of stdout
coloredlogs.install(level="INFO", stream=sys.stderr)
logger = get_logger(__name__)


@dataclass
class ToolResult:
    """Result of a tool execution"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self):
        result = {"success": self.success}
        if self.data is not None:
            result["data"] = self.data
        if self.error is not None:
            result["error"] = self.error
        return result


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

    def tool_start_fsm(self, app_description: str) -> ToolResult:
        """Tool implementation for starting a new FSM session"""
        try:
            logger.info(f"[FSMTools] Starting new FSM session with description: {app_description}")

            # Check if there's an active session first
            if self.fsm_api.is_active():
                logger.warning("[FSMTools] There's an active FSM session already. Completing it before starting a new one.")
                self.fsm_api.complete_fsm()

            result = self.fsm_api.start_fsm(user_input=app_description)

            # Return error if result contains error
            if "error" in result:
                return ToolResult(success=False, error=result["error"], data=result)

            logger.info(f"[FSMTools] Started FSM session")
            return ToolResult(success=True, data=result)

        except Exception as e:
            logger.exception(f"[FSMTools] Error starting FSM: {str(e)}")
            return ToolResult(success=False, error=f"Failed to start FSM: {str(e)}")

    def tool_confirm_state(self) -> ToolResult:
        """Tool implementation for confirming the current state"""
        try:
            if not self.fsm_api.is_active():
                logger.error("[FSMTools] No active FSM session")
                return ToolResult(success=False, error="No active FSM session")

            logger.info("[FSMTools] Confirming current state")
            result = self.fsm_api.confirm_state()

            # Return error if result contains error
            if "error" in result:
                return ToolResult(success=False, error=result["error"], data=result)

            logger.info(f"[FSMTools] FSM advanced to state {result.get('current_state')}")
            return ToolResult(success=True, data=result)

        except Exception as e:
            logger.exception(f"[FSMTools] Error confirming state: {str(e)}")
            return ToolResult(success=False, error=f"Failed to confirm state: {str(e)}")

    def tool_provide_feedback(self, feedback: str, component_name: str = None) -> ToolResult:
        """Tool implementation for providing feedback"""
        try:
            if not self.fsm_api.is_active():
                logger.error("[FSMTools] No active FSM session")
                return ToolResult(success=False, error="No active FSM session")

            logger.info(f"[FSMTools] Providing feedback")

            result = self.fsm_api.provide_feedback(
                feedback=feedback,
                component_name=component_name
            )

            # Return error if result contains error
            if "error" in result:
                return ToolResult(success=False, error=result["error"], data=result)

            logger.info(f"[FSMTools] FSM updated with feedback, now in state {result.get('current_state')}")
            return ToolResult(success=True, data=result)

        except Exception as e:
            logger.exception(f"[FSMTools] Error providing feedback: {str(e)}")
            return ToolResult(success=False, error=f"Failed to provide feedback: {str(e)}")

    def tool_complete_fsm(self) -> ToolResult:
        """Tool implementation for completing the FSM and getting all artifacts"""
        try:
            if not self.fsm_api.is_active():
                logger.error("[FSMTools] No active FSM session")
                return ToolResult(success=False, error="No active FSM session")

            logger.info("[FSMTools] Completing FSM session")

            result = self.fsm_api.complete_fsm()

            # Check for errors in result
            if "error" in result:
                logger.error(f"[FSMTools] FSM completion failed with error: {result['error']}")
                return ToolResult(success=False, error=result["error"], data=result)

            # Check for silent failures
            if result.get("status") == "failed":
                error_msg = "FSM completion failed with status 'failed'"
                logger.error(f"[FSMTools] {error_msg}")
                return ToolResult(success=False, error=error_msg, data=result)

            # Check for empty outputs
            if result.get("final_outputs") == {} or not result.get("final_outputs"):
                error_msg = "FSM completed without generating any artifacts"
                logger.error(f"[FSMTools] {error_msg}")
                return ToolResult(success=False, error=error_msg, data=result)

            # Convert the result to an ApplicationOut object for consistent output format
            final_output = ApplicationOut.from_context(self.fsm_api.fsm_instance.context)

            # Include both the raw result and the structured output
            result["application_out"] = final_output

            logger.info(f"[FSMTools] FSM completed successfully")
            return ToolResult(success=True, data=result)

        except Exception as e:
            logger.exception(f"[FSMTools] Error completing FSM: {str(e)}")
            return ToolResult(success=False, error=f"Failed to complete FSM: {str(e)}")


def run_with_claude(processor: FSMToolProcessor, client: LLMClient,
                   messages: List[MessageParam]) -> Tuple[MessageParam, bool, ToolResult | None]:
    """
    Send messages to Claude with FSM tool definitions and process tool use responses.

    Args:
        processor: FSMToolProcessor instance with tool implementation
        client: LLM client instance
        messages: List of messages to send to Claude

    """
    response = client.messages.create(
        messages=messages,
        max_tokens=1024 * 16,
        stream=False,
        tools=processor.tool_definitions,
    )

    # Record if any tool was used (requiring further processing)
    is_complete = False
    final_tool_result = None
    tool_results = []

    # Process all content blocks in the response
    for message in response.content:
        match message.type:
            case "text":
                logger.info(f"[Claude Response] Message: {message.text}")
            case "tool_use":
                tool_use = message.to_dict()

                tool_params = tool_use['input']
                logger.info(f"[Claude Response] Tool use: {tool_use['name']}, params: {tool_params}")
                tool_method = processor.tool_mapping.get(tool_use['name'])

                if tool_method:
                    result: ToolResult = tool_method(**tool_params)
                    logger.info(f"[Claude Response] Tool result: {result.to_dict()}")

                    # Special cases for determining if the interaction is complete
                    if tool_use["name"] == "complete_fsm" and result.success:
                        is_complete = True
                        final_tool_result = result

                    # Add result to the tool results list
                    tool_results.append({
                        "tool": tool_use['name'],
                        "result": result
                    })
                else:
                    raise ValueError(f"Unexpected tool name: {tool_use['name']}")
            case _:
                raise ValueError(f"Unexpected message type: {message.type}")

    # Create a single new message with all tool results
    if tool_results:
        _template = """
        <tool>
        {{ tool_name }}
        </tool>
        {% if data %}
        <result>
        {{ data | safe }}
        </result>
        {% endif %}
        {% if error %}
        <error>
        {{ error }}
        </error>
        {% endif %}
        """.rstrip()
        template = jinja2.Template(_template)
        # Format the tool results nicely
        formatted_results = []
        for result in tool_results:
            tool_name = result["tool"]
            tool_result: ToolResult = result["result"]

            is_success = tool_result.success
            data = tool_result.data
            error = tool_result.error
            formatted_results.append(template.render(tool_name=tool_name, data=data, error=error))

        new_message = {
            "role": "user",
            "content": f"Tool execution results:\n{'\n'.join(formatted_results)}\nPlease continue based on these results, addressing any failures or errors if they exist."
        }
        return new_message, is_complete, final_tool_result
    else:
        # No tools were used
        return None, is_complete, final_tool_result

def main(initial_prompt: str = "A simple greeting app that says hello in five languages"):
    """
    Main entry point for the FSM tools module.
    Initializes an FSM tool processor and interacts with Claude.
    """
    logger.info("[Main] Initializing FSM tools...")
    client = get_sync_client()
    fsm_manager = FSMManager(
        client=client,
    )
    processor = FSMToolProcessor(fsm_api=fsm_manager)
    logger.info("[Main] FSM tools initialized successfully")

    # Create the initial prompt for the AI agent
    logger.info("[Main] Sending request to Claude...")
    current_messages = [{
        "role": "user",
        "content": f"""You are a software engineering expert who can generate application code using a code generation framework. This framework uses a Finite State Machine (FSM) to guide the generation process.

Here is the description of the application you need to generate:
<app_description>
{initial_prompt}
</app_description>

Your task is to control the FSM through the following stages of code generation:
1. TypeSpec schema (API specification)
2. Drizzle schema (database models)
3. TypeScript types and interfaces
4. Handler test files
5. Handler implementation files

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

Do not consider the work complete until all five components (TypeSpec schema, Drizzle schema, TypeScript types and interfaces, handler test files, and handler implementation files) have been generated and the complete_fsm tool has been called.
        """
    }]
    is_complete = False
    final_tool_result = None

    # Main interaction loop
    while not is_complete:
        new_message, is_complete, final_tool_result = run_with_claude(
            processor,
            client,
            current_messages
        )
        
        logger.info(f"[Main] New message: {new_message}")
        if new_message:
            current_messages = current_messages + [new_message]

        # breaking for test purposes
        if len(current_messages) < 3 and "typespec_review" in current_messages[-1]["content"]:
            current_messages[-1]["content"] += "<errors>Too many handlers, one should be removed</errors>"

        logger.info(f"[Main] Iteration completed: {len(current_messages) - 1}")

    app_out = final_tool_result.data["application_out"]
    interpolator = Interpolator()
    interpolator.bake(app_out, "/tmp/output_dir")
    logger.info("[Main] FSM interaction completed successfully")

if __name__ == "__main__":
    Fire(main)
