import tempfile
import uuid
import random
import os
import sys
import anyio
import logging
import string
import subprocess
import time
import docker
import shutil
import httpx
import pytest

from fire import Fire
from langfuse.decorators import langfuse_context

import dagger
from application import Application
from dag_compiler import Compiler
from core.interpolator import Interpolator
from fsm_core.llm_common import get_sync_client, CacheMode
from log import get_logger


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


logger = get_logger(__name__)

DEFAULT_PROMPT = "make me a very simple bot: it should take name from the input message and return greeting for this name, it must have only one handler"


def generate_random_name(prefix, length=8):
    return prefix + "".join(
        random.choices(string.ascii_lowercase + string.digits, k=length)
    )


async def test_end2end(initial_description: str = DEFAULT_PROMPT, mode: CacheMode = "replay"):
    """Full bot creation and update workflow"""
    # Use the correct Docker image names from prepare_containers.sh
    compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")
    client = get_sync_client(
        cache_mode=mode,
        model_name="sonnet",
    )
    application = Application(client, compiler)
    langfuse_context.configure(enabled=bool(os.getenv("LANGFUSE_ENABLED", "")))

    bot_id = str(uuid.uuid4().hex)
    prepared_bot = await application.prepare_bot([initial_description], bot_id=bot_id)
    my_bot = await application.update_bot(
        typespec_schema=prepared_bot.typespec.typespec_definitions or "",
        bot_id=bot_id,
        capabilities=prepared_bot.capabilities.capabilities or [],
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        interpolator = Interpolator(os.path.join(current_dir, "../"))
        # Only use bake with ApplicationOut, not ApplicationPrepareOut
        interpolator.bake(my_bot, temp_dir)

        logger.info("Generation complete, testing in docker")
        # change directory to tempdir and run docker compose
        dir_to_return = os.getcwd()
        os.chdir(temp_dir)

        env = os.environ.copy()
        env["APP_CONTAINER_NAME"] = generate_random_name("app_")
        env["POSTGRES_CONTAINER_NAME"] = generate_random_name("db_")
        env["NETWORK_NAME"] = generate_random_name("network_")
        env["RUN_MODE"] = "http-server"
        try:
            cmd = ["docker", "compose", "-p", "botbuild", "up", "-d"]
            result = subprocess.run(
                cmd, check=False, env=env, capture_output=True, text=True
            )
            assert (
                result.returncode == 0
            ), f"Docker compose failed with error: {result.stderr}"
            time.sleep(5)
            client = docker.from_env()
            app_container = client.containers.get(env["APP_CONTAINER_NAME"])
            db_container = client.containers.get(env["POSTGRES_CONTAINER_NAME"])

            assert (
                app_container.status == "running"
            ), f"App container {env['APP_CONTAINER_NAME']} is not running"
            assert (
                db_container.status == "running"
            ), f"Postgres container {env['POSTGRES_CONTAINER_NAME']} is not running"

            # make a request to the http server
            base_url = "http://localhost:8989"
            time.sleep(5)  # to ensure migrations are done
            # retry a few times to handle potential timeouts on slower machines
            max_retries = 3  # typically need 2 for a local machine, but CI might need more
            response = None
            for attempt in range(max_retries):
                try:
                    response = httpx.post(
                        f"{base_url}/chat",
                        json={"message": "hello", "user_id": "123"},
                        timeout=15,
                    )
                    break
                except httpx.HTTPError as e:
                    if attempt < max_retries - 1:
                        logger.info(
                            f"request timed out, retrying ({attempt+1}/{max_retries}). Error: {e}"
                        )

                        # fetch fresh container status and logs
                        app_status = app_container.status
                        db_status = db_container.status

                        app_logs = app_container.logs()
                        db_logs = db_container.logs()

                        logger.info(f"App container status: {app_status}")
                        logger.info(f"App container logs: {app_logs}")
                        logger.info(f"DB container status: {db_status}")
                        logger.info(f"DB container logs: {db_logs}")

                        time.sleep(3 * (attempt + 1))
                    else:
                        raise

            # FixMe: if Bedrock credentials are available, the response should be 200, otherwise 500
            # CI has no Bedrock credentials, so we expect 500, in local development, we expect 200
            # Should be unified!
            assert response.status_code in (
                200,
                500,
            ), f"Expected status code 200 or 500, got {response.status_code}"
            if response.status_code == 200:
                assert response.json()["reply"]
            logger.info("Docker compose test passed")
        finally:
            try:
                cmd = ["docker", "compose", "-p", "botbuild", "down"]
                subprocess.run(cmd, check=True, env=env, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                logger.exception(f"Error downing docker compose: {e}")
                raise e
            os.chdir(dir_to_return)


def update_cache(
    prompt: str = DEFAULT_PROMPT,
    mode: CacheMode = "record",
):
    test_end2end(prompt, mode=mode)


if __name__ == "__main__":
    Fire(update_cache)
