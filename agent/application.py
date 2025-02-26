import jinja2
import concurrent.futures
from anthropic import AnthropicBedrock
from compiler.core import Compiler
from tracing_client import TracingClient
from langfuse.decorators import langfuse_context, observe
from policies import common, handlers, typespec, drizzle, typescript, app_testcases, handler_tests, refine
from core import feature_flags
from core.datatypes import *


class Application:
    def __init__(self, client: AnthropicBedrock, compiler: Compiler, branch_factor: int = 2, max_depth: int = 4, max_workers: int = 5, dfs_budget: int = 20):
        self.client = TracingClient(client)
        self.compiler = compiler
        self.jinja_env = jinja2.Environment()
        self._model = "anthropic.claude-3-5-sonnet-20241022-v2:0"
        self.BRANCH_FACTOR = branch_factor
        self.MAX_DEPTH = max_depth
        self.MAX_WORKERS = max_workers
        self.DFS_BUDGET = dfs_budget

    @observe(capture_output=False)
    def create_bot(self, application_description: str, bot_id: str | None = None):
        if bot_id is not None:
            langfuse_context.update_current_observation(metadata={"bot_id": bot_id})

        if feature_flags.refine_initial_prompt:
            print("Refining Initial Description...")
            app_prompt = self._refine_initial_prompt(application_description)
        else:
            print("Skipping Initial Description Refinement")
            app_prompt = RefineOut(application_description, None)

        print("Compiling TypeSpec...")
        typespec = self._make_typespec(app_prompt.refined_description)
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

        print("Compiling Handler Tests...")
        handler_test_dict = self._make_handler_tests(typescript_functions, typescript_schema_definitions, drizzle_schema)

        print("Compiling Handlers...")
        handlers = self._make_handlers(typescript_functions, handler_test_dict, typespec_definitions, typescript_schema_definitions, drizzle_schema)

        langfuse_context.update_current_observation(
            output = {
                "refined_description": app_prompt.__dict__,
                "typespec": typespec.__dict__,
                "typescript_schema": typescript_schema.__dict__,
                "drizzle": drizzle.__dict__,
                "handlers": {k: v.__dict__ for k, v in handlers.items()},
                "handler_tests": {k: v.__dict__ for k, v in handler_test_dict.items()},
                "gherkin": gherkin.__dict__,
                "scenarios": {f.name: f.scenario for f in typespec.llm_functions},
            },
            metadata = {
                "refined_description_ok": app_prompt.error_output is None,
                "typespec_ok": typespec.error_output is None,
                "typescript_schema_ok": typescript_schema.error_output is None,
                "drizzle_ok": drizzle.error_output is None,
                "all_handlers_ok": all(handler.error_output is None for handler in handlers.values()),
                "all_handler_tests_ok": all(handler_test.error_output is None for handler_test in handler_test_dict.values()),
                "gherkin_ok": gherkin.error_output is None,
            },
        )
        return ApplicationOut(app_prompt, typespec, drizzle, handlers, handler_test_dict, typescript_schema, gherkin, langfuse_context.get_current_trace_id())

    @observe(capture_input=False, capture_output=False)
    def _make_typescript_schema(self, typespec_definitions: str):
        content = self.jinja_env.from_string(typescript.PROMPT).render(typespec_definitions=typespec_definitions)
        message = {"role": "user", "content": content}
        with typescript.TypescriptTaskNode.platform(self.client, self.compiler, self.jinja_env):
            ts_data = typescript.TypescriptTaskNode.run([message], init=True)
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
        content = self.jinja_env.from_string(typespec.PROMPT).render(application_description=application_description)
        message = {"role": "user", "content": content}
        with typespec.TypespecTaskNode.platform(self.client, self.compiler, self.jinja_env):
            tsp_data = typespec.TypespecTaskNode.run([message], init=True)
            tsp_root = typespec.TypespecTaskNode(tsp_data)
            tsp_solution = common.bfs(tsp_root, self.MAX_DEPTH, self.BRANCH_FACTOR, self.MAX_WORKERS)
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
            dzl_data = drizzle.DrizzleTaskNode.run([message], init=True)
            dzl_root = drizzle.DrizzleTaskNode(dzl_data)
            dzl_solution = common.bfs(dzl_root, self.MAX_DEPTH, self.BRANCH_FACTOR, self.MAX_WORKERS)
        match dzl_solution.data.output:
            case Exception() as e:
                return DrizzleOut(None, None, str(e))
            case output:
                return DrizzleOut(output.reasoning, output.drizzle_schema, output.error_or_none)

    @observe(capture_input=False, capture_output=False)
    def _make_handler_test(
        self,
        content: str,
        function_name: str,
        typescript_schema: str,
        drizzle_schema: str,
        *args,
        **kwargs,
    ) -> HandlerTestsOut:
        prompt_params = {
            "function_name": function_name,
            "typescript_schema": typescript_schema,
            "drizzle_schema": drizzle_schema,
        }
        message = {"role": "user", "content": content}
        test_data = handler_tests.HandlerTestTaskNode.run([message], init=True, **prompt_params)
        test_root = handler_tests.HandlerTestTaskNode(test_data)
        test_solution = common.dfs(test_root, 5, self.BRANCH_FACTOR, self.DFS_BUDGET, **prompt_params)
        match test_solution.data.output:
            case Exception() as e:
                return HandlerTestsOut(None, None, str(e))
            case output:
                return HandlerTestsOut(function_name, output.content, None)

    @observe(capture_input=False, capture_output=False)
    def _make_handler_tests(
        self,
        llm_functions: list[typescript.FunctionDeclaration],
        typescript_schema: str,
        drizzle_schema: str,
    ) -> dict[str, HandlerTestsOut]:
        trace_id = langfuse_context.get_current_trace_id()
        observation_id = langfuse_context.get_current_observation_id()
        results: dict[str, HandlerTestsOut] = {}
        with handler_tests.HandlerTestTaskNode.platform(self.client, self.compiler, self.jinja_env):
            with concurrent.futures.ThreadPoolExecutor(self.MAX_WORKERS) as executor:
                future_to_handler: dict[concurrent.futures.Future[HandlerTestsOut], str] = {}
                for function in llm_functions:
                    test_prompt_params = {
                        "function_name": function.name,
                        "typescript_schema": typescript_schema,
                        "drizzle_schema": drizzle_schema,
                    }
                    content = self.jinja_env.from_string(handler_tests.PROMPT).render(**test_prompt_params)
                    future_to_handler[executor.submit(
                        self._make_handler_test,
                        content,
                        function.name,
                        typescript_schema,
                        drizzle_schema,
                        langfuse_parent_trace_id=trace_id,
                        langfuse_parent_observation_id=observation_id,
                    )] = function.name
                for future in concurrent.futures.as_completed(future_to_handler):
                    function_name, result = future_to_handler[future], future.result()
                    results[function_name] = result
        return results

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
        test_suite: str | None,
        *args,
        **kwargs,
    ) -> HandlerOut:
        prompt_params = {
            "function_name": function_name,
            "argument_type": argument_type,
            "argument_schema": argument_schema,
            "typespec_schema": typespec_definitions,
            "typescript_schema": typescript_schema,
            "drizzle_schema": drizzle_schema,
            "test_suite": test_suite,
        }
        message = {"role": "user", "content": content}
        output = handlers.HandlerTaskNode.run([message], init=True, **prompt_params)
        root_node = handlers.HandlerTaskNode(output)
        solution = common.dfs(root_node, 5, self.BRANCH_FACTOR, self.DFS_BUDGET, **prompt_params)
        match solution.data.output:
            case Exception() as e:
                return HandlerOut(None, None, None, str(e))
            case output:
                return HandlerOut(output.name, output.handler, argument_schema, None)

    @observe(capture_input=False, capture_output=False)
    def _make_handlers(self, llm_functions: list[typescript.FunctionDeclaration], handler_tests: dict[str, HandlerTestsOut], typespec_definitions: str, typescript_schema: str, drizzle_schema: str):
        trace_id = langfuse_context.get_current_trace_id()
        observation_id = langfuse_context.get_current_observation_id()
        results: dict[str, HandlerOut] = {}
        with handlers.HandlerTaskNode.platform(self.client, self.compiler, self.jinja_env):
            with concurrent.futures.ThreadPoolExecutor(self.MAX_WORKERS) as executor:
                future_to_handler: dict[concurrent.futures.Future[HandlerOut], str] = {}
                for function in llm_functions:
                    match handler_tests.get(function.name):
                        case HandlerTestsOut(_, test_content, None) if test_content is not None:
                            test_suite = test_content
                        case _:
                            test_suite = None
                    handler_prompt_params = {
                        "function_name": function.name,
                        "argument_type": function.argument_type,
                        "argument_schema": function.argument_schema,
                        "typespec_schema": typespec_definitions,
                        "typescript_schema": typescript_schema,
                        "drizzle_schema": drizzle_schema,
                        "test_suite": test_suite,
                    }
                    content = self.jinja_env.from_string(handlers.PROMPT).render(**handler_prompt_params)
                    future_to_handler[executor.submit(
                        self._make_handler,
                        content,
                        function.name,
                        function.argument_type,
                        function.argument_schema,
                        typespec_definitions,
                        typescript_schema,
                        drizzle_schema,
                        test_suite,
                        langfuse_parent_trace_id=trace_id,
                        langfuse_parent_observation_id=observation_id,
                    )] = function.name
                for future in concurrent.futures.as_completed(future_to_handler):
                    function_name, result = future_to_handler[future], future.result()
                    results[function_name] = result
        return results

    @observe(capture_input=False, capture_output=False)
    def _refine_initial_prompt(self, initial_description: str):
        with refine.RefinementTaskNode.platform(self.client, self.jinja_env):
            refinement_data = refine.RefinementTaskNode.run([{"role": "user",
                "content": self.jinja_env.from_string(refine.PROMPT).render(application_description=initial_description)
            }])
            match refinement_data.output:
                case Exception() as e:
                    return RefineOut(initial_description, str(e))
                case output:
                    return RefineOut(output.requirements, output.error_or_none)
