import os
import enum
import uuid
import socket
import anyio
import logging
from dag_compiler import Compiler
from langfuse import Langfuse
from fsm_core.llm_common import LLMClient, get_sync_client
from fsm_core.helpers import agent_dfs, span_claude_bedrock
from fsm_core import typespec, drizzle, typescript, handler_tests, handlers
from fsm_core.common import AgentMachine
import statemachine
from core.datatypes import ApplicationPrepareOut, CapabilitiesOut, DrizzleOut, TypespecOut, ApplicationOut
from core.datatypes import RefineOut, GherkinOut, TypescriptOut, HandlerTestsOut, HandlerOut
from typing import TypedDict, NotRequired

logger = logging.getLogger(__name__)


async def solve_agent[T](
    init: AgentMachine[T],
    context: T,
    m_claude: LLMClient,
    langfuse: Langfuse,
    langfuse_parent_trace_id: str,
    langfuse_parent_observation_id: str,
    max_depth: int = 3,
    max_width: int = 2,
):
    def llm_fn(messages, generation):
        completion = span_claude_bedrock(m_claude, messages, generation)
        return {"role": "assistant", "content": completion.content}

    solution = await agent_dfs(
        init,
        context,
        llm_fn,
        langfuse,
        langfuse_parent_trace_id,
        langfuse_parent_observation_id,
        max_depth=max_depth,
        max_width=max_width,
    )
    return solution


# set up actors

class ActorContext:
    def __init__(self, compiler: Compiler):
        self.compiler = compiler


class TypespecActor:
    def __init__(self, m_claude: LLMClient, compiler: Compiler, langfuse_client: Langfuse, trace_id: str, observation_id: str):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client
        self.trace_id = trace_id
        self.observation_id = observation_id

    async def execute(self, user_requests: list[str], feedback: str | None = None, previous_schema: str | None = None):
        """
        Execute TypeSpec generation or revision

        Args:
            user_requests: List of user prompts
            feedback: Optional feedback for revision
            previous_schema: Previous TypeSpec schema for context (required if feedback provided)
        """
        is_revision = feedback is not None
        span_name = "typespec_revision" if is_revision else "typespec"
        span = self.langfuse_client.span(
            name=span_name,
            trace_id=self.trace_id,
            parent_observation_id=self.observation_id,
        )

        # Create appropriate entry based on operation type
        start = self._create_entry(user_requests, feedback, previous_schema)

        result, _ = await solve_agent(start, ActorContext(self.compiler), self.m_claude, self.langfuse_client, self.trace_id, span.id)
        if result is None:
            raise ValueError("Failed to solve typespec")
        if not isinstance(result.data.inner, typespec.Success):
            raise Exception("Bad state: " + str(result.data.inner))

        # Include feedback in the span data if provided
        output_data = result.data.inner.__dict__.copy()
        if feedback:
            output_data["feedback"] = feedback
        span.end(output=output_data)

        return result.data.inner

    def _create_entry(self, user_requests: list[str], feedback: str | None = None, previous_schema: str | None = None):
        """
        Create the appropriate entry for this actor based on operation type

        Args:
            user_requests: List of user prompts
            feedback: Optional feedback for revision
            previous_schema: Previous TypeSpec schema (required if feedback provided)

        Returns:
            Entry or FeedbackEntry instance
        """
        if feedback and previous_schema:
            # Use dedicated FeedbackEntry for revision with context
            return typespec.FeedbackEntry(user_requests, previous_schema, feedback)
        else:
            # Use regular Entry for initial creation or backward compatibility
            return typespec.Entry(user_requests)


class DrizzleActor:
    def __init__(self, m_claude: LLMClient, compiler: Compiler, langfuse_client: Langfuse, trace_id: str, observation_id: str):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client
        self.trace_id = trace_id
        self.observation_id = observation_id

    async def execute(self, typespec_definitions: str, feedback: str = None, previous_schema: str = None):
        """
        Execute Drizzle schema generation or revision

        Args:
            typespec_definitions: TypeSpec schema to generate Drizzle from
            feedback: Optional feedback for revision
            previous_schema: Previous Drizzle schema for context (required if feedback provided)
        """
        is_revision = feedback is not None
        span_name = "drizzle_revision" if is_revision else "drizzle"
        span = self.langfuse_client.span(
            name=span_name,
            trace_id=self.trace_id,
            parent_observation_id=self.observation_id,
        )

        # Create appropriate entry based on operation type
        start = self._create_entry(typespec_definitions, feedback, previous_schema)

        result, _ = await solve_agent(start, ActorContext(self.compiler), self.m_claude, self.langfuse_client, self.trace_id, span.id)
        if result is None:
            raise ValueError("Failed to solve drizzle")
        if not isinstance(result.data.inner, drizzle.Success):
            raise Exception("Failed to solve drizzle: " + str(result.data.inner))

        # Include feedback in the span data if provided
        output_data = result.data.inner.__dict__.copy()
        if feedback:
            output_data["feedback"] = feedback
        span.end(output=output_data)

        return result.data.inner

    def _create_entry(self, typespec_definitions: str, feedback: str = None, previous_schema: str = None):
        """
        Create the appropriate entry for this actor based on operation type

        Args:
            typespec_definitions: TypeSpec schema to generate Drizzle from
            feedback: Optional feedback for revision
            previous_schema: Previous Drizzle schema (required if feedback provided)

        Returns:
            Entry or FeedbackEntry instance
        """
        if feedback and previous_schema:
            # Use dedicated FeedbackEntry for revision with context
            return drizzle.FeedbackEntry(typespec_definitions, previous_schema, feedback)
        else:
            # Use regular Entry for initial creation
            return drizzle.Entry(typespec_definitions)


class TypescriptActor:
    def __init__(self, m_claude: LLMClient, compiler: Compiler, langfuse_client: Langfuse, trace_id: str, observation_id: str):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client
        self.trace_id = trace_id
        self.observation_id = observation_id

    async def execute(self, typespec_definitions: str, feedback: str = None):
        span_name = "typescript_revision" if feedback else "typescript"
        span = self.langfuse_client.span(
            name=span_name,
            trace_id=self.trace_id,
            parent_observation_id=self.observation_id,
        )

        # Create entry with feedback if available
        start = typescript.Entry(typespec_definitions, feedback)
        result, _ = await solve_agent(start, ActorContext(self.compiler), self.m_claude, self.langfuse_client, self.trace_id, span.id)
        if result is None:
            raise ValueError("Failed to solve typescript")
        if not isinstance(result.data.inner, typescript.Success):
            raise Exception("Failed to solve typescript: " + str(result.data.inner))

        # Include feedback in the span data if provided
        output_data = result.data.inner.__dict__.copy()
        if feedback:
            output_data["feedback"] = feedback
        span.end(output=output_data)

        return result.data.inner


class HandlerTestsActor:
    def __init__(self, m_claude: LLMClient, compiler: Compiler, langfuse_client: Langfuse, trace_id: str, observation_id: str, max_workers=5):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client
        self.trace_id = trace_id
        self.observation_id = observation_id
        self.max_workers = max_workers

    async def execute(self, functions: list[typescript.FunctionDeclaration], typescript_schema: str, drizzle_schema: str, feedback: dict[str, str] = None) -> dict[str, handler_tests.Success]:
        has_feedback = feedback is not None and len(feedback) > 0
        span_name = "handler_tests_revision" if has_feedback else "handler_tests"
        span = self.langfuse_client.span(
            name=span_name,
            trace_id=self.trace_id,
            parent_observation_id=self.observation_id,
        )

        result_dict: dict[str, handler_tests.Success] = {}

        async def run_test(function: typescript.FunctionDeclaration):
            # Use feedback for the function if available
            function_feedback = feedback.get(function.name) if feedback else None

            # Create entry with feedback if available
            start = handler_tests.Entry(function.name, typescript_schema, drizzle_schema, function_feedback)
            result, _ = await solve_agent(start, ActorContext(self.compiler), self.m_claude, self.langfuse_client, self.trace_id, span.id)
            if result is None:
                raise ValueError(f"Failed to solve handler tests for {function}")
            if not isinstance(result.data.inner, handler_tests.Success):
                raise Exception(f"Failed to solve handler tests for {function}: " + str(result.data.inner))
            result_dict[function.name] = result.data.inner

        async with anyio.create_task_group() as tg:
            for fn in functions:
                tg.start_soon(run_test, fn)

        # Include feedback in the span data if provided
        output_data = {k: v.__dict__ for k, v in result_dict.items()}
        if feedback:
            output_data["feedback"] = feedback
        span.end(output=output_data)

        return result_dict


class HandlersActor:
    def __init__(self, m_claude: LLMClient, compiler: Compiler, langfuse_client: Langfuse, trace_id: str, observation_id: str):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client
        self.trace_id = trace_id
        self.observation_id = observation_id

    async def execute(self, functions: list[typescript.FunctionDeclaration], typescript_schema: str, drizzle_schema: str, tests: dict[str, handler_tests.Success], feedback: dict[str, str] = None) -> dict[str, handlers.Success | handlers.TestsError]:
        has_feedback = feedback is not None and len(feedback) > 0
        span_name = "handlers_revision" if has_feedback else "handlers"
        span = self.langfuse_client.span(
            name=span_name,
            trace_id=self.trace_id,
            parent_observation_id=self.observation_id,
        )

        result_dict = {}

        async def run_handler(function: typescript.FunctionDeclaration):
            # Get function-specific feedback if available
            function_feedback = feedback.get(function.name) if feedback else None

            # Create entry with feedback if available
            start = handlers.Entry(function.name, typescript_schema, drizzle_schema, tests[function.name].source, function_feedback)
            result, _ = await solve_agent(start, ActorContext(self.compiler), self.m_claude, self.langfuse_client, self.trace_id, span.id)
            if result is None:
                raise ValueError(f"Failed to solve handlers for {function}")
            if isinstance(result.data.inner, handlers.TestsError) and result.data.inner.score == 0:
                raise Exception(f"Failed to solve handlers for {function}: " + str(result.data.inner))
            result_dict[function.name] = result.data.inner

        async with anyio.create_task_group() as tg:
            for fn in functions:
                tg.start_soon(run_handler, fn)

        # Include feedback in the span data if provided
        output_data = {k: v.__dict__ if hasattr(v, "__dict__") else str(v) for k, v in result_dict.items()}
        if feedback:
            output_data["feedback"] = feedback
        span.end(output=output_data)

        return result_dict


class FsmState(str, enum.Enum):
    TYPESPEC = "typespec"
    TYPESPEC_REVIEW = "typespec_review"
    DRIZZLE = "drizzle"
    DRIZZLE_REVIEW = "drizzle_review"
    TYPESCRIPT = "typescript"
    TYPESCRIPT_REVIEW = "typescript_review"
    HANDLER_TESTS = "handler_tests"
    HANDLER_TESTS_REVIEW = "handler_tests_review"
    HANDLERS = "handlers"
    HANDLERS_REVIEW = "handlers_review"
    COMPLETE = "complete"
    FAILURE = "failure"
    WAIT = "wait"


class InteractionMode(enum.Enum):
    INTERACTIVE = "interactive"  # All stages require confirmation
    NON_INTERACTIVE = "non_interactive"  # No stages require confirmation
    TYPESPEC_ONLY = "typespec_only"  # Only typespec stage requires confirmation


# Define state transitions for FSM
FSM_TRANSITIONS = {
    FsmState.TYPESPEC: {
        'processing': FsmState.TYPESPEC,
        'review': FsmState.TYPESPEC_REVIEW,
        'next': FsmState.DRIZZLE
    },
    FsmState.DRIZZLE: {
        'processing': FsmState.DRIZZLE,
        'review': FsmState.DRIZZLE_REVIEW,
        'next': FsmState.TYPESCRIPT
    },
    FsmState.TYPESCRIPT: {
        'processing': FsmState.TYPESCRIPT,
        'review': FsmState.TYPESCRIPT_REVIEW,
        'next': FsmState.HANDLER_TESTS
    },
    FsmState.HANDLER_TESTS: {
        'processing': FsmState.HANDLER_TESTS,
        'review': FsmState.HANDLER_TESTS_REVIEW,
        'next': FsmState.HANDLERS
    },
    FsmState.HANDLERS: {
        'processing': FsmState.HANDLERS,
        'review': FsmState.HANDLERS_REVIEW,
        'next': FsmState.COMPLETE
    }
}

# Define which stages require confirmation in each mode
MODE_CONFIG = {
    InteractionMode.INTERACTIVE: [
        FsmState.TYPESPEC, FsmState.DRIZZLE, FsmState.TYPESCRIPT,
        FsmState.HANDLER_TESTS, FsmState.HANDLERS
    ],
    InteractionMode.NON_INTERACTIVE: [],  # No states require interaction
    InteractionMode.TYPESPEC_ONLY: [FsmState.TYPESPEC]  # Only typespec requires confirmation
}


class FsmEvent:
    # Event types
    PROMPT = "PROMPT"
    CONFIRM = "CONFIRM"
    REVISE_TYPESPEC = "REVISE_TYPESPEC"
    REVISE_DRIZZLE = "REVISE_DRIZZLE"
    REVISE_TYPESCRIPT = "REVISE_TYPESCRIPT"
    REVISE_HANDLER_TESTS = "REVISE_HANDLER_TESTS"
    REVISE_HANDLERS = "REVISE_HANDLERS"

    def __init__(self, type_: str, feedback: str | None = None):
        self.type = type_
        self.feedback = feedback

    # For backward compatibility with string comparison
    def __eq__(self, other):
        if isinstance(other, str):
            return self.type == other
        return self.type == other.type if hasattr(other, "type") else False

    def __hash__(self):
        return hash(self.type)

    def __str__(self):
        return self.type




class FSMContext(TypedDict):
    description: str
    capabilities: NotRequired[list[str]]
    typespec_schema: NotRequired[typespec.Success]
    drizzle_schema: NotRequired[drizzle.Success]
    typescript_schema: NotRequired[typescript.Success]
    handler_tests: NotRequired[dict[str, handler_tests.Success]]
    handlers: NotRequired[dict[str, handlers.Success | handlers.TestsError]]
    # Feedback fields for revision
    typespec_feedback: NotRequired[str]
    drizzle_feedback: NotRequired[str]
    typescript_feedback: NotRequired[str]
    handler_tests_feedback: NotRequired[dict[str, str]]
    handlers_feedback: NotRequired[dict[str, str]]



class Application:
    def __init__(
        self,
        client: LLMClient,
        compiler: Compiler,
        langfuse_client: Langfuse | None = None,
        interaction_mode: InteractionMode = InteractionMode.NON_INTERACTIVE
    ):
        self.client = client
        self.compiler = compiler
        self.langfuse_client = langfuse_client or Langfuse()
        self.interaction_mode = interaction_mode

    def get_effective_state(self, fsm: statemachine.StateMachine[FSMContext]) -> FsmState:
        """
        Gets the effective state of the FSM, taking errors into account.
        This method encapsulates the logic for determining the actual state
        when errors are present in the context.
        """
        # Check if there's an error in the context
        if "error" in fsm.context:
            return FsmState.FAILURE

        # If no error, return the actual state path
        if not fsm.stack_path:
            return FsmState.FAILURE  # Default to failure if stack is empty

        return fsm.stack_path[-1]

    async def prepare_bot(self, prompts: list[str], bot_id: str | None = None, capabilities: list[str] | None = None, *args, **kwargs) -> ApplicationPrepareOut:
        logger.info(f"Preparing bot with prompts: {prompts}")
        trace = self.langfuse_client.trace(
            id=kwargs.get("langfuse_observation_id", uuid.uuid4().hex),
            name="create_bot",
            user_id=os.environ.get("USER_ID", socket.gethostname()),
            metadata={"bot_id": bot_id},
        )
        logger.info(f"Created trace with ID: {trace.id}")

        fsm_context: FSMContext = {"description": "", "user_requests": prompts}
        fsm_states = self.make_fsm_states(trace.id, trace.id)
        fsm = statemachine.StateMachine[FSMContext](fsm_states, fsm_context)
        logger.info("Initialized state machine, sending PROMPT event")
        fsm.send(FsmEvent.PROMPT)

        # Get effective state that takes errors into account
        effective_state = self.get_effective_state(fsm)
        logger.info(f"State machine finished at state: {effective_state}")

        result = {"capabilities": capabilities, "status": "processing"}
        error_output = None

        match effective_state:
            case FsmState.COMPLETE:
                typespec_schema = fsm.context["typespec_schema"]
                result.update({"typespec": typespec_schema})
                result.update({"status": "success"})
            case FsmState.FAILURE:
                error_output = fsm.context["error"]
                result.update({"error": error_output})
                result.update({"status": "error"})
            case FsmState.TYPESPEC_REVIEW:
                typespec_schema = fsm.context["typespec_schema"]
                result.update({"typespec": typespec_schema})
                result.update({"status": "success"}) # until we have router we let user iterate in done state
            case _:
                raise ValueError(F"Unexpected state: {effective_state}")

        trace.update(output=result)

        refined = RefineOut(refined_description="", error_output=error_output)
        return ApplicationPrepareOut(
            refined_description=refined,
            capabilities=CapabilitiesOut(capabilities if capabilities is not None else [], error_output),
            typespec=TypespecOut(
                reasoning=getattr(result.get("typespec"), "reasoning", None),
                typespec_definitions=getattr(result.get("typespec"), "typespec", None),
                llm_functions=getattr(result.get("typespec"), "llm_functions", None),
                error_output=error_output
            ),
            status=result.get("status", "success")
        )

    async def update_bot(self, typespec_schema: str, bot_id: str | None = None, capabilities: list[str] | None = None, *args, **kwargs) -> ApplicationOut:
        logger.info(f"Updating bot with ID: {bot_id if bot_id else 'unknown'}")
        trace = self.langfuse_client.trace(
            id=kwargs.get("langfuse_observation_id", uuid.uuid4().hex),
            name="update_bot",
            user_id=os.environ.get("USER_ID", socket.gethostname()),
            metadata={"bot_id": bot_id},
        )
        logger.info(f"Created trace with ID: {trace.id}")

        # hack typespec output
        logger.info("Processing typespec schema")
        # Check if typespec already has tags
        if not (("<reasoning>" in typespec_schema and "</reasoning>" in typespec_schema) and
                ("<typespec>" in typespec_schema and "</typespec>" in typespec_schema)):
            # Wrap the schema in the expected format
            logger.info("Adding default reasoning and typespec tags")
            typespec_schema = f"""
            <reasoning>
            Auto-generated reasoning.
            </reasoning>

            <typespec>
            {typespec_schema}
            </typespec>
            """
        reasoning, typespec_parsed, llm_functions = typespec.TypespecMachine.parse_output(typespec_schema)
        typespec_input = typespec.Success(reasoning, typespec_parsed, llm_functions, {"exit_code": 0})
        logger.info(f"Parsed typespec schema with {len(llm_functions) if llm_functions else 0} LLM functions")

        fsm_context: FSMContext = {"description": "", "typespec_schema": typespec_input}
        fsm_states = self.make_fsm_states(trace.id, trace.id)
        fsm = statemachine.StateMachine[FSMContext](fsm_states, fsm_context)
        logger.info("Initialized state machine, sending CONFIRM event")
        fsm.send(FsmEvent.CONFIRM)

        # Get effective state that takes errors into account
        effective_state = self.get_effective_state(fsm)
        logger.info(f"State machine finished at state: {effective_state}")

        result = {"capabilities": capabilities}
        error_output = None

        match effective_state:
            case FsmState.COMPLETE:
                result.update(fsm.context)
            case FsmState.FAILURE:
                error_output = fsm.context["error"]
                result.update({"error": error_output})
            case _:
                raise ValueError(F"Unexpected state: {effective_state}")

        trace.update(output=result)

        # Use ApplicationOut.from_context to create the result
        return ApplicationOut.from_context(
            result=result,
            capabilities=capabilities,
            trace_id=trace.id,
            error_output=error_output
        )

    def get_next_state(self, current_state: FsmState) -> FsmState:
        """
        Determine the next state based on the current state and interaction mode.

        Raises:
            ValueError: If no transitions are defined for the state
        """
        # Special handling for terminal states
        if current_state in [FsmState.COMPLETE, FsmState.FAILURE]:
            return current_state

        # Get transition info for this state
        transitions = FSM_TRANSITIONS.get(current_state)
        if not transitions:
            raise ValueError(f"No transitions defined for state {current_state}")

        # Check if this state requires review in the current interaction mode
        if current_state in MODE_CONFIG.get(self.interaction_mode, []):
            return transitions['review']
        else:
            return transitions['next']

    def make_fsm_states(self, trace_id: str, observation_id: str) -> statemachine.State:
        typespec_actor = TypespecActor(self.client, self.compiler, self.langfuse_client, trace_id, observation_id)
        drizzle_actor = DrizzleActor(self.client, self.compiler, self.langfuse_client, trace_id, observation_id)
        typescript_actor = TypescriptActor(self.client, self.compiler, self.langfuse_client, trace_id, observation_id)
        handler_tests_actor = HandlerTestsActor(self.client, self.compiler, self.langfuse_client, trace_id, observation_id)
        handlers_actor = HandlersActor(self.client, self.compiler, self.langfuse_client, trace_id, observation_id)

        # Define target states based on interaction mode
        typespec_target = self.get_next_state(FsmState.TYPESPEC)
        drizzle_target = self.get_next_state(FsmState.DRIZZLE)
        typescript_target = self.get_next_state(FsmState.TYPESCRIPT)
        handler_tests_target = self.get_next_state(FsmState.HANDLER_TESTS)
        handlers_target = self.get_next_state(FsmState.HANDLERS)

        def fsm_ctx_set(key: str):
            async def _set_val(ctx: FSMContext, value):
                # Set the value in the context
                ctx[key] = value
            return _set_val

        # Base state configuration
        states: statemachine.State[FSMContext] = {
            "on": {
                FsmEvent.PROMPT: FsmState.TYPESPEC,
                FsmEvent.CONFIRM: FsmState.DRIZZLE,
            },
            "states": {
                FsmState.TYPESPEC: {
                    "invoke": {
                        "src": typespec_actor,
                        "input_fn": lambda ctx: (
                            ctx["user_requests"],
                            ctx.get("typespec_feedback", ""),
                            ctx["typespec_schema"].typespec if ctx.get("typespec_schema") else None,
                        ),
                        "on_done": {
                            "target": typespec_target,
                            "actions": [fsm_ctx_set("typespec_schema")],
                        },
                        "on_error": {
                            "target": FsmState.FAILURE,
                            "actions": [fsm_ctx_set("error")],
                        },
                    },
                },
                FsmState.DRIZZLE: {
                    "invoke": {
                        "src": drizzle_actor,
                        "input_fn": lambda ctx: (
                            ctx["typespec_schema"].typespec,
                            ctx.get("drizzle_feedback", ""),
                            ctx["drizzle_schema"].drizzle_schema if ctx.get("drizzle_schema") else None,
                        ),
                        "on_done": {
                            "target": drizzle_target,
                            "actions": [fsm_ctx_set("drizzle_schema")],
                        },
                        "on_error": {
                            "target": FsmState.FAILURE,
                            "actions": [fsm_ctx_set("error")],
                        },
                    }
                },
                FsmState.TYPESCRIPT: {
                    "invoke": {
                        "src": typescript_actor,
                        "input_fn": lambda ctx: (ctx["typespec_schema"].typespec, ctx.get("typescript_feedback")),
                        "on_done": {
                            "target": typescript_target,
                            "actions": [fsm_ctx_set("typescript_schema")],
                        },
                        "on_error": {
                            "target": FsmState.FAILURE,
                            "actions": [fsm_ctx_set("error")],
                        },
                    }
                },
                FsmState.HANDLER_TESTS: {
                    "invoke": {
                        "src": handler_tests_actor,
                        "input_fn": lambda ctx: (ctx["typescript_schema"].functions, ctx["typescript_schema"].typescript_schema, ctx["drizzle_schema"].drizzle_schema, ctx.get("handler_tests_feedback")),
                        "on_done": {
                            "target": handler_tests_target,
                            "actions": [fsm_ctx_set("handler_tests")],
                        },
                        "on_error": {
                            "target": FsmState.FAILURE,
                            "actions": [fsm_ctx_set("error")],
                        },
                    }
                },
                FsmState.HANDLERS: {
                    "invoke": {
                        "src": handlers_actor,
                        "input_fn": lambda ctx: (ctx["typescript_schema"].functions, ctx["typescript_schema"].typescript_schema, ctx["drizzle_schema"].drizzle_schema, ctx["handler_tests"], ctx.get("handlers_feedback")),
                        "on_done": {
                            "target": handlers_target,
                            "actions": [fsm_ctx_set("handlers")],
                        },
                        "on_error": {
                            "target": FsmState.FAILURE,
                            "actions": [fsm_ctx_set("error")],
                        },
                    }
                },
                FsmState.COMPLETE: {
                    # Terminal state with no transitions
                },
                FsmState.FAILURE: {
                    # Terminal failure state with no transitions to other states
                    # This ensures it doesn't automatically transition to COMPLETE
                },
                FsmState.WAIT: {},
            }
        }

        # Always add all review states, but they'll only be used if the interaction mode requires them
        states["states"].update({
            FsmState.TYPESPEC_REVIEW: {
                "on": {
                    FsmEvent.CONFIRM: FsmState.DRIZZLE,
                    FsmEvent.REVISE_TYPESPEC: FsmState.TYPESPEC,
                },
            },
            FsmState.DRIZZLE_REVIEW: {
                "on": {
                    FsmEvent.CONFIRM: FsmState.TYPESCRIPT,
                    FsmEvent.REVISE_DRIZZLE: FsmState.DRIZZLE,
                },
            },
            FsmState.TYPESCRIPT_REVIEW: {
                "on": {
                    FsmEvent.CONFIRM: FsmState.HANDLER_TESTS,
                    FsmEvent.REVISE_TYPESCRIPT: FsmState.TYPESCRIPT,
                },
            },
            FsmState.HANDLER_TESTS_REVIEW: {
                "on": {
                    FsmEvent.CONFIRM: FsmState.HANDLERS,
                    FsmEvent.REVISE_HANDLER_TESTS: FsmState.HANDLER_TESTS,
                },
            },
            FsmState.HANDLERS_REVIEW: {
                "on": {
                    FsmEvent.CONFIRM: FsmState.COMPLETE,
                    FsmEvent.REVISE_HANDLERS: FsmState.HANDLERS,
                },
            },
        })

        return states
