import requests
from compiler.core import Compiler, CompileResult


class CompilerService:
    def __init__(self, address: str | None = None):
        self.address = address
        if address is None:
            self.compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
            
            
    def compile_typescript(self, schema: str) -> CompileResult:
        if self.address:
            response = requests.post(
                f"{self.address}/compile/typescript",
                json={"payload": schema},
            )
            response.raise_for_status()
            return CompileResult(**response.json())
        else:
            return self.compiler.compile_typescript({"src/common/schema.ts": schema})
    
    def compile_typespec(self, schema: str) -> CompileResult:
        if self.address:
            response = requests.post(
                f"{self.address}/compile/typespec",
                json={"payload": schema},
            )
            response.raise_for_status()
            return CompileResult(**response.json())
        else:
            return self.compiler.compile_typespec(schema)
        
    def compile_drizzle(self, schema: str) -> CompileResult:
        if self.address:
            response = requests.post(
                f"{self.address}/compile/drizzle",
                json={"payload": schema},
            )
            response.raise_for_status()
            return CompileResult(**response.json())
        else:
            return self.compiler.compile_drizzle(schema)