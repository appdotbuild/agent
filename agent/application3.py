import os
import enum
import uuid
import socket
import concurrent.futures
from anthropic import AnthropicBedrock
from compiler.core import Compiler
from langfuse import Langfuse
from fsm_core.helpers import agent_dfs, span_claude_bedrock
from fsm_core import typespec, drizzle, typescript, handler_tests, handlers
from fsm_core.common import Node, AgentState, AgentMachine
import statemachine
from core.datatypes import ApplicationPrepareOut, CapabilitiesOut, DrizzleOut, TypespecOut, ApplicationOut
from core.datatypes import RefineOut, GherkinOut, TypescriptOut, HandlerTestsOut, HandlerOut


def solve_agent[T](
    init: AgentMachine[T],
    context: T,
    m_claude: AnthropicBedrock,
    langfuse: Langfuse,
    langfuse_parent_trace_id: str,
    langfuse_parent_observation_id: str,
    max_depth: int = 3,
    max_width: int = 2,
):
    def llm_fn(messages, generation):
        completion = span_claude_bedrock(m_claude, messages, generation)
        return {"role": "assistant", "content": completion.content}

    solution = agent_dfs(
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
    def __init__(self, m_claude: AnthropicBedrock, compiler: Compiler, langfuse_client: Langfuse, trace_id: str, observation_id: str):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client
        self.trace_id = trace_id
        self.observation_id = observation_id

    def execute(self, user_requests: list[str]):
        span = self.langfuse_client.span(
            name="typespec",
            trace_id=self.trace_id,
            parent_observation_id=self.observation_id,
        )
        start = typespec.Entry(user_requests)
        result, _ = solve_agent(start, ActorContext(self.compiler), self.m_claude, self.langfuse_client, self.trace_id, span.id)
        if result is None:
            raise ValueError("Failed to solve typespec")
        if not isinstance(result.data.inner, typespec.Success):
            raise Exception("Bad state: " + str(result.data.inner))
        span.end(output=result.data.inner.__dict__)
        return result.data.inner


class DrizzleActor:
    def __init__(self, m_claude: AnthropicBedrock, compiler: Compiler, langfuse_client: Langfuse, trace_id: str, observation_id: str):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client
        self.trace_id = trace_id
        self.observation_id = observation_id

    def execute(self, typespec_definitions: str):
        span = self.langfuse_client.span(
            name="drizzle",
            trace_id=self.trace_id,
            parent_observation_id=self.observation_id,
        )
        start = drizzle.Entry(typespec_definitions)
        result, _ = solve_agent(start, ActorContext(self.compiler), self.m_claude, self.langfuse_client, self.trace_id, span.id)
        if result is None:
            raise ValueError("Failed to solve drizzle")
        if not isinstance(result.data.inner, drizzle.Success):
            raise Exception("Failed to solve drizzle: " + str(result.data.inner))
        span.end(output=result.data.inner.__dict__)
        return result.data.inner


class TypescriptActor:
    def __init__(self, m_claude: AnthropicBedrock, compiler: Compiler, langfuse_client: Langfuse, trace_id: str, observation_id: str):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client
        self.trace_id = trace_id
        self.observation_id = observation_id

    def execute(self, typespec_definitions: str):
        span = self.langfuse_client.span(
            name="typescript",
            trace_id=self.trace_id,
            parent_observation_id=self.observation_id,
        )
        start = typescript.Entry(typespec_definitions)
        result, _ = solve_agent(start, ActorContext(self.compiler), self.m_claude, self.langfuse_client, self.trace_id, span.id)
        if result is None:
            raise ValueError("Failed to solve typescript")
        if not isinstance(result.data.inner, typescript.Success):
            raise Exception("Failed to solve typescript: " + str(result.data.inner))
        span.end(output=result.data.inner.__dict__)
        return result.data.inner


class HandlerTestsActor:
    def __init__(self, m_claude: AnthropicBedrock, compiler: Compiler, langfuse_client: Langfuse, trace_id: str, observation_id: str, max_workers=5):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client
        self.trace_id = trace_id
        self.observation_id = observation_id
        self.max_workers = max_workers
    
    def execute(self, functions: list[typescript.FunctionDeclaration], typescript_schema: str, drizzle_schema: str) -> dict[str, handler_tests.Success]:
        span = self.langfuse_client.span(
            name="handler_tests",
            trace_id=self.trace_id,
            parent_observation_id=self.observation_id,
        )
        future_to_tests: dict[concurrent.futures.Future[tuple[Node[AgentState] | None, Node[AgentState]]], str] = {}
        result_dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for function in functions:
                start = handler_tests.Entry(function.name, typescript_schema, drizzle_schema)
                future_to_tests[executor.submit(solve_agent, start, ActorContext(self.compiler), self.m_claude, self.langfuse_client, self.trace_id, span.id)] = function.name
            for future in concurrent.futures.as_completed(future_to_tests):
                function = future_to_tests[future]
                result, _ = future.result()
                # can skip if failure and generate what succeeded
                if result is None:
                    raise ValueError(f"Failed to solve handler tests for {function}")
                if not isinstance(result.data.inner, handler_tests.Success):
                    raise Exception(f"Failed to solve handler tests for {function}: " + str(result.data.inner))
                result_dict[function] = result.data.inner
        span.end(output=result_dict)
        return result_dict


class HandlersActor:
    def __init__(self, m_claude: AnthropicBedrock, compiler: Compiler, langfuse_client: Langfuse, trace_id: str, observation_id: str):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client
        self.trace_id = trace_id
        self.observation_id = observation_id

    def execute(self, functions: list[typescript.FunctionDeclaration], typescript_schema: str, drizzle_schema: str, tests: dict[str, handler_tests.Success]) -> dict[str, handlers.Success | handlers.TestsError]:
        span = self.langfuse_client.span(
            name="handlers",
            trace_id=self.trace_id,
            parent_observation_id=self.observation_id,
        )
        futures_to_handlers: dict[concurrent.futures.Future[tuple[Node[AgentState] | None, Node[AgentState]]], str] = {}
        result_dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            for function in functions:
                start = handlers.Entry(function.name, typescript_schema, drizzle_schema, tests[function.name].source)
                futures_to_handlers[executor.submit(solve_agent, start, ActorContext(self.compiler), self.m_claude, self.langfuse_client, self.trace_id, span.id)] = function.name
            for future in concurrent.futures.as_completed(futures_to_handlers):
                function = futures_to_handlers[future]
                result, _ = future.result()
                if result is None:
                    raise ValueError(f"Failed to solve handlers for {function}")
                if isinstance(result.data.inner, handlers.TestsError) and result.data.inner.score == 0:
                    raise Exception(f"Failed to solve handlers for {function}: " + str(result.data.inner))
                result_dict[function] = result.data.inner
        span.end(output=result_dict)
        return result_dict


class FsmState(str, enum.Enum):
    TYPESPEC = "typespec"
    DRIZZLE = "drizzle"
    TYPESCRIPT = "typescript"
    HANDLER_TESTS = "handler_tests"
    HANDLERS = "handlers"
    COMPLETE = "complete"
    FAILURE = "failure"
    WAIT = "wait"


class FsmEvent(str, enum.Enum):
    PROMPT = "PROMPT"
    CONFIRM = "CONFIRM"



class Application3:
    def __init__(self, client: AnthropicBedrock, compiler: Compiler):
        self.client = client
        self.compiler = compiler
        self.langfuse_client = Langfuse()
    
    def prepare_bot(self, prompts: list[str], bot_id: str | None = None, capabilities: list[str] | None = None, *args, **kwargs) -> ApplicationPrepareOut:
        trace = self.langfuse_client.trace(
            id=kwargs.get("langfuse_observation_id", uuid.uuid4().hex),
            name="create_bot",
            user_id=os.environ.get("USER_ID", socket.gethostname()),
            metadata={"bot_id": bot_id},
        )

        fsm_context = {"user_requests": prompts}
        fsm_states = self.make_fsm_states(trace.id, trace.id)
        fsm = statemachine.StateMachine(fsm_states, fsm_context)
        fsm.send(FsmEvent.PROMPT)
        print(fsm.context)

        result = {"capabilities": capabilities}
        error_output = None
        
        match fsm.stack_path[-1]:
            case FsmState.COMPLETE:
                typespec_schema = fsm.context["typespec_schema"]
                result.update({"typespec": typespec_schema})
            case FsmState.FAILURE:
                error_output = fsm.context["error"]
                result.update({"error": error_output})
            case _:
                raise ValueError(F"Unexpected state: {fsm.stack_path}")
        
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
            )
        )
    
    def update_bot(self, typespec_schema: str, bot_id: str | None = None, capabilities: list[str] | None = None, *args, **kwargs) -> ApplicationOut:
        trace = self.langfuse_client.trace(
            id=kwargs.get("langfuse_observation_id", uuid.uuid4().hex),
            name="update_bot",
            user_id=os.environ.get("USER_ID", socket.gethostname()),
            metadata={"bot_id": bot_id},
        )

        # hack typespec output
        reasoning, typespec_parsed, llm_functions = typespec.TypespecMachine.parse_output(typespec_schema)
        typespec_input = typespec.Success(reasoning, typespec_parsed, llm_functions, {"exit_code": 0})

        fsm_context = {"typespec_schema": typespec_input}
        fsm_states = self.make_fsm_states(trace.id, trace.id)
        fsm = statemachine.StateMachine(fsm_states, fsm_context)
        fsm.send(FsmEvent.CONFIRM)

        result = {"capabilities": capabilities}
        error_output = None
        
        match fsm.stack_path[-1]:
            case FsmState.COMPLETE:
                result.update(fsm.context)
            case FsmState.FAILURE:
                error_output = fsm.context["error"]
                result.update({"error": error_output})
            case _:
                raise ValueError(F"Unexpected state: {fsm.stack_path}")
        
        trace.update(output=result)
        refined = RefineOut(refined_description="", error_output=error_output)
        
        # Process typescript_schema if available
        typescript_result = result.get("typescript_schema")
        typescript_out = TypescriptOut(
            reasoning=getattr(typescript_result, "reasoning", None),
            typescript_schema=getattr(typescript_result, "typescript_schema", None),
            functions=getattr(typescript_result, "functions", None),
            error_output=error_output
        ) if typescript_result else None
        
        # Convert handler test outputs
        handler_tests_dict = {}
        for name, test in result.get("handler_tests", {}).items():
            handler_tests_dict[name] = HandlerTestsOut(
                name=name,
                content=getattr(test, "source", None),
                error_output=error_output
            )
        
        # Convert handler outputs
        handlers_dict = {}
        for name, handler in result.get("handlers", {}).items():
            handlers_dict[name] = HandlerOut(
                name=name,
                handler=getattr(handler, "source", None),
                argument_schema=None,
                error_output=error_output
            )
        
        return ApplicationOut(
            refined_description=refined,
            capabilities=CapabilitiesOut(capabilities if capabilities is not None else [], error_output),
            typespec=TypespecOut(
                reasoning=getattr(result.get("typespec_schema"), "reasoning", None),
                typespec_definitions=getattr(result.get("typespec_schema"), "typespec", None),
                llm_functions=getattr(result.get("typespec_schema"), "llm_functions", None),
                error_output=error_output
            ),
            drizzle=DrizzleOut(
                reasoning=getattr(result.get("drizzle_schema"), "reasoning", None),
                drizzle_schema=getattr(result.get("drizzle_schema"), "drizzle_schema", None),
                error_output=error_output
            ),
            handlers=handlers_dict,
            handler_tests=handler_tests_dict,
            typescript_schema=typescript_out,
            gherkin=GherkinOut(reasoning=None, gherkin=None, error_output=error_output),
            trace_id=trace.id
        )

    def make_fsm_states(self, trace_id: str, observation_id: str) -> statemachine.State:
        typespec_actor = TypespecActor(self.client, self.compiler, self.langfuse_client, trace_id, observation_id)
        drizzle_actor = DrizzleActor(self.client, self.compiler, self.langfuse_client, trace_id, observation_id)
        typescript_actor = TypescriptActor(self.client, self.compiler, self.langfuse_client, trace_id, observation_id)
        handler_tests_actor = HandlerTestsActor(self.client, self.compiler, self.langfuse_client, trace_id, observation_id)
        handlers_actor = HandlersActor(self.client, self.compiler, self.langfuse_client, trace_id, observation_id)

        states: statemachine.State = {
            "on": {
                FsmEvent.PROMPT: FsmState.TYPESPEC,
                FsmEvent.CONFIRM: FsmState.DRIZZLE,
            },
            "states": {
                FsmState.TYPESPEC: {
                    "invoke": {
                        "src": typespec_actor,
                        "input_fn": lambda ctx: (ctx["user_requests"],),
                        "on_done": {
                            "target": FsmState.WAIT,
                            "actions": [lambda ctx, event: ctx.update({"typespec_schema": event})],
                        },
                        "on_error": {
                            "target": FsmState.FAILURE,
                            "actions": [lambda ctx, event: ctx.update({"error": event})],
                        },
                    },
                },
                FsmState.DRIZZLE: {
                    "invoke": {
                        "src": drizzle_actor,
                        "input_fn": lambda ctx: (ctx["typespec_schema"].typespec,),
                        "on_done": {
                            "target": FsmState.TYPESCRIPT,
                            "actions": [lambda ctx, event: ctx.update({"drizzle_schema": event})],
                        },
                        "on_error": {
                            "target": FsmState.FAILURE,
                            "actions": [lambda ctx, event: ctx.update({"error": event})],
                        },
                    }
                },
                FsmState.TYPESCRIPT: {
                    "invoke": {
                        "src": typescript_actor,
                        "input_fn": lambda ctx: (ctx["typespec_schema"].typespec,),
                        "on_done": {
                            "target": FsmState.HANDLER_TESTS,
                            "actions": [lambda ctx, event: ctx.update({"typescript_schema": event})],
                        },
                        "on_error": {
                            "target": FsmState.FAILURE,
                            "actions": [lambda ctx, event: ctx.update({"error": event})],
                        },
                    }
                },
                FsmState.HANDLER_TESTS: {
                    "invoke": {
                        "src": handler_tests_actor,
                        "input_fn": lambda ctx: (ctx["typescript_schema"].functions, ctx["typescript_schema"].typescript_schema, ctx["drizzle_schema"].drizzle_schema),
                        "on_done": {
                            "target": FsmState.HANDLERS,
                            "actions": [lambda ctx, event: ctx.update({"handler_tests": event})],
                        },
                        "on_error": {
                            "target": FsmState.FAILURE,
                            "actions": [lambda ctx, event: ctx.update({"error": event})],
                        },
                    }
                },
                FsmState.HANDLERS: {
                    "invoke": {
                        "src": handlers_actor,
                        "input_fn": lambda ctx: (ctx["typescript_schema"].functions, ctx["typescript_schema"].typescript_schema, ctx["drizzle_schema"].drizzle_schema, ctx["handler_tests"]),
                        "on_done": {
                            "target": FsmState.COMPLETE,
                            "actions": [lambda ctx, event: ctx.update({"handlers": event})],
                        },
                        "on_error": {
                            "target": FsmState.FAILURE,
                            "actions": [lambda ctx, event: ctx.update({"error": event})],
                        },
                    }
                },
                FsmState.COMPLETE: {},
                FsmState.FAILURE: {},
                FsmState.WAIT: {},
            }
        }
    
        return states
