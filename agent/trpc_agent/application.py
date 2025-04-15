import os
import anyio
import logging
import uuid
import enum
from typing import Dict, Any, List, Self, TypedDict, NotRequired, Optional, Callable, Literal
from dataclasses import dataclass, field, asdict
import json
from core.actors import BaseData
from core.base_node import Node
from core.statemachine import StateMachine, State, Actor, Context, MachineCheckpoint
from llm.common import AsyncLLM
from llm.anthropic_bedrock import AnthropicBedrockLLM
from anthropic import AsyncAnthropicBedrock
from core.workspace import Workspace
from trpc_agent.actors import DraftActor, HandlersActor, IndexActor, FrontendActor
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


@dataclass(frozen=True) # Use dataclass for easier serialization, frozen=True makes it hashable by default if needed
class FSMEvent:
    type_: Literal["CONFIRM", "FEEDBACK"]
    feedback: Optional[str] = None

    def __eq__(self, other):
        match other:
            case FSMEvent():
                return self.type_ == other.type_
            case str():
                return self.type_ == other
            case _:
                raise TypeError(f"Cannot compare FSMEvent with {type(other)}")

    def __hash__(self):
        return hash(self.type_)

    def __str__(self):
        return self.type_


@dataclass
class ApplicationContext(Context):
    """Context for the fullstack application state machine"""
    user_prompt: str
    draft: Optional[str] = None
    feedback_data: Optional[str] = None
    feedback_component: Optional[str] = None
    server_files: Dict[str, str] = field(default_factory=dict)
    frontend_files: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None

    def dump(self) -> dict:
        """Dump context to a serializable dictionary"""
        # Convert dataclass to dictionary
        data = {
            "user_prompt": self.user_prompt,
            "draft": self.draft,
            "feedback_data":self.feedback_data,
            "feedback_component": self.feedback_component,
            "server_files": self.server_files,
            "frontend_files": self.frontend_files,
            "error": self.error
        }
        return data

    @classmethod
    def load(cls, data: object) -> Self:
        """Load context from a serializable dictionary"""
        if not isinstance(data, dict):
            raise ValueError(f"Invalid data type: {type(data)}")
        return cls(**data)


class FSMApplication:
    def __init__(self, fsm: StateMachine[ApplicationContext, FSMEvent]):
        self.fsm = fsm

    @classmethod
    async def load(cls, data: MachineCheckpoint) -> Self:
        root = await cls.make_states()
        fsm = await StateMachine[ApplicationContext, FSMEvent].load(root, data, ApplicationContext)
        return cls(fsm)

    @classmethod
    def base_execution_plan(cls) -> str:
        return "\n".join([
            "1. Draft app design",
            "2. Implement handlers",
            "3. Create index file",
            "4. Build frontend",
        ])

    @classmethod
    async def start_fsm(cls, user_prompt: str) -> Self:
        """Create the state machine for the application"""
        states = await cls.make_states()
        context = ApplicationContext(user_prompt=user_prompt)
        fsm = StateMachine[ApplicationContext, FSMEvent](states, context)
        await fsm.send(FSMEvent("CONFIRM")) # confirm running first stage immediately
        return cls(fsm)

    @classmethod
    async def make_states(cls) -> State[ApplicationContext, FSMEvent]:
        def agg_node_files(solution: Node[BaseData]) -> dict[str, str]:
            files = {}
            for node in solution.get_trajectory():
                files.update(node.data.files)
            return files

        # Define actions to update context
        async def update_handler_files(ctx: ApplicationContext, result: dict[str, Node[BaseData]]) -> None:
            logger.info("Updating handler files from result")
            for handler_name, node in result.items():
                ctx.server_files.update(agg_node_files(node))

        async def update_frontend_files(ctx: ApplicationContext, result: Node[BaseData]) -> None:
            logger.info("Updating frontend files from result")
            ctx.frontend_files.update(agg_node_files(result))

        async def update_draft(ctx: ApplicationContext, result: Node[BaseData]) -> None:
            logger.info("Updating draft in context")
            files = agg_node_files(result)
            ctx.server_files.update(files)
            ctx.draft = "\n".join(files.values())

        async def update_index_files(ctx: ApplicationContext, result: Node[BaseData]) -> None:
            logger.info("Updating index files from result.")
            ctx.server_files.update(agg_node_files(result))

        async def set_error(ctx: ApplicationContext, error: Exception) -> None:
            """Set error in context"""
            logger.error(f"Setting error in context: {error}")
            ctx.error = str(error)

        llm = cls.get_async_llm()
        model_params = {
            "model": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
            "max_tokens": 8192,
        }
        workspace = await Workspace.create(
            base_image="oven/bun:1.2.5-alpine",
            context=dagger.dag.host().directory("./trpc_agent/template"),
            setup_cmd=[["bun", "install"]],
        )
        backend_workspace = workspace.clone().cwd("/app/server")
        frontend_workspace = workspace.clone().cwd("/app/client")

        draft_actor = DraftActor(llm, backend_workspace.clone(), model_params)
        handlers_actor = HandlersActor(llm, backend_workspace.clone(), model_params, beam_width=3)
        index_actor = IndexActor(llm, backend_workspace.clone(), model_params, beam_width=3)
        front_actor = FrontendActor(llm, frontend_workspace.clone(), model_params, beam_width=1, max_depth=20)

        # Define state machine states
        states = State[ApplicationContext, FSMEvent](
            on={
                FSMEvent("CONFIRM"): FSMState.DRAFT
            },
            states={
                FSMState.DRAFT: State(
                    invoke={
                        "src": draft_actor,
                        "input_fn": lambda ctx: (ctx.feedback_data or ctx.user_prompt,),
                        "on_done": {
                            "target": FSMState.REVIEW_DRAFT,
                            "actions": [update_draft],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.REVIEW_DRAFT: State(
                    on={
                        FSMEvent("CONFIRM"): FSMState.HANDLERS,
                        FSMEvent("FEEDBACK"): FSMState.DRAFT,
                    },
                ),
                FSMState.HANDLERS: State(
                    invoke={
                        "src": handlers_actor,
                        "input_fn": lambda ctx: (ctx.server_files,),
                        "on_done": {
                            "target": FSMState.REVIEW_HANDLERS,
                            "actions": [update_handler_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.REVIEW_HANDLERS: State(
                    on={
                        FSMEvent("CONFIRM"): FSMState.INDEX,
                        FSMEvent("FEEDBACK"): FSMState.HANDLERS,
                    },
                ),
                FSMState.INDEX: State(
                    invoke={
                        "src": index_actor,
                        "input_fn": lambda ctx: (ctx.server_files,),
                        "on_done": {
                            "target": FSMState.REVIEW_INDEX,
                            "actions": [update_index_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    }
                ),
                FSMState.REVIEW_INDEX: State(
                    on={
                        FSMEvent("CONFIRM"): FSMState.FRONTEND,
                        FSMEvent("FEEDBACK"): FSMState.INDEX,
                    },
                ),
                FSMState.FRONTEND: State(
                    invoke={
                        "src": front_actor,
                        "input_fn": lambda ctx: (ctx.user_prompt, ctx.server_files),
                        "on_done": {
                            "target": FSMState.REVIEW_FRONTEND,
                            "actions": [update_frontend_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.REVIEW_FRONTEND: State(
                    on={
                        FSMEvent("CONFIRM"): FSMState.COMPLETE,
                        FSMEvent("FEEDBACK"): FSMState.FRONTEND,
                    },
                ),
                FSMState.COMPLETE: State(),
                FSMState.FAILURE: State(),
            },
        )

        return states

    async def confirm_state(self):
        await self.fsm.send(FSMEvent("CONFIRM"))

    async def provide_feedback(self, feedback: str, component_name: str):
        self.fsm.context.feedback_data = feedback
        self.fsm.context.feedback_component = component_name
        await self.fsm.send(FSMEvent("FEEDBACK"))

    async def complete_fsm(self):
        while (self.current_state not in (FSMState.COMPLETE, FSMState.FAILURE)):
            await self.fsm.send(FSMEvent("CONFIRM"))

    @property
    def is_completed(self) -> bool:
        return self.current_state == FSMState.COMPLETE

    def maybe_error(self) -> str | None:
        return self.fsm.context.error

    @property
    def current_state(self) -> str:
        if self.fsm.stack_path:
            return self.fsm.stack_path[-1]
        return ""

    @property
    def state_output(self) -> dict:
        match self.current_state:
            case FSMState.REVIEW_DRAFT:
                return {"draft": self.fsm.context.draft}
            case FSMState.REVIEW_HANDLERS:
                handler_files = {
                    filename: content for filename, content in self.fsm.context.server_files.items()
                    if "/handlers/" in filename
                }
                return {"handlers": handler_files}
            case FSMState.REVIEW_INDEX:
                return {"index": self.fsm.context.server_files["index.ts"]}
            case FSMState.REVIEW_FRONTEND:
                return {"frontend": self.fsm.context.frontend_files}
            case FSMState.COMPLETE:
                return {
                    "server_files": self.fsm.context.server_files,
                    "frontend_files": self.fsm.context.frontend_files,
                }
            case FSMState.FAILURE:
                return {"error": self.fsm.context.error or "Unknown error"}
            case _:
                logger.debug(f"State {self.current_state} is a processing state, returning processing status")
                return {"status": "processing"}

    @property
    def available_actions(self) -> dict[str, str]:
        actions = {}
        match self.current_state:
            case FSMState.REVIEW_DRAFT | FSMState.REVIEW_HANDLERS | FSMState.REVIEW_INDEX | FSMState.REVIEW_FRONTEND:
                actions = {
                    "confirm": "Accept current output and continue",
                    "revise": "Provide feedback and revise"
                }
                logger.debug(f"Review state detected: {self.current_state}, offering confirm/revise actions")
            case FSMState.COMPLETE:
                actions = {"complete": "Finalize and get all artifacts"}
                logger.debug("FSM is in COMPLETE state, offering complete action")
            case FSMState.FAILURE:
                actions = {"get_error": "Get error details"}
                logger.debug("FSM is in FAILURE state, offering get_error action")
            case _:
                actions = {"wait": "Wait for processing to complete"}
                logger.debug(f"FSM is in processing state: {self.current_state}, offering wait action")
        return actions

    @classmethod
    def get_async_llm(cls) -> AsyncLLM:
        # TODO: use extensible llm provider injection
        return AnthropicBedrockLLM(AsyncAnthropicBedrock(aws_profile="dev", aws_region="us-west-2"))


async def main(user_prompt="Simple todo app"):
    async with dagger.connection(dagger.Config(log_output=open(os.devnull, "w"))):
        fsm_app = await FSMApplication.start_fsm(user_prompt)

        while (fsm_app.current_state not in (FSMState.COMPLETE, FSMState.FAILURE)):
            await fsm_app.fsm.send(FSMEvent("CONFIRM"))

        # Print the results
        context = fsm_app.fsm.context
        if fsm_app.maybe_error():
            logger.error(f"Application run failed: {context.error or 'Unknown error'}")
        else:
            logger.info("Application run completed successfully")
            # Count files generated
            server_files = context.server_files or {}
            frontend_files = context.frontend_files or {}
            logger.info(f"Generated {len(server_files)} server files and {len(frontend_files)} frontend files")


if __name__ == "__main__":
    anyio.run(main)
