import sys
import anyio
import subprocess
import dagger
from dagger import dag


DRY_RUN = """
import sys
import anyio
import dagger
from dagger import dag

async def main():
    async with dagger.connection(dagger.Config(log_output=sys.stderr)):
        print("inside async with dagger")
        container = dag.container().from_("oven/bun:1.2.5-alpine")
        result = await container.with_exec(["bun"])
        print(await result.stdout())


if __name__ == "__main__":
    anyio.run(main)
""".strip()


async def build_runtime_docker(tag: str):
    alpine = dag.container().from_("alpine:3.20.6")
    base = (
        dag.container()
        .from_("registry.dagger.io/engine:v0.17.1")
        .with_env_variable("DAGGER_VERSION", "0.17.1")
        .with_env_variable("_EXPERIMENTAL_DAGGER_RUNNER_HOST", "unix:///var/run/buildkit/buildkitd.sock")
        .with_directory("/lib/apk/db", alpine.directory("/lib/apk/db"))
        .with_directory("/etc/apk", alpine.directory("/etc/apk"))
    )
    runtime = (
        base
        .with_exec(["apk", "update"])
        .with_exec(["apk", "add", "curl"])
        .with_exec(["apk", "add", "python3"])
        .with_exec(["curl", "-fsSL", "https://astral.sh/uv/install.sh", "-o", "/tmp/install.sh"])
        .with_exec(["sh", "-c", "XDG_BIN_HOME=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh /tmp/install.sh"])
        .with_workdir("/app")
        .with_directory("/app", dag.host().directory("./fullstack", include=["uv.lock", "pyproject.toml", ".python-version"]))
        .with_new_file("/app/dry_run.py", DRY_RUN)
        .with_exec(["uv", "run", "dry_run.py"], experimental_privileged_nesting=True)
    )
    img_path = "./appbuild_runtime.tar"
    await runtime.export(img_path)
    load_cmd = subprocess.run(["docker", "load", "-i", img_path], capture_output=True)
    print(load_cmd)
    img_hash = load_cmd.stdout.decode().split(":")[-1].strip()
    tag_cmd = subprocess.run(["docker", "tag", img_hash, tag], capture_output=True)
    print(tag_cmd)
    subprocess.run(["rm", img_path])


async def main(tag: str):
    async with dagger.connection(dagger.Config(log_output=sys.stderr)):
        await build_runtime_docker(tag)


if __name__ == "__main__":
    tag = "appbuild_alpine:latest"
    anyio.run(main, tag)
