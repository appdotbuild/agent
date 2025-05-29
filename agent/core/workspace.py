from os import name
from typing import Self
import dagger
from dagger import dag, function, object_type, Container, Directory, ReturnType
from log import get_logger
import hashlib
from core.postgres_utils import create_postgres_service
from core.dagger_utils import ExecResult
import uuid

logger = get_logger(name)


def _sorted_set(s: set[str]) -> list[str]:
    return sorted(list(s))


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

        ctr = ctr.with_env_variable("INSTANCE_ID", uuid.uuid4().hex)
        return cls(ctr=ctr, start=context, protected=set(protected), allowed=set(allowed))

    @function
    def permissions(self, protected: list[str] = [], allowed: list[str] = []) -> Self:
        self.protected = set(protected)
        self.allowed = set(allowed)
        return self

    @function
    def cwd(self, path: str) -> Self:
        self.ctr = self.ctr.with_workdir(path)
        return self

    @function
    def rm(self, path: str) -> Self:
        protected = self.protected - self.allowed # allowed take precedence
        if any(path.startswith(p) for p in protected):
            raise PermissionError(f"Attempted to remove {path} which is in protected paths: {_sorted_set(protected)}")
        self.ctr = self.ctr.without_file(path)
        return self

    @function
    async def ls(self, path: str) -> list[str]:
        try:
            return await self.ctr.directory(path).entries()
        except dagger.QueryError:
            raise FileNotFoundError(f"Directory not found: {path}")

    @function
    async def read_file(self, path: str) -> str:
        try:
            return await self.ctr.file(path).contents()
        except dagger.QueryError:
            raise FileNotFoundError(f"File not found: {path}")

    @function
    def write_file(self, path: str, contents: str, force: bool = False) -> Self:
        if not force:
            protected = self.protected - self.allowed # allowed take precedence
            if self.allowed and not any(path.startswith(p) for p in self.allowed):
                raise PermissionError(f"Attempted to write {path} which is not in allowed paths: {_sorted_set(self.allowed)}")
            if any(path.startswith(p) for p in protected):
                raise PermissionError(f"Attempted to write {path} which is in protected paths: {_sorted_set(protected)}")
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
    async def diff(self) -> str:
        start = dag.container().from_("alpine/git").with_workdir("/app").with_directory("/app", self.start)
        if ".git" not in await self.start.entries():
            start = (
                start.with_exec(["git", "init"])
                .with_exec(["git", "config", "--global", "user.email", "agent@appbuild.com"])
                .with_exec(["git", "add", "."])
                .with_exec(["git", "commit", "-m", "'initial'"])
            )
        diff_output = (
            await start.with_directory(".", self.ctr.directory("."))
            .with_exec(["git", "add", "."])
            .with_exec(["git", "diff", "HEAD"])
            .stdout()
        )

        # ------------------- Added verbose logging -------------------
        diff_len = len(diff_output)
        diff_hash = hashlib.sha256(diff_output.encode("utf-8")).hexdigest()
        logger.info(
            "workspace.diff: Generated diff (length=%d, sha256=%s)",
            diff_len,
            diff_hash,
        )
        if diff_output:
            preview_lines = "\n".join(diff_output.splitlines()[20:])
            logger.debug("workspace.diff preview (last 20 lines):\n%s", preview_lines)
        else:
            logger.debug("workspace.diff: Diff output is empty.")
        # -------------------------------------------------------------

        return diff_output

    @function
    async def exec(self, command: list[str], cwd: str = ".") -> ExecResult:
        return await ExecResult.from_ctr(
            self.ctr.with_workdir(cwd).with_exec(command, expect=ReturnType.ANY)
        )

    @function
    async def exec_with_pg(self, command: list[str], cwd: str = ".") -> ExecResult:
        postgresdb = create_postgres_service()

        return await ExecResult.from_ctr(
            self.ctr
            .with_exec(["apk", "--update", "add", "postgresql-client"]) # TODO: might be not needed
            .with_service_binding("postgres", postgresdb)
            .with_env_variable("APP_DATABASE_URL", "postgres://postgres:postgres@postgres:5432/postgres")
            .with_exec(["sh", "-c", "while ! pg_isready -h postgres -U postgres; do sleep 1; done"])
            .with_workdir(cwd)
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
        return type(self)(
            ctr=self.ctr,
            start=self.start,
            protected=self.protected,
            allowed=self.allowed
        )

    @function
    async def run_playwright(self,
                            service: dagger.Service,
                            output_path: str | None,
                            port: int = 5173
    ) -> ExecResult:
        config_content = await self.read_file("playwright.config.ts")
        host = "debughost"
        updated_config = config_content.replace(
            'baseURL: "http://127.0.0.1:8080"',
            f'baseURL: "http://{host}:{port}"'
        )
        playwright_ctr = (
            dag.container()
            .from_("mcr.microsoft.com/playwright:v1.52.0")
            .with_directory("/app", self.ctr.directory("."))
            .with_workdir("/app")
            .with_new_file("playwright.config.ts", updated_config)
            .with_service_binding(host, service)
            .with_exposed_port(port)
            .with_exec(["npm", "install"])
            .with_exec(["npx", "playwright", "test"], expect=ReturnType.ANY)
        )

        result = await ExecResult.from_ctr(
            playwright_ctr
        )
        if output_path:
            await playwright_ctr.directory("/app/test_results").export(output_path)
        return result
