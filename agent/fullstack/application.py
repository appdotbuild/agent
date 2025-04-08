import os
import anyio
import logging
import uuid
import enum
from typing import Dict, Any, List, TypedDict, NotRequired, Optional, Callable
from dataclasses import dataclass, field
import json
from statemachine import StateMachine, State, Actor, Context
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



@dataclass
class ApplicationContext(Context):
    """Context for the fullstack application state machine"""
    user_prompt: str
    draft: Optional[str] = None
    draft_feedback: Optional[str] = None
    # Using default_factory for mutable types like dict
    handlers_feedback: Optional[Dict[str, str]] = field(default_factory=dict)
    index_feedback: Optional[str] = None
    frontend_feedback: Optional[str] = None
    server_files: Optional[Dict[str, str]] = field(default_factory=dict)
    frontend_files: Optional[Dict[str, str]] = field(default_factory=dict)
    error: Optional[str] = None

    def dump(self) -> dict:
        """Dump context to a serializable dictionary"""
        # Convert dataclass to dictionary
        data = {
            "user_prompt": self.user_prompt,
            "draft": self.draft,
            "draft_feedback": self.draft_feedback,
            "handlers_feedback": self.handlers_feedback,
            "index_feedback": self.index_feedback,
            "frontend_feedback": self.frontend_feedback,
            "server_files": self.server_files,
            "frontend_files": self.frontend_files,
            "error": self.error
        }
        return data

    @classmethod
    def load(cls, data: object) -> "ApplicationContext":
        """Load context from a serializable dictionary"""
        return cls(**data)


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
        self.context: ApplicationContext = ApplicationContext(user_prompt=user_prompt)

        # Define actions to update context
        async def update_server_files(ctx: ApplicationContext, result: Any) -> None:
            """Update server files in context from actor result"""
            logger.info("Updating server files from result")
            if hasattr(result, "get_trajectory"):
                for node in result.get_trajectory():
                    if hasattr(node.data, "files") and node.data.files:
                        if not hasattr(ctx, "server_files"):
                            ctx.server_files = {}
                        ctx.server_files.update(node.data.files)

        async def update_frontend_files(ctx: ApplicationContext, result: Any) -> None:
            """Update frontend files in context from actor result"""
            logger.info("Updating frontend files from result")
            if hasattr(result, "get_trajectory"):
                for node in result.get_trajectory():
                    if hasattr(node.data, "files") and node.data.files:
                        ctx.frontend_files = node.data.files

        async def update_draft(ctx: ApplicationContext, result: Any) -> None:
            """Update the draft in context"""
            logger.info("Updating draft in context")
            if hasattr(result, "get_trajectory"):
                draft_content = ""
                for node in result.get_trajectory():
                    if hasattr(node.data, "files") and node.data.files:
                        draft_content = "\n".join(node.data.files.values())
                ctx.draft = draft_content

        async def set_error(ctx: ApplicationContext, error: Exception) -> None:
            """Set error in context"""
            logger.error(f"Setting error in context: {error}")
            ctx.error = str(error)

        # Define state machine states
        states: State[ApplicationContext] = {
            "initial": FSMState.DRAFT, # Define the initial state
            "states": {
                FSMState.DRAFT: {
                    "invoke": {
                        "src": self.draft_actor,
                        "input_fn": lambda ctx: (ctx.draft_feedback or ctx.user_prompt,),
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
                        "input_fn": lambda ctx: (ctx.server_files,),
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
                        "input_fn": lambda ctx: (ctx.server_files,),
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
                        "input_fn": lambda ctx: (ctx.user_prompt, ctx.server_files),
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
                    "type": "final" # Mark as a final state
                },
                FSMState.FAILURE: {
                    "type": "final" # Mark as a final state
                }
            },
        }

        logger.info("Creating state machine")
        self.fsm = StateMachine[ApplicationContext](states, self.context)
        if "on" not in states:
            states["on"] = {}
        states["on"][FSMEvent.PROMPT] = FSMState.DRAFT
        self.current_state = FSMState.DRAFT

    async def start(self, client_callback: Callable | None):
        if not self.workspace:

            await self.initialize()

        try:
            await self.send_event(FSMEvent.PROMPT, client_callback=client_callback)
        except Exception as e:
            logger.exception(f"Error starting FSM: {e}")
            self.current_state = FSMState.FAILURE
            if self.context:
                self.context.error = str(e)

            error_checkpoint = self.as_checkpoint()
            if client_callback:
                client_callback(self.current_state, error_checkpoint)

        return self.current_state

    async def send_event(self, event: FSMEvent, data: Optional[str] = None,
                     client_callback : Callable | None = None):
        if not self.fsm:
            logger.error("FSM not initialized")
            return False

        # Handle feedback events using match-case
        match event:
            case FSMEvent.FEEDBACK_DRAFT if data:
                self.context.draft_feedback = data
            case FSMEvent.FEEDBACK_HANDLERS if data:
                if not self.context.handlers_feedback:
                    self.context.handlers_feedback = {}
                # In a real implementation, we would need to specify which handler
                # gets the feedback, for now we'll just set a general feedback
                self.context.handlers_feedback["general"] = data
            case FSMEvent.FEEDBACK_INDEX if data:
                self.context.index_feedback = data
            case FSMEvent.FEEDBACK_FRONTEND if data:
                self.context.frontend_feedback = data
            case _:
                pass   # not a feedback event

        # Store the previous state for change detection
        previous_state = self.current_state

        # Send the event
        logger.info(f"Sending event {event} to FSM")

        async with dagger.connection(dagger.Config(log_output=open(os.devnull, "w"))):
            try:
                await self.fsm.send(event)
                self.current_state = self.fsm.stack_path[-1] if self.fsm.stack_path else FSMState.FAILURE

                # Dump context after transition if requested
                if previous_state != self.current_state:
                    checkpoint = self.as_checkpoint()
                    if client_callback:
                        client_callback(self.current_state, checkpoint)
                return True
            except Exception as e:
                logger.exception(f"Error sending event to FSM: {e}")
                return False

    def get_state(self) -> FSMState:
        return self.current_state

    def get_context(self) -> ApplicationContext:
        return self.context if self.context else ApplicationContext(user_prompt="")

    def is_complete(self) -> bool:
        if not self.fsm or not self.fsm.stack_path:
            return False
        return self.current_state in (FSMState.COMPLETE, FSMState.FAILURE)

    def is_error(self) -> bool:
        return self.current_state == FSMState.FAILURE

    def is_review_state(self) -> bool:
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

    def as_checkpoint(self) -> dict:
        if not self.fsm:
            raise RuntimeError("FSM not initialized")

        checkpoint = self.get_context().dump()
        checkpoint["current_state"] = self.current_state
        return checkpoint

    @classmethod
    async def from_checkpoint(cls, checkpoint: dict) -> "FSMApplication":
        app = cls()
        await app.initialize()

        app.create_fsm("")  # Create with empty prompt - will be replaced
        state = checkpoint.pop("current_state", FSMState.DRAFT)
        app.context = ApplicationContext.load(checkpoint.get("context", {}))
        app.current_state = state
        logger.info(f"Restored FSM checkpoint to state: {app.current_state}")
        return app

    @classmethod
    async def from_prompt(cls, user_prompt: str, client_callback: Callable | None):
        app = cls()
        await app.initialize()
        app.create_fsm(user_prompt)
        initial_checkpoint = app.as_checkpoint()
        return app


async def main(user_prompt="Simple todo app"):
    client_callback = None
    fsm_app = await FSMApplication.from_prompt(user_prompt, client_callback=None)
    await fsm_app.start(client_callback)

    while not fsm_app.is_complete():
        if fsm_app.is_review_state():
            logger.info(f"FSM is in review state {fsm_app.get_state()}, available events: {fsm_app.get_available_events()}")
            # Auto-confirm in this example
            await fsm_app.send_event(FSMEvent.CONFIRM, client_callback=client_callback)
        else:
            # Wait for the FSM to complete the current state
            await anyio.sleep(0.1)

    # Print the results
    context = fsm_app.get_context()
    if fsm_app.is_error():
        logger.error(f"Application run failed: {context.error or 'Unknown error'}")
    else:
        logger.info("Application run completed successfully")
        # Count files generated
        server_files = context.server_files or {}
        frontend_files = context.frontend_files or {}
        logger.info(f"Generated {len(server_files)} server files and {len(frontend_files)} frontend files")


if __name__ == "__main__":
    anyio.run(main)
