import docker
import httpx
import asyncio
import logging
import os
import sys
import time

import coloredlogs
coloredlogs.install(level='INFO')

DOCKERFILE_PATH = "./Dockerfile"
BUILD_CONTEXT = "."
IMAGE_NAME = "api-async-server:debug"
CONTAINER_NAME = "api-async-server"
HOST_PORT = 8001
CONTAINER_PORT = 8001
HEALTHCHECK_URL = f"http://localhost:{HOST_PORT}/health"
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 2
REQUEST_TIMEOUT = 5
STARTUP_WAIT = 3

# --- Logging ---
logger = logging.getLogger(__name__)

# --- Docker Client ---
try:
    docker_client = docker.from_env()
    docker_client.ping()
except Exception as e:
    logger.error(f"Docker client init failed: {e}")
    sys.exit(1)

async def check_server_health():
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for attempt in range(MAX_RETRIES):
            try:
                response = await client.get(HEALTHCHECK_URL)
                response.raise_for_status() # Raise exception for 4xx/5xx
                data = response.json()
                if data.get("status") == "healthy":
                    logger.info(f"✅ Server healthy (Attempt {attempt + 1})")
                    return True
                else:
                     logger.warning(f"⚠️ Healthcheck unhealthy content: {data} (Attempt {attempt + 1})")
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                logger.warning(f"⚠️ Healthcheck failed: {type(e).__name__} (Attempt {attempt + 1})")
            except Exception as e:
                 logger.exception(f"⚠️ Healthcheck unexpected error: {e} (Attempt {attempt + 1})")

            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_DELAY_SECONDS)
    logger.error(f"❌ Server health check failed after {MAX_RETRIES} attempts.")
    return False



async def main():
    container = None
    exit_code = 1 # Default to failure
    try:
        logger.info(f"Building image {IMAGE_NAME}...")
        try:
             docker_client.images.build(
                path=BUILD_CONTEXT, dockerfile=DOCKERFILE_PATH, tag=IMAGE_NAME, rm=True, forcerm=True
            )
        except docker.errors.BuildError as e:
            logger.error("Docker build failed:")
            for line in e.build_log:
                if 'stream' in line: logger.error(f"  {line['stream'].strip()}")
            return 1 # Exit code 1 for build failure

        logger.info(f"Running container {CONTAINER_NAME}...")
        container = docker_client.containers.run(
            IMAGE_NAME, name=CONTAINER_NAME, ports={f'{CONTAINER_PORT}/tcp': HOST_PORT}, detach=True
        )

        logger.info(f"Waiting {STARTUP_WAIT}s for server startup...")
        await asyncio.sleep(STARTUP_WAIT)

        if container.status == "exited":
            raise RuntimeError("Container exited unexpectedly, check logs")

        if not await check_server_health():
            breakpoint()
            raise RuntimeError("Server health check failed.")

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
    finally:
        if container:
            logger.info(f"Stopping and removing container {CONTAINER_NAME}...")
            try:
                container.stop()
                container.remove(force=True)
            except Exception as e:
                logger.error(f"Failed to stop/remove container: {e}")


if __name__ == "__main__":
    exit_status = asyncio.run(main())
    sys.exit(exit_status)
