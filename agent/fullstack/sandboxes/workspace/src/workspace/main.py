from typing import Self
from dagger import dag, function, object_type, Container, Directory, ReturnType


@object_type
class Workspace:
    ctr: Container
    start: Directory

    @classmethod
    async def create(cls, base_image: str = "alpine", context: Directory = dag.directory()):
        ctr = (
            dag
            .container()
            .from_(base_image)
            .with_workdir("/app")
            .with_directory("/app", context)
        )
        return cls(ctr=ctr, start=context)
    
    @function
    async def ls(self, path: str) -> list[str]:
        return await self.ctr.directory(path).entries()
    
    @function
    async def read_file(self, path: str) -> str:
        return await self.ctr.file(path).contents()
    
    @function
    def write_file(self, path: str, contents: str) -> Self:
        self.ctr = self.ctr.with_new_file(path, contents)
        return self

    @function
    async def read_file_lines(self, path: str, start: int = 1, end: int = 100) -> str:
        return (
            await self.ctr
            .with_exec([
                "sed",
                "-n",
                f"'{start},{end}p'",
                path
            ]).stdout()
        )
    
    @function
    def exec(self, command: list[str]) -> Container:
        return self.ctr.with_exec(command, expect=ReturnType.ANY)
    
    @function
    async def exec_mut(self, command: list[str]) -> Self:
        cmd = (
            self.ctr
            .with_exec(command, expect=ReturnType.ANY)
        )
        if await cmd.exit_code() != 0:
            raise Exception(f"Command failed: {command}\nError: {await cmd.stderr()}")
        self.ctr = cmd
        return self
    
    @function
    def reset(self) -> Self:
        self.ctr = self.ctr.with_directory(".", self.start)
        return self
    
    @function
    def container(self) -> Container:
        return self.ctr
