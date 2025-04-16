import os
import subprocess
import jinja2
from shutil import copytree, ignore_patterns
from capabilities import all_custom_tools
from .datatypes import *  # ruff # noqa: F403
from logging import getLogger

logger = getLogger(__name__)

def run_git_command(command, cwd, check=False):
    """
    Run a git command with default configurations for test environments.
    This helps when running in environments without git user configuration.
    """
    try:
        # Set default git config for tests
        env = os.environ.copy()
        env.update({
            'GIT_AUTHOR_NAME': 'Test User',
            'GIT_AUTHOR_EMAIL': 'test@example.com',
            'GIT_COMMITTER_NAME': 'Test User',
            'GIT_COMMITTER_EMAIL': 'test@example.com',
        })

        return subprocess.run(command, cwd=cwd, check=check, env=env, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        logger.warning(f"Git command failed: {' '.join(command)}, exit code: {e.returncode}")
        logger.warning(f"Error output: {e.stderr}")
        if check:
            raise
        return e

TOOL_TEMPLATE = """
import * as schema from './common/schema';
import type { ToolHandler } from './common/tool-handler';
{% for handler in handlers %}import * as {{ handler.name }} from './handlers/{{ handler.name }}';
{% endfor %}

export const handlers: ToolHandler<any>[] = [{% for handler in handlers %}
    {
        name: '{{ handler.name }}',
        description: `{{ handler.description }}`,
        handler: {{ handler.name }}.handle,
        inputSchema: {{ handler.argument_schema }},
    },{% endfor %}
];
""".strip()

CUSTOM_TOOL_TEMPLATE = """
import type { CustomToolHandler } from './common/tool-handler';
import * as schema from './common/schema';
{% set imported_modules = [] %}
{% for handler in handlers %}
{% set module_name = handler.name.split('.')[0] %}
{% if module_name not in imported_modules %}
import * as {{ module_name }} from './integrations/{{ module_name }}';
{% set _ = imported_modules.append(module_name) %}
{% endif %}
{% endfor %}

export const custom_handlers: CustomToolHandler[] = [{% for handler in handlers %}
{% set module_name = handler.name.split('.')[0] %}
    {
        name: '{{ handler.name.replace('.', '_') }}',
        description: `{{ handler.description }}`,
        handler: {{ handler.name }},
        inputSchema: {{ handler.name }}_params_schema,
        can_handle: {{ module_name }}.can_handle,
    },{% endfor %}
];
""".strip()

class Interpolator:
    def __init__(self, root_dir: str | None = None):
        if root_dir is None:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            root_dir = os.path.join(current_dir, "../")
        self.root_dir = root_dir
        self.environment = jinja2.Environment()

    def bake(self, application, output_dir: str, overwrite: bool = False) -> str:
        """
        Bake the application into the output directory.
        The template directory is copied to the output directory overwriting existing files.
        Returns the diff of the application as a string relative to the application template.
        """
        # we for now rely on git installed on the machine to generate the diff
        # Initialize git repository in the output directory if it doesn't exist
        logger.info(f"Initializing git repository in {output_dir}")
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        run_git_command(["git", "init"], cwd=output_dir)

        template_dir = os.path.join(self.root_dir, "templates")
        if not overwrite: # if overwrite is False, we are creating a new application, otherwise no need to update the template
            copytree(template_dir, output_dir, ignore=ignore_patterns('*.pyc', '__pycache__', 'node_modules'), dirs_exist_ok=True)

            run_git_command(["git", "add", "."], cwd=output_dir)
            run_git_command(["git", "commit", "-m", "Initial commit of the template"], cwd=output_dir)

        # TODO: optimize overwriting some files below of user wants to update only some handlers / capabilities / etc
        with open(os.path.join(output_dir, "tsp_schema", "main.tsp"), "a") as f:
            f.write(application.typespec.typespec_definitions)

        with open(os.path.join(output_dir, "app_schema", "src", "db", "schema", "application.ts"), "w") as f:
            f.write(application.drizzle.drizzle_schema)

        with open(os.path.join(output_dir, "app_schema", "src", "common", "schema.ts"), "w") as f:
            f.write(application.typescript_schema.typescript_schema)

        handler_tools = [
            {
                "name": name,
                "description": next((f.description for f in application.typespec.llm_functions if f.name == name), ""),
                "argument_schema": f"schema.{handler.argument_schema}",
            }
            for name, handler in application.handlers.items()
        ]

        capability_list = []
        if application.capabilities is not None:
            if hasattr(application.capabilities, 'capabilities') and application.capabilities.capabilities is not None:
                capability_list = application.capabilities.capabilities
        custom_tools = [x for x in all_custom_tools if x['name'] in capability_list]

        with open(os.path.join(output_dir, "app_schema", "src", "tools.ts"), "w") as f:
            f.write(self.environment.from_string(TOOL_TEMPLATE).render(handlers=handler_tools))

        with open(os.path.join(output_dir, "app_schema", "src", "custom_tools.ts"), "w") as f:
            f.write(self.environment.from_string(CUSTOM_TOOL_TEMPLATE).render(handlers=custom_tools))

        for name, handler in application.handlers.items():
            with open(os.path.join(output_dir, "app_schema", "src", "handlers", f"{name}.ts"), "w") as f:
                if handler.handler:
                    f.write(handler.handler)
                else:
                    logger.error(f"Handler {name} does not have a handler function")
                    f.write("/// handler code was not generated")

        for name, handler_test in application.handler_tests.items():
            with open(os.path.join(output_dir, "app_schema", "src", "tests", "handlers", f"{name}.test.ts"), "w") as f:
                f.write(handler_test.content)

        logger.info(f"Adding all changes to git in {output_dir}")
        run_git_command(["git", "add", "."], cwd=output_dir)
        run_git_command(["git", "commit", "-m", "Update application files"], cwd=output_dir)

        try:
            diff_command = ["git", "diff", "HEAD~1", "HEAD", "--unified=0"]
            diff_result = run_git_command(diff_command, cwd=output_dir, check=True)
            diff_string = diff_result.stdout if hasattr(diff_result, 'stdout') else ""
        except Exception as e:
            logger.warning(f"Failed to generate diff: {str(e)}")
            diff_string = "Git diff not available. Check the output directory for generated files."

        logger.info(f"Diff result: {diff_string}")

        return diff_string
