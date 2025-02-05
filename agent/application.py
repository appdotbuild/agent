import os
import jinja2
import concurrent.futures
from anthropic import AnthropicBedrock
from core import stages
from shutil import copytree, ignore_patterns
from search import Node, SearchPolicy
from services import CompilerService
from core.interpolator import Interpolator
from langfuse.decorators import langfuse_context, observe
from policies import handlers

class Application:
    def __init__(self, client: AnthropicBedrock, compiler: CompilerService, template_dir: str = "templates", output_dir: str = "app_output"):
        self.client = client
        self.policy = SearchPolicy(client, compiler)
        self.jinja_env = jinja2.Environment()
        self.typespec_tpl = self.jinja_env.from_string(stages.typespec.PROMPT)
        self.typescript_schema_tpl = self.jinja_env.from_string(stages.typescript.PROMPT)
        self.drizzle_tpl = self.jinja_env.from_string(stages.drizzle.PROMPT)
        self.router_tpl = self.jinja_env.from_string(stages.router.PROMPT)
        self.handlers_tpl = self.jinja_env.from_string(stages.handlers.PROMPT)
        self.preprocessors_tpl = self.jinja_env.from_string(stages.processors.PROMPT_PRE)
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
        print("Generating Typescript Schema Definitions...")
        typescript_schema = self._make_typescript_schema(typespec.data["output"]["typespec_definitions"])
        if typescript_schema.score != 1:
            raise Exception("Failed to generate typescript schema")
        typescript_schema_definitions = typescript_schema.data["output"]["typescript_schema"]
        print("Compiling Drizzle...")        
        typespec_definitions = typespec.data["output"]["typespec_definitions"]
        llm_functions = typespec.data["output"]["llm_functions"]
        drizzle = self._make_drizzle(typespec_definitions)
        if drizzle.score != 1:
            raise Exception("Failed to generate drizzle")
        drizzle_schema = drizzle.data["output"]["drizzle_schema"]
        print("Generating Router...")
        router = self._make_router(application_description, typespec_definitions)
        print("Generating Handlers...")
        handlers = self._make_handlers(llm_functions, typespec_definitions, typescript_schema_definitions, drizzle_schema)
        print("Generating Application...")
        application = self._make_application(typespec_definitions, typescript_schema_definitions, drizzle_schema, router, handlers)
        return {
            "typespec": typespec.data,
            "drizzle": drizzle.data,
            "router": router,
            "handlers": handlers,
            "typescript_schema": typescript_schema,
            "application": application,
        }

    def _make_application(self, typespec_definitions: str, typescript_schema_definitions: str, drizzle_schema: str, router: dict, handlers: dict):
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
            f.write(typescript_schema_definitions)
        
        typescript_schema_type_names = stages.typescript.parse_typescript_schema_type_names(typescript_schema_definitions)
        
        interpolator = Interpolator(self.generation_dir)
        
        return interpolator.interpolate_all(handlers, typescript_schema_type_names, router)

    @observe(capture_input=False, capture_output=False)
    def _make_typescript_schema(self, typespec_definitions: str):
        BRANCH_FACTOR, MAX_DEPTH, MAX_WORKERS = 3, 3, 5

        typespec_schema_prompt_params = {"typespec_definitions": typespec_definitions}
        typespec_schema_prompt = self.typescript_schema_tpl.render(**typespec_schema_prompt_params)
        init_typespec_schema = {"role": "user", "content": typespec_schema_prompt}
        data_typespec_schema = self.policy.run_typescript([init_typespec_schema], self.policy.client, self.policy.compiler, self.policy._model)
        root_typespec_schema = Node(data_typespec_schema, int(data_typespec_schema["feedback"]["stderr"] is None))
        best_typespec_schema = self.policy.bfs_typescript(init_typespec_schema, root_typespec_schema, MAX_DEPTH, BRANCH_FACTOR, MAX_WORKERS)
        return best_typespec_schema
   
    @observe(capture_input=False, capture_output=False)
    def _make_typespec(self, application_description: str):
        BRANCH_FACTOR, MAX_DEPTH, MAX_WORKERS = 3, 3, 5

        typespec_prompt_params = {"application_description": application_description}
        prompt_typespec = self.typespec_tpl.render(**typespec_prompt_params)
        init_typespec = {"role": "user", "content": prompt_typespec}
        data_typespec = SearchPolicy.run_typespec([init_typespec], self.policy.client, self.policy.compiler, self.policy._model)
        root_typespec = Node(data_typespec, data_typespec["feedback"]["exit_code"] == 0)
        best_typespec = self.policy.bfs_typespec(init_typespec, root_typespec, MAX_DEPTH, BRANCH_FACTOR, MAX_WORKERS)
        return best_typespec
    
    @observe(capture_input=False, capture_output=False)
    def _make_drizzle(self, typespec_definitions: str):
        BRANCH_FACTOR, MAX_DEPTH, MAX_WORKERS = 3, 3, 5

        drizzle_prompt_params = {"typespec_definitions": typespec_definitions}
        prompt_drizzle = self.drizzle_tpl.render(**drizzle_prompt_params)
        init_drizzle = {"role": "user", "content": prompt_drizzle}
        data_drizzle = SearchPolicy.run_drizzle([init_drizzle], self.policy.client, self.policy.compiler, self.policy._model)
        root_drizzle = Node(data_drizzle, int(data_drizzle["feedback"]["stderr"] is None))
        best_drizzle = self.policy.bfs_drizzle(init_drizzle, root_drizzle, MAX_DEPTH, BRANCH_FACTOR, MAX_WORKERS)
        return best_drizzle

    @observe(capture_input=False, capture_output=False)
    def _make_router(self, application_description: str, typespec_definitions: str):
        router_prompt_params = {"user_request": application_description, "typespec_definitions": typespec_definitions}
        prompt_router = self.router_tpl.render(**router_prompt_params)
        init_router = {"role": "user", "content": prompt_router}
        return SearchPolicy.run_router([init_router], self.policy.client, self.policy._model)
    
    @observe(capture_input=False, capture_output=False)
    def _make_preprocessors(self, llm_functions: list[str], typespec_definitions: str):
        MAX_WORKERS = 5
        trace_id = langfuse_context.get_current_trace_id()
        observation_id = langfuse_context.get_current_observation_id()
        preprocessors: dict[str, stages.processors.PreprocessorOutput] = {}
        with concurrent.futures.ThreadPoolExecutor(MAX_WORKERS) as executor:
            future_to_preprocessor = {}
            for function_name in llm_functions:
                preprocessor_prompt_params = {"function_name": function_name, "typespec_definitions": typespec_definitions}
                prompt_preprocessor = self.preprocessors_tpl.render(**preprocessor_prompt_params)
                init_preprocessor = {"role": "user", "content": prompt_preprocessor}
                future_to_preprocessor[executor.submit(
                    SearchPolicy.run_preprocessor,
                    [init_preprocessor],
                    self.policy.client,
                    self.policy._model,
                    langfuse_parent_trace_id=trace_id,
                    langfuse_parent_observation_id=observation_id,
                )] = function_name
            for future in concurrent.futures.as_completed(future_to_preprocessor):
                function_name = future_to_preprocessor[future]
                preprocessors[function_name] = future.result()
        return preprocessors
    
    @observe(capture_input=False, capture_output=False)
    def _make_handlers(self, llm_functions: list[str], typespec_definitions: str, typescript_schema_definitions: str, drizzle_schema: str):
        MAX_WORKERS = 5
        trace_id = langfuse_context.get_current_trace_id()
        observation_id = langfuse_context.get_current_observation_id()
        results: dict[str, stages.handlers.HandlerOutput] = {}
        with concurrent.futures.ThreadPoolExecutor(MAX_WORKERS) as executor:
            future_to_handler = {}
            for function_name in llm_functions:
                #typescript_schema_type_names = stages.typescript.parse_typescript_schema_type_names(typescript_schema_definitions)
                handler_prompt_params = {
                    "function_name": function_name,
                    "typespec_schema": typespec_definitions,
                    "typescript_schema": typescript_schema_definitions,
                    "drizzle_schema": drizzle_schema
                }
                prompt_handler = self.handlers_tpl.render(**handler_prompt_params)
                message = {"role": "user", "content": prompt_handler}
                # TODO: Add policy execution
                with handlers.HandlerTaskNode.platform(self.policy.client, self.policy.compiler, self.jinja_env):
                    output = handlers.HandlerTaskNode.run([message], function_name=function_name,
                                          typespec_schema=typespec_definitions,
                                          typescript_schema=typescript_schema_definitions,
                                          drizzle_schema=drizzle_schema)
                    results[function_name] = output
        return results