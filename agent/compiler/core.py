from typing import TypedDict, overload
import time
import uuid
import shlex
from contextlib import contextmanager
import docker
import docker.models
from docker.errors import APIError
import docker.models.containers
from logging import getLogger

logger = getLogger(__name__)

class CompileResult(TypedDict):
    exit_code: int
    stdout: str | None
    stderr: str | None


class Compiler:
    def __init__(self, tsp_image: str, app_image: str):
        self.tsp_image = tsp_image
        self.app_image = app_image
        self.client = docker.from_env()

    def compile_typespec(self, schema: str):
        container = self.client.containers.run(
            self.tsp_image,
            command=["sleep", "10"],
            detach=True,
        )
        schema_path, schema = "schema.tsp", shlex.quote(schema)
        command = [
            "sh",
            "-c",
            f"echo {schema} > {schema_path} && tsp compile {schema_path} --no-emit"
        ]
        result = self.exec_demux(container, command)
        container.remove(force=True)
        return result

    def compile_gherkin(self, testcases: str):
        with self.app_container() as container:
            schema_path, schema = "testcases.feature", shlex.quote(testcases)
            command = [
                "sh",
                "-c",
                f"echo {schema} > {schema_path} && npx gherkin-lint {schema_path} -c gherkin-lint.config.json"
            ]
            return self.exec_demux(container, command)

    def compile_drizzle(self, schema: str):
        with self.tmp_network() as network, self.tmp_postgres() as postgres, self.app_container() as container:
            network.connect(postgres)
            network.connect(container)
            Compiler.copy_files(container, {"src/db/schema/application.ts": schema})
            result = self.exec_demux(container, ["npx", "tsc", "--noEmit"])
            if result["exit_code"] != 0:
                return result
            return self.exec_demux(container, ["npx", "drizzle-kit", "push", "--force"])

    @overload
    def compile_typescript(self, files: dict[str, str]) -> CompileResult:
        ...

    @overload
    def compile_typescript(self, files: dict[str, str], cmds: list[list[str]]) -> list[CompileResult]:
        ...

    def compile_typescript(self, files: dict[str, str], cmds: list[list[str]] = None) -> CompileResult | list[CompileResult]:
        with self.tmp_network() as network, self.tmp_postgres() as postgres, self.app_container() as container:
            network.connect(postgres)
            network.connect(container)
            Compiler.copy_files(container, files)
            result = self.exec_demux(container, ["npx", "tsc", "--noEmit"])
            if result["exit_code"]:
                error = result["stderr"] or result["stdout"]
                logger.info(f"Typescript compilation failed: {error}")
            if cmds is None:
                return result
            cmds = [self.exec_demux(container, cmd) for cmd in cmds]
            return [result, *cmds]

    @staticmethod
    def copy_files(container: docker.models.containers.Container, files: dict[str, str]):
        for path, content in files.items():
            path, content = shlex.quote(path), shlex.quote(content)
            command = ["sh", "-c", f"echo {content} > {path}"]
            exit_code, _ = container.exec_run(
                command,
                demux=True,
                environment={"NO_COLOR": "1", "FORCE_COLOR": "0"},
            )
            if exit_code != 0:
                raise ValueError(f"Failed to write file {path}")

    @staticmethod
    def exec_demux(container: docker.models.containers.Container, command: list[str]) -> CompileResult:
        exit_code, (stdout, stderr) = container.exec_run(
            command,
            demux=True,
            environment={"NO_COLOR": "1", "FORCE_COLOR": "0", "APP_DATABASE_URL": "postgres://postgres:postgres@postgres:5432/postgres"},
        )
        return CompileResult(
            exit_code=exit_code,
            stdout=stdout.decode("utf-8", errors="replace") if stdout else None,
            stderr=stderr.decode("utf-8", errors="replace") if stderr else None,
        )

    @contextmanager
    def app_container(self):
        container = self.client.containers.run(
            self.app_image,
            command=["sleep", "10"],
            detach=True,
        )
        try:
            yield container
        finally:
            container.remove(force=True)

    @contextmanager
    def tmp_network(self, network_name: str | None = None, driver: str = "bridge"):
        network_name = network_name or uuid.uuid4().hex
        try:
            network = self.client.networks.create(network_name, driver=driver)
            yield network
        finally:
            network.remove()

    @contextmanager
    def tmp_postgres(self):
        container = self.client.containers.run(
            "postgres:17.0-alpine",
            detach=True,
            hostname="postgres",
            environment={
                "POSTGRES_USER": "postgres",
                "POSTGRES_PASSWORD": "postgres",
                "POSTGRES_DB": "postgres",
            },
        )
        try:
            while True:
                try:
                    is_ready = container.exec_run(["pg_isready", "-U", "postgres"])
                    if is_ready.exit_code == 0:
                        break
                except APIError:
                    time.sleep(0.1)
            yield container
        finally:
            container.remove(force=True, v=True)
