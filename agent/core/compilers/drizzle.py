import os
import subprocess
from . import CompilationStatus, CompilationResult


def timeout_retry_decorator(num_retries=1):
    def wrapper(func):
        def wrapped(*args, **kwargs):
            for _ in range(num_retries):
                try:
                    return func(*args, **kwargs)
                except subprocess.TimeoutExpired:
                    continue
            raise
        return wrapped
    return wrapper


class DrizzleCompiler:
    def __init__(self, root_dir: str):
        self.workdir = os.path.join(root_dir, 'app_schema')

    @timeout_retry_decorator(num_retries=3)
    def compile(self, drizzle_schema: str):
        with open(os.path.join(self.workdir, 'src', 'db', 'schema', 'application.ts'), 'w') as f:
            f.write(drizzle_schema)
        try:
            print("start checking drizzle")
            result = subprocess.run(
                ['npx', 'drizzle-kit', "push"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.workdir,
                env={**dict(os.environ), 'NO_COLOR': '1', 'FORCE_COLOR': '0'},
                timeout=30.0,
            )
            print("end checking drizzle")
            errors = result.stderr.decode('utf-8') if result.stderr else None
            stdout = result.stdout.decode('utf-8') if result.stdout else None
            status = CompilationStatus.SUCCESS if result.returncode == 0 and errors is None else CompilationStatus.FAILURE
            return CompilationResult(result=status, errors=errors, stdout=stdout)
        except Exception as e:
            return CompilationResult(result=CompilationStatus.FAILURE, error=str(e), stdout=None)

    def reset(self):
        result = subprocess.run(
            ['npx', 'tsx', 'src/helpers/reset.ts'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.workdir,
            env={**dict(os.environ), 'NO_COLOR': '1', 'FORCE_COLOR': '0'},
        )
        errors = result.stderr.decode('utf-8') if result.stderr else None
        if result.returncode != 0 or errors:
            raise RuntimeError(errors)
        with open(os.path.join(self.workdir, 'src', 'db', 'schema', 'application.ts'), 'w') as f:
            f.write('')
