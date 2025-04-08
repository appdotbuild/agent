import os
import anyio
import logging
import uuid
import enum
from typing import Dict, Any, List, TypedDict, NotRequired, Optional

from statemachine import StateMachine, State, Actor
from models.anthropic_bedrock import AnthropicBedrockLLM
from anthropic import AsyncAnthropicBedrock
from workspace import Workspace
from trpc_agent import DraftActor, HandlersActor, IndexActor, FrontendActor
import dagger

# Set up logging
logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)
for package in ['urllib3', 'httpx', 'google_genai.models']:
    logging.getLogger(package).setLevel(logging.WARNING)


class FSMState(str, enum.Enum):
    DRAFT = "draft"
    REVIEW_DRAFT = "review_draft"
    HANDLERS = "handlers"
    REVIEW_HANDLERS = "review_handlers"
    INDEX = "index"
    REVIEW_INDEX = "review_index"
    FRONTEND = "frontend"
    REVIEW_FRONTEND = "review_frontend"
    COMPLETE = "complete"
    FAILURE = "failure"


class FSMEvent(str, enum.Enum):
    START = "START"
    PROMPT = "PROMPT"
    CONFIRM = "CONFIRM"
    FEEDBACK_DRAFT = "FEEDBACK_DRAFT"
    FEEDBACK_HANDLERS = "FEEDBACK_HANDLERS"
    FEEDBACK_INDEX = "FEEDBACK_INDEX"
    FEEDBACK_FRONTEND = "FEEDBACK_FRONTEND"


class ApplicationContext(TypedDict):
    """Context for the fullstack application state machine"""
    user_prompt: str
    draft: NotRequired[str]
    draft_feedback: NotRequired[str]
    handlers_feedback: NotRequired[Dict[str, str]]
    index_feedback: NotRequired[str]
    frontend_feedback: NotRequired[str]
    server_files: NotRequired[Dict[str, str]]
    frontend_files: NotRequired[Dict[str, str]]
    error: NotRequired[str]


class FSMApplication:
    def __init__(self):
        self.workspace = None
        self.backend_workspace = None
        self.frontend_workspace = None
        self.m_client = None
        self.model_params = {
            "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            "max_tokens": 8192,
        }
        self.context = None
        self.draft_actor = None
        self.handlers_actor = None
        self.index_actor = None
        self.front_actor = None
        self.fsm = None
        self.current_state = FSMState.DRAFT

    async def initialize(self):
        self.workspace = await Workspace.create(
            base_image="oven/bun:1.2.5-alpine",
            context=dagger.dag.host().directory("./prefabs/trpc_fullstack"),
            setup_cmd=[["bun", "install"]],
        )
        self.backend_workspace = self.workspace.clone().cwd("/app/server")
        self.frontend_workspace = self.workspace.clone().cwd("/app/client")

        # Set up LLM client
        self.m_client = AnthropicBedrockLLM(AsyncAnthropicBedrock(aws_profile="dev", aws_region="us-west-2"))

        # Create actors
        self.draft_actor = DraftActor(self.m_client, self.backend_workspace.clone(), self.model_params)
        self.handlers_actor = HandlersActor(self.m_client, self.backend_workspace.clone(), self.model_params, beam_width=3)
        self.index_actor = IndexActor(self.m_client, self.backend_workspace.clone(), self.model_params, beam_width=3)
        self.front_actor = FrontendActor(self.m_client, self.frontend_workspace.clone(), self.model_params, beam_width=1, max_depth=20)

    def create_fsm(self, user_prompt: str):
        """Create the state machine for the application"""
        # Create the initial context
        self.context: ApplicationContext = {"user_prompt": user_prompt}

        # Define actions to update context
        async def update_server_files(ctx: ApplicationContext, result: Any) -> None:
            """Update server files in context from actor result"""
            logger.info("Updating server files from result")
            if hasattr(result, "get_trajectory"):
                for node in result.get_trajectory():
                    if hasattr(node.data, "files") and node.data.files:
                        if "server_files" not in ctx:
                            ctx["server_files"] = {}
                        ctx["server_files"].update(node.data.files)

        async def update_frontend_files(ctx: ApplicationContext, result: Any) -> None:
            """Update frontend files in context from actor result"""
            logger.info("Updating frontend files from result")
            if hasattr(result, "get_trajectory"):
                for node in result.get_trajectory():
                    if hasattr(node.data, "files") and node.data.files:
                        ctx["frontend_files"] = node.data.files

        async def update_draft(ctx: ApplicationContext, result: Any) -> None:
            """Update the draft in context"""
            logger.info("Updating draft in context")
            if hasattr(result, "get_trajectory"):
                draft_content = ""
                for node in result.get_trajectory():
                    if hasattr(node.data, "files") and node.data.files:
                        draft_content = "\n".join(node.data.files.values())
                ctx["draft"] = draft_content

        async def set_error(ctx: ApplicationContext, error: Exception) -> None:
            """Set error in context"""
            logger.error(f"Setting error in context: {error}")
            ctx["error"] = str(error)

        # Define state machine states
        states: State[ApplicationContext] = {
            "states": {
                FSMState.DRAFT: {
                    "invoke": {
                        "src": self.draft_actor,
                        "input_fn": lambda ctx: (ctx.get("draft_feedback", ctx["user_prompt"]),),
                        "on_done": {
                            "target": FSMState.REVIEW_DRAFT,
                            "actions": [update_server_files, update_draft],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    }
                },
                FSMState.REVIEW_DRAFT: {
                    "on": {
                        FSMEvent.CONFIRM: FSMState.HANDLERS,
                        FSMEvent.FEEDBACK_DRAFT: FSMState.DRAFT,
                    }
                },
                FSMState.HANDLERS: {
                    "invoke": {
                        "src": self.handlers_actor,
                        "input_fn": lambda ctx: (ctx["server_files"],),
                        "on_done": {
                            "target": FSMState.REVIEW_HANDLERS,
                            "actions": [update_server_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    }
                },
                FSMState.REVIEW_HANDLERS: {
                    "on": {
                        FSMEvent.CONFIRM: FSMState.INDEX,
                        FSMEvent.FEEDBACK_HANDLERS: FSMState.HANDLERS,
                    }
                },
                FSMState.INDEX: {
                    "invoke": {
                        "src": self.index_actor,
                        "input_fn": lambda ctx: (ctx["server_files"],),
                        "on_done": {
                            "target": FSMState.REVIEW_INDEX,
                            "actions": [update_server_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    }
                },
                FSMState.REVIEW_INDEX: {
                    "on": {
                        FSMEvent.CONFIRM: FSMState.FRONTEND,
                        FSMEvent.FEEDBACK_INDEX: FSMState.INDEX,
                    }
                },
                FSMState.FRONTEND: {
                    "invoke": {
                        "src": self.front_actor,
                        "input_fn": lambda ctx: (ctx["user_prompt"], ctx["server_files"]),
                        "on_done": {
                            "target": FSMState.REVIEW_FRONTEND,
                            "actions": [update_frontend_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    }
                },
                FSMState.REVIEW_FRONTEND: {
                    "on": {
                        FSMEvent.CONFIRM: FSMState.COMPLETE,
                        FSMEvent.FEEDBACK_FRONTEND: FSMState.FRONTEND,
                    }
                },
                FSMState.COMPLETE: {
                    # Terminal success state
                },
                FSMState.FAILURE: {
                    # Terminal failure state
                }
            },
            "on": {
                FSMEvent.START: FSMState.DRAFT,
                FSMEvent.PROMPT: FSMState.DRAFT
            }
        }

        # Create the state machine
        logger.info("Creating state machine")
        self.fsm = StateMachine[ApplicationContext](states, self.context)
        self.current_state = FSMState.DRAFT

    async def start(self, user_prompt: str):
        """Start the FSM with a prompt"""
        if not self.draft_actor:
            await self.initialize()

        self.create_fsm(user_prompt)

        # Start the FSM
        logger.info("Starting FSM with prompt")
        try:
            await self.fsm.send(FSMEvent.START)
            self.current_state = self.fsm.stack_path[-1] if self.fsm.stack_path else FSMState.FAILURE
        except Exception as e:
            logger.exception(f"Error starting FSM: {e}")
            self.current_state = FSMState.FAILURE
            if self.context:
                self.context["error"] = str(e)

        return self.current_state

    async def send_event(self, event: FSMEvent, data: Optional[str] = None):
        """Send an event to the FSM"""
        if not self.fsm:
            logger.error("FSM not initialized")
            return False

        # Handle feedback events
        if event == FSMEvent.FEEDBACK_DRAFT and data:
            self.context["draft_feedback"] = data
        elif event == FSMEvent.FEEDBACK_HANDLERS and data:
            if "handlers_feedback" not in self.context:
                self.context["handlers_feedback"] = {}
            # In a real implementation, we would need to specify which handler
            # gets the feedback, for now we'll just set a general feedback
            self.context["handlers_feedback"]["general"] = data
        elif event == FSMEvent.FEEDBACK_INDEX and data:
            self.context["index_feedback"] = data
        elif event == FSMEvent.FEEDBACK_FRONTEND and data:
            self.context["frontend_feedback"] = data

        # Send the event
        logger.info(f"Sending event {event} to FSM")
        try:
            await self.fsm.send(event)
            self.current_state = self.fsm.stack_path[-1] if self.fsm.stack_path else FSMState.FAILURE
            return True
        except Exception as e:
            logger.exception(f"Error sending event to FSM: {e}")
            return False

    def get_state(self) -> FSMState:
        """Get the current state of the FSM"""
        return self.current_state

    def get_context(self) -> ApplicationContext:
        """Get the current context"""
        return self.context if self.context else {"user_prompt": ""}

    def is_complete(self) -> bool:
        """Check if the FSM has completed"""
        if not self.fsm or not self.fsm.stack_path:
            return False
        return self.current_state in (FSMState.COMPLETE, FSMState.FAILURE)

    def is_error(self) -> bool:
        """Check if the FSM has failed"""
        return self.current_state == FSMState.FAILURE

    def is_review_state(self) -> bool:
        """Check if the FSM is in a review state"""
        return self.current_state in (
            FSMState.REVIEW_DRAFT,
            FSMState.REVIEW_HANDLERS,
            FSMState.REVIEW_INDEX,
            FSMState.REVIEW_FRONTEND
        )

    def get_available_events(self) -> List[FSMEvent]:
        """Get the events available in the current state"""
        if not self.fsm:
            return []
        
        # Find the current state definition in the FSM
        for state in self.fsm.state_stack:
            if "states" in state and self.current_state in state["states"]:
                state_def = state["states"][self.current_state]
                return list(state_def.get("on", {}).keys())
                
        return []


async def main(user_prompt="Simple todo app"):
    async with dagger.connection(dagger.Config(log_output=open(os.devnull, "w"))):
        fsm_app = FSMApplication()

        # Start the FSM with the user prompt
        state = await fsm_app.start(user_prompt)
        logger.info(f"FSM started, current state: {state}")

        # In a real application, this would interact with a user interface
        # For this example, we'll just auto-confirm each review state
        while not fsm_app.is_complete():
            if fsm_app.is_review_state():
                logger.info(f"FSM is in review state {fsm_app.get_state()}, available events: {fsm_app.get_available_events()}")

                # Auto-confirm in this example
                await fsm_app.send_event(FSMEvent.CONFIRM)
            else:
                # Wait for the FSM to complete the current state
                await anyio.sleep(0.1)

    # Print the results
    context = fsm_app.get_context()
    if fsm_app.is_error():
        logger.error(f"Application run failed: {context.get('error', 'Unknown error')}")
    else:
        logger.info("Application run completed successfully")

        # Count files generated
        server_files = context.get("server_files", {})
        frontend_files = context.get("frontend_files", {})
        logger.info(f"Generated {len(server_files)} server files and {len(frontend_files)} frontend files")


if __name__ == "__main__":
    anyio.run(main)
