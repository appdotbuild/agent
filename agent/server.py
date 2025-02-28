from typing import Optional
from typing_extensions import Self
import os
import shutil
import tempfile
import requests
import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, model_validator

from anthropic import AnthropicBedrock
from core.interpolator import Interpolator
from application import Application
from compiler.core import Compiler
from langfuse.decorators import langfuse_context, observe

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
    prompt: str
    botId: Optional[str] = None

    @model_validator(mode="after")
    def validate_urls(self) -> Self:
        # we don't support modifications yet
        if self.readUrl:
            raise ValueError("readUrl is not supported")
        return self


class BuildResponse(BaseModel):
    status: str
    message: str
    trace_id: str
    metadata: dict = {}


@app.post("/compile", response_model=BuildResponse)
def compile(request: BuildRequest):
    with tempfile.TemporaryDirectory() as tmpdir:
        application = Application(client, compiler)
        interpolator = Interpolator(".")
        logger.info(f"Creating bot with prompt: {request.prompt}")
        bot = application.create_bot(request.prompt, request.botId)
        logger.info(f"Baked bot to {tmpdir}")
        interpolator.bake(bot, tmpdir)
        zipfile = shutil.make_archive(
            base_name=os.path.join(tmpdir, "app_schema"),
            format="zip",
            root_dir=os.path.join(tmpdir, "app_schema"),
        )
        with open(zipfile, "rb") as f:
            upload_result = requests.put(
                request.writeUrl,
                data=f.read(),
            )
            upload_result.raise_for_status()
        metadata = {"functions": bot.typespec.llm_functions}
        logger.info(f"Uploaded bot to {request.writeUrl}")
        return BuildResponse(status="success", message="done", trace_id=bot.trace_id, metadata=metadata)


@app.get("/healthcheck", response_model=BuildResponse, include_in_schema=False)
def healthcheck():
    return BuildResponse(status="success", message="ok")
