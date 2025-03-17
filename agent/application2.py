import os
import socket
import jinja2
from typing import Callable
from functools import partial
from anthropic import AnthropicBedrock
from anthropic.types import MessageParam
from compiler.core import Compiler
from tracing_client import TracingClient
from langfuse import Langfuse
from langfuse.client import StatefulGenerationClient
from langfuse.decorators import langfuse_context, observe
from policies import common, app_testcases, refine
import policies.typespec as policies_typespec
import policies.handlers as policies_handlers
import policies.handler_tests as policies_handler_tests
from policies.typespec import TypespecTaskNode
from fsm_core import typespec, drizzle, typescript, handlers, handler_tests
from core import feature_flags
from core.datatypes import *
from fsm_core.common import AgentState, Node, AgentMachine, dfs_rewind

class Context:
    def __init__(self, compiler: Compiler, jinja_env: jinja2.Environment):
        self.compiler = compiler
        self.jinja_env = jinja_env

def bedrock_claude(
    client: AnthropicBedrock,
    messages: list[MessageParam],
    model: str = "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    max_tokens: int = 8192,
    temperature: float = 1.0,
    thinking_budget: int = 0,
):
    if thinking_budget > 0:
        thinking_config = {
            "type": "enabled",
            "budget_tokens": thinking_budget,
        }
    else:
        thinking_config = {
            "type": "disabled",
        }
    return client.messages.create(
        max_tokens=max_tokens + thinking_budget,
        model=model,
        messages=messages,
        temperature=temperature,
        thinking=thinking_config,
    )

def span_claude_bedrock(
    client: AnthropicBedrock,
    messages: list[MessageParam],
    generation: StatefulGenerationClient,
    model: str = "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    max_tokens: int = 8192,
    temperature: float = 1.0,
    thinking_budget: int = 0,
):
    generation.update(
        name="Anthropic-generation",
        input=messages,
        model=model,
        model_parameters={
            "maxTokens": max_tokens,
            "temperature": temperature,
            "thinkingBudget": thinking_budget,
        },
    )
    completion = bedrock_claude(
        client,
        messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        thinking_budget=thinking_budget,
    )
    generation.end(
        output=MessageParam(role="assistant", content=completion.content),
        usage={
            "input": completion.usage.input_tokens,
            "output": completion.usage.output_tokens,
        }
    )
    return completion

def langfuse_expand(
    context: Context,
    llm_fn: Callable[[list[MessageParam], StatefulGenerationClient], MessageParam],
    langfuse: Langfuse,
    langfuse_parent_trace_id: str,
    langfuse_parent_observation_id: str,
) -> Callable[[Node[AgentState]], Node[AgentState]]:
    def expand_fn(node: Node[AgentState]) -> Node[AgentState]:
        span = langfuse.span(
            trace_id=langfuse_parent_trace_id,
            parent_observation_id=node._id if node.parent else langfuse_parent_observation_id,
            name="expand",
        )
        message = llm_fn([m for n in node.get_trajectory() for m in n.data.thread], span.generation())
        new_node = Node(AgentState(node.data.inner.on_message(context, message), message), parent=node, id=span.id)
        span.end(
            output=new_node.data.inner.__dict__,
            metadata={"child_node_id": new_node._id, "parent_node_id": node._id},
        )
        return new_node
    return expand_fn

def agent_dfs(
    init: AgentMachine,
    context: Context,
    llm_fn: Callable[[list[MessageParam], StatefulGenerationClient], MessageParam],
    langfuse: Langfuse,
    langfuse_parent_trace_id: str,
    langfuse_parent_observation_id: str,
    max_depth: int = 5,
    max_width: int = 3,
    max_budget: int | None = None,
) -> tuple[Node[AgentState] | None, Node[AgentState]]:
    span = langfuse.span(
        name="dfs",
        trace_id=langfuse_parent_trace_id,
        parent_observation_id=langfuse_parent_observation_id,
        input=init.__dict__,
    )
    root = Node(AgentState(init, None), id=span.id)
    expand_fn = langfuse_expand(context, llm_fn, langfuse, langfuse_parent_trace_id, span.id)
    solution = dfs_rewind(root, expand_fn, max_depth, max_width, max_budget)
    span.end(
        output=solution.data.inner.__dict__ if solution else None,
        metadata={"child_node_id": root._id}
    )
    return solution, root

def solve_agent(
    init: AgentMachine,
    trace_name: str,
    client: AnthropicBedrock,
    langfuse: Langfuse,
    context: Context,
    max_depth: int = 3,
    max_width: int = 2,
):
    def llm_fn(
        messages: list[MessageParam],
        generation: StatefulGenerationClient,
    ) -> MessageParam:
        completion = span_claude_bedrock(client, messages, generation)
        return MessageParam(role="assistant", content=completion.content)

    @observe(capture_input=False, capture_output=False, name=trace_name)
    def _inner():
        trace_id = langfuse_context.get_current_trace_id()
        observation_id = langfuse_context.get_current_observation_id()
        assert trace_id and observation_id, "missing trace_id or observation_id"
        langfuse_context.update_current_trace(name=trace_name)
        solution, root = agent_dfs(
            init,
            context,
            llm_fn,
            langfuse,
            trace_id,
            observation_id,
            max_depth=max_depth,
            max_width=max_width,
        )
        return solution, root
    return _inner()

class Application2:
    def __init__(self, client: AnthropicBedrock, compiler: Compiler, branch_factor: int = 2, max_depth: int = 4, thinking_budget: int = 0):
        self.client = client
        self.compiler = compiler
        self.jinja_env = jinja2.Environment()
        self.BRANCH_FACTOR = branch_factor
        self.MAX_DEPTH = max_depth
        self.thinking_budget = thinking_budget
        self.langfuse = Langfuse()

    @observe(capture_output=False)
    def prepare_bot(self, prompts: list[str], bot_id: str | None = None, capabilities: list[str] | None = None, *args, **kwargs):
        langfuse_context.update_current_trace(user_id=os.environ.get("USER_ID", socket.gethostname()))
        if bot_id is not None:
            langfuse_context.update_current_observation(metadata={"bot_id": bot_id})

        print("Compiling TypeSpec...")
        typespec_result = self._make_typespec(prompts)
        if typespec_result.error_output is not None:
            raise Exception(f"Failed to generate typespec: {typespec_result.error_output}")
        typespec_definitions = typespec_result.typespec_definitions

        if feature_flags.gherkin:
            print("Compiling Gherkin Test Cases...")
            gherkin = self._make_testcases(typespec_definitions)
            if gherkin.error_output is not None:
                raise Exception(f"Failed to generate gherkin test cases: {gherkin.error_output}")
        else:
            gherkin = GherkinOut(None, None, None)

        langfuse_context.update_current_observation(
            output = {
                "typespec": typespec_result.__dict__,
                "gherkin": gherkin.__dict__,
                "scenarios": {f.name: f.scenario for f in typespec_result.llm_functions},
                "capabilities": capabilities,
            },
            metadata = {
                "typespec_ok": typespec_result.error_output is None,
                "gherkin_ok": gherkin.error_output is None,
            },
        )
        capabilities_out = CapabilitiesOut(capabilities if capabilities is not None else [], None)
        return ApplicationOut(refined_description=None,
                              capabilities=capabilities_out, 
                              typespec=typespec_result,
                              drizzle=None,
                              handlers={}, 
                              handler_tests={}, 
                              typescript_schema=None,
                              gherkin=gherkin,
                              trace_id=langfuse_context.get_current_trace_id())
    
    @observe(capture_output=False)
    def update_bot(self, typespecSchema: str, bot_id: str | None = None, capabilities: list[str] | None = None, *args, **kwargs):
        langfuse_context.update_current_trace(user_id=os.environ.get("USER_ID", socket.gethostname()))
        if bot_id is not None:
            langfuse_context.update_current_observation(metadata={"bot_id": bot_id})
        
        # Create a refined description from the typespec
        print("Creating prompt from TypeSpec...")
        app_prompt = RefineOut(typespecSchema, None)
        
        # We already have the typespec, so create a TypespecOut object
        print("Processing TypeSpec...")
        
        # TODO: fix with separating typespec parsing from typespec generation
        _, typespec_definitions, llm_functions = TypespecTaskNode.parse_output(f"<reasoning>...</reasoning><typespec>{typespecSchema}</typespec>")
        
        typespec_out = TypespecOut(
            reasoning="Imported from existing typespec",
            typespec_definitions=typespec_definitions,
            llm_functions=llm_functions,
            error_output=None
        )
        
        # Process all steps sequentially using FSM approach
        context = Context(self.compiler, self.jinja_env)
        solver = partial(solve_agent, 
                        client=self.client, 
                        langfuse=self.langfuse, 
                        context=context,
                        max_depth=self.MAX_DEPTH, 
                        max_width=self.BRANCH_FACTOR)

        if feature_flags.gherkin:
            print("Generating Gherkin Test Cases...")
            gherkin_start = app_testcases.Entry(typespec_definitions)
            gherkin_result, _gherkin_root = solver(gherkin_start, "solve_gherkin")
            if gherkin_result and isinstance(gherkin_result.data.inner, app_testcases.Success):
                gherkin = GherkinOut(gherkin_result.data.inner.reasoning, 
                                     gherkin_result.data.inner.gherkin, None)
            else:
                gherkin = GherkinOut(None, None, "Failed to generate gherkin test cases")
        else:
            gherkin = GherkinOut(None, None, None)
        
        print("Generating Typescript Schema...")
        ts_start = typescript.Entry(typespec_definitions)
        ts_result, _ts_root = solver(ts_start, "solve_typescript")
        if not (ts_result and isinstance(ts_result.data.inner, typescript.Success)):
            raise Exception("Failed to generate typescript schema")
        
        typescript_functions = [TypescriptFunction(
            name=f.name, 
            argument_type=f.argument_type, 
            argument_schema=f.argument_schema, 
            return_type=f.return_type) 
            for f in ts_result.data.inner.functions]
        
        typescript_schema = TypescriptOut(
            ts_result.data.inner.reasoning, 
            ts_result.data.inner.typescript_schema, 
            typescript_functions, 
            None)
        
        print("Generating Drizzle Schema...")
        dz_start = drizzle.Entry(typespec_definitions)
        dz_result, _dz_root = solver(dz_start, "solve_drizzle")
        if not (dz_result and isinstance(dz_result.data.inner, drizzle.Success)):
            raise Exception("Failed to generate drizzle schema")
            
        drizzle_out = DrizzleOut(
            dz_result.data.inner.reasoning, 
            dz_result.data.inner.drizzle_schema, 
            None)
        
        print("Generating Handler Tests and Handlers...")
        handler_test_dict = {}
        handlers_dict = {}
        
        for function in typescript_functions:
            # Generate handler tests
            print(f"Generating tests for {function.name}...")
            tests_start = handler_tests.Entry(
                function.name, 
                typescript_schema.typescript_schema, 
                drizzle_out.drizzle_schema)
            
            tests_result, _tests_root = solver(tests_start, f"solve_handler_tests_{function.name}")
            
            if tests_result and isinstance(tests_result.data.inner, handler_tests.Success):
                handler_test_dict[function.name] = HandlerTestsOut(
                    function.name, 
                    tests_result.data.inner.source, 
                    None)
                
                # Generate handler implementation using the test
                print(f"Generating handler for {function.name}...")
                handler_start = handlers.Entry(
                    function.name, 
                    typescript_schema.typescript_schema, 
                    drizzle_out.drizzle_schema, 
                    tests_result.data.inner.source)
                
                handler_result, _handler_root = solver(handler_start, f"solve_handlers_{function.name}")
                
                if handler_result and isinstance(handler_result.data.inner, handlers.Success):
                    handlers_dict[function.name] = HandlerOut(
                        function.name,
                        handler_result.data.inner.source,
                        function.argument_schema,
                        None)
                else:
                    handlers_dict[function.name] = HandlerOut(
                        function.name,
                        None,
                        function.argument_schema, 
                        "Failed to generate handler")
            else:
                handler_test_dict[function.name] = HandlerTestsOut(
                    function.name, 
                    None, 
                    "Failed to generate handler tests")
                handlers_dict[function.name] = HandlerOut(
                    function.name,
                    None,
                    function.argument_schema, 
                    "Failed to generate handler due to missing tests")
        
        updated_capabilities = capabilities if capabilities is not None else []
        
        langfuse_context.update_current_observation(
            output = {
                "refined_description": app_prompt.__dict__,
                "typespec": typespec_out.__dict__,
                "typescript_schema": typescript_schema.__dict__,
                "drizzle": drizzle_out.__dict__,
                "handlers": {k: v.__dict__ for k, v in handlers_dict.items()},
                "handler_tests": {k: v.__dict__ for k, v in handler_test_dict.items()},
                "gherkin": gherkin.__dict__,
                "scenarios": {f.name: f.scenario for f in typespec_out.llm_functions},
                "capabilities": updated_capabilities,
            },
            metadata = {
                "refined_description_ok": app_prompt.error_output is None,
                "typespec_ok": True,  # We trust the provided typespec
                "typescript_schema_ok": typescript_schema.error_output is None,
                "drizzle_ok": drizzle_out.error_output is None,
                "all_handlers_ok": all(handler.error_output is None for handler in handlers_dict.values()),
                "all_handler_tests_ok": all(handler_test.error_output is None for handler_test in handler_test_dict.values()),
                "gherkin_ok": gherkin.error_output is None,
                "is_update": True,
            },
        )
        
        capabilities_out = CapabilitiesOut(updated_capabilities, None)
        return ApplicationOut(
            app_prompt, 
            capabilities_out, 
            typespec_out, 
            drizzle_out, 
            handlers_dict, 
            handler_test_dict, 
            typescript_schema, 
            gherkin, 
            langfuse_context.get_current_trace_id()
        )
    
    @observe(capture_output=False)
    def create_bot(self, application_description: str, bot_id: str | None = None, capabilities: list[str] | None = None, *args, **kwargs):
        langfuse_context.update_current_trace(user_id=os.environ.get("USER_ID", socket.gethostname()))
        if bot_id is not None:
            langfuse_context.update_current_observation(metadata={"bot_id": bot_id})

        context = Context(self.compiler, self.jinja_env)
        solver = partial(solve_agent, 
                       client=self.client, 
                       langfuse=self.langfuse, 
                       context=context,
                       max_depth=self.MAX_DEPTH, 
                       max_width=self.BRANCH_FACTOR)

        if feature_flags.refine_initial_prompt:
            print("Refining Initial Description...")
            refine_start = refine.Entry(application_description)
            refine_result, _refine_root = solver(refine_start, "solve_refine")
            if refine_result and isinstance(refine_result.data.inner, refine.Success):
                app_prompt = RefineOut(refine_result.data.inner.requirements, None)
            else:
                app_prompt = RefineOut(application_description, "Failed to refine prompt")
        else:
            print("Skipping Initial Description Refinement")
            app_prompt = RefineOut(application_description, None)

        print("Compiling TypeSpec...")
        tsp_start = typespec.Entry(app_prompt.refined_description)
        tsp_result, _tsp_root = solver(tsp_start, "solve_typespec")
        if not (tsp_result and isinstance(tsp_result.data.inner, typespec.Success)):
            raise Exception("Failed to generate typespec")
        
        typespec_out = TypespecOut(
            tsp_result.data.inner.reasoning, 
            tsp_result.data.inner.typespec, 
            tsp_result.data.inner.llm_functions, 
            None)
        
        typespec_definitions = typespec_out.typespec_definitions

        if feature_flags.gherkin:
            print("Compiling Gherkin Test Cases...")
            gherkin_start = app_testcases.Entry(typespec_definitions)
            gherkin_result, _gherkin_root = solver(gherkin_start, "solve_gherkin")
            if gherkin_result and isinstance(gherkin_result.data.inner, app_testcases.Success):
                gherkin = GherkinOut(gherkin_result.data.inner.reasoning, 
                                     gherkin_result.data.inner.gherkin, None)
            else:
                gherkin = GherkinOut(None, None, "Failed to generate gherkin test cases")
        else:
            gherkin = GherkinOut(None, None, None)

        print("Compiling Typescript Schema Definitions...")
        ts_start = typescript.Entry(typespec_definitions)
        ts_result, _ts_root = solver(ts_start, "solve_typescript")
        if not (ts_result and isinstance(ts_result.data.inner, typescript.Success)):
            raise Exception("Failed to generate typescript schema")
        
        typescript_functions = [TypescriptFunction(
            name=f.name, 
            argument_type=f.argument_type, 
            argument_schema=f.argument_schema, 
            return_type=f.return_type) 
            for f in ts_result.data.inner.functions]
        
        typescript_schema = TypescriptOut(
            ts_result.data.inner.reasoning, 
            ts_result.data.inner.typescript_schema, 
            typescript_functions, 
            None)

        print("Compiling Drizzle...")
        dz_start = drizzle.Entry(typespec_definitions)
        dz_result, _dz_root = solver(dz_start, "solve_drizzle")
        if not (dz_result and isinstance(dz_result.data.inner, drizzle.Success)):
            raise Exception("Failed to generate drizzle schema")
            
        drizzle_out = DrizzleOut(
            dz_result.data.inner.reasoning, 
            dz_result.data.inner.drizzle_schema, 
            None)

        print("Compiling Handler Tests and Handlers...")
        handler_test_dict = {}
        handlers_dict = {}
        
        for function in typescript_functions:
            # Generate handler tests
            print(f"Generating tests for {function.name}...")
            tests_start = handler_tests.Entry(
                function.name, 
                typescript_schema.typescript_schema, 
                drizzle_out.drizzle_schema)
            
            tests_result, _tests_root = solver(tests_start, f"solve_handler_tests_{function.name}")
            
            if tests_result and isinstance(tests_result.data.inner, handler_tests.Success):
                handler_test_dict[function.name] = HandlerTestsOut(
                    function.name, 
                    tests_result.data.inner.source, 
                    None)
                
                # Generate handler implementation using the test
                print(f"Generating handler for {function.name}...")
                handler_start = handlers.Entry(
                    function.name, 
                    typescript_schema.typescript_schema, 
                    drizzle_out.drizzle_schema, 
                    tests_result.data.inner.source)
                
                handler_result, _handler_root = solver(handler_start, f"solve_handlers_{function.name}")
                
                if handler_result and isinstance(handler_result.data.inner, handlers.Success):
                    handlers_dict[function.name] = HandlerOut(
                        function.name,
                        handler_result.data.inner.source,
                        function.argument_schema,
                        None)
                else:
                    handlers_dict[function.name] = HandlerOut(
                        function.name,
                        None,
                        function.argument_schema, 
                        "Failed to generate handler")
            else:
                handler_test_dict[function.name] = HandlerTestsOut(
                    function.name, 
                    None, 
                    "Failed to generate handler tests")
                handlers_dict[function.name] = HandlerOut(
                    function.name,
                    None,
                    function.argument_schema, 
                    "Failed to generate handler due to missing tests")

        langfuse_context.update_current_observation(
            output = {
                "refined_description": app_prompt.__dict__,
                "typespec": typespec_out.__dict__,
                "typescript_schema": typescript_schema.__dict__,
                "drizzle": drizzle_out.__dict__,
                "handlers": {k: v.__dict__ for k, v in handlers_dict.items()},
                "handler_tests": {k: v.__dict__ for k, v in handler_test_dict.items()},
                "gherkin": gherkin.__dict__,
                "scenarios": {f.name: f.scenario for f in typespec_out.llm_functions},
                "capabilities": capabilities,
            },
            metadata = {
                "refined_description_ok": app_prompt.error_output is None,
                "typespec_ok": typespec_out.error_output is None,
                "typescript_schema_ok": typescript_schema.error_output is None,
                "drizzle_ok": drizzle_out.error_output is None,
                "all_handlers_ok": all(handler.error_output is None for handler in handlers_dict.values()),
                "all_handler_tests_ok": all(handler_test.error_output is None for handler_test in handler_test_dict.values()),
                "gherkin_ok": gherkin.error_output is None,
            },
        )
        capabilities_out = CapabilitiesOut(capabilities if capabilities is not None else [], None)
        return ApplicationOut(
            app_prompt, 
            capabilities_out, 
            typespec_out, 
            drizzle_out, 
            handlers_dict, 
            handler_test_dict, 
            typescript_schema, 
            gherkin, 
            langfuse_context.get_current_trace_id()
        )

    @observe(capture_input=False, capture_output=False)
    def _make_typespec(self, prompts: list[str]):
        """Legacy method for prepare_bot functionality"""
        content = self.jinja_env.from_string(policies_typespec.PROMPT).render(user_requests=prompts)
        message = {"role": "user", "content": content}
        with policies_typespec.TypespecTaskNode.platform(self.client, self.compiler, self.jinja_env):
            tsp_data = policies_typespec.TypespecTaskNode.run([message], init=True)
            tsp_root = policies_typespec.TypespecTaskNode(tsp_data)
            tsp_solution = common.bfs(tsp_root, self.MAX_DEPTH, self.BRANCH_FACTOR, self.MAX_WORKERS)
        match tsp_solution.data.output:
            case Exception() as e:
                return TypespecOut(None, None, None, str(e))
            case output:
                return TypespecOut(output.reasoning, output.typespec_definitions, output.llm_functions, output.error_or_none)

    @observe(capture_input=False, capture_output=False)
    def _make_testcases(self, typespec_definitions: str):
        """Legacy method for prepare_bot functionality"""
        content = self.jinja_env.from_string(app_testcases.PROMPT).render(typespec_schema=typespec_definitions)
        message = {"role": "user", "content": content}
        with app_testcases.GherkinTaskNode.platform(self.client, self.compiler, self.jinja_env):
            tc_data = app_testcases.GherkinTaskNode.run([message])
            tc_root = app_testcases.GherkinTaskNode(tc_data)
            tc_solution = common.bfs(tc_root, self.MAX_DEPTH, self.BRANCH_FACTOR, self.MAX_WORKERS)
        match tc_solution.data.output:
            case Exception() as e:
                return GherkinOut(None, None, str(e))
            case output:
                return GherkinOut(output.reasoning, output.gherkin, output.error_or_none)