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
from policies import common, handlers, typespec, drizzle, typescript, router


@dataclass
class TypespecOut:
    reasoning: str | None
    typespec_definitions: str | None
    llm_functions: list[str] | None
    error_output: str | None


@dataclass
class TypescriptOut:
    reasoning: str | None
    typescript_schema: str | None
    type_names: list[str] | None
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
    handler: str | None
    error_output: str | None


@dataclass
class ApplicationOut:
    typespec: TypespecOut
    drizzle: DrizzleOut
    router: RouterOut
    handlers: dict[str, HandlerOut]
    typescript_schema: TypescriptOut
    application: dict[str, dict]


class Application:
    def __init__(self, client: AnthropicBedrock, compiler: Compiler, template_dir: str = "templates", output_dir: str = "app_output"):
        self.client = TracingClient(client)
        self.compiler = compiler
        self.jinja_env = jinja2.Environment()
        self.template_dir = template_dir
        self.iteration = 0
        self.output_dir = os.path.join(output_dir, "generated")
        self._model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    
    @observe(capture_output=False)
    def create_bot(self, application_description: str, bot_id: str | None = None):
        if bot_id is not None:
            langfuse_context.update_current_observation(metadata={"bot_id": bot_id})

        print("Compiling TypeSpec...")
        typespec = self._make_typespec(application_description)
        if typespec.error_output is not None:
            raise Exception(f"Failed to generate typespec: {typespec.error_output}")
        typespec_definitions = typespec.typespec_definitions
        llm_functions = typespec.llm_functions

        print("Compiling Typescript Schema Definitions...")
        typescript_schema = self._make_typescript_schema(typespec_definitions)
        if typescript_schema.error_output is not None:
            raise Exception(f"Failed to generate typescript schema: {typescript_schema.error_output}")
        typescript_schema_definitions = typescript_schema.typescript_schema
        typescript_type_names = typescript_schema.type_names

        print("Compiling Drizzle...")
        drizzle = self._make_drizzle(typespec_definitions)
        if drizzle.error_output is not None:
            raise Exception(f"Failed to generate drizzle schema: {drizzle.error_output}")
        drizzle_schema = drizzle.drizzle_schema

        print("Generating Router...")
        router = self._make_router(typespec_definitions)
        if router.error_output is not None:
            raise Exception(f"Failed to generate router: {router.error_output}")

        print("Compiling Handlers...")
        handlers = self._make_handlers(llm_functions, typespec_definitions, typescript_schema_definitions, drizzle_schema)

        langfuse_context.update_current_observation(
            output = {
                "typespec": typespec.__dict__,
                "typescript_schema": typescript_schema.__dict__,
                "drizzle": drizzle.__dict__,
                "router": router.__dict__,
                "handlers": {k: v.__dict__ for k, v in handlers.items()},
            },
            metadata = {
                "typespec_ok": typespec.error_output is None,
                "typescript_schema_ok": typescript_schema.error_output is None,
                "drizzle_ok": drizzle.error_output is None,
                "router_ok": router.error_output is None,
                "all_handlers_ok": all(handler.error_output is None for handler in handlers.values()),
            },
        )

        print("Generating Application...")
        application = self._make_application(typespec_definitions, typescript_schema_definitions, typescript_type_names, drizzle_schema, router.functions, handlers)
        return ApplicationOut(typespec, drizzle, router, handlers, typescript_schema, application)

    def _make_application(self, typespec_definitions: str, typescript_schema: str, typescript_type_names: list[str], drizzle_schema: str, user_functions: list[dict], handlers: dict[str, HandlerOut]):
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

        raw_handlers = {k: v.handler for k, v in handlers.items()}

        return interpolator.interpolate_all(raw_handlers, typescript_type_names, user_functions)

    @observe(capture_input=False, capture_output=False)
    def _make_typescript_schema(self, typespec_definitions: str):
        BRANCH_FACTOR, MAX_DEPTH, MAX_WORKERS = 3, 3, 5

        content = self.jinja_env.from_string(typescript.PROMPT).render(typespec_definitions=typespec_definitions)
        message = {"role": "user", "content": content}
        with typescript.TypescriptTaskNode.platform(self.client, self.compiler, self.jinja_env):
            ts_data = typescript.TypescriptTaskNode.run([message])
            ts_root = typescript.TypescriptTaskNode(ts_data)
            ts_solution = common.bfs(ts_root, MAX_DEPTH, BRANCH_FACTOR, MAX_WORKERS)
        match ts_solution.data.output:
            case Exception() as e:
                return TypescriptOut(None, None, None, str(e))
            case output:
                return TypescriptOut(output.reasoning, output.typescript_schema, output.type_names, output.error_or_none)
   
    @observe(capture_input=False, capture_output=False)
    def _make_typespec(self, application_description: str):
        BRANCH_FACTOR, MAX_DEPTH, MAX_WORKERS = 3, 3, 5

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
        BRANCH_FACTOR, MAX_DEPTH, MAX_WORKERS = 3, 3, 5

        content = self.jinja_env.from_string(drizzle.PROMPT).render(typespec_definitions=typespec_definitions)
        message = {"role": "user", "content": content}
        with drizzle.DrizzleTaskNode.platform(self.client, self.compiler, self.jinja_env):
            dzl_data = drizzle.DrizzleTaskNode.run([message])
            dzl_root = drizzle.DrizzleTaskNode(dzl_data)
            dzl_solution = common.bfs(dzl_root, MAX_DEPTH, BRANCH_FACTOR, MAX_WORKERS)
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
    
    @staticmethod
    @observe(capture_input=False, capture_output=False)
    def _make_handler(
        content: str,
        function_name: str,
        typespec_definitions: str,
        typescript_schema: str,
        drizzle_schema: str,
        *args,
        **kwargs,
    ) -> handlers.HandlerTaskNode:
        BRANCH_FACTOR, MAX_DEPTH, MAX_WORKERS = 3, 3, 5
        prompt_params = {
            "function_name": function_name,
            "typespec_schema": typespec_definitions,
            "typescript_schema": typescript_schema,
            "drizzle_schema": drizzle_schema,
        }
        message = {"role": "user", "content": content}
        output = handlers.HandlerTaskNode.run([message], **prompt_params)
        root_node = handlers.HandlerTaskNode(output)
        solution = common.bfs(root_node, MAX_DEPTH, BRANCH_FACTOR, MAX_WORKERS, **prompt_params)
        return solution
    
    @observe(capture_input=False, capture_output=False)
    def _make_handlers(self, llm_functions: list[str], typespec_definitions: str, typescript_schema: str, drizzle_schema: str):
        MAX_WORKERS = 5
        trace_id = langfuse_context.get_current_trace_id()
        observation_id = langfuse_context.get_current_observation_id()
        results: dict[str, HandlerOut] = {}
        with handlers.HandlerTaskNode.platform(self.client, self.compiler, self.jinja_env):
            with concurrent.futures.ThreadPoolExecutor(MAX_WORKERS) as executor:
                future_to_handler: dict[concurrent.futures.Future[handlers.HandlerTaskNode], str] = {}
                for function_name in llm_functions:
                    prompt_params = {
                        "function_name": function_name,
                        "typespec_schema": typespec_definitions,
                        "typescript_schema": typescript_schema,
                        "drizzle_schema": drizzle_schema,
                    }
                    content = self.jinja_env.from_string(handlers.PROMPT).render(**prompt_params)
                    future_to_handler[executor.submit(
                        Application._make_handler,
                        content,
                        function_name,
                        typespec_definitions,
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
                            results[function_name] = HandlerOut(output.handler, None)
        return results
