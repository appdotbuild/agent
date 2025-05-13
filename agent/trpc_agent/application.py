import os
import anyio
import logging
import enum
from typing import Dict, Self, Optional, Literal, Any
from dataclasses import dataclass, field
from core.statemachine import StateMachine, State, Context
from llm.utils import get_llm_client
from core.actors import BaseData
from core.base_node import Node
from core.statemachine import MachineCheckpoint
from core.workspace import Workspace
from trpc_agent import playbooks
from trpc_agent.silly import EditActor
from trpc_agent.actors import DraftActor, HandlersActor, FrontendActor, ConcurrentActor
import dagger

# Set up logging
logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)
for package in ['urllib3', 'httpx', 'google_genai.models']:
    logging.getLogger(package).setLevel(logging.WARNING)


class FSMState(str, enum.Enum):
    DRAFT = "draft"
    REVIEW_DRAFT = "review_draft"
    APPLICATION = "application"
    REVIEW_APPLICATION = "review_application"
    APPLY_FEEDBACK = "apply_feedback"
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
    feedback_data: Optional[str] = None
    feedback_component: Optional[str] = None
    files: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None

    def dump(self) -> dict:
        """Dump context to a serializable dictionary"""
        # Convert dataclass to dictionary
        data = {
            "user_prompt": self.user_prompt,
            "feedback_data":self.feedback_data,
            "feedback_component": self.feedback_component,
            "files": self.files,
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
    async def start_fsm(cls, user_prompt: str, settings: Dict[str, Any] | None = None) -> Self:
        """Create the state machine for the application"""
        states = await cls.make_states(settings)
        context = ApplicationContext(user_prompt=user_prompt)
        fsm = StateMachine[ApplicationContext, FSMEvent](states, context)
        await fsm.send(FSMEvent("CONFIRM")) # confirm running first stage immediately
        return cls(fsm)

    @classmethod
    async def make_states(cls, settings: Dict[str, Any] | None = None) -> State[ApplicationContext, FSMEvent]:
        def agg_node_files(solution: Node[BaseData]) -> dict[str, str]:
            files = {}
            for node in solution.get_trajectory():
                files.update(node.data.files)
            return files

        # Define actions to update context
        async def update_node_files(ctx: ApplicationContext, result: Node[BaseData] | Dict[str, Node[BaseData]]) -> None:
            logger.info("Updating context files from result")
            if isinstance(result, Node):
                ctx.files.update(agg_node_files(result))
            elif isinstance(result, dict):
                for key, node in result.items():
                    ctx.files.update(agg_node_files(node))

        async def set_error(ctx: ApplicationContext, error: Exception) -> None:
            """Set error in context"""
            # Use logger.exception to include traceback
            logger.exception("Setting error in context:", exc_info=error)
            ctx.error = str(error)

        llm = get_llm_client()
        vlm = get_llm_client(model_name="gemini-flash-lite")
        model_params = settings or {}
        g_llm = get_llm_client(model_name="gemini-pro")
        workspace = await Workspace.create(
            base_image="oven/bun:1.2.5-alpine",
            context=dagger.dag.host().directory("./trpc_agent/template"),
            setup_cmd=[["bun", "install"]],
        )

        draft_actor = DraftActor(llm, workspace.clone(), model_params)
        application_actor = ConcurrentActor(
            handlers=HandlersActor(llm, workspace.clone(), model_params, beam_width=3),
            frontend=FrontendActor(llm, vlm, workspace.clone(), model_params, beam_width=1, max_depth=20)
        )
        edit_actor = EditActor(
            g_llm,
            workspace.clone(),
            playbooks.SILLY_PROMPT,
            ws_allowed=[
                "server/src/schema.ts",
                "server/src/db/schema.ts",
                "server/src/handlers/",
                "server/src/tests/",
                "server/src/index.ts",
                "client/src/App.tsx",
                "client/src/components/",
                "client/src/App.css",
            ],
            ws_protected=[
                "server/src/db/index.ts",
                "client/src/utils/trpc.ts",
                "client/src/components/ui",
            ],
            ws_injected=[
                "client/src/utils/trpc.ts",
                "client/src/lib/utils.ts",
            ],
            ws_visible=["client/src/components/ui/"],
            max_depth=70,
        )

        # Define state machine states
        states = State[ApplicationContext, FSMEvent](
            on={
                FSMEvent("CONFIRM"): FSMState.DRAFT,
                FSMEvent("FEEDBACK"): FSMState.APPLY_FEEDBACK,
            },
            states={
                FSMState.DRAFT: State(
                    invoke={
                        "src": draft_actor,
                        "input_fn": lambda ctx: (ctx.feedback_data or ctx.user_prompt,),
                        "on_done": {
                            "target": FSMState.REVIEW_DRAFT,
                            "actions": [update_node_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.REVIEW_DRAFT: State(
                    on={
                        FSMEvent("CONFIRM"): FSMState.APPLICATION,
                        FSMEvent("FEEDBACK"): FSMState.DRAFT,
                    },
                ),
                FSMState.APPLICATION: State(
                    invoke={
                        "src": application_actor,
                        "input_fn": lambda ctx: (ctx.user_prompt, ctx.files),
                        "on_done": {
                            "target": FSMState.REVIEW_APPLICATION,
                            "actions": [update_node_files],
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    },
                ),
                FSMState.REVIEW_APPLICATION: State(
                    on={
                        FSMEvent("CONFIRM"): FSMState.COMPLETE,
                        FSMEvent("FEEDBACK"): FSMState.APPLICATION,
                    },
                ),
                FSMState.APPLY_FEEDBACK: State(
                    invoke={
                        "src": edit_actor,
                        "input_fn": lambda ctx: (ctx.files, ctx.feedback_data),
                        "on_done": {
                            "target": FSMState.COMPLETE,
                            "actions": [update_node_files]
                        },
                        "on_error": {
                            "target": FSMState.FAILURE,
                            "actions": [set_error],
                        },
                    }
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
        return self.current_state == FSMState.REVIEW_APPLICATION or self.current_state == FSMState.FAILURE

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
                return {"draft": self.fsm.context.files}
            case FSMState.REVIEW_APPLICATION:
                return {"application": self.fsm.context.files}
            case FSMState.COMPLETE:
                return {"application": self.fsm.context.files}
            case FSMState.FAILURE:
                return {"error": self.fsm.context.error or "Unknown error"}
            case _:
                logger.debug(f"State {self.current_state} is a processing state, returning processing status")
                return {"status": "processing"}

    @property
    def available_actions(self) -> dict[str, str]:
        actions = {}
        match self.current_state:
            case FSMState.REVIEW_DRAFT | FSMState.REVIEW_APPLICATION:
                actions = {"confirm": "Accept current output and continue"}
                logger.debug(f"Review state detected: {self.current_state}, offering confirm action")
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

    async def get_diff_with(self, snapshot: dict[str, str]) -> str:
        # Start with the template directory
        context = dagger.dag.host().directory("./trpc_agent/template")

        # Write snapshot (initial) files
        for key, value in snapshot.items():
            context = context.with_new_file(key, value)

        # Create workspace with git
        workspace = await Workspace.create(base_image="alpine/git", context=context)

        # Write current (final) files
        for key, value in self.fsm.context.files.items():
            workspace.write_file(key, value)

        # If we're in the COMPLETE state, ensure we return a diff even if empty
        if self.current_state == FSMState.COMPLETE:
            diff = await workspace.diff()
            # If the diff is empty but we have files, return a special marker
            if not diff.strip() and self.fsm.context.files:
                # Return empty string, but with special note that the system can recognize
                return "# Note: This is a valid empty diff (means no changes from template)"
            return diff

        return await workspace.diff()


async def main(user_prompt="Simple todo app"):
    async with dagger.connection(dagger.Config(log_output=open(os.devnull, "w"))):
        fsm_app = await FSMApplication.start_fsm(user_prompt)

        while (fsm_app.current_state not in (FSMState.COMPLETE, FSMState.FAILURE)):
            await fsm_app.fsm.send(FSMEvent("CONFIRM"))

        context = fsm_app.fsm.context
        if fsm_app.maybe_error():
            logger.error(f"Application run failed: {context.error or 'Unknown error'}")
        else:
            logger.info("Application run completed successfully")
            logger.info(f"Generated {len(context.files)} files")
            logger.info("Applying edit to application.")
            await fsm_app.fsm.send(FSMEvent("FEEDBACK", "Add header that says 'Hello World'"))

            if fsm_app.maybe_error():
                logger.error(f"Failed to apply edit: {context.error or 'Unknown error'}")
            else:
                logger.info("Edit applied successfully")


if __name__ == "__main__":
    anyio.run(main)
