import os
import jinja2
from shutil import copytree, ignore_patterns

from core import feature_flags
from .datatypes import *

TOOL_TEMPLATE = """
import { z } from 'zod';
import * as schema from './common/schema';
{% for handler in handlers %}import * as {{ handler.name }} from './handlers/{{ handler.name }}';
{% endfor %}

interface ToolHandler<argSchema extends z.ZodObject<any>> {
    name: string;
    description: string;
    handler: (options: z.infer<argSchema>) => any;
    inputSchema: argSchema;
}

export const handlers: ToolHandler<any>[] = [{% for handler in handlers %}
    {
        name: '{{ handler.name }}',
        description: `{{ handler.description }}`,
        handler: {{ handler.name }}.handle,
        inputSchema: {{ handler.argument_schema }},
    },{% endfor %}
];
""".strip()



class Interpolator:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.environment = jinja2.Environment()

    def bake(self, application: ApplicationOut, output_dir: str):
        template_dir = os.path.join(self.root_dir, "templates")
        copytree(template_dir, output_dir, ignore=ignore_patterns('*.pyc', '__pycache__', 'node_modules'), dirs_exist_ok=True)

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
        
        if feature_flags.perplexity:
            handler_tools.append({
                "name": "web_search",
                "description": "search the web for information",
                "argument_schema": "web_search.webSearchParamsSchema",
            })

        with open(os.path.join(output_dir, "app_schema", "src", "tools.ts"), "w") as f:
            f.write(self.environment.from_string(TOOL_TEMPLATE).render(handlers=handler_tools))
        
        for name, handler in application.handlers.items():
            with open(os.path.join(output_dir, "app_schema", "src", "handlers", f"{name}.ts"), "w") as f:
                f.write(handler.handler)
        
        for name, handler_test in application.handler_tests.items():
            with open(os.path.join(output_dir, "app_schema", "src", "tests", "handlers", f"{name}.test.ts"), "w") as f:
                f.write(handler_test.content)
