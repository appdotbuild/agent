import os
import jinja2
import concurrent.futures
from anthropic import AnthropicBedrock
from core import stages
from shutil import copytree, ignore_patterns
from search import Node, SearchPolicy
from services import CompilerService
from core.interpolator import Interpolator

class Application:
    def __init__(self, client: AnthropicBedrock, compiler: CompilerService, template_dir: str = "templates", output_dir: str = "app_output"):
        self.client = client
        self.policy = SearchPolicy(client, compiler)
        self.jinja_env = jinja2.Environment()
        self.typespec_tpl = self.jinja_env.from_string(stages.typespec.PROMPT)
        self.drizzle_tpl = self.jinja_env.from_string(stages.drizzle.PROMPT)
        self.router_tpl = self.jinja_env.from_string(stages.router.PROMPT)
        self.handlers_tpl = self.jinja_env.from_string(stages.handlers.PROMPT)
        self.preprocessors_tpl = self.jinja_env.from_string(stages.processors.PROMPT_PRE)
        self.template_dir = template_dir
        self.iteration = 0
        self.output_dir = os.path.join(output_dir, "generated")
        self._model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
    
    def create_bot(self, application_description: str):
        print("Compiling TypeSpec...")
        typespec = self._make_typespec(application_description)
        if typespec.score != 1:
            raise Exception("Failed to generate typespec")
        print("Compiling Drizzle...")
        typespec_definitions = typespec.data["output"]["typespec_definitions"]
        llm_functions = typespec.data["output"]["llm_functions"]
        drizzle = self._make_drizzle(typespec_definitions)
        if drizzle.score != 1:
            raise Exception("Failed to generate drizzle")
        drizzle_schema = drizzle.data["output"]["drizzle_schema"]
        print("Generating Router...")
        router = self._make_router(application_description, typespec_definitions)
        print("Generating Preprocessors...")
        preprocessors = self._make_preprocessors(llm_functions, typespec_definitions)
        print("Generating Handlers...")
        handlers = self._make_handlers(llm_functions, typespec_definitions, drizzle_schema)
        print("Generating Application...")
        application = self._make_application(preprocessors, handlers)
        return {
            "typespec": typespec.data,
            "drizzle": drizzle.data,
            "router": router,
            "preprocessors": preprocessors,
            "handlers": handlers,
            "application": application,
        }

    def _make_application(self, preprocessors: dict, handlers: dict):
        self.iteration += 1
        self.generation_dir = os.path.join(self.output_dir, f"generation-{self.iteration}")
        copytree(self.template_dir, self.generation_dir, ignore=ignore_patterns('*.pyc', '__pycache__', 'node_modules'))
        interpolator = Interpolator(self.generation_dir)
        return interpolator.interpolate_all(preprocessors, handlers)
    
    def _make_typespec(self, application_description: str):
        BRANCH_FACTOR, MAX_DEPTH, MAX_WORKERS = 3, 3, 5

        typespec_prompt_params = {"application_description": application_description}
        prompt_typespec = self.typespec_tpl.render(**typespec_prompt_params)
        init_typespec = {"role": "user", "content": prompt_typespec}
        data_typespec = self.policy.run_typespec([init_typespec], self.policy.client, self.policy.compiler, self.policy._model)
        root_typespec = Node(data_typespec, data_typespec["feedback"]["exit_code"] == 0)
        best_typespec = self.policy.bfs_typespec(init_typespec, root_typespec, MAX_DEPTH, BRANCH_FACTOR, MAX_WORKERS)
        return best_typespec
    
    def _make_drizzle(self, typespec_definitions: str):
        BRANCH_FACTOR, MAX_DEPTH, MAX_WORKERS = 3, 3, 5

        drizzle_prompt_params = {"typespec_definitions": typespec_definitions}
        prompt_drizzle = self.drizzle_tpl.render(**drizzle_prompt_params)
        init_drizzle = {"role": "user", "content": prompt_drizzle}
        data_drizzle = self.policy.run_drizzle([init_drizzle], self.policy.client, self.policy.compiler, self.policy._model)
        root_drizzle = Node(data_drizzle, int(data_drizzle["feedback"]["stderr"] is None))
        best_drizzle = self.policy.bfs_drizzle(init_drizzle, root_drizzle, MAX_DEPTH, BRANCH_FACTOR, MAX_WORKERS)
        return best_drizzle

    def _make_router(self, application_description: str, typespec_definitions: str):
        router_prompt_params = {"user_request": application_description, "typespec_definitions": typespec_definitions}
        prompt_router = self.router_tpl.render(**router_prompt_params)
        init_router = {"role": "user", "content": prompt_router}
        return self.policy.run_router([init_router], self.policy.client, self.policy._model)
    
    def _make_preprocessors(self, llm_functions: list[str], typespec_definitions: str):
        MAX_WORKERS = 5
        preprocessors: dict[str, stages.processors.PreprocessorOutput] = {}
        with concurrent.futures.ThreadPoolExecutor(MAX_WORKERS) as executor:
            future_to_preprocessor = {}
            for function_name in llm_functions:
                preprocessor_prompt_params = {"function_name": function_name, "typespec_definitions": typespec_definitions}
                prompt_preprocessor = self.preprocessors_tpl.render(**preprocessor_prompt_params)
                init_preprocessor = {"role": "user", "content": prompt_preprocessor}
                future_to_preprocessor[executor.submit(
                    self.policy.run_preprocessor,
                    [init_preprocessor],
                    self.policy.client,
                    self.policy._model,
                )] = function_name
            for future in concurrent.futures.as_completed(future_to_preprocessor):
                function_name = future_to_preprocessor[future]
                preprocessors[function_name] = future.result()
        return preprocessors
    
    def _make_handlers(self, llm_functions: list[str], typespec_definitions: str, drizzle_schema: str):
        MAX_WORKERS = 5
        handlers: dict[str, stages.handlers.HandlerOutput] = {}
        with concurrent.futures.ThreadPoolExecutor(MAX_WORKERS) as executor:
            future_to_handler = {}
            for function_name in llm_functions:
                handler_prompt_params = {"function_name": function_name, "typespec_definitions": typespec_definitions, "drizzle_schema": drizzle_schema}
                prompt_handler = self.handlers_tpl.render(**handler_prompt_params)
                init_handler = {"role": "user", "content": prompt_handler}
                future_to_handler[executor.submit(
                    self.policy.run_handler,
                    [init_handler],
                    self.policy.client,
                    self.policy._model,
                )] = function_name
            for future in concurrent.futures.as_completed(future_to_handler):
                function_name = future_to_handler[future]
                handlers[function_name] = future.result()
        return handlers