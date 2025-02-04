from typing import TypedDict
import time
import uuid
from contextlib import contextmanager
import docker
from docker.errors import APIError


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
        schema_path, schema = "schema.tsp", schema.replace("'", "\'")
        command = [
            "sh",
            "-c",
            f"echo '{schema}' > {schema_path} && tsp compile {schema_path} --no-emit"
        ]
        exit_code, (stdout, stderr) = container.exec_run(
            command,
            demux=True,
            environment={"NO_COLOR": "1", "FORCE_COLOR": "0"},
        )
        container.remove(force=True)
        return CompileResult(
            exit_code=exit_code,
            stdout=stdout.decode("utf-8") if stdout else None,
            stderr=stderr.decode("utf-8") if stderr else None,
        )
    
    def compile_drizzle(self, schema: str):
        with self.tmp_network() as network, self.tmp_postgres() as postgres:
            network.connect(postgres)
            schema_path, schema = "src/db/schema/application.ts", schema.replace("'", "\'")
            container = self.client.containers.run(
                self.app_image,
                command=["sleep", "10"],
                detach=True,
                network=network.name,
            )
            command = [
                "sh",
                "-c",
                f"echo '{schema}' > {schema_path} && npx drizzle-kit push"
            ]
            exit_code, (stdout, stderr) = container.exec_run(
                command,
                demux=True,
                environment={"NO_COLOR": "1", "FORCE_COLOR": "0"},
            )
            container.remove(force=True)
            return CompileResult(
                exit_code=exit_code,
                stdout=stdout.decode("utf-8") if stdout else None,
                stderr=stderr.decode("utf-8") if stderr else None,
            )
        
    def compile_typescript(self, files: dict[str, str]):
        container = self.client.containers.run(
            self.app_image,
            command=["sleep", "10"],
            detach=True,
        )
        for path, content in files.items():
            content = content.replace("'", "\'")
            command = [
                "sh",
                "-c",
                f"echo '{content}' > {path}"
            ]
            container.exec_run(
                command,
                environment={"NO_COLOR": "1", "FORCE_COLOR": "0"},
            )
        exit_code, (stdout, stderr) = container.exec_run(
            ["npx", "tsc", "--noEmit"],
            demux=True,
            environment={"NO_COLOR": "1", "FORCE_COLOR": "0"},
        )
        container.remove(force=True)
        return CompileResult(
            exit_code=exit_code,
            stdout=stdout.decode("utf-8") if stdout else None,
            stderr=stderr.decode("utf-8") if stderr else None,
        )
    
    @contextmanager
    def tmp_network(self, network_name: str = None, driver: str = "bridge"):
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
            container.remove(force=True)
