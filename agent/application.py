import os
import jinja2
import concurrent.futures
from anthropic import AnthropicBedrock
from shutil import copytree, ignore_patterns
from compiler.core import Compiler
from tracing_client import TracingClient
from core.interpolator import Interpolator
from langfuse.decorators import langfuse_context, observe
from policies import common, handlers, typespec, drizzle, typescript, router

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
            langfuse_context.update_current_observation(
                metadata={"bot_id": bot_id}
            )
        print("Compiling TypeSpec...")
        typespec = self._make_typespec(application_description)
        if typespec.score != 1:
            raise Exception("Failed to generate typespec")
        typespec_definitions = typespec.data.output.typespec_definitions
        llm_functions = typespec.data.output.llm_functions
        print("Generating Typescript Schema Definitions...")
        typescript_schema = self._make_typescript_schema(typespec_definitions)
        if typescript_schema.score != 1:
            raise Exception("Failed to generate typescript schema")
        typescript_schema_definitions = typescript_schema.data.output.typescript_schema
        typescript_type_names = typescript_schema.data.output.type_names
        print("Compiling Drizzle...")
        drizzle = self._make_drizzle(typespec_definitions)
        if drizzle.score != 1:
            raise Exception("Failed to generate drizzle")
        drizzle_schema = drizzle.data.output.drizzle_schema
        print("Generating Router...")
        router = self._make_router(typespec_definitions)
        print("Generating Handlers...")
        handlers = self._make_handlers(llm_functions, typespec_definitions, typescript_schema_definitions, drizzle_schema)
        print("Generating Application...")
        application = self._make_application(typespec_definitions, typescript_schema_definitions, typescript_type_names, drizzle_schema, router.data.output.functions, handlers)
        return {
            "typespec": typespec.data,
            "drizzle": drizzle.data,
            "router": router,
            "handlers": handlers,
            "typescript_schema": typescript_schema,
            "application": application,
        }

    def _make_application(self, typespec_definitions: str, typescript_schema: str, typescript_type_names: list[str], drizzle_schema: str, user_functions: list[dict], handlers: dict[str, handlers.HandlerTaskNode]):
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

        raw_handlers = {k: v.data.output.handler for k, v in handlers.items()}

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
        return ts_solution
   
    @observe(capture_input=False, capture_output=False)
    def _make_typespec(self, application_description: str):
        BRANCH_FACTOR, MAX_DEPTH, MAX_WORKERS = 3, 3, 5

        content = self.jinja_env.from_string(typespec.PROMPT).render(application_description=application_description)
        message = {"role": "user", "content": content}
        with typespec.TypespecTaskNode.platform(self.client, self.compiler, self.jinja_env):
            tsp_data = typespec.TypespecTaskNode.run([message])
            tsp_root = typespec.TypespecTaskNode(tsp_data)
            tsp_solution = common.bfs(tsp_root, MAX_DEPTH, BRANCH_FACTOR, MAX_WORKERS)
        return tsp_solution
    
    @observe(capture_input=False, capture_output=False)
    def _make_drizzle(self, typespec_definitions: str):
        BRANCH_FACTOR, MAX_DEPTH, MAX_WORKERS = 3, 3, 5

        content = self.jinja_env.from_string(drizzle.PROMPT).render(typespec_definitions=typespec_definitions)
        message = {"role": "user", "content": content}
        with drizzle.DrizzleTaskNode.platform(self.client, self.compiler, self.jinja_env):
            dzl_data = drizzle.DrizzleTaskNode.run([message])
            dzl_root = drizzle.DrizzleTaskNode(dzl_data)
            dzl_solution = common.bfs(dzl_root, MAX_DEPTH, BRANCH_FACTOR, MAX_WORKERS)
        return dzl_solution

    @observe(capture_input=False, capture_output=False)
    def _make_router(self, typespec_definitions: str):
        content = self.jinja_env.from_string(router.PROMPT).render(typespec_definitions=typespec_definitions)
        message = {"role": "user", "content": content}
        with router.RouterTaskNode.platform(self.client, self.jinja_env):
            router_data = router.RouterTaskNode.run([message], typespec_definitions=typespec_definitions)
            router_root = router.RouterTaskNode(router_data)
            router_solution = common.bfs(router_root)
        return router_solution
    
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
        prompt_params = {
            "function_name": function_name,
            "typespec_schema": typespec_definitions,
            "typescript_schema": typescript_schema,
            "drizzle_schema": drizzle_schema,
        }
        message = {"role": "user", "content": content}
        output = handlers.HandlerTaskNode.run([message], **prompt_params)
        root_node = handlers.HandlerTaskNode(output)
        solution = common.bfs(root_node)
        return solution
    
    @observe(capture_input=False, capture_output=False)
    def _make_handlers(self, llm_functions: list[str], typespec_definitions: str, typescript_schema: str, drizzle_schema: str):
        MAX_WORKERS = 5
        trace_id = langfuse_context.get_current_trace_id()
        observation_id = langfuse_context.get_current_observation_id()
        results: dict[str, handlers.HandlerTaskNode] = {}
        with handlers.HandlerTaskNode.platform(self.client, self.compiler, self.jinja_env):
            with concurrent.futures.ThreadPoolExecutor(MAX_WORKERS) as executor:
                future_to_handler = {}
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
                    results[function_name] = result
        return results
