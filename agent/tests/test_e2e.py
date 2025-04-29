import os
import pytest
import subprocess
import tempfile
import anyio
from datetime import datetime
import docker

from fire import Fire
from api.agent_server.agent_client import AgentApiClient
from api.agent_server.agent_api_client import apply_patch, latest_unified_diff, DEFAULT_APP_REQUEST
from log import get_logger

logger = get_logger(__name__)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'

def generate_random_name(prefix):
    return f"{prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}"

async def run_e2e(prompt: str, standalone: bool):
    async with AgentApiClient() as client:
        events, request = await client.send_message(prompt)
        assert events, "No response received from agent"
        diff = latest_unified_diff(events)
        assert diff, "No diff was generated in the agent response"

        with tempfile.TemporaryDirectory() as temp_dir:
            success, message = apply_patch(diff, temp_dir)
            assert success, f"Failed to apply patch: {message}"

            db_container_name = generate_random_name("db")
            app_container_name = generate_random_name("app")
            frontend_container_name = generate_random_name("frontend")

            os.environ["POSTGRES_CONTAINER_NAME"] = db_container_name
            os.environ["BACKEND_CONTAINER_NAME"] = app_container_name
            os.environ["FRONTEND_CONTAINER_NAME"] = frontend_container_name
            os.environ["DB_PUSH_CONTAINER_NAME"] = generate_random_name("db_push_")
            os.environ["NETWORK_NAME"] = generate_random_name("network_")

            original_dir = os.getcwd()
            try:
                os.chdir(temp_dir)

                logger.info(f"Starting Docker containers in {temp_dir}")
                _= subprocess.run(
                    ["docker", "compose", "up", "-d"],
                    check=True,
                    capture_output=True,
                    text=True
                )

                docker_cli = docker.from_env()

                timeout = 30  # seconds
                interval = 1 # seconds
                start_time = anyio.current_time()

                while anyio.current_time() - start_time < timeout:
                    all_healthy = True
                    for name, kind in zip(
                        [db_container_name, app_container_name, frontend_container_name],
                        ["db", "app", "frontend"]
                    ):
                        container = docker_cli.containers.get(name)
                        if container.status != "running":
                            logger.info(f"{kind} container is not running yet: {container.status}")
                            all_healthy = False
                            break

                        health_status = container.attrs.get('State', {}).get('Health', {}).get('Status')
                        if health_status != 'healthy':
                            logger.info(f"{kind} container is not healthy yet: {health_status}")
                            all_healthy = False
                            break
                        logger.info(f"{kind} container is healthy.")

                    if all_healthy:
                        logger.info("All containers are healthy.")
                        break
                    await anyio.sleep(interval)

                if anyio.current_time() - start_time >= timeout:
                    raise RuntimeError(f"Containers did not become healthy within {timeout} seconds")

                if standalone:
                    input(f"App is running on http://localhost:80/, app dir is {temp_dir}; Press Enter to continue and tear down...")
                    print("🧹Tearing down containers... ")

            finally:
                # Restore original directory
                os.chdir(original_dir)

                # Clean up Docker containers
                try:
                    subprocess.run(
                        ["docker", "compose", "down", "-v"],
                        cwd=temp_dir,
                        check=False,
                        capture_output=True,
                        text=True
                    )
                except Exception as e:
                    logger.exception(f"Error cleaning up Docker: {e}")

async def test_e2e_generation():
    await run_e2e(standalone=False, prompt=DEFAULT_APP_REQUEST)

def create_app(prompt):
    import coloredlogs

    coloredlogs.install(level="INFO")
    anyio.run(run_e2e, prompt, True)


if __name__ == "__main__":
    Fire(create_app)
