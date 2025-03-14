from typing import Optional
from typing_extensions import Self
import os
import uuid
import shutil
import tempfile
import requests
import zipfile
import sentry_sdk
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from anthropic import AnthropicBedrock
from core.interpolator import Interpolator
from application import Application
from compiler.core import Compiler
import capabilities as cap_module
from iteration import get_typespec_metadata, get_scenarios_message
import logging

logger = logging.getLogger(__name__)


client = AnthropicBedrock(aws_region="us-west-2")
compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")

sentry_dns = os.getenv("SENTRY_DSN")

if sentry_dns:
    sentry_sdk.init(
        dsn=sentry_dns,
        # Add data like request headers and IP for users,
        # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
        send_default_pii=True,
        # Set traces_sample_rate to 1.0 to capture 100%
        # of transactions for tracing.
        traces_sample_rate=1.0,
        # Set profiles_sample_rate to 1.0 to profile 100%
        # of sampled transactions.
        # We recommend adjusting this value in production.
        profiles_sample_rate=1.0,
    )

app = FastAPI()


@app.middleware("http")
async def check_bearer(request: Request, call_next):
    bearer = os.getenv("BUILDER_TOKEN")
    if request.headers.get("Authorization") != f"Bearer {bearer}":
        return JSONResponse(status_code=401, content={"message": "Unauthorized"})
    response = await call_next(request)
    return response


class BuildRequest(BaseModel):
    readUrl: Optional[str] = None
    writeUrl: str
    prompt: Optional[str] = None # deprecated
    prompts: Optional[list[str]] = None
    botId: Optional[str] = None
    capabilities: Optional[list[str]] = None
    
    
class PrepareRequest(BaseModel):
    readUrl: Optional[str] = None
    writeUrl: str
    prompts: Optional[list[str]] = None
    botId: Optional[str] = None
    capabilities: Optional[list[str]] = None


class ReBuildRequest(BaseModel):
    typespec: str
    writeUrl: str
    scenarios: list[str]
    readUrl: Optional[str] = None
    botId: Optional[str] = None
    capabilities: Optional[list[str]] = None


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
        bot = application.create_bot(prompts[0], bot_id, langfuse_observation_id=trace_id, capabilities=capabilities)
        logger.info(f"Baked bot to {tmpdir}")
        interpolator.bake(bot, tmpdir)
        zipfile = shutil.make_archive(
            base_name=tmpdir,
            format="zip",
            root_dir=tmpdir,
        )
        with open(zipfile, "rb") as f:
            upload_result = requests.put(write_url, data=f.read())
            upload_result.raise_for_status()


def generate_update_bot(write_url: str, read_url: str, typespec: str, scenarios: list[str], trace_id: str, bot_id: str | None, capabilities: list[str] | None = None):
    with tempfile.TemporaryDirectory() as tmpdir:
        application = Application(client, compiler)
        interpolator = Interpolator(".")
        logger.info(f"Updating bot with typespec: {typespec} and scenarios: {scenarios}")
        
        # Use the update_bot method instead of create_bot
        bot = application.update_bot(typespec, scenarios, bot_id, langfuse_observation_id=trace_id, capabilities=capabilities)
        logger.info(f"Updated bot successfully")
        
        # download the bot from read_url
        if read_url:
            with requests.get(read_url) as r:
                r.raise_for_status()
                with open(os.path.join(tmpdir, "bot.zip"), "wb") as f:
                    f.write(r.content)
                # unzip the bot
                with zipfile.ZipFile(os.path.join(tmpdir, "bot.zip"), "r") as zip_ref:
                    zip_ref.extractall(tmpdir)
            # bake the bot overwriting parts of the existing bot
            interpolator.bake(bot, tmpdir, overwrite=True)
        else:
            interpolator.bake(bot, tmpdir)
            
        # zip the bot
        zip_path = shutil.make_archive(
            base_name=tmpdir,
            format="zip",
            root_dir=tmpdir,
        )
        # upload the bot
        with open(zip_path, "rb") as f:
            upload_result = requests.put(write_url, data=f.read())
            upload_result.raise_for_status()


def prepare_bot(prompts: list[str], trace_id: str, bot_id: str | None, capabilities: list[str] | None = None):
    with tempfile.TemporaryDirectory() as tmpdir:
        application = Application(client, compiler)
        logger.info(f"Creating bot with prompts: {prompts}")
        if not prompts:
            logger.error("No prompts provided")
            raise ValueError("No prompts provided")
        bot = application.prepare_bot(prompts, bot_id, langfuse_observation_id=trace_id, capabilities=capabilities)
        logger.info(f"Baked bot to {tmpdir}")
        return bot

@app.post("/prepare", response_model=BuildResponse)
def prepare(request: PrepareRequest):
    trace_id = uuid.uuid4().hex
    bot = prepare_bot(request.prompts, trace_id, request.botId, request.capabilities)
    
    typespec_dict = get_typespec_metadata(bot)
    scenarios = get_scenarios_message(bot)
    
    message = f"Your bot's type specification has been prepared. Use cases implemented: {scenarios}"
    
    return BuildResponse(status="success", message=message, trace_id=trace_id, metadata=typespec_dict)


@app.post("/rebuild", response_model=BuildResponse)
def compile(request: ReBuildRequest, background_tasks: BackgroundTasks):
    trace_id = uuid.uuid4().hex
    background_tasks.add_task(generate_update_bot, request.writeUrl, request.readUrl, request.prompts if request.prompts else [request.prompt], trace_id, request.botId, request.capabilities)
    return BuildResponse(status="success", message="done", trace_id=trace_id)


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
