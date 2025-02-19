from typing import TypedDict
import os
import jinja2
import concurrent.futures
from dataclasses import dataclass
from anthropic import AnthropicBedrock
from shutil import copytree, ignore_patterns
from compiler.core import Compiler
from tracing_client import TracingClient
from core.interpolator import Interpolator
from langfuse.decorators import langfuse_context, observe
from policies import common, handlers, typespec, drizzle, typescript, router, app_testcases, handler_tests
from core import feature_flags

@dataclass
class TypespecOut:
    reasoning: str | None
    typespec_definitions: str | None
    llm_functions: list[str] | None
    error_output: str | None

@dataclass
class TypescriptFunction:
    name: str
    argument_type: str
    argument_schema: str
    return_type: str

@dataclass
class TypescriptOut:
    reasoning: str | None
    typescript_schema: str | None
    functions: list[TypescriptFunction] | None
    error_output: str | None

@dataclass
class GherkinOut:
    reasoning: str | None
    gherkin: str | None
    error_output: str | None

@dataclass
class DrizzleOut:
    reasoning: str | None
    drizzle_schema: str | None
    error_output: str | None


class RouterFunc(TypedDict):
    name: str
    description: str
    examples: list[str]


@dataclass
class RouterOut:
    functions: list[RouterFunc] | None
    error_output: str | None


@dataclass
class HandlerOut:
    name: str | None
    handler: str | None
    error_output: str | None


@dataclass
class ApplicationOut:
    typespec: TypespecOut
    drizzle: DrizzleOut
    router: RouterOut
    handlers: dict[str, HandlerOut]
    typescript_schema: TypescriptOut
    gherkin: GherkinOut
    application: dict[str, dict]


class Application:
    def __init__(self, client: AnthropicBedrock, compiler: Compiler, template_dir: str = "templates", output_dir: str = "app_output", 
                 branch_factor: int = 2, max_depth: int = 4, max_workers: int = 5):
        self.client = TracingClient(client)
        self.compiler = compiler
        self.jinja_env = jinja2.Environment()
        self.template_dir = template_dir
        self.iteration = 0
        self.output_dir = os.path.join(output_dir, "generated")
        self._model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        self.BRANCH_FACTOR = branch_factor
        self.MAX_DEPTH = max_depth
        self.MAX_WORKERS = max_workers
    
    @observe(capture_output=False)
    def create_bot(self, application_description: str, bot_id: str | None = None):
        if bot_id is not None:
            langfuse_context.update_current_observation(metadata={"bot_id": bot_id})

        print("Compiling TypeSpec...")
        typespec = self._make_typespec(application_description)
        if typespec.error_output is not None:
            raise Exception(f"Failed to generate typespec: {typespec.error_output}")
        typespec_definitions = typespec.typespec_definitions

        if feature_flags.gherkin:
            print("Compiling Gherkin Test Cases...")
            gherkin = self._make_testcases(typespec_definitions)
            if gherkin.error_output is not None:
                raise Exception(f"Failed to generate gherkin test cases: {gherkin.error_output}")
        else:
            gherkin = GherkinOut(None, None, None)

        print("Compiling Typescript Schema Definitions...")
        typescript_schema = self._make_typescript_schema(typespec_definitions)
        if typescript_schema.error_output is not None:
            raise Exception(f"Failed to generate typescript schema: {typescript_schema.error_output}")
        typescript_schema_definitions = typescript_schema.typescript_schema
        typescript_functions = typescript_schema.functions

        print("Compiling Drizzle...")
        drizzle = self._make_drizzle(typespec_definitions)
        if drizzle.error_output is not None:
            raise Exception(f"Failed to generate drizzle schema: {drizzle.error_output}")
        drizzle_schema = drizzle.drizzle_schema

        print("Generating Router...")
        router = self._make_router(typespec_definitions)
        if router.error_output is not None:
            raise Exception(f"Failed to generate router: {router.error_output}")

        if feature_flags.gherkin:
            print("Compiling Handler Tests...")
            #handler_interfaces, handler_tests = self._make_handler_tests(llm_functions, typespec_definitions, gherkin.gherkin, typescript_schema_definitions, drizzle_schema)
        else:
            handler_tests = {}
            handler_interfaces = {}
            
        print("Compiling Handlers...")
        handlers = self._make_handlers(typescript_functions, handler_interfaces, handler_tests, typespec_definitions, typescript_schema_definitions, drizzle_schema)
        
        langfuse_context.update_current_observation(
            output = {
                "typespec": typespec.__dict__,
                "typescript_schema": typescript_schema.__dict__,
                "drizzle": drizzle.__dict__,
                "router": router.__dict__,
                "handlers": {k: v.__dict__ for k, v in handlers.items()},
                "handler_tests": {k: v.__dict__ for k, v in handler_tests.items()},
                "gherkin": gherkin.__dict__,
            },
            metadata = {
                "typespec_ok": typespec.error_output is None,
                "typescript_schema_ok": typescript_schema.error_output is None,
                "drizzle_ok": drizzle.error_output is None,
                "router_ok": router.error_output is None,
                "all_handlers_ok": all(handler.error_output is None for handler in handlers.values()),
                "all_handler_tests_ok": all(handler_test.error_output is None for handler_test in handler_tests.values()),
                "gherkin_ok": gherkin.error_output is None,
            },
        )

        print("Generating Application...")
        application = self._make_application(typespec_definitions, typescript_schema_definitions, drizzle_schema, router.functions, handlers, handler_tests, gherkin.gherkin, typescript_functions)
        return ApplicationOut(typespec, drizzle, router, handlers, typescript_schema, gherkin, application)

    def _make_application(self, typespec_definitions: str, typescript_schema: str, drizzle_schema: str, user_functions: list[dict], handlers: dict[str, HandlerOut], handler_tests: dict[str, HandlerOut], gherkin: str, typescript_functions: list[TypescriptFunction]):
        self.iteration += 1
        self.generation_dir = os.path.join(self.output_dir, f"generation-{self.iteration}")

        copytree(self.template_dir, self.generation_dir, ignore=ignore_patterns('*.pyc', '__pycache__', 'node_modules'))
        
        with open(os.path.join(self.generation_dir, "tsp_schema", "main.tsp"), "a") as f:
            f.write("\n")
            f.write(typespec_definitions)
        

        with open(os.path.join(self.generation_dir, "tsp_schema", "main.tsp"), "a") as f:
            f.write("\n")
            f.write(typespec_definitions)
        
        with open(os.path.join(self.generation_dir, "app_schema/src/db/schema", "application.ts"), "a") as f:
            f.write("\n")
            f.write(drizzle_schema)

        with open(os.path.join(self.generation_dir, "app_schema/src/common", "schema.ts"), "a") as f:
            f.write(typescript_schema)
        
        interpolator = Interpolator(self.generation_dir)

        fn_map = {f.name: f for f in typescript_functions}
        raw_handlers = {k: {
            "code": v.handler,
            "name": v.name,
            "argument_type": fn_map[k].argument_type,
            "argument_schema": fn_map[k].argument_schema,
            } for k, v in handlers.items()
        }
        handler_tests = {k: v.handler_tests for k, v in handler_tests.items()}
        return interpolator.interpolate_all(raw_handlers, handler_tests, user_functions, gherkin)

    @observe(capture_input=False, capture_output=False)
    def _make_typescript_schema(self, typespec_definitions: str):
        content = self.jinja_env.from_string(typescript.PROMPT).render(typespec_definitions=typespec_definitions)
        message = {"role": "user", "content": content}
        with typescript.TypescriptTaskNode.platform(self.client, self.compiler, self.jinja_env):
            ts_data = typescript.TypescriptTaskNode.run([message])
            ts_root = typescript.TypescriptTaskNode(ts_data)
            ts_solution = common.bfs(ts_root, self.MAX_DEPTH, self.BRANCH_FACTOR, self.MAX_WORKERS)
        match ts_solution.data.output:
            case Exception() as e:
                return TypescriptOut(None, None, None, str(e))
            case output:
                functions = [TypescriptFunction(name=f.name, argument_type=f.argument_type, argument_schema=f.argument_schema, return_type=f.return_type) for f in output.functions]
                return TypescriptOut(output.reasoning, output.typescript_schema, functions, output.error_or_none)

    @observe(capture_input=False, capture_output=False)
    def _make_testcases(self, typespec_definitions: str):
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
   
    @observe(capture_input=False, capture_output=False)
    def _make_typespec(self, application_description: str):
        BRANCH_FACTOR, MAX_DEPTH, MAX_WORKERS = 2, 4, 5

        content = self.jinja_env.from_string(typespec.PROMPT).render(application_description=application_description)
        message = {"role": "user", "content": content}
        with typespec.TypespecTaskNode.platform(self.client, self.compiler, self.jinja_env):
            tsp_data = typespec.TypespecTaskNode.run([message])
            tsp_root = typespec.TypespecTaskNode(tsp_data)
            tsp_solution = common.bfs(tsp_root, MAX_DEPTH, BRANCH_FACTOR, MAX_WORKERS)
        match tsp_solution.data.output:
            case Exception() as e:
                return TypespecOut(None, None, None, str(e))
            case output:
                return TypespecOut(output.reasoning, output.typespec_definitions, output.llm_functions, output.error_or_none)
    
    @observe(capture_input=False, capture_output=False)
    def _make_drizzle(self, typespec_definitions: str):
        content = self.jinja_env.from_string(drizzle.PROMPT).render(typespec_definitions=typespec_definitions)
        message = {"role": "user", "content": content}
        with drizzle.DrizzleTaskNode.platform(self.client, self.compiler, self.jinja_env):
            dzl_data = drizzle.DrizzleTaskNode.run([message])
            dzl_root = drizzle.DrizzleTaskNode(dzl_data)
            dzl_solution = common.bfs(dzl_root, self.MAX_DEPTH, self.BRANCH_FACTOR, self.MAX_WORKERS)
        match dzl_solution.data.output:
            case Exception() as e:
                return DrizzleOut(None, None, str(e))
            case output:
                return DrizzleOut(output.reasoning, output.drizzle_schema, output.error_or_none)

    @observe(capture_input=False, capture_output=False)
    def _make_router(self, typespec_definitions: str):
        content = self.jinja_env.from_string(router.PROMPT).render(typespec_definitions=typespec_definitions)
        message = {"role": "user", "content": content}
        with router.RouterTaskNode.platform(self.client, self.jinja_env):
            router_data = router.RouterTaskNode.run([message], typespec_definitions=typespec_definitions)
            router_root = router.RouterTaskNode(router_data)
            router_solution = common.bfs(router_root)
        match router_solution.data.output:
            case Exception() as e:
                return RouterOut(None, str(e))
            case output:
                return RouterOut(output.functions, None)
    
    @observe(capture_input=False, capture_output=False)
    def _make_handler(
        self,
        content: str,
        function_name: str,
        argument_type: str,
        argument_schema: str,
        typespec_definitions: str,
        typescript_schema: str,
        drizzle_schema: str,
        *args,
        **kwargs,
    ) -> handlers.HandlerTaskNode:
        prompt_params = {
            "function_name": function_name,
            "argument_type": argument_type,
            "argument_schema": argument_schema,
            "typespec_schema": typespec_definitions,
            "typescript_schema": typescript_schema,
            "drizzle_schema": drizzle_schema,
        }
        message = {"role": "user", "content": content}
        output = handlers.HandlerTaskNode.run([message], **prompt_params)
        root_node = handlers.HandlerTaskNode(output)
        solution = common.bfs(root_node, self.MAX_DEPTH, self.BRANCH_FACTOR, self.MAX_WORKERS, **prompt_params)
        return solution
    
    @observe(capture_input=False, capture_output=False)
    def _make_handler_tests_and_interfaces(self, llm_functions: list[str], test_cases: str, typescript_schema: str, drizzle_schema: str):
        raise NotImplementedError("Not implemented")

    @observe(capture_input=False, capture_output=False)
    def _make_handler_tests(self, llm_functions: list[str], typespec_definitions: str, test_cases: str, typescript_schema: str, drizzle_schema: str):
        trace_id = langfuse_context.get_current_trace_id()
        observation_id = langfuse_context.get_current_observation_id()
        results: dict[str, HandlerOut] = {}
        with handlers.HandlerTaskNode.platform(self.client, self.compiler, self.jinja_env):
            with concurrent.futures.ThreadPoolExecutor(self.MAX_WORKERS) as executor:
                future_to_handler: dict[concurrent.futures.Future[handlers.HandlerTaskNode], str] = {}
                for function_name in llm_functions:

                    test_prompt_params = {
                        "function_name": function_name,
                        "typespec_schema": typespec_definitions,
                        "typescript_schema": typescript_schema,
                        "drizzle_schema": drizzle_schema,
                    }
                    content = self.jinja_env.from_string(handler_tests.PROMPT).render(**test_prompt_params)
                    future_to_handler[executor.submit(
                        self._make_handler_tests_and_interfaces,
                        content,
                        function_name,
                        test_cases,
                        typescript_schema,
                        drizzle_schema,
                        langfuse_parent_trace_id=trace_id,
                        langfuse_parent_observation_id=observation_id,
                    )] = function_name
                for future in concurrent.futures.as_completed(future_to_handler):
                    function_name, result = future_to_handler[future], future.result()
                    match result.data.output:
                        case Exception() as e:
                            results[function_name] = HandlerOut(None, str(e))
                        case output:
                            results[function_name] = HandlerOut(output.handler_tests, output.handler_interfaces, None)
        return results
    
    @observe(capture_input=False, capture_output=False)
    def _make_handlers(self, llm_functions: list[typescript.FunctionDeclaration], handler_interfaces: dict[str], handler_tests: dict[str], typespec_definitions: str, typescript_schema: str, drizzle_schema: str):
        trace_id = langfuse_context.get_current_trace_id()
        observation_id = langfuse_context.get_current_observation_id()
        results: dict[str, HandlerOut] = {}
        with handlers.HandlerTaskNode.platform(self.client, self.compiler, self.jinja_env):
            with concurrent.futures.ThreadPoolExecutor(self.MAX_WORKERS) as executor:
                future_to_handler: dict[concurrent.futures.Future[handlers.HandlerTaskNode], str] = {}
                for function in llm_functions:
                    #handler_interface_set = handler_interfaces.get(function_name, None)
                    #handler_test_suite = handler_tests.get(function_name, None)
                    handler_prompt_params = {
                        "function_name": function.name,
                        #"handler_interfaces": handler_interface_set,
                        #"handler_tests": handler_test_suite,
                        "argument_type": function.argument_type,
                        "argument_schema": function.argument_schema,
                        "typespec_schema": typespec_definitions,
                        "typescript_schema": typescript_schema,
                        "drizzle_schema": drizzle_schema,
                    }
                    content = self.jinja_env.from_string(handlers.PROMPT).render(**handler_prompt_params)
                    future_to_handler[executor.submit(
                        self._make_handler,
                        content,
                        function.name,
                        #handler_interfaces,
                        #handler_tests,
                        function.argument_type,
                        function.argument_schema,
                        typespec_definitions,
                        typescript_schema,
                        drizzle_schema,
                        langfuse_parent_trace_id=trace_id,
                        langfuse_parent_observation_id=observation_id,
                    )] = function.name
                for future in concurrent.futures.as_completed(future_to_handler):
                    function_name, result = future_to_handler[future], future.result()
                    match result.data.output:
                        case Exception() as e:
                            results[function_name] = HandlerOut(None, None, str(e))
                        case output:
                            results[function_name] = HandlerOut(output.name, output.handler, None)
        return results
