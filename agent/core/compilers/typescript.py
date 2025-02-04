import os
import subprocess
from . import CompilationStatus, CompilationResult


class TypeScriptCompiler:
    def __init__(self, root_dir: str):
        self.workdir = os.path.join(root_dir, 'app_schema')

    def compile(self, typescript_schema: str, schema_name: str = 'schema.ts') -> CompilationResult: # TODO: multifile
        with open(os.path.join(self.workdir, schema_name), 'w') as f:
            f.write(typescript_schema)
        try:
            result = subprocess.run(
                ['npx', 'tsx', schema_name, "--noEmit"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.workdir,
                env={**dict(os.environ), 'NO_COLOR': '1', 'FORCE_COLOR': '0'},
            )
            stdout = result.stdout.decode('utf-8') if result.stdout else None
            # tsp returns code 1 on errors, but doesn't write to stderr
            errors = stdout if result.returncode != 0 else None
            status = CompilationStatus.SUCCESS if result.returncode == 0 and errors is None else CompilationStatus.FAILURE
            return CompilationResult(result=status, errors=errors, stdout=stdout)
        except Exception as e:
            return CompilationResult(result=CompilationStatus.FAILURE, error=str(e), stdout=None)

    def reset(self, schema_name: str = 'schema.ts'):
        os.remove(os.path.join(self.workdir, schema_name))
