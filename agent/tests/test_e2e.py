import os
import pytest
import tempfile
import anyio
import contextlib

from fire import Fire
from api.agent_server.agent_client import AgentApiClient
from api.agent_server.agent_api_client import apply_patch, latest_unified_diff, DEFAULT_APP_REQUEST, spawn_local_server
from api.docker_utils import setup_docker_env, start_docker_compose, wait_for_healthy_containers, stop_docker_compose, get_container_logs
from log import get_logger

logger = get_logger(__name__)

pytestmark = pytest.mark.anyio


@contextlib.contextmanager
def empty_context():
    yield

@pytest.fixture
def anyio_backend():
    return 'asyncio'

async def run_e2e(prompt: str, standalone: bool):
    context = empty_context() if standalone else spawn_local_server()
    with context:
        async with AgentApiClient() as client:
            events, request = await client.send_message(prompt)
            assert events, "No response received from agent"
            diff = latest_unified_diff(events)
            assert diff, "No diff was generated in the agent response"

            with tempfile.TemporaryDirectory() as temp_dir:
                success, message = apply_patch(diff, temp_dir)
                assert success, f"Failed to apply patch: {message}"

                original_dir = os.getcwd()
                container_names = setup_docker_env()
                try:
                    os.chdir(temp_dir)

                    success, error_message = start_docker_compose(temp_dir, container_names["project_name"])
                    if not success:
                        # Get logs if possible for debugging
                        try:
                            logs = get_container_logs([
                                container_names["db_container_name"],
                                container_names["app_container_name"],
                                container_names["frontend_container_name"]
                            ])
                            for container, log in logs.items():
                                logger.error(f"Container {container} logs: {log}")
                        except Exception:
                            logger.error("Failed to get container logs")

                        logger.error(f"Error starting Docker containers: {error_message}")
                        raise RuntimeError(f"Failed to start Docker containers: {error_message}")

                    container_healthy = await wait_for_healthy_containers(
                        [
                            container_names["db_container_name"],
                            container_names["app_container_name"],
                            container_names["frontend_container_name"]
                        ],
                        ["db", "app", "frontend"],
                        timeout=30,
                        interval=1
                    )

                    if not container_healthy:
                        raise RuntimeError("Containers did not become healthy within the timeout period")

                    if standalone:
                        input(f"App is running on http://localhost:80/, app dir is {temp_dir}; Press Enter to continue and tear down...")
                        print("🧹Tearing down containers... ")

                finally:
                    # Restore original directory
                    os.chdir(original_dir)

                    # Clean up Docker containers
                    stop_docker_compose(temp_dir, container_names["project_name"])

async def test_e2e_generation():
    await run_e2e(standalone=False, prompt=DEFAULT_APP_REQUEST)

def create_app(prompt):
    import coloredlogs

    coloredlogs.install(level="INFO")
    anyio.run(run_e2e, prompt, True)


if __name__ == "__main__":
    Fire(create_app)
