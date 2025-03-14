import os
import jinja2
from shutil import copytree, ignore_patterns
from capabilities import all_custom_tools
from .datatypes import *

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
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.environment = jinja2.Environment()

    def bake(self, application: ApplicationOut, output_dir: str, overwrite: bool = False):
        """
        Bake the application into the output directory.
        The template directory is copied to the output directory overwriting existing files.
        """
        template_dir = os.path.join(self.root_dir, "templates")
        copytree(template_dir, output_dir, ignore=ignore_patterns('*.pyc', '__pycache__', 'node_modules'), dirs_exist_ok=True, overwrite=True)

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
                f.write(handler.handler)
        
        for name, handler_test in application.handler_tests.items():
            with open(os.path.join(output_dir, "app_schema", "src", "tests", "handlers", f"{name}.test.ts"), "w") as f:
                f.write(handler_test.content)
