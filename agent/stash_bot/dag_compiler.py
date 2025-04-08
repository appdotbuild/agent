from typing import TypedDict, overload
import os
from dagger import dag, Container, Service, ReturnType
from logging import getLogger


logger = getLogger(__name__)


class CompileResult(TypedDict):
    exit_code: int
    stdout: str | None
    stderr: str | None


class Compiler:
    def __init__(self, root_path: str = "."):
        tpl_path = os.path.join(root_path, "templates")
        self.tsp_image = (
            dag
            .container()
            .from_("node:23-alpine")
            .with_workdir("/app")
            .with_directory("/app", dag.host().directory(os.path.join(tpl_path, "tsp_schema"), exclude=["node_modules"]))
            .with_exec(["npm", "install", "-g", "@typespec/compiler"])
            .with_exec(["tsp", "install"])
        )
        self.app_image = (
            dag
            .container()
            .from_("oven/bun:1.2.5-alpine")
            .with_exec(["apk", "--update", "add", "postgresql-client"])
            .with_workdir("/app")
            .with_directory("/app", dag.host().directory(os.path.join(tpl_path, "app_schema"), exclude=["node_modules"]))
            .with_exec(["bun", "install"])
        )
        self.pg_shim = "while ! pg_isready -h postgres -U postgres; do sleep 1; done"

    async def compile_typespec(self, schema: str):
        container = self.tsp_image.with_new_file("schema.tsp", schema)
        result = await self.exec_demux(container, ["tsp", "compile", "schema.tsp", "--no-emit"])
        if result["exit_code"]:
            logger.info(f"Typespec compilation failed with code {result['exit_code']}: stderr {result['stderr']}\nstdout {result['stdout']}")
        return result

    async def compile_gherkin(self, testcases: str):
        container = self.app_image.with_new_file("testcases.feature", testcases)
        return await self.exec_demux(container, ["bun", "run", "gherkin-lint", "testcases.feature", "-c", "gherkin-lint.config.json"])

    async def compile_drizzle(self, schema: str):
        container = (
            self.app_image
            .with_service_binding("postgres", self.tmp_postgres())
            .with_exec(["sh", "-c", self.pg_shim]) # postgres shim
            .with_env_variable("APP_DATABASE_URL", "postgres://postgres:postgres@postgres:5432/postgres")
            .with_new_file("src/db/schema/application.ts", schema)
        )
        result = await self.exec_demux(container, ["bun", "run", "tsc", "--noEmit"])
        if result["exit_code"] != 0:
            logger.info(f"Drizzle compilation failed with code {result['exit_code']}: stderr {result['stderr']}\nstdout {result['stdout']}")
            return result
        return await self.exec_demux(container, ["bun", "run", "drizzle-kit", "push", "--force"])

    @overload
    async def compile_typescript(self, files: dict[str, str]) -> CompileResult:
        ...

    @overload
    async def compile_typescript(self, files: dict[str, str], cmds: list[list[str]]) -> list[CompileResult]:
        ...

    async def compile_typescript(self, files: dict[str, str], cmds: list[list[str]] = None) -> CompileResult | list[CompileResult]:
        container = (
            self.app_image
            .with_service_binding("postgres", self.tmp_postgres())
            .with_exec(["sh", "-c", self.pg_shim]) # postgres shim
            .with_env_variable("APP_DATABASE_URL", "postgres://postgres:postgres@postgres:5432/postgres")
        )
        for path, content in files.items():
            container = container.with_new_file(path, content)
        result = await self.exec_demux(container, ["bun", "run", "tsc", "--noEmit"])
        if result["exit_code"]:
            logger.info(f"Typescript compilation failed with code {result['exit_code']}: stderr {result['stderr']}\nstdout {result['stdout']}")
        if cmds is None:
            return result
        extra_res = [await self.exec_demux(container, cmd) for cmd in cmds]
        return [result, *extra_res]

    @staticmethod
    async def exec_demux(container: Container, command: list[str]) -> CompileResult:
        result = container.with_exec(command, expect=ReturnType.ANY)
        exit_code = await result.exit_code()
        stdout = await result.stdout()
        stderr = await result.stderr()
        if exit_code == 137:
            raise RuntimeError(f"Exec failed: {command} with exit code {exit_code}, stdout: {stdout}, stderr: {stderr}")
        return CompileResult(
            exit_code=exit_code,
            stdout=stdout if stdout else None,
            stderr=stderr if stderr else None,
        )
    
    @staticmethod
    def tmp_postgres() -> Service:
        postgresdb = (
            dag.container()
            .from_("postgres:17.0-alpine")
            .with_env_variable("POSTGRES_USER", "postgres")
            .with_env_variable("POSTGRES_PASSWORD", "postgres")
            .with_env_variable("POSTGRES_DB", "postgres")
            .with_exposed_port(5432)
            .as_service(use_entrypoint=True)
        )
        return postgresdb
