from typing import Optional
from typing_extensions import Self
import os
import uuid
import shutil
import tempfile
import requests
import zipfile
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.interpolator import Interpolator
from application import Application, InteractionMode
from compiler.core import Compiler
import capabilities as cap_module
from iteration import get_typespec_metadata, get_scenarios_message
from common import get_logger, init_sentry
from fsm_core.llm_common import get_sync_client
from api.agent_server_api import get_app as get_agent_server_app

logger = get_logger(__name__)
init_sentry()

client = get_sync_client()
compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")

app = FastAPI()

# Include the agent server API routes
agent_server_app = get_agent_server_app()
app.mount("/agent", agent_server_app, name="agent_server")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # This should be restricted in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def check_bearer(request: Request, call_next):
    # Skip auth for agent server API
    if request.url.path.startswith("/agent"):
        return await call_next(request)
        
    bearer = os.getenv("BUILDER_TOKEN")
    if request.headers.get("Authorization") != f"Bearer {bearer}":
        return JSONResponse(status_code=401, content={"message": "Unauthorized"})
    response = await call_next(request)
    return response

from dataclasses import dataclass
from typing import Optional
from datetime import datetime

class Prompt(BaseModel):
    prompt: str
    createdAt: datetime
    kind: str

    def __iter__(self):
        yield "prompt", self.prompt
        yield "createdAt", self.createdAt.isoformat()
        yield "kind", self.kind

class BuildRequest(BaseModel):
    readUrl: Optional[str] = None
    writeUrl: str
    prompt: Optional[str] = None # deprecated
    prompts: Optional[list[Prompt]] = None
    botId: Optional[str] = None
    capabilities: Optional[list[str]] = None


class PrepareRequest(BaseModel):
    prompts: list[Prompt]
    botId: Optional[str] = None
    capabilities: Optional[list[str]] = None


class ReBuildRequest(BaseModel):
    typespecSchema: str
    writeUrl: str
    readUrl: Optional[str] = None
    capabilities: Optional[list[str]] = None
    botId: Optional[str] = None


class BuildResponse(BaseModel):
    status: str
    message: str
    trace_id: str | None
    metadata: dict = {}


class CapabilitiesResponse(BaseModel):
    status: str
    message: str
    trace_id: str | None
    capabilities: list[str]


def generate_bot(write_url: str, read_url: str, prompts: list[str], trace_id: str, bot_id: str | None, capabilities: list[str] | None = None):
    with tempfile.TemporaryDirectory() as tmpdir:
        application = Application(client, compiler)
        interpolator = Interpolator(".")
        logger.info(f"Creating bot with prompts: {prompts}")
        # Extract prompt text if it's a Prompt object, otherwisse use as is
        prompt_texts = [p.prompt if hasattr(p, 'prompt') else p for p in prompts]
        bot = application.prepare_bot(prompt_texts, bot_id, langfuse_observation_id=trace_id, capabilities=capabilities)
        logger.info(f"Prepared bot {tmpdir}")
        updated_bot = application.update_bot(bot.typespec.typespec_schema, bot_id, langfuse_observation_id=trace_id, capabilities=capabilities)
        logger.info(f"Updated bot {tmpdir}")
        interpolator.bake(updated_bot, tmpdir)
        logger.info(f"Baked bot to {tmpdir}")
        zipfile = shutil.make_archive(
            base_name=tmpdir,
            format="zip",
            root_dir=tmpdir,
        )
        with open(zipfile, "rb") as f:
            upload_result = requests.put(write_url, data=f.read())
            upload_result.raise_for_status()


def generate_update_bot(write_url: str, read_url: str, typespec: str, trace_id: str, bot_id: str | None, capabilities: list[str] | None = None):
    try:
        logger.info(f"Staring background job to update bot")
        application = Application(client, compiler, interaction_mode=InteractionMode.NON_INTERACTIVE)
        interpolator = Interpolator(".")
        logger.info(f"Updating bot with typespec: {typespec}")

        bot = application.update_bot(typespec, bot_id, langfuse_observation_id=trace_id, capabilities=capabilities)
        logger.info(f"Completed bot update stage: {bot}")

        with tempfile.TemporaryDirectory() as tmpdir:
            # download the bot from read_url
            if read_url:
                try:
                    logger.info(f"Reading bot from {read_url}")
                    with requests.get(read_url) as r:
                        r.raise_for_status()
                        with open(os.path.join(tmpdir, "bot.zip"), "wb") as f:
                            f.write(r.content)
                        # unzip the bot
                        with zipfile.ZipFile(os.path.join(tmpdir, "bot.zip"), "r") as zip_ref:
                            zip_ref.extractall(tmpdir)
                        logger.info(f"Extracted bot from successfully to {tmpdir}")
                    # bake the bot overwriting parts of the existing bot
                    interpolator.bake(bot, tmpdir, overwrite=True)
                    logger.info(f"Baked bot successfully to {tmpdir}")
                except Exception:
                    logger.exception(f"Failed to read or process existing bot from {read_url}")
                    logger.info(f"Falling back to fresh bot build")
                    interpolator.bake(bot, tmpdir)
                    logger.info(f"Baked fresh bot successfully to {tmpdir}")
            else:
                interpolator.bake(bot, tmpdir)
                logger.info(f"Baked bot successfully to {tmpdir}")

            # zip the bot
            zip_path = shutil.make_archive(
                base_name=tmpdir,
                format="zip",
                root_dir=tmpdir,
            )
            logger.info(f"Zipped bot successfully to {zip_path}")
            # upload the bot
            with open(zip_path, "rb") as f:
                upload_result = requests.put(write_url, data=f.read())
                upload_result.raise_for_status()
                logger.info(f"Uploaded bot successfully to {write_url}")
    except Exception:
        logger.exception(f"Failed to update bot (trace_id: {trace_id}, bot_id: {bot_id}, read_url {read_url}, write_url {write_url})")
        raise


def prepare_bot(prompts: list[Prompt], trace_id: str, bot_id: str | None, capabilities: list[str] | None = None):
    application = Application(client, compiler, interaction_mode=InteractionMode.INTERACTIVE)
    logger.info(f"Creating bot with prompts: {prompts}")
    if not prompts:
        logger.exception("No prompts provided")
        raise ValueError("No prompts provided")
    bot = application.prepare_bot([p.prompt for p in prompts], bot_id, langfuse_observation_id=trace_id, capabilities=capabilities)
    return bot

@app.post("/prepare", response_model=BuildResponse)
def prepare(request: PrepareRequest):
    trace_id = uuid.uuid4().hex
    bot = prepare_bot(request.prompts, trace_id, request.botId, request.capabilities)
    typespec_dict = get_typespec_metadata(bot)
    scenarios = get_scenarios_message(bot)
    message = f"""Your bot's type specification has been prepared.
Use cases implemented: {scenarios}.
Please let me know if these use cases match what you're looking for, and if you would like me to start implementing the application."""
    return BuildResponse(status=bot.status, message=message, trace_id=trace_id, metadata=typespec_dict)


@app.post("/recompile", response_model=BuildResponse)
def compile(request: ReBuildRequest, background_tasks: BackgroundTasks):
    trace_id = uuid.uuid4().hex
    background_tasks.add_task(generate_update_bot, request.writeUrl, request.readUrl, request.typespecSchema, trace_id, request.botId, request.capabilities)
    message = f"Your bot's implementation is being updated in the background"
    return BuildResponse(status="success", message=message, trace_id=trace_id)


# TODO: remove this once we have the new build endpoint
@app.post("/compile", response_model=BuildResponse)
def compile_legacy(request: BuildRequest, background_tasks: BackgroundTasks):
    trace_id = uuid.uuid4().hex
    background_tasks.add_task(generate_bot, request.writeUrl, request.readUrl, request.prompts if request.prompts else [request.prompt], trace_id, request.botId, request.capabilities)
    return BuildResponse(status="success", message="done", trace_id=trace_id)


@app.get("/capabilities", response_model=CapabilitiesResponse)
def get_capabilities():
    trace_id = uuid.uuid4().hex
    return CapabilitiesResponse(status="success", message="ok", trace_id=trace_id, capabilities=cap_module.all_custom_tools)


@app.get("/healthcheck", response_model=BuildResponse, include_in_schema=False)
def healthcheck():
    return BuildResponse(status="success", message="ok", trace_id=None)
