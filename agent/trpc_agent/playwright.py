import os
import re
import logging
import contextlib
from typing import Literal
from tempfile import TemporaryDirectory
import jinja2
from trpc_agent import playbooks
from core.base_node import Node
from core.workspace import ExecResult
from core.actors import BaseData
from llm.common import AsyncLLM, Message, TextRaw, AttachedFiles
from llm.utils import merge_text

from dagger import dag

logger = logging.getLogger(__name__)


def extract_tag(source: str | None, tag: str):
    if source is None:
        return None
    pattern = re.compile(rf"<{tag}>(.*?)</{tag}>", re.DOTALL)
    match = pattern.search(source)
    if match:
        return match.group(1).strip()
    return None


@contextlib.contextmanager
def ensure_dir(dir_path: str | None):
    if dir_path is not None:
        yield dir_path
    else:
        with TemporaryDirectory() as temp_dir:
            yield temp_dir


class PlaywrightRunner:
    def __init__(self, vlm: AsyncLLM):
        self._ts_cleanup_pattern = re.compile(r"(\?v=)[a-f0-9]+(:[0-9]+:[0-9]+)?")
        self.vlm = vlm

    @staticmethod
    async def run(
        node: Node[BaseData],
        mode: Literal["client", "full"] = "client",
        log_dir: str | None = None,
    ) -> tuple[ExecResult, str | None]:
        logger.info("Running Playwright tests")

        workspace = node.data.workspace
        ctr = workspace.ctr.with_exec(["bun", "install", "."])

        match mode:
            case "client":
                entrypoint = "dev:client"
                postgresdb = None
            case "full":
                postgresdb = (
                    dag.container()
                    .from_("postgres:17.0-alpine")
                    .with_env_variable("POSTGRES_USER", "postgres")
                    .with_env_variable("POSTGRES_PASSWORD", "postgres")
                    .with_env_variable("POSTGRES_DB", "postgres")
                    .as_service(use_entrypoint=True)
                )
                push_result = await workspace.exec_with_pg(
                    ["bun", "run", "drizzle-kit", "push", "--force"], cwd="server"
                )
                if push_result.exit_code != 0:
                    raise RuntimeError(f"Drizzle kit push failed: {push_result.stderr}")
                entrypoint = "dev:all"

        app_ctr = await ctr.with_entrypoint(["bun", "run", entrypoint]).with_exposed_port(5173)

        if postgresdb:
            app_ctr = (
                app_ctr.with_service_binding("postgres", postgresdb)
                .with_exposed_port(2022)
                .with_env_variable("APP_DATABASE_URL", "postgres://postgres:postgres@postgres:5432/postgres")
            )

        status = await ExecResult.from_ctr(app_ctr)
        if status.exit_code != 0:
            raise RuntimeError(f"Failed to start app: {status.stderr}")

        app_service = app_ctr.as_service()
        with ensure_dir(log_dir) as temp_dir:
            result = await node.data.workspace.run_playwright(
                app_service,
                temp_dir,
            )
            if result.exit_code == 0:
                logger.debug("Playwright tests succeeded")
                return result, None

            logger.warning(f"Playwright tests failed with exit code {result.exit_code}")
            return result, f"Error running Playwright tests: {result.stderr}"

    async def evaluate(
        self, node: Node[BaseData], user_prompt: str, mode: Literal["client", "full"] = "client"
    ) -> list[str]:
        errors = []
        with TemporaryDirectory() as temp_dir:
            match mode:
                case "client":
                    prompt_template = playbooks.FRONTEND_VALIDATION_PROMPT
                case "full":
                    prompt_template = playbooks.FULL_UI_VALIDATION_PROMPT
                case _:
                    raise ValueError(f"Unknown mode: {mode}")

            result, err = await self.run(node, log_dir=temp_dir, mode=mode)
            if err:
                errors.append(err)
            else:
                browsers = ("chromium", "webkit")  # firefox is flaky, let's skip it for now?
                expected_files = [f"{browser}-screenshot.png" for browser in browsers]
                console_logs = ""
                for browser in browsers:
                    console_log_file = os.path.join(temp_dir, f"{browser}-console.log")
                    screenshot_file = os.path.join(temp_dir, f"{browser}-screenshot.png")
                    if not os.path.exists(os.path.join(temp_dir, screenshot_file)):
                        errors.append(f"Could not make screenshot: {screenshot_file}")

                    if os.path.exists(os.path.join(temp_dir, console_log_file)):
                        with open(console_log_file, "r") as f:
                            console_logs += f"\n{browser}:\n"
                            logs = f.read()
                            # remove stochastic parts of the logs for caching
                            console_logs += self._ts_cleanup_pattern.sub(r"\1", logs)

                prompt = jinja2.Environment().from_string(prompt_template)
                prompt_rendered = prompt.render(console_logs=console_logs, user_prompt=user_prompt)
                message = Message(role="user", content=[TextRaw(prompt_rendered)])
                attach_files = AttachedFiles(
                    files=[os.path.join(temp_dir, file) for file in expected_files], _cache_key=node.data.file_cache_key
                )
                vlm_feedback = await self.vlm.completion(
                    messages=[message],
                    max_tokens=1024,
                    attach_files=attach_files,
                )
                (vlm_feedback,) = merge_text(list(vlm_feedback.content))
                vlm_text = vlm_feedback.text  # pyright: ignore

                answer = extract_tag(vlm_text, "answer") or ""
                reason = extract_tag(vlm_text, "reason") or ""
                if "no" in answer.lower():
                    logger.info(f"Playwright validation failed. Answer: {answer}, reason: {reason}")
                    errors.append(f"Playwright validation failed with the reason: {reason}")
                else:
                    logger.info(f"Playwright validation succeeded. Answer: {answer}, reason: {reason}")
        return errors
