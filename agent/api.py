import shutil
import time
import traceback
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from anthropic import AnthropicBedrock
import jinja2
from core import stages
from shutil import copytree, ignore_patterns
from core.compilers import drizzle as drizzle_compiler
from core.compilers import typespec as typespec_compiler
import docker

app = FastAPI()
docker_client = docker.from_env()

def make_typespec_cmd(typespec_definitions: str):
    return [
        "sh",
        "-c",
        f"echo '{typespec_definitions}' > schema.tsp && tsp compile schema.tsp --no-emit"
    ]

def make_drizzle_cmd(schema: str):
    return [
        "sh",
        "-c",
        f"echo '{schema}' > src/db/schema/application.ts && npx drizzle-kit push"
    ]

def test_drizzle(schema: str):
    containers = docker_client.containers.list(filters={'network': 'test-network'})
    for container in containers:
        container.stop()

    # Remove network
    try:
        docker_client.networks.get('test-network').remove()
    except docker.errors.NotFound:
        pass

    network = docker_client.networks.create("test-network", driver="bridge")
    postgres = docker_client.containers.run(
        "postgres:17.0-alpine",
        detach=True,
        network="test-network",
        hostname="postgres",
        environment={
            "POSTGRES_USER": "postgres",
            "POSTGRES_PASSWORD": "postgres",
            "POSTGRES_DB": "postgres",
        },
    )
    print("healthcheck started")
    # run healthchecks until postgres is ready
    while True:
        try:
            is_ready = postgres.exec_run(["pg_isready", "-U", "postgres"])
            if is_ready.exit_code == 0:
                break
        except docker.errors.APIError:
            time.sleep(0.5)
    print("healthcheck passed")
    print("schema", schema)
    container = docker_client.containers.run(
        "botbuild/app_schema",
        make_drizzle_cmd(schema),
        stderr=True,
        detach=True,
        network="test-network",
        environment={"NO_COLOR": "1", "FORCE_COLOR": "0", "DATABASE_URL": "postgres://postgres:postgres@postgres/postgres"},
    )
    print("attaching container")
    output = container.attach(stdout=True, stderr=True, stream=True, logs=True)
    for line in output:
        print(line.strip())
    print(output)
    print("calling container.wait")
    result = container.wait()
    print("result", result)
    container.remove()
    postgres.stop()
    postgres.remove()
    network.remove()
    return result["StatusCode"]


class Builder:
    def __init__(self, client: AnthropicBedrock, template_dir: str = "templates"):
        self.client = client
        self.template_dir = template_dir
        self.jinja_env = jinja2.Environment()
        self.typespec_tpl = self.jinja_env.from_string(stages.typespec.PROMPT)
        self.drizzle_tpl = self.jinja_env.from_string(stages.drizzle.PROMPT)
        self.router_tpl = self.jinja_env.from_string(stages.router.PROMPT)
        self._model = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    def build(self, application_description: str, out_dir: str = "app_output"):
        try:
            copytree(
                self.template_dir, out_dir, ignore=ignore_patterns("*.pyc", "__pycache__")
            )
        except (shutil.Error, OSError) as e:
            raise Exception(f"Failed to copy template files: {str(e)}")
        # compiler_typespec = typespec_compiler.TypeSpecCompiler(out_dir)
        prompt_typespec = self.typespec_tpl.render(
            application_description=application_description,
        )
        try:
            typespec_response = self.client.messages.create(
                model=self._model,
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt_typespec}],
            )
        except Exception as e:
            raise Exception(f"LLM API call failed: {str(e)}")
        try:
            typespec_definitions =stages.typespec.parse_output(
                typespec_response.content[0].text
            )
        except KeyError as e:
            raise Exception(f"Failed to parse TypeSpec output: {str(e)}")
        
        with open("templates/tsp_schema/main.tsp", "r") as f:
            tsp_schema = f.read()

        tsp_schema = tsp_schema.replace("//{{typespec_definitions}}", typespec_definitions["typespec_definitions"])

        typespec_cmd = make_typespec_cmd(tsp_schema)
        try:
            container = docker_client.containers.run(
                "botbuild/tsp_compiler",
                typespec_cmd,
                stderr=True,
                detach=True,
                remove=True,
                environment={"NO_COLOR": "1", "FORCE_COLOR": "0"},
            )
            print("container", container)
            output = container.attach(stdout=True, stderr=True, stream=True, logs=True)
            for line in output:
                print(line.strip())
            print(output)
            typespec_result = container.wait()
            
            print("typespec_result", typespec_result)
        except docker.errors.ContainerError as e:
            raise Exception(f"TypeSpec compilation failed: {str(e)}")

        print("finished typespec", typespec_result)
        if typespec_result["StatusCode"] != 0:
           raise Exception("Failed to compile typespec")

        # compiler_drizzle = drizzle_compiler.DrizzleCompiler(out_dir)
        prompt_drizzle = self.drizzle_tpl.render(
            typespec_definitions=typespec_definitions["typespec_definitions"],
        )
        drizzle_response = self.client.messages.create(
            model=self._model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt_drizzle}],
        )
        drizzle_schema = stages.drizzle.parse_output(drizzle_response.content[0].text)
        # drizzle_result = compiler_drizzle.compile(drizzle_schema["drizzle_schema"])

        code = test_drizzle(drizzle_schema["drizzle_schema"])
        print("drizzle test finished", code)
        if code != 0:
            raise Exception("Failed to compile drizzle")

        prompt_router = self.router_tpl.render(
            typespec_definitions=typespec_definitions["typespec_definitions"],
            user_request=application_description,
        )
        router_response = self.client.messages.create(
            model=self._model,
            max_tokens=8192,
            tools=stages.router.TOOLS,
            messages=[{"role": "user", "content": prompt_router}],
        )
        print("ROUTER_RESPONSE", router_response)
        router_result = stages.router.parse_outputs(
            [content for content in router_response.content]
        )["user_functions"]
        return {
            "typespec": tsp_schema,
            "drizzle": drizzle_schema["drizzle_schema"],
            "router": router_result,
        }


class BuildRequest(BaseModel):
    description: str


@app.post("/build")
async def build_endpoint(request: BuildRequest):
    try:
        client = AnthropicBedrock(aws_profile="dev", aws_region="us-west-2")
        builder = Builder(client, template_dir="templates")
        shutil.rmtree('app_output')
        app_result = builder.build(request.description, out_dir="app_output")
        return app_result
    except shutil.Error as e:
        print(e)
        raise HTTPException(status_code=500, detail="File system operation failed")
    except Exception as e:
        print(e)
        print("Traceback:")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
