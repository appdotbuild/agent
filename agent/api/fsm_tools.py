from typing import Awaitable, Callable, Self, Protocol, runtime_checkable, Dict, Any
import coloredlogs
import sys
import anyio
from fire import Fire

from core.application import ApplicationBase
from llm.utils import AsyncLLM
from llm.common import Message, ToolUse, ToolResult as CommonToolResult
from llm.common import ToolUseResult, TextRaw, Tool
from log import get_logger


# Configure logging to use stderr instead of stdout
coloredlogs.install(level="INFO", stream=sys.stderr)
logger = get_logger(__name__)


@runtime_checkable
class FSMInterface(ApplicationBase, Protocol):
    @classmethod
    async def start_fsm(cls, user_prompt: str, settings: Dict[str, Any]) -> Self: ...
    async def confirm_state(self): ...
    async def provide_feedback(self, feedback: str, component_name: str): ...
    async def complete_fsm(self): ...
    @classmethod
    def base_execution_plan(cls) -> str: ...
    @property
    def available_actions(self) -> dict[str, str]: ...# FSMTools Specific


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
        self.tool_mapping: dict[str, Callable[..., Awaitable[CommonToolResult]]] = {
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

            self.fsm_app = await self.fsm_class.start_fsm(user_prompt=app_description, settings=self.settings)

            # Check for errors
            if (error_msg := self.fsm_app.maybe_error()):
                return CommonToolResult(content=f"FSM initialization failed: {error_msg}", is_error=True)

            # Prepare the result
            result = self.fsm_as_result()
            logger.info("[FSMTools] Started FSM session")
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

    async def tool_provide_feedback(self, feedback: str, component_name: str) -> CommonToolResult:
        """Tool implementation for providing feedback"""
        try:
            if not self.fsm_app:
                logger.error("[FSMTools] No active FSM session")
                return CommonToolResult(content="No active FSM session", is_error=True)

            # Determine current state and feedback event type
            current_state = self.fsm_app.current_state
            logger.info(f"[FSMTools] Current state: {current_state}")

            # Handle feedback
            logger.info("[FSMTools] Providing feedback")
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

    async def step(self, messages: list[Message], llm: AsyncLLM, model_params: dict) -> list[Message]:
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
                    logger.info(f"[Claude Response] Message: {text}")
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
                            logger.info(f"[Claude Response] Tool result: {result.content}")
                            tool_results.append(ToolUseResult.from_tool_use(
                                tool_use=block,
                                content=result.content
                            ))
                        case _:
                            raise RuntimeError(f"Invalid tool call: {block}")
        thread = [Message(role="assistant", content=response.content)]
        if tool_results:
            thread.append(Message(role="user", content=[
                *tool_results,
                TextRaw("Please continue based on these results, addressing any failures or errors if they exist.")
            ]))
        return thread

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
        
    async def bake(self, app_description: str, temp_dir: str = None) -> dict:
        """
        Generate an application in one go without interactive confirmation steps.
        
        This method handles the entire process of creating an FSM application:
        1. Initializes the FSM with the app description
        2. Automatically confirms each state
        3. Saves all generated files to a temporary directory
        4. Returns the final state and output
        
        Args:
            app_description: Description of the application to generate
            temp_dir: Optional path to save generated files (uses tempfile if None)
            
        Returns:
            Dictionary with final state, output, and paths to generated files
        """
        import tempfile
        
        try:
            logger.info(f"[FSMTools] Baking application with description: {app_description}")
            
            # Create temp directory if not provided
            if not temp_dir:
                temp_dir = tempfile.mkdtemp(prefix="fsm_bake_")
                logger.info(f"[FSMTools] Created temporary directory: {temp_dir}")
            
            self.fsm_app = await self.fsm_class.start_fsm(user_prompt=app_description, settings=self.settings)
            
            # Check for errors
            if (error_msg := self.fsm_app.maybe_error()):
                return {"error": f"FSM initialization failed: {error_msg}"}
            
            while True:
                current_state = self.fsm_app.current_state
                logger.info(f"[FSMTools] Processing state: {current_state}")
                
                if current_state == "complete" or "complete" in current_state.lower():
                    logger.info("[FSMTools] Reached terminal state, baking complete")
                    break
                
                await self.fsm_app.confirm_state()
                
                # Check for errors after confirmation
                if (error_msg := self.fsm_app.maybe_error()):
                    return {"error": f"FSM confirmation failed at state {current_state}: {error_msg}"}
                
                if self.fsm_app.current_state == current_state:
                    logger.warning(f"[FSMTools] State didn't change after confirmation: {current_state}")
                    await self.fsm_app.confirm_state()
                    if self.fsm_app.current_state == current_state:
                        return {"error": f"FSM stuck in state {current_state}"}
            
            file_paths = await self._save_generated_files(temp_dir)
            
            # Prepare final result
            result = {
                "current_state": self.fsm_app.current_state,
                "output": self.fsm_app.state_output,
                "file_paths": file_paths,
                "temp_dir": temp_dir
            }
            
            logger.info(f"[FSMTools] Baking completed successfully with {len(file_paths)} files")
            return result
            
        except Exception as e:
            logger.exception(f"[FSMTools] Error during baking: {str(e)}")
            return {"error": f"Failed to bake application: {str(e)}"}
    
    async def _save_generated_files(self, output_dir: str) -> dict:
        """
        Save all generated files from the FSM to the specified directory.
        
        Args:
            output_dir: Directory to save files to
            
        Returns:
            Dictionary mapping file names to their full paths
        """
        import os
        import json
        
        if not self.fsm_app:
            raise RuntimeError("No active FSM session")
        
        file_paths = {}
        
        try:
            os.makedirs(output_dir, exist_ok=True)
            
            state_output = self.fsm_app.state_output
            
            if isinstance(state_output, dict):
                if "files" in state_output:
                    files = state_output["files"]
                    for file_name, content in files.items():
                        file_path = os.path.join(output_dir, file_name)
                        os.makedirs(os.path.dirname(file_path), exist_ok=True)
                        
                        with open(file_path, "w") as f:
                            f.write(content)
                        
                        file_paths[file_name] = file_path
                        logger.info(f"[FSMTools] Saved file: {file_path}")
                
                if "server_template" in state_output:
                    server_dir = os.path.join(output_dir, "server")
                    os.makedirs(server_dir, exist_ok=True)
                    
                    for file_name, content in state_output["server_template"].items():
                        file_path = os.path.join(server_dir, file_name)
                        os.makedirs(os.path.dirname(file_path), exist_ok=True)
                        
                        with open(file_path, "w") as f:
                            f.write(content)
                        
                        file_paths[f"server/{file_name}"] = file_path
                        logger.info(f"[FSMTools] Saved server file: {file_path}")
                
                if "frontend_template" in state_output:
                    frontend_dir = os.path.join(output_dir, "frontend")
                    os.makedirs(frontend_dir, exist_ok=True)
                    
                    for file_name, content in state_output["frontend_template"].items():
                        file_path = os.path.join(frontend_dir, file_name)
                        os.makedirs(os.path.dirname(file_path), exist_ok=True)
                        
                        with open(file_path, "w") as f:
                            f.write(content)
                        
                        file_paths[f"frontend/{file_name}"] = file_path
                        logger.info(f"[FSMTools] Saved frontend file: {file_path}")
            
            metadata_path = os.path.join(output_dir, "fsm_metadata.json")
            with open(metadata_path, "w") as f:
                json.dump({
                    "file_count": len(file_paths),
                    "files": list(file_paths.keys()),
                    "state": self.fsm_app.current_state
                }, f, indent=2)
            
            file_paths["fsm_metadata.json"] = metadata_path
            logger.info(f"[FSMTools] Saved metadata: {metadata_path}")
            
            return file_paths
            
        except Exception as e:
            logger.exception(f"[FSMTools] Error saving generated files: {str(e)}")
            return {"error": str(e)}


async def main(initial_prompt: str = "A simple greeting app that says hello in five languages"):
    """
    Main entry point for the FSM tools module.
    Initializes an FSM tool processor and interacts with Claude.
    """
    import os
    import dagger
    from trpc_agent.application import FSMApplication
    from llm.utils import get_llm_client
    logger.info("[Main] Initializing FSM tools...")
    client = get_llm_client()
    model_params = {"max_tokens": 8192 }

    # Create processor without FSM instance - it will be created in start_fsm tool
    #fsm_app = await FSMApplication.start
    processor = FSMToolProcessor(FSMApplication)
    logger.info("[Main] FSM tools initialized successfully")

    # Create the initial prompt for the AI agent
    logger.info("[Main] Sending request to Claude...")
    current_messages = [
        Message(role="user", content=[TextRaw(initial_prompt)]),
    ]

    async with dagger.connection(dagger.Config(log_output=open(os.devnull, "w"))):
        # Main interaction loop
        while True:
            new_messages = await processor.step(current_messages, client, model_params)

            logger.info(f"[Main] New messages: {new_messages}")
            if new_messages:
                current_messages += new_messages

            logger.info(f"[Main] Iteration completed: {len(current_messages) - 1}")

            break # Early out until feedback is wired to component name

    logger.info("[Main] FSM interaction completed successfully")
    return new_messages

def run_main(initial_prompt: str = "A simple greeting app that says hello in five languages and stores history of greetings"):
    return anyio.run(main, initial_prompt)

if __name__ == "__main__":
    Fire(run_main)
