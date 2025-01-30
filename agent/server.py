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
from services import CompilerService


client = AnthropicBedrock(aws_region="us-west-2")
compiler = CompilerService()


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

    @model_validator(mode="after")
    def validate_urls(self) -> Self:
        # we don't support modifications yet
        if self.readUrl:
            raise ValueError("readUrl is not supported")
        return self


class BuildResponse(BaseModel):
    status: str
    message: str


@app.post("/compile", response_model=BuildResponse)
def compile(request: BuildRequest):
    with tempfile.TemporaryDirectory() as tmpdir:
        application = Application(client, compiler, output_dir=tmpdir)
        application.create_bot(request.prompt)
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
    return BuildResponse(status="success", message="done")
