import os
import jinja2


class Interpolator:
    def __init__(self, root_dir: str):
        self.template_dir = os.path.join(root_dir, 'interpolation')
        self.workdir = os.path.join(root_dir, 'app_schema/src')
        self.environment = jinja2.Environment()

    def _interpolate(self, params: dict, template_name: str, output_name: str): 
        file_content = None
        with open(os.path.join(self.template_dir, template_name), "r") as f:
            template = self.environment.from_string(f.read())
            file_content = template.render(**params)
        
        with open(os.path.join(self.workdir, output_name), 'w') as f:
            f.write(file_content)


    def _interpolate_module_name(self, handler_name: str):
        # Convert PascalCase to snake_case for file naming
        return ''.join(['_' + c.lower() if c.isupper() else c for c in handler_name]).lstrip('_')


    def _interpolate_handler(self, handler_name: str, handler: str, typescript_schema_type_names: list[str]):
        params = {
            "handler_name": handler_name,
            "handler": handler,
            "typescript_schema_type_names": typescript_schema_type_names,
        }
        handler_snake_name = self._interpolate_module_name(handler_name)
        self._interpolate(params, "handler.tpl", f"handlers/{handler_snake_name}.ts")
        return handler_snake_name
    
    
    def _interpolate_index(self, handlers: dict):
        params = {
            "handlers": handlers,
        }
        self._interpolate(params, "logic_index.tpl", "logic/index.ts")


    def _interpolate_router(self, functions: list[dict]):
        params = {
            "functions": functions,
        }
        self._interpolate(params, "logic_router.tpl", "logic/router.ts")

    def interpolate_all(self, handlers: dict, typescript_schema_type_names: list[str], functions: list[dict]):
        processed_handlers = {}
        for handler_name in handlers.keys():
            handler = handlers[handler_name]
            module = self._interpolate_handler(handler_name, handler, typescript_schema_type_names)
            processed_handlers[handler_name] = {"module": module}
        
        self._interpolate_index(processed_handlers)
        self._interpolate_router(functions)
        
        return processed_handlers