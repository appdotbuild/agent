import anyio
import dagger
from dagger import dag, Container
from sandboxes.workspace.src.workspace import Workspace


def run_with_postgres(container: Container, command: list[str]) -> Container:
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
        container
        .with_service_binding("postgres", postgresdb)
        .with_exec(command)
    )


async def run_application():
    workspace = await Workspace.create(
        base_image="oven/bun:1.2.5-alpine",
        context=dag.host().directory("./prefabs/backend", exclude=["node_modules"])
    )
    workspace = await workspace.exec_mut(["bun", "install"]) # this will overwrite container
    head = await workspace.read_file("src/main.ts")
    print("src/main.ts", head[:20])
    print("=" * 80)

    result = workspace.exec(["bun", "tsc", "--noEmit"])
    exit_code = await result.exit_code()
    stdout = await result.stdout()
    stderr = await result.stderr()
    print("tsc compile", exit_code, stdout, stderr)
    print("=" * 80)

    result = run_with_postgres(workspace.ctr, ["bun", "run", "drizzle-kit", "push", "--force"])
    exit_code = await result.exit_code()
    stdout = await result.stdout()
    stderr = await result.stderr()
    print("drizzle-kit push", exit_code, stdout, stderr)
    print("=" * 80)


BAD_TYPESPEC = """
model Pet {
  id: int32;
  name: string;
  age: int36;
  kind: petType;
}

enum petType {
  dog: "dog",
  cat: "cat",
  fish: "fish",
  bird: "bird",
  reptile: "reptile",
}
""".strip()


async def run_typespec():
    workspace = await Workspace.create(
        base_image="node:23-alpine",
        context=dag.host().directory("./prefabs/typespec")
    )
    workspace = await workspace.exec_mut(["npm", "install", "-g", "@typespec/compiler"])
    workspace = await workspace.exec_mut(["tsp", "install"])

    result = (
        workspace
        .write_file("schema.tsp", BAD_TYPESPEC)
        .exec(["tsp", "compile", "schema.tsp", "--no-emit"])
    )
    exit_code = await result.exit_code()
    stdout = await result.stdout()
    stderr = await result.stderr()
    print("tsp_compile", exit_code, stdout, stderr)
    print("=" * 80)


async def main():
    async with dagger.connection():
        await run_application()
        await run_typespec()


anyio.run(main)