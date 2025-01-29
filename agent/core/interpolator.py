
import os
import jinja2


class Interpolator:
    def __init__(self, root_dir: str):
        self.template_dir = os.path.join(root_dir, 'interpolation')
        self.workdir = os.path.join(root_dir, 'app_schema/src')
        self.environment = jinja2.Environment()

    def interpolate(self, params: dict, template_name: str, output_name: str): 
        file_content = None
        with open(os.path.join(self.template_dir, template_name), "r") as f:
            template = self.environment.from_string(f.read())
            file_content = template.render(**params)
        
        with open(os.path.join(self.workdir, output_name), 'w') as f:
            f.write(file_content)


    def interpolate_module_name(self, handler_name: str):
        # Convert PascalCase to snake_case for file naming
        return ''.join(['_' + c.lower() if c.isupper() else c for c in handler_name]).lstrip('_')


    def interpolate_handler(self, handler_name: str, handler: str, instructions: str, examples: str):
        params = {
            "handler_name": handler_name,
            "handler": handler,
            "instructions": instructions,
            "examples": examples,
        }
        handler_snake_name = self.interpolate_module_name(handler_name)
        self.interpolate(params, "handler.tpl", f"handlers/{handler_snake_name}.ts")
        return handler_snake_name
    
    
    def interpolate_index(self, handlers: dict):
        params = {
            "handlers": handlers,
        }
        self.interpolate(params, "logic_index.tpl", "logic/index.ts")


    def interpolate_router(self, handlers: dict):
        params = {
            "handlers": handlers,
        }
        self.interpolate(params, "logic_router.tpl", "logic/router.ts")

    def interpolate_all(self, handlers: dict, pre_processors: dict):
        processed_handlers = {}
        for handler_name in handlers.keys():
            handler = handlers[handler_name]["handler"]
            instructions = pre_processors[handler_name]["instructions"]
            examples = pre_processors[handler_name]["examples"]
            module = self.interpolate_handler(handler_name, handler, instructions, examples)
            processed_handlers[handler_name] = {**handlers[handler_name], "module": module}
        
        self.interpolate_index(processed_handlers)
        self.interpolate_router(processed_handlers)
        
        return processed_handlers