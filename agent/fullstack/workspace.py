from typing import Self
import dagger
from dagger import dag, function, object_type, Container, Directory, ReturnType


@object_type
class Workspace:
    ctr: Container
    start: Directory
    protected: set[str]
    allowed: set[str]

    @classmethod
    async def create(
        cls,
        base_image: str = "alpine",
        context: Directory = dag.directory(),
        setup_cmd: list[list[str]] = [],
        protected: list[str] = [],
        allowed: list[str] = [],
    ) -> Self:
        ctr = (
            dag
            .container()
            .from_(base_image)
            .with_workdir("/app")
            .with_directory("/app", context)
        )
        for cmd in setup_cmd:
            ctr = ctr.with_exec(cmd)
        return cls(ctr=ctr, start=context, protected=set(protected), allowed=set(allowed))
    
    @function
    def permissions(self, protected: list[str] = [], allowed: list[str] = []) -> Self:
        self.protected = set(protected)
        self.allowed = set(allowed)
        return self
    
    @function
    def rm(self, path: str) -> Self:
        protected = self.protected - self.allowed # allowed take precedence
        if any(path.startswith(p) for p in protected):
            raise PermissionError(f"Attempted to remove {path} which is in protected paths: {protected}")
        self.ctr = self.ctr.without_file(path)
        return self
    
    @function
    async def ls(self, path: str) -> list[str]:
        try:
            return await self.ctr.directory(path).entries()
        except dagger.QueryError as e:
            raise FileNotFoundError(f"Directory not found: {path}")
    
    @function
    async def read_file(self, path: str) -> str:
        try:
            return await self.ctr.file(path).contents()
        except dagger.QueryError as e:
            raise FileNotFoundError(f"File not found: {path}")
    
    @function
    def write_file(self, path: str, contents: str) -> Self:
        protected = self.protected - self.allowed # allowed take precedence
        if self.allowed and not any(path.startswith(p) for p in self.allowed):
            raise PermissionError(f"Attempted to write {path} which is not in allowed paths: {self.allowed}")
        if any(path.startswith(p) for p in protected):
            raise PermissionError(f"Attempted to write {path} which is in protected paths: {protected}")
        self.ctr = self.ctr.with_new_file(path, contents)
        return self

    @function
    async def read_file_lines(self, path: str, start: int = 1, end: int = 100) -> str:
        return (
            await self.ctr
            .with_exec(["sed", "-n", f"{start},{end}p", path])
            .stdout()
        )
    
    @function
    def exec(self, command: list[str]) -> Container:
        return self.ctr.with_exec(command, expect=ReturnType.ANY)
    
    @function
    def exec_with_pg(self, command: list[str]) -> Container:
        postgresdb = (
            dag.container()
            .from_("postgres:17.0-alpine")
            .with_env_variable("POSTGRES_USER", "postgres")
            .with_env_variable("POSTGRES_PASSWORD", "postgres")
            .with_env_variable("POSTGRES_DB", "postgres")
            .with_exposed_port(5432)
            .as_service(use_entrypoint=True)
        )

        return (
            self.ctr
            .with_service_binding("postgres", postgresdb)
            .with_env_variable("DATABASE_URL", "postgres://postgres:postgres@postgres:5432/postgres")
            .with_exec(command, expect=ReturnType.ANY)
        )
    
    @function
    async def exec_mut(self, command: list[str]) -> Self:
        ctr = self.ctr.with_exec(command, expect=ReturnType.ANY)
        if await ctr.exit_code() != 0:
            raise Exception(f"Command failed: {command}\nError: {await ctr.stderr()}")
        self.ctr = ctr
        return self
    
    @function
    def reset(self) -> Self:
        self.ctr = self.ctr.with_directory(".", self.start)
        return self
    
    @function
    def container(self) -> Container:
        return self.ctr
    
    @function
    def clone(self) -> Self:
        return Workspace(
            ctr=self.ctr,
            start=self.start,
            protected=self.protected,
            allowed=self.allowed
        )
