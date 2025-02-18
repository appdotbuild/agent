from typing import Optional
from typing_extensions import Self
import os
import shutil
import tempfile
import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, model_validator

from anthropic import AnthropicBedrock
from application import Application
from compiler.core import Compiler


client = AnthropicBedrock(aws_region="us-west-2")
compiler = Compiler("botbuild/tsp_compiler", "botbuild/app_schema")


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
    metadata: dict = {}


@app.post("/compile", response_model=BuildResponse)
def compile(request: BuildRequest):
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            application = Application(client, compiler, output_dir=tmpdir)
            bot = application.create_bot(request.prompt, request.botId)
        zipfile = shutil.make_archive(
            f"{tmpdir}/app_schema",
            "zip",
            f"{application.generation_dir}/app_schema",
        )
        with open(zipfile, "rb") as f:
            upload_result = requests.put(
                request.writeUrl,
                data=f.read(),
            )
            upload_result.raise_for_status()
        metadata = {"functions": bot.router.functions}
        return BuildResponse(status="success", message="done", metadata=metadata)
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@app.get("/healthcheck", response_model=BuildResponse, include_in_schema=False)
def healthcheck():
    return BuildResponse(status="success", message="ok")
