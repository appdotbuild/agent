import concurrent.futures
from anthropic import AnthropicBedrock
from compiler.core import Compiler
from langfuse import Langfuse
from fsm_core.helpers import solve_agent
from fsm_core import typespec, drizzle, typescript, handler_tests, handlers
from fsm_core.common import Node, AgentState
import statemachine


# placeholder functions
def not_impl(ctx):
    raise NotImplementedError("Not implemented")

def fail_state(ctx):
    print("FAILED")


# set up actors

class ActorContext:
    def __init__(self, compiler: Compiler):
        self.compiler = compiler


class TypespecActor:
    def __init__(self, m_claude: AnthropicBedrock, compiler: Compiler, langfuse_client: Langfuse):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client

    def execute(self, application_description: str):
        start = typespec.Entry(application_description)
        result, _ = solve_agent(start, ActorContext(self.compiler), "solve_typespec", self.m_claude, self.langfuse_client)
        if result is None:
            raise ValueError("Failed to solve typespec")
        if not isinstance(result.data.inner, typespec.Success):
            raise Exception("Bad state: " + str(result.data.inner))
        return result.data.inner


class DrizzleActor:
    def __init__(self, m_claude: AnthropicBedrock, compiler: Compiler, langfuse_client: Langfuse):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client

    def execute(self, typespec_definitions: str):
        start = drizzle.Entry(typespec_definitions)
        result, _ = solve_agent(start, ActorContext(self.compiler), "solve_drizzle", self.m_claude, self.langfuse_client)
        if result is None:
            raise ValueError("Failed to solve drizzle")
        if not isinstance(result.data.inner, drizzle.Success):
            raise Exception("Failed to solve drizzle: " + str(result.data.inner))
        return result.data.inner


class TypescriptActor:
    def __init__(self, m_claude: AnthropicBedrock, compiler: Compiler, langfuse_client: Langfuse):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client

    def execute(self, typespec_definitions: str):
        start = typescript.Entry(typespec_definitions)
        result, _ = solve_agent(start, ActorContext(self.compiler), "solve_typescript", self.m_claude, self.langfuse_client)
        if result is None:
            raise ValueError("Failed to solve typescript")
        if not isinstance(result.data.inner, typescript.Success):
            raise Exception("Failed to solve typescript: " + str(result.data.inner))
        return result.data.inner


class HandlerTestsActor:
    def __init__(self, m_claude: AnthropicBedrock, compiler: Compiler, langfuse_client: Langfuse, max_workers=5):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client
        self.max_workers = max_workers
    
    def execute(self, functions: list[typescript.FunctionDeclaration], typescript_schema: str, drizzle_schema: str) -> dict[str, handler_tests.Success]:
        future_to_tests: dict[concurrent.futures.Future[tuple[Node[AgentState] | None, Node[AgentState]]], str] = {}
        result_dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for function in functions:
                start = handler_tests.Entry(function.name, typescript_schema, drizzle_schema)
                future_to_tests[executor.submit(solve_agent, start, ActorContext(self.compiler), "solve_handler_tests", self.m_claude, self.langfuse_client)] = function.name
            for future in concurrent.futures.as_completed(future_to_tests):
                function = future_to_tests[future]
                result, _ = future.result()
                # can skip if failure and generate what succeeded
                if result is None:
                    raise ValueError(f"Failed to solve handler tests for {function}")
                if not isinstance(result.data.inner, handler_tests.Success):
                    raise Exception(f"Failed to solve handler tests for {function}: " + str(result.data.inner))
                result_dict[function] = result.data.inner
        return result_dict


class HandlersActor:
    def __init__(self, m_claude: AnthropicBedrock, compiler: Compiler, langfuse_client: Langfuse):
        self.m_claude = m_claude
        self.compiler = compiler
        self.langfuse_client = langfuse_client

    def execute(self, functions: list[typescript.FunctionDeclaration], typescript_schema: str, drizzle_schema: str, tests: dict[str, handler_tests.Success]) -> dict[str, handlers.Success]:
        futures_to_handlers: dict[concurrent.futures.Future[tuple[Node[AgentState] | None, Node[AgentState]]], str] = {}
        result_dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            for function in functions:
                start = handlers.Entry(function.name, typescript_schema, drizzle_schema, tests[function.name].source)
                futures_to_handlers[executor.submit(solve_agent, start, ActorContext(self.compiler), "solve_handlers", self.m_claude, self.langfuse_client)] = function.name
            for future in concurrent.futures.as_completed(futures_to_handlers):
                function = futures_to_handlers[future]
                result, _ = future.result()
                if result is None:
                    raise ValueError(f"Failed to solve handlers for {function}")
                if isinstance(result.data.inner, handlers.TestsError) and result.data.inner.score == 0:
                    raise Exception(f"Failed to solve handlers for {function}: " + str(result.data.inner))
                
                # more strict criteria
                # if not isinstance(result.data.inner, handlers.Success):
                #     raise Exception(f"Failed to solve handlers for {function}: " + str(result.data.inner))

                result_dict[function] = result.data.inner
        return result_dict


if __name__ == "__main__":
    langfuse_client = Langfuse()
    compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    m_claude = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")

    typespec_actor = TypespecActor(m_claude, compiler, langfuse_client)
    drizzle_actor = DrizzleActor(m_claude, compiler, langfuse_client)
    typescript_actor = TypescriptActor(m_claude, compiler, langfuse_client)
    handler_tests_actor = HandlerTestsActor(m_claude, compiler, langfuse_client)
    handlers_actor = HandlersActor(m_claude, compiler, langfuse_client)


    machine_states: statemachine.State = {
        "on": {
            "START": "typespec",
        },
        "states": {
            "typespec": {
                "on": {
                    "PROMPT": "adjust",
                    "CONFIRM": "core",
                },
                "states": {
                    "init": {
                        "invoke": {
                            "src": typespec_actor,
                            "input_fn": lambda ctx: (ctx["application_description"],),
                            "on_done": {
                                "target": "wait",
                                "actions": [lambda ctx, event: ctx.update({"typespec_schema": event})],
                            }
                        }
                    },
                    "adjust": {
                        "entry": [not_impl], # pop user prompt from ctx and jump into init
                    },
                    "wait": {},
                },
                "always": {
                    "guard": lambda ctx: "typespec_schema" not in ctx,
                    "target": "init",
                }
            },
            "core": {
                "states": {
                    "drizzle": {
                        "invoke": {
                            "src": drizzle_actor,
                            "input_fn": lambda ctx: (ctx["typespec_schema"].typespec,),
                            "on_done": {
                                "target": "typescript",
                                "actions": [lambda ctx, event: ctx.update({"drizzle_schema": event})],
                            },
                            "on_error": {
                                "target": "failure",
                                "actions": [lambda ctx, event: ctx.update({"error": event})],
                            },
                        }
                    },
                    "typescript": {
                        "invoke": {
                            "src": typescript_actor,
                            "input_fn": lambda ctx: (ctx["typespec_schema"].typespec,),
                            "on_done": {
                                "target": "handler_tests",
                                "actions": [lambda ctx, event: ctx.update({"typescript_schema": event})],
                            },
                            "on_error": {
                                "target": "failure",
                                "actions": [lambda ctx, event: ctx.update({"error": event})],
                            },
                        }
                    },
                    "handler_tests": {
                        "invoke": {
                            "src": handler_tests_actor,
                            "input_fn": lambda ctx: (ctx["typescript_schema"].functions, ctx["typescript_schema"].typescript_schema, ctx["drizzle_schema"].drizzle_schema),
                            "on_done": {
                                "target": "handlers",
                                "actions": [lambda ctx, event: ctx.update({"handler_tests": event})],
                            },
                            "on_error": {
                                "target": "failure",
                                "actions": [lambda ctx, event: ctx.update({"error": event})],
                            },
                        }
                    },
                    "handlers": {
                        "invoke": {
                            "src": handlers_actor,
                            "input_fn": lambda ctx: (ctx["typescript_schema"].functions, ctx["typescript_schema"].typescript_schema, ctx["drizzle_schema"].drizzle_schema, ctx["handler_tests"]),
                            "on_done": {
                                "target": "complete",
                                "actions": [lambda ctx, event: ctx.update({"handlers": event})],
                            },
                            "on_error": {
                                "target": "failure",
                                "actions": [lambda ctx, event: ctx.update({"error": event})],
                            },
                        }
                    },
                },
                "always": {
                    "guard": lambda ctx: "typespec_schema" in ctx,
                    "target": "drizzle",
                }
            },
            "complete": {
                "on": {
                    "PROMPT": "edit_application", # pop user prompt from ctx and jump into init typespec?
                }
            },
            "failure": {
                "entry": [fail_state],
            },
            "edit_application": {
                "entry": [not_impl],
            },
        }
    }

    fsm = statemachine.StateMachine(machine_states, {"application_description": "Make me a greeting bot"})

    fsm.send("START")
    fsm.send("CONFIRM")

    print(fsm.context)
    print("Done")

    # serialize and load state for edits later (still need to recreate actors though)
    import pickle
    with open("fsm_context.pkl", "wb") as f:
        pickle.dump(fsm.context, f, pickle.HIGHEST_PROTOCOL)